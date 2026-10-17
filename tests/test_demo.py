"""Synthetic work process + existing demo API. Never contacts real work service 8768."""
import json
import os
from pathlib import Path
import sys
import socket
import subprocess
import acceptance_common as t


def main():
    os.environ['TMS_COLLAB_DEMO'] = '0'
    os.environ.pop('TMS_ACCEPTANCE_DATABASE_URL', None)
    status = 'failed'
    process = None
    demo_process = None
    work_base = t.BASE
    report = t.WORK / ('acceptance-demo-v010-' + t.RUN + '.json')
    try:
        with t.LOG.open('w', encoding='utf-8') as log:
            process = t.boot(log)
            client = t.Client()
            client.identity = client.post('/setup', dict(username='synthetic.work', password='Synthetic-Work-2026!', display_name='合成隔离验收', company='仅临时验收'))
            work_identity = client.identity
            work_cookie = {c.name: c.value for c in client.cookies}
            client.post('/demo-login', {'role': 'owner'}, status=404)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                demo_port = probe.getsockname()[1]
            t.BASE = f'http://127.0.0.1:{demo_port}'
            environment = os.environ.copy()
            environment.pop('TMS_COLLAB_DATABASE_URL', None)
            environment.update(TMS_COLLAB_DEMO='1', TMS_COLLAB_PORT=str(demo_port),
                               TMS_DATA_DIR=str(t.WORK / ('demo-isolation-' + t.RUN)))
            demo_process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.collaboration:app',
                '--host', '127.0.0.1', '--port', str(demo_port)], cwd=t.ROOT, env=environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            t.wait_ready(demo_process)
            client.identity = None
            t.check('demo status explicitly marked', client.get('/status')['demo'])
            client.get('/me', 401)
            for role in ['owner', 'employee', 'partner']:
                client.identity = client.post('/demo-login', {'role': role})
                t.check('synthetic role ' + role, client.identity['user']['role'], role)
                t.check('synthetic identity ' + role, client.identity['user']['id'].startswith('DEMO-'))
                data = client.get('/project-logistics')
                t.check('synthetic role sees nonempty orders ' + role, len(data['orders']) >= 6)
                if role == 'partner':
                    client.get('/imports', 403)
                t.check('both cookie names coexist ' + role, sorted(c.name for c in client.cookies), ['tms_collab_demo_session', 'tms_collab_session'])
                t.check('work cookie never overwritten ' + role, {c.name: c.value for c in client.cookies}['tms_collab_session'], work_cookie['tms_collab_session'])
            client.post('/logout', {})
            t.check('demo logout only removes demo cookie', sorted(c.name for c in client.cookies), ['tms_collab_session'])
            t.BASE = work_base
            client.identity = work_identity
            t.check('work identity remains logged in', client.get('/me')['user']['id'], work_identity['user']['id'])
            t.check('work database receives no demo projects', client.get('/project-logistics')['projects'], [])

            sys.path.insert(0, str(t.ROOT))
            from backend import collab_database as db, collab_demo, collab_backup
            from backend.project_models import TransportOrder, TransportReference
            from backend.collab_models import User
            from sqlmodel import Session, select
            path = t.WORK / ('demo-seed-isolation-' + t.RUN + '.sqlite')
            engine = db.make_engine('sqlite:///' + path.as_posix())
            db.migrate(engine)
            collab_demo.seed(engine)
            first = collab_backup.manifest_for(collab_backup.snapshot(engine))
            collab_demo.seed(engine)
            t.check('seed is idempotent including business rows and identities', collab_backup.manifest_for(collab_backup.snapshot(engine)), first)
            with Session(engine) as session:
                orders = session.exec(select(TransportOrder)).all()
                t.check('seed covers all six stages', {o.status for o in orders}, {'assigned', 'accepted', 'in_transit', 'partial_delivered', 'delivered', 'closed'})
                t.check('seed includes sea and international express', {o.mode for o in orders}, {'sea', 'express'})
                t.check('seed contains three synthetic identities', {u.id for u in session.exec(select(User)).all()}, set(collab_demo.DEMO_USERS.values()))
                refs = session.exec(select(TransportReference)).all()
                t.check('sample references never look like real tracking numbers', bool(refs) and all(r.value.startswith('DEMO-ONLY-') for r in refs))
            engine.dispose()
            previous = os.environ.get('TMS_COLLAB_DATABASE_URL')
            os.environ['TMS_COLLAB_DEMO'] = '1'
            os.environ['TMS_COLLAB_DATABASE_URL'] = 'sqlite:///do-not-open-work.sqlite'
            rejected = False
            try:
                db.database_url()
            except ValueError:
                rejected = True
            finally:
                os.environ['TMS_COLLAB_DEMO'] = '0'
                if previous is None:
                    os.environ.pop('TMS_COLLAB_DATABASE_URL', None)
                else:
                    os.environ['TMS_COLLAB_DATABASE_URL'] = previous
            t.check('demo refuses a work database override before opening it', rejected)
            status = 'passed'
    finally:
        t.BASE = work_base
        t.stop(demo_process)
        t.stop(process)
        report.write_text(json.dumps({'result': status, 'checks': len(t.CHECKS), 'items': t.CHECKS, 'synthetic_work_database': str(t.DATABASE)}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': status, 'checks': len(t.CHECKS), 'report': str(report)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
