"""Private evidence HTTP + backup/restore failures, always on an isolated database."""
import base64
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from unittest.mock import patch
import urllib.error
import urllib.request
from uuid import uuid4

import acceptance_common as t

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j4ioAAAAASUVORK5CYII=')


def pdf():
    chunks = [b'%PDF-1.4\n']
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents 4 0 R >>', b'<< /Length 0 >>\nstream\n\nendstream']
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(sum(map(len, chunks))); chunks.append(f'{index} 0 obj\n'.encode() + body + b'\nendobj\n')
    start = sum(map(len, chunks))
    chunks.append(b'xref\n0 5\n0000000000 65535 f \n' + b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets[1:]))
    chunks.append(f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return b''.join(chunks)


def binary(client, path):
    headers = {'X-Expected-User': client.identity['user']['id']} if client.identity else {}
    request = urllib.request.Request(t.BASE + path, headers=headers)
    try:
        result = client.opener.open(request, timeout=10)
    except urllib.error.HTTPError as error:
        result = error
    return result.status, dict(result.headers), result.read()


def main():
    os.environ['TMS_COLLAB_DEMO'] = '0'
    report = t.WORK / ('acceptance-evidence-v011-' + t.RUN + '.json')
    run_dir = t.WORK / ('evidence-v011-' + t.RUN)
    run_dir.mkdir()
    process = None
    result = 'failed'
    try:
        with t.LOG.open('w', encoding='utf-8') as log:
            process = t.boot(log)
            owner, employee, partner, outsider = t.Client(), t.Client(), t.Client(), t.Client()
            owner.identity = owner.post('/setup', dict(username='evidence.owner', password='Synthetic-Owner-2026!', display_name='凭证验收负责人', company='合成凭证验收企业'))
            project = owner.post('/project-logistics/projects', t.command(code='SYNTH-EVIDENCE', name='合成凭证项目', owner='测试员', department='测试部'))['id']
            forwarder = owner.post('/project-logistics/partners', t.command(name='合成凭证货代', kind='forwarder', contact='虚构联系人'))['id']
            req = owner.post('/project-logistics/requests', t.command(project_id=project, title='附件隔离验收', cargo='合成货物', unit_kind='package', unit_count=6, origin='东莞演示仓', destination='大阪演示仓', requested_delivery='2026-12-20', owner='测试员'))['id']
            order_a = owner.post('/project-logistics/orders', t.command(request_id=req, request_version=1, partner_id=forwarder, mode='sea', owner='测试员', unit_count=3))['id']
            order_b = owner.post('/project-logistics/orders', t.command(request_id=req, request_version=2, partner_id=forwarder, mode='sea', owner='测试员', unit_count=3))['id']
            unit_a = owner.get('/project-logistics/orders/' + order_a)['units'][0]['id']
            unit_b = owner.get('/project-logistics/orders/' + order_b)['units'][0]['id']
            user_ids = {}
            for client, role in [(employee, 'employee'), (partner, 'partner')]:
                body = dict(username='evidence.' + role, password='Synthetic-Initial-2026!', display_name='合成' + role, role=role)
                if role == 'partner': body['partner_id'] = forwarder
                user_ids[role] = owner.post('/users', body)['id']
                client.login(body['username'], body['password']); client.change_password(body['password'], 'Synthetic-Changed-2026!')
            emp_grant = owner.post('/grants', dict(user_id=user_ids['employee'], kind='project', resource_id=project))['id']
            partner_grant = owner.post('/grants', dict(user_id=user_ids['partner'], kind='order', resource_id=order_a))['id']
            a = '/project-logistics/orders/' + order_a
            b = '/project-logistics/orders/' + order_b
            outsider.get(a + '/evidence', 401)
            partner.get(b + '/evidence', 404)
            partner.post(a + '/evidence-requirements', t.command(kind='delivery_receipt', note='越权待补'), status=403)
            owner.post(a + '/evidence-requirements', t.command(kind='delivery_receipt', unit_id=unit_b, note='跨票范围'), status=422)
            requirement_body = t.command(kind='delivery_receipt', unit_id=unit_a, note='合成要求：补第一箱签收回单')
            requirement = employee.post(a + '/evidence-requirements', requirement_body)['id']
            t.check('requirement retry idempotent', employee.post(a + '/evidence-requirements', requirement_body)['replayed'])
            t.check('requirement initially missing', partner.get(a + '/evidence')['requirements'][0]['status'], 'missing')
            def upload_body(content=PNG, name='合成凭证.png', **extra):
                return t.command(filename=name, source_base64=base64.b64encode(content).decode(), kind='cargo_photo', **extra)
            payload = upload_body(pdf(), '合成回单.pdf', unit_id=unit_a, requirement_id=requirement, note='合成测试材料，不代表真实签收')
            payload['kind'] = 'delivery_receipt'
            item = partner.post(a + '/evidence', payload)
            t.check('file metadata excludes storage path', 'storage_key' not in item and 'signature' not in item and 'command_id' not in item)
            t.check('upload records authenticated identity', item['uploaded_by'], user_ids['partner'])
            t.check('upload never changes order status', owner.get(a)['order']['status'], 'assigned')
            t.check('upload retry does not duplicate', partner.post(a + '/evidence', payload)['replayed'])
            t.check('one file after retry', len(owner.get(a + '/evidence')['files']), 1)
            partner.post(a + '/evidence', {**payload, 'note': '修改相同编号内容'}, status=409)
            t.check('requirement waits for internal review', partner.get(a + '/evidence')['requirements'][0]['status'], 'pending_review')
            code, headers, content = binary(partner, item['download_url'])
            t.check('authorized binary download succeeds', code, 200)
            t.check('download bytes exact', content, pdf())
            t.check('download forced attachment', headers.get('content-disposition', headers.get('Content-Disposition', '')).startswith('attachment;'))
            t.check('download cannot execute in page context', 'sandbox' in headers.get('content-security-policy', headers.get('Content-Security-Policy', '')))
            t.check('anonymous cannot download', binary(outsider, item['download_url'])[0], 401)
            t.check('file cannot be addressed through another order', binary(owner, item['download_url'].replace(order_a, order_b))[0], 404)
            partner.post(a + '/evidence/' + item['id'] + '/reviews', t.command(version=1, outcome='approved', note='货代越权复核'), status=403)
            review = t.command(version=1, outcome='rejected', note='合成复核：日期不清楚，请重新补充')
            employee.post(a + '/evidence/' + item['id'] + '/reviews', review)
            t.check('review replay idempotent', employee.post(a + '/evidence/' + item['id'] + '/reviews', review)['replayed'])
            t.check('rejection returns requirement to missing', owner.get(a + '/evidence')['requirements'][0]['status'], 'missing')
            employee.post(a + '/evidence/' + item['id'] + '/reviews', t.command(version=1, outcome='approved', note='过期复核'), status=409)
            employee.post(a + '/evidence/' + item['id'] + '/reviews', t.command(version=2, outcome='approved', note='合成复核：重新核对文件，确认材料信息'))
            listing = owner.get(a + '/evidence')
            t.check('requirement derives approved from reviewed file', listing['requirements'][0]['status'], 'approved')
            t.check('all review decisions retained', len(listing['reviews']), 2)
            t.check('reviews do not imply delivery', owner.get(a)['order']['status'], 'assigned')
            employee.post(a + '/evidence', upload_body(unit_id=unit_b), status=422)
            mismatched = upload_body(requirement_id=requirement)
            employee.post(a + '/evidence', mismatched, status=422)
            for name in ['../outside.pdf', 'C:\\outside.pdf', 'bad\nname.pdf', 'active.svg']:
                employee.post(a + '/evidence', upload_body(pdf(), name), status=422)
            employee.post(a + '/evidence', upload_body(b'<html>not a png</html>'), status=422)
            employee.post(a + '/evidence', upload_body(pdf(), 'wrong.png'), status=422)
            employee.post(a + '/evidence', upload_body(b''), status=422)
            employee.post(a + '/evidence', upload_body(b'x' * (2 * 1024 * 1024 + 1)), status=422)
            employee.post(a + '/evidence', {'x': 'x' * 2_850_000}, status=413)
            employee.post('/imports', {'x': 'x' * 100_000}, status=413)
            owner.delete('/grants/' + partner_grant)
            t.check('revocation blocks download immediately', binary(partner, item['download_url'])[0], 404)
            partner.get(a + '/evidence', 404)
            partner.post(a + '/evidence', upload_body(), status=404)
            owner.delete('/grants/' + emp_grant)
            employee.get(a + '/evidence', 404)
            employee.post(a + '/evidence/' + item['id'] + '/reviews', t.command(version=3, outcome='approved', note='撤权后复核'), status=404)
            owner.post('/grants', dict(user_id=user_ids['employee'], kind='project', resource_id=project))
            second = employee.post(a + '/evidence', upload_body())

            # Count enforcement under simultaneous submissions to the final free slot.
            for i in range(29): owner.post(b + '/evidence', upload_body(name=f'合成上限{i}.png'))
            clients = [t.Client(), t.Client()]
            for client in clients: client.login('evidence.owner', 'Synthetic-Owner-2026!')
            barrier = threading.Barrier(2)
            def last_slot(index):
                barrier.wait()
                return clients[index].call('POST', b + '/evidence', upload_body(name=f'最后名额{index}.png'))[0]
            with ThreadPoolExecutor(max_workers=2) as pool:
                t.check('per-order cap atomic across concurrent uploads', sorted(pool.map(last_slot, [0, 1])), [200, 422])
            t.check('file cap never exceeded', len(owner.get(b + '/evidence')['files']), 30)
            owner.post(b + '/evidence-requirements', t.command(kind='delivery_receipt', note='合成待补：此材料不自动阻止关单'))
            for action in ['accept', 'dispatch', 'receive', 'close']:
                detail = owner.get(b)
                extra = {'unit_ids': [u['id'] for u in detail['units']], 'receiver': '合成收货员'} if action == 'receive' else {}
                t.business_action(owner, order_b, detail['order']['version'], action, **extra)
            t.check('missing evidence requirement does not impose a blanket close gate', owner.get(b)['order']['status'], 'closed')

            # Application backup must include files; inspect only this synthetic database.
            sys.path.insert(0, str(t.ROOT))
            from backend import collab_database as database, collab_backup as backup, evidence_storage as storage
            from backend.evidence_models import EvidenceFile
            from sqlmodel import Session, select
            from sqlalchemy import inspect, text
            source_url = os.environ.get('TMS_ACCEPTANCE_DATABASE_URL', 'sqlite:///' + t.DATABASE.as_posix())
            engine = database.make_engine(source_url)
            with Session(engine) as session:
                file_record = session.get(EvidenceFile, item['id']).model_dump()
            file_path = storage.file_path(engine, file_record['storage_key'])
            t.check('file stored outside web root', not file_path.resolve().is_relative_to((t.ROOT / 'web').resolve()))
            t.check('storage key not exposed as static route', binary(owner, '/attachments/' + file_record['storage_key'])[0], 404)
            original_bytes = file_path.read_bytes()
            file_path.write_bytes(b'x' * len(original_bytes))
            t.check('corrupt download fails closed', binary(owner, item['download_url'])[0], 409)
            try:
                backup.create_backup(engine, run_dir / 'corrupt-backup')
                raise AssertionError('corrupt file silently backed up')
            except ValueError:
                t.check('backup refuses mismatched file hash', True)
            employee.post(a + '/evidence/' + item['id'] + '/reviews', t.command(version=3, outcome='approved', note='不应通过损坏文件'), status=409)
            file_path.unlink()
            try:
                backup.create_backup(engine, run_dir / 'missing-backup')
                raise AssertionError('missing file silently backed up')
            except ValueError:
                t.check('backup refuses missing file', True)
            storage.write_file(engine, file_record['storage_key'], original_bytes)
            summary = backup.create_backup(engine, run_dir / 'backups')
            archive = run_dir / 'backups' / summary['file']
            payload, manifest = backup.read_backup(archive)
            t.check('backup carries every attachment', len(payload['files']), 32)
            # Recompute the outer envelope hash to ensure inner file validation is exercised.
            damaged = {**payload, 'files': {**payload['files'], file_record['storage_key']: base64.b64encode(b'x' * len(original_bytes)).decode()}}
            damaged_body = backup.canonical(damaged)
            damaged_archive = run_dir / 'damaged-content.json.gz'
            with gzip.open(damaged_archive, 'wb') as stream: stream.write(damaged_body)
            damaged_archive.with_suffix('.manifest.json').write_text(json.dumps({**manifest, 'sha256': hashlib.sha256(damaged_body).hexdigest()}), encoding='utf-8')
            try:
                backup.read_backup(damaged_archive)
                raise AssertionError('inner attachment corruption accepted')
            except ValueError:
                t.check('backup reader checks attachment bytes beyond envelope hash', True)
            target = database.make_engine('sqlite:///' + (run_dir / 'restored.sqlite').as_posix())
            database.migrate(target)
            restored = backup.restore_backup(target, archive)
            t.check('restore reports file count', restored['files_restored'], 32)
            t.check('restored tables content exact', backup.manifest_for(backup.snapshot(target)), backup.manifest_for(backup.snapshot(engine)))
            t.check('restored source file exact', storage.read_verified(target, file_record), original_bytes)
            try:
                backup.restore_backup(target, archive)
                raise AssertionError('nonempty destination overwritten')
            except ValueError:
                t.check('restore refuses nonempty database', True)
            target.dispose()

            # Fail the second actual file installation: roll back rows and remove first file.
            failed = database.make_engine('sqlite:///' + (run_dir / 'restore-failure.sqlite').as_posix())
            database.migrate(failed)
            real_write = storage.write_file
            writes = []
            def fail_second(*args):
                writes.append(True)
                if len(writes) == 2: raise OSError('synthetic disk failure')
                return real_write(*args)
            with patch.object(storage, 'write_file', fail_second):
                try:
                    backup.restore_backup(failed, archive)
                    raise AssertionError('injected restore failure ignored')
                except OSError: pass
            t.check('failed restore rolls back all business rows', all(len(rows) == 0 for rows in backup.snapshot(failed).values()))
            t.check('failed restore removes installed files', list(storage.root_for(failed).glob('*')), [])
            t.check('retry after failed restore succeeds', backup.restore_backup(failed, archive)['files_restored'], 32)
            failed.dispose()
            broken_key = storage.key()
            with patch.object(storage.os, 'fsync', side_effect=OSError('synthetic fsync failure')):
                try:
                    storage.write_file(engine, broken_key, PNG)
                    raise AssertionError('injected fsync failure ignored')
                except OSError: pass
            t.check('write failure removes its own partial file', not storage.file_path(engine, broken_key).exists())
            try:
                storage.file_path(engine, '../../outside.bin')
                raise AssertionError('path traversal accepted')
            except ValueError: t.check('opaque file key prevents traversal', True)

            # Build valid historical backup envelopes using only historically available columns.
            for old_rev, excluded in [('0002_query_indexes', backup.EVIDENCE_TABLES | {'co_import_batch'}), ('0003_import_batches', backup.EVIDENCE_TABLES)]:
                old_tables = {name: rows for name, rows in payload['tables'].items() if name not in excluded}
                old_data = {k: v for k, v in payload.items() if k not in ['files']}
                old_data.update(revision=old_rev, tables=old_tables)
                body = backup.canonical(old_data)
                old_path = run_dir / (old_rev + '.json.gz')
                with gzip.open(old_path, 'wb') as stream: stream.write(body)
                old_summary = {**manifest, 'revision': old_rev, 'tables': backup.manifest_for(old_tables), 'sha256': hashlib.sha256(body).hexdigest()}
                old_summary.pop('files', None)
                old_path.with_suffix('.manifest.json').write_text(json.dumps(old_summary), encoding='utf-8')
                legacy = database.make_engine('sqlite:///' + (run_dir / (old_rev + '.sqlite')).as_posix())
                database.migrate(legacy)
                t.check('old backup restores without missing new table ' + old_rev, backup.restore_backup(legacy, old_path)['files_restored'], 0)
                legacy.dispose()
            engine.dispose()
            t.stop(process); process = t.boot(log)
            t.check('file metadata survives native restart', len(owner.get(a + '/evidence')['files']), 2)
            t.check('file bytes survive native restart', binary(owner, item['download_url'])[2], original_bytes)
            result = 'passed'
    finally:
        t.stop(process)
        report.write_text(json.dumps({'result': result, 'checks': len(t.CHECKS), 'items': t.CHECKS, 'database': str(t.DATABASE), 'evidence_directory': str(run_dir), 'log': str(t.LOG)}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': result, 'checks': len(t.CHECKS), 'report': str(report)}, ensure_ascii=False))


if __name__ == '__main__': main()
