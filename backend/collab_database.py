"""Independent collaboration database and explicit schema lifecycle."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect, text, UniqueConstraint
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, create_engine

from .collab_models import AUTH_MODELS
from .db import DATA, ROOT
from .models import Audit
from .project_models import PROJECT_TABLES, CommandReceipt

from .import_models import ImportBatch
from .evidence_models import EVIDENCE_MODELS

HEAD = '0004_order_evidence'
LEGACY_MODELS = [*PROJECT_TABLES.values(), CommandReceipt, Audit, *AUTH_MODELS]
LEGACY_NAMES = {m.__table__.name for m in LEGACY_MODELS}
MODELS = [*LEGACY_MODELS, ImportBatch, *EVIDENCE_MODELS]
NAMES = {m.__table__.name for m in MODELS}
TABLES = [t for t in SQLModel.metadata.sorted_tables if t.name in NAMES]


def database_url():
    if os.environ.get('TMS_COLLAB_DEMO') == '1':
        demo = f'sqlite:///{(DATA / "collaboration-demo.sqlite").as_posix()}'
        configured = os.environ.get('TMS_COLLAB_DATABASE_URL')
        if configured and configured != demo:
            raise ValueError('演示模式拒绝使用指定的工作数据库，请清除 TMS_COLLAB_DATABASE_URL')
        return demo
    return os.environ.get('TMS_COLLAB_DATABASE_URL', f'sqlite:///{(DATA / "collaboration.sqlite").as_posix()}')


def make_engine(url=None):
    url = make_url(url or database_url())
    if url.drivername not in ('sqlite', 'postgresql+psycopg'):
        raise ValueError('协同库仅支持 SQLite 或 postgresql+psycopg')
    if url.drivername == 'sqlite':
        if not url.database or url.database == ':memory:':
            raise ValueError('协同库需要独立的持久化文件')
        path = Path(url.database).resolve()
        if path.name in ('demo.sqlite', 'workspace.sqlite'):
            raise ValueError('协同服务不能使用旧版资料库')
        path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 20} if url.drivername == 'sqlite' else {}, pool_pre_ping=True)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def settings(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA busy_timeout=20000')
            connection.execute('PRAGMA journal_mode=WAL')
    return engine


def config(connection):
    cfg = Config()
    cfg.set_main_option('script_location', str(ROOT / 'migrations'))
    cfg.attributes['connection'] = connection
    return cfg


def revision(connection):
    if 'alembic_version' not in inspect(connection).get_table_names():
        return None
    rows = connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
    if len(rows) != 1:
        raise RuntimeError('迁移版本标记不完整，请检查数据库')
    return rows[0]


def sqlite_snapshot(engine, directory):
    """Online SQLite backup includes WAL contents without copying a live file."""
    source = Path(engine.url.database).resolve()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = directory / f'before-migration-{stamp}.sqlite'
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('升级前备份完整性检查失败')
    return destination


def validate_legacy(connection):
    """Adopt v0.8 only after checking its complete table and column inventory."""
    inspector = inspect(connection)
    names = set(inspector.get_table_names()) - {'alembic_version'}
    if names != LEGACY_NAMES:
        raise RuntimeError('现有库与 v0.8 协同表结构不一致，拒绝自动接管')
    if connection.execute(text('SELECT version FROM co_schema_version')).scalars().all() != [1]:
        raise RuntimeError('未知协同库版本，拒绝升级')
    for table in TABLES:
        if table.name not in LEGACY_NAMES:
            continue
        cols = inspector.get_columns(table.name)
        if {c['name'] for c in cols} != set(table.c.keys()):
            raise RuntimeError(f'{table.name} 字段与基线不一致')
        if set(inspector.get_pk_constraint(table.name)['constrained_columns']) != {c.name for c in table.primary_key.columns}:
            raise RuntimeError(f'{table.name} 主键与基线不一致')
        actual_fk = {(tuple(fk['constrained_columns']), fk['referred_table'], tuple(fk['referred_columns'])) for fk in inspector.get_foreign_keys(table.name)}
        expected_fk = {(tuple(fk.column_keys), next(iter(fk.elements)).column.table.name, tuple(el.column.name for el in fk.elements)) for fk in table.foreign_key_constraints}
        if actual_fk != expected_fk:
            raise RuntimeError(f'{table.name} 外键与基线不一致')
        actual_unique = {tuple(c['column_names']) for c in inspector.get_unique_constraints(table.name)}
        actual_unique |= {tuple(i['column_names']) for i in inspector.get_indexes(table.name) if i['unique']}
        expected_unique = {tuple(c.name for c in u.columns) for u in table.constraints if isinstance(u, UniqueConstraint)}
        expected_unique |= {tuple(c.name for c in i.columns) for i in table.indexes if i.unique}
        if actual_unique != expected_unique:
            raise RuntimeError(f'{table.name} 唯一性约束与基线不一致')
        for c in cols:
            expected = table.c[c['name']]
            if c['type']._type_affinity is not expected.type._type_affinity or c['nullable'] != expected.nullable:
                raise RuntimeError(f'{table.name} 字段类型或空值规则与基线不一致')


def migrate(engine):
    # A file snapshot is recovery evidence; schema changes below are serialized.
    with engine.connect() as connection:
        existing = bool(inspect(connection).get_table_names())
        current = revision(connection)
    if current == HEAD:
        return HEAD
    if current not in (None, '0001_collaboration', '0002_query_indexes', '0003_import_batches'):
        raise RuntimeError('协同库版本未知或比程序更新，停止启动以保护资料')
    if existing and engine.dialect.name == 'sqlite':
        sqlite_snapshot(engine, Path(engine.url.database).parent / 'backups' / 'schema')
    with engine.connect() as connection:
        if engine.dialect.name == 'sqlite':
            connection.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            connection.begin()
            connection.execute(text('SELECT pg_advisory_xact_lock(736286609)'))
        try:
            current = revision(connection)
            if current is None and inspect(connection).get_table_names():
                validate_legacy(connection)
                command.stamp(config(connection), '0001_collaboration')
            command.upgrade(config(connection), 'head')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return HEAD
