"""Trusted local, portable backups. Restore only into an empty migrated database."""
import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect, select, text

from .collab_database import HEAD, TABLES, revision
from . import evidence_storage

FORMAT = 'harbor-collaboration-backup-v1'
EXCLUDED = {'co_session', 'co_login_attempt', 'co_schema_version'}
DATA_TABLES = [t for t in TABLES if t.name not in EXCLUDED]
MAX_BYTES = 128 * 1024 * 1024
EVIDENCE_TABLES = {'co_evidence_file', 'co_evidence_review', 'co_evidence_requirement'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def table_digest(rows):
    return hashlib.sha256(canonical(sorted(rows, key=lambda r: str(r['id'])))).hexdigest()


def snapshot(engine):
    with engine.connect() as con:
        if engine.dialect.name == 'postgresql':
            con = con.execution_options(isolation_level='REPEATABLE READ')
            con.begin()
            con.execute(text('SET TRANSACTION READ ONLY'))
        else:
            con.exec_driver_sql('BEGIN')
        if revision(con) != HEAD:
            raise ValueError('请先升级数据库结构，再制作备份')
        rows = {t.name: [dict(row) for row in con.execute(select(t)).mappings()] for t in DATA_TABLES}
        for values in rows.values():
            values.sort(key=lambda row: str(row['id']))
        return rows


def manifest_for(rows):
    return {name: {'count': len(values), 'sha256': table_digest(values)} for name, values in rows.items()}


def files_manifest(records):
    return {r['storage_key']: {'byte_size': r['byte_size'], 'sha256': r['sha256']} for r in records}


def create_backup(engine, directory):
    rows = snapshot(engine)
    created = datetime.now(timezone.utc).isoformat()
    payload = {'format': FORMAT, 'revision': HEAD, 'created_at': created,
               'source_dialect': engine.dialect.name, 'tables': rows}
    evidence = rows['co_evidence_file']
    if len(canonical(payload)) + sum((r['byte_size'] + 2) // 3 * 4 + 80 for r in evidence) > MAX_BYTES:
        raise ValueError('备份超过128 MiB便携格式上限，请将数据库与私有附件目录一起做原生备份')
    # Files are immutable and not deletable through the API. Read exactly the metadata snapshot.
    payload['files'] = evidence_storage.encode_snapshot(engine, evidence)
    body = canonical(payload)
    if len(body) > MAX_BYTES:
        raise ValueError('备份超过128 MiB便携格式上限，请将数据库与私有附件目录一起做原生备份')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    filename = 'collaboration-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    archive = directory / (filename + '.json.gz')
    summary = {'format': FORMAT, 'revision': HEAD, 'created_at': created, 'file': archive.name,
               'source_dialect': engine.dialect.name, 'tables': manifest_for(rows),
               'files': files_manifest(evidence), 'sessions_restored': False, 'sha256': hashlib.sha256(body).hexdigest()}
    pending = archive.with_suffix('.pending')
    with pending.open('xb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as stream:
            stream.write(body)
        raw.flush()
        os.fsync(raw.fileno())
    pending.rename(archive)
    with archive.with_suffix('.manifest.json').open('x', encoding='utf-8') as out:
        json.dump(summary, out, ensure_ascii=False, indent=2)
    return summary


def read_backup(archive):
    archive = Path(archive)
    summary = json.loads(archive.with_suffix('.manifest.json').read_text(encoding='utf-8'))
    with gzip.open(archive, 'rb') as stream:
        body = stream.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError('备份超出读取上限')
    if hashlib.sha256(body).hexdigest() != summary.get('sha256'):
        raise ValueError('备份校验失败：文件与清单不一致')
    data = json.loads(body)
    if data.get('format') != FORMAT or data.get('revision') not in [HEAD, '0002_query_indexes', '0003_import_batches']:
        raise ValueError('备份格式或结构版本不受当前程序支持')
    tables = data.get('tables', {})
    excluded = set() if data['revision'] == HEAD else EVIDENCE_TABLES
    if data['revision'] == '0002_query_indexes':
        excluded = excluded | {'co_import_batch'}
    accepted_tables = [t for t in DATA_TABLES if t.name not in excluded]
    if set(tables) != {t.name for t in accepted_tables}:
        raise ValueError('备份表清单不完整')
    for table in accepted_tables:
        if not isinstance(tables[table.name], list):
            raise ValueError('备份记录格式无效')
        for row in tables[table.name]:
            if not isinstance(row, dict) or set(row) != set(table.c.keys()):
                raise ValueError(f'{table.name} 字段清单不一致')
    if manifest_for(tables) != summary.get('tables'):
        raise ValueError('备份逐表校验失败')
    if data['revision'] != HEAD:
        if data.get('files'):
            raise ValueError('旧结构备份不能包含未登记附件')
        for name in excluded:
            tables[name] = []
        data['files'] = {}
        summary = {**summary, 'tables': manifest_for(tables)}
    else:
        evidence_storage.decode_snapshot(tables['co_evidence_file'], data.get('files'))
        if summary.get('files') != files_manifest(tables['co_evidence_file']):
            raise ValueError('备份附件清单校验失败')
    return data, summary


def ordered_rows(table, rows):
    # Replacement references can point to an older row in this same table.
    if table.name != 'pl_reference':
        return rows
    remaining = {row['id']: row for row in rows}
    if len(remaining) != len(rows):
        raise ValueError('备份含重复主键')
    result, done = [], set()
    while remaining:
        ready = [row for row in remaining.values() if not row['replaces_id'] or row['replaces_id'] in done]
        if not ready:
            raise ValueError('换单关系断裂或存在循环')
        for row in ready:
            result.append(row)
            done.add(row['id'])
            del remaining[row['id']]
    return result


def restore_backup(engine, archive):
    data, summary = read_backup(archive)
    files = evidence_storage.decode_snapshot(data['tables']['co_evidence_file'], data['files'])
    created_files = []
    with engine.connect() as con:
        if engine.dialect.name == 'sqlite':
            con.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            con.begin()
            con.execute(text('SELECT pg_advisory_xact_lock(736286609)'))
            con.execute(text('LOCK TABLE ' + ', '.join(t.name for t in TABLES) + ' IN ACCESS EXCLUSIVE MODE'))
        try:
            if revision(con) != HEAD:
                raise ValueError('目标库需要先执行 upgrade')
            if set(inspect(con).get_table_names()) != {t.name for t in TABLES} | {'alembic_version'}:
                raise ValueError('目标库包含未知表，拒绝恢复')
            for table in TABLES:
                if table.name != 'co_schema_version' and con.execute(select(table).limit(1)).first() is not None:
                    raise ValueError('目标库已有资料，拒绝覆盖；请使用新的空库')
            destination = evidence_storage.root_for(engine)
            if destination.exists() and any(destination.iterdir()):
                raise ValueError('目标附件目录已有文件，拒绝覆盖；请使用新的空库及空附件目录')
            for table in DATA_TABLES:
                for row in ordered_rows(table, data['tables'][table.name]):
                    con.execute(table.insert().values(**row))
            verified = {t.name: [dict(row) for row in con.execute(select(t)).mappings()] for t in DATA_TABLES}
            if manifest_for(verified) != summary['tables']:
                raise ValueError('恢复后的逐表数量或内容摘要不一致')
            for key, content in files.items():
                created_files.append(evidence_storage.write_file(engine, key, content))
            for record in data['tables']['co_evidence_file']:
                evidence_storage.read_verified(engine, record)
            con.commit()
        except Exception:
            con.rollback()
            for path in created_files:
                path.unlink(missing_ok=True)
            raise
    return {'result': 'verified', 'tables': summary['tables'], 'files_restored': len(files), 'sessions_restored': False, 'revision': HEAD}


def list_backups(directory):
    records = []
    for path in sorted(Path(directory).glob('*.manifest.json'), reverse=True)[:20]:
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
            archive = Path(directory) / row['file']
            if archive.parent.resolve() != Path(directory).resolve():
                continue
            records.append({'file': archive.name, 'created_at': row['created_at'],
                            'records': sum(v['count'] for v in row['tables'].values()),
                            'available': archive.is_file(), 'revision': row['revision']})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return records
