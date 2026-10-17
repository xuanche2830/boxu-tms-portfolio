"""v0.11 regression of the unchanged 169-check v0.8 business suite.
Only the expected Alembic head was updated.

End-to-end HTTP acceptance against a separate disposable collaboration database.

Run with the project's Python runtime. The live 8766 database is never opened.
"""
from concurrent.futures import ThreadPoolExecutor
import threading
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.test-runs'
WORK.mkdir(exist_ok=True)
RUN = uuid4().hex[:8]
DATABASE = WORK / f'acceptance-collaboration-{RUN}.sqlite'
REPORT = WORK / f'acceptance-collaboration-{RUN}.json'
LOG = WORK / f'acceptance-collaboration-{RUN}.log'
assert DATABASE.resolve().is_relative_to(WORK.resolve())
assert ROOT.is_dir() and not DATABASE.exists()

with socket.socket() as probe:
    probe.bind(('127.0.0.1', 0))
    PORT = probe.getsockname()[1]
BASE = f'http://127.0.0.1:{PORT}'
PREFIX = '/api/collab'
CHECKS = []
SERVER_PIDS = []


def check(name, actual, expected=True):
    if actual != expected:
        raise AssertionError(f'{name}: expected={expected!r}, actual={actual!r}')
    CHECKS.append(name)


def command(**kwargs):
    return {'command_id': str(uuid4()), **kwargs}


def moment():
    return datetime.now(timezone.utc).isoformat()


class Client:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.identity = None

    def call(self, method, path, body=None, csrf=True, client_header=True, origin=None, expected_id=None):
        headers = {'Accept': 'application/json'}
        if method != 'GET':
            headers['Content-Type'] = 'application/json'
            if client_header:
                headers['X-TMS-Client'] = 'collaboration-v1'
            if origin is not None:
                headers['Origin'] = origin
            if csrf and self.identity:
                headers['X-CSRF-Token'] = self.identity['csrf']
        if self.identity:
            headers['X-Expected-User'] = expected_id or self.identity['user']['id']
        data = json.dumps(body if body is not None else {}, ensure_ascii=False).encode() if method != 'GET' else None
        request = urllib.request.Request(BASE + PREFIX + path, data=data, method=method, headers=headers)
        try:
            response = self.opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read()
        return response.status, json.loads(raw) if raw else {}

    def get(self, path, status=200, **options):
        code, body = self.call('GET', path, **options)
        check(f'GET {path} status {status}', code, status)
        return body

    def post(self, path, body, status=200, **options):
        code, result = self.call('POST', path, body, **options)
        check(f'POST {path} status {status}', code, status)
        return result

    def put(self, path, body, status=200):
        code, result = self.call('PUT', path, body)
        check(f'PUT {path} status {status}', code, status)
        return result

    def delete(self, path, status=200):
        code, result = self.call('DELETE', path, {})
        check(f'DELETE {path} status {status}', code, status)
        return result

    def login(self, username, password):
        self.identity = self.post('/login', {'username': username, 'password': password})
        return self.identity

    def change_password(self, current, new):
        self.identity = self.post('/password', {'current_password': current, 'new_password': new})


def wait_ready(process):
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError('验收服务提前退出，请查看独立日志')
        try:
            with urllib.request.urlopen(BASE + '/api/health', timeout=1) as response:
                payload = json.load(response)
                if payload.get('application') == 'harbor-tms-collaboration':
                    return payload['pid']
        except (urllib.error.URLError, TimeoutError):
            time.sleep(.2)
    raise TimeoutError('独立验收服务未就绪')


def boot(log_handle):
    environment = os.environ.copy()
    environment['TMS_COLLAB_DEMO'] = '0'
    environment['TMS_DATA_DIR'] = str(WORK / ('runtime-' + RUN))
    test_url = os.environ.get('TMS_ACCEPTANCE_DATABASE_URL', 'sqlite:///' + DATABASE.as_posix())
    if not test_url.startswith('sqlite:'):
        from sqlalchemy.engine import make_url
        if not make_url(test_url).database.startswith('tms_acceptance_'):
            raise RuntimeError('Only explicitly named acceptance PostgreSQL databases are allowed')
    environment['TMS_COLLAB_DATABASE_URL'] = test_url
    environment['TMS_COLLAB_BACKUP_DIR'] = str(WORK / ('acceptance-backups-' + RUN))
    environment['TMS_COLLAB_PORT'] = str(PORT)
    args = [sys.executable, '-m', 'uvicorn', 'backend.collaboration:app', '--host', '127.0.0.1', '--port', str(PORT)]
    process = subprocess.Popen(args, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                               stdout=log_handle, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        process.server_pid = wait_ready(process)
        SERVER_PIDS.append(process.server_pid)
    except Exception:
        stop(process)
        raise
    return process


def stop(process):
    if process and process.poll() is None:
        # Windows venv python.exe can be a launcher with a native Python child.
        # Terminate the owned process tree rather than leaving the actual server running.
        if os.name == 'nt':
            killed = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if killed.returncode != 0 and process.poll() is None:
                raise RuntimeError('独立验收进程树未能停止')
        else:
            process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def business_action(client, order, version, action, **extra):
    return client.post(f'/project-logistics/orders/{order}/actions',
                       command(version=version, action=action, occurred_at=moment(),
                               reported_by='虚构验收联系人', evidence='独立验收资料', **extra))


def main():
    process = None
    status = 'failed'
    try:
        with LOG.open('w', encoding='utf-8') as log:
            process = boot(log)
            outsider, owner, staff, pa, pb = (Client() for _ in range(5))
            check('empty setup state', outsider.get('/status')['setup_required'])
            outsider.get('/me', 401)
            outsider.get('/project-logistics', 401)
            owner.identity = owner.post('/setup', {'company': '验收虚构企业', 'display_name': '模拟负责人',
                             'username': 'owner.qa', 'password': 'Temporary-Owner-2026!'})
            check('second setup blocked', outsider.post('/setup', {'company': '重复', 'display_name': '重复',
                  'username': 'other.owner', 'password': 'Temporary-Other-2026!'}, status=409).get('detail') is not None)
            check('owner role', owner.get('/me')['user']['role'], 'owner')
            check('setup no longer required', outsider.get('/status')['setup_required'], False)
            owner.post('/logout', {})
            owner.identity = None
            owner.get('/project-logistics', 401)
            owner.login('owner.qa', 'Temporary-Owner-2026!')

            partner_a = owner.post('/project-logistics/partners', command(name='演练货代A', kind='forwarder', contact='模拟联系人A'))['id']
            partner_b = owner.post('/project-logistics/partners', command(name='演练货代B', kind='forwarder', contact='模拟联系人B'))['id']
            project_a = owner.post('/project-logistics/projects', command(code='AUTH-A', name='验收项目A',
                       owner='模拟负责人', department='测试组', note='SECRET-A-project'))['id']
            project_b = owner.post('/project-logistics/projects', command(code='AUTH-B', name='验收项目B',
                       owner='模拟负责人', department='测试组', note='SECRET-B-project'))['id']

            def request(project, title, count):
                return owner.post('/project-logistics/requests', command(project_id=project, title=title,
                    cargo='模拟设备附件', unit_kind='package', unit_count=count, origin='中国东莞',
                    destination='德国慕尼黑', requested_delivery='2026-11-01',
                    owner='模拟负责人', note='SECRET-request'))['id']

            request_a, request_b = request(project_a, '首批四件', 4), request(project_b, '无关项目', 1)

            def order(req, req_version, partner, count):
                return owner.post('/project-logistics/orders', command(request_id=req, request_version=req_version,
                    partner_id=partner, mode='air', carrier='模拟承运商', owner='模拟负责人',
                    unit_count=count, note='SECRET-order'))['id']

            order_a = order(request_a, 1, partner_a, 2)
            order_b = order(request_a, 2, partner_b, 2)
            order_c = order(request_b, 1, partner_a, 1)
            check('two-way demand allocation', next(r for r in owner.get('/project-logistics')['requests'] if r['id'] == request_a)['allocated_count'], 4)

            users = {}
            for name, role, partner in [('staff.qa', 'employee', None), ('forwarder.a', 'partner', partner_a),
                                        ('forwarder.b', 'partner', partner_b)]:
                body = {'username': name, 'display_name': name, 'password': 'Temporary-Account-2026!', 'role': role}
                if partner:
                    body['partner_id'] = partner
                users[name] = owner.post('/users', body)['id']
            for account, name in [(staff, 'staff.qa'), (pa, 'forwarder.a'), (pb, 'forwarder.b')]:
                account.login(name, 'Temporary-Account-2026!')
                account.get('/project-logistics', 403)
                account.change_password('Temporary-Account-2026!', 'Changed-Account-2026!')
                check(f'{name} password changed', account.get('/me')['user']['must_change_password'], False)

            outsider.get('/maintenance', 401)
            staff.get('/maintenance', 403)
            staff.post('/maintenance/backups', {}, status=403)
            pa.get('/maintenance', 403)
            pa.post('/maintenance/backups', {}, status=403)
            check('owner sees migrated database status', owner.get('/maintenance')['revision'], '0004_order_evidence')
            owner.post('/maintenance/backups', {}, status=403, csrf=False)
            backup_result = owner.post('/maintenance/backups', {})
            check('backup manifest appears in owner list', backup_result['file'] in {b['file'] for b in owner.get('/maintenance')['backups']})

            owner.post('/grants', {'user_id': users['staff.qa'], 'kind': 'project', 'resource_id': project_a})
            owner.post('/grants', {'user_id': users['forwarder.a'], 'kind': 'order', 'resource_id': order_a})
            owner.post('/grants', {'user_id': users['forwarder.b'], 'kind': 'order', 'resource_id': order_b})
            owner.post('/grants', {'user_id': users['forwarder.a'], 'kind': 'order', 'resource_id': order_b}, status=422)

            staff_view = staff.get('/project-logistics')
            check('employee sees project A only', {p['id'] for p in staff_view['projects']}, {project_a})
            check('employee sees both A orders', {o['id'] for o in staff_view['orders']}, {order_a, order_b})
            staff.get(f'/project-logistics/orders/{order_c}', 404)
            staff.post('/project-logistics/requests', command(project_id=project_b, title='禁止写入', cargo='禁止',
                        unit_kind='package', unit_count=1, origin='X', destination='Y',
                        requested_delivery='2026-11-01', owner='模拟员工'), status=404)
            staff.post('/users', {'username': 'forbidden', 'display_name': 'No',
                       'password': 'Temporary-Account-2026!', 'role': 'employee'}, status=403)
            staff.post('/project-logistics/partners', command(name='员工不能建伙伴',kind='forwarder',contact='X'),status=403)

            pa_view = pa.get('/project-logistics')
            check('partner A sees only assigned order', {o['id'] for o in pa_view['orders']}, {order_a})
            check('partner A demand count scoped to own units', pa_view['requests'][0]['unit_count'], 2)
            check('partner A project count scoped to own orders', pa_view['projects'][0]['order_count'], 1)
            check('partner A gets own partner only', {p['id'] for p in pa_view['partners']}, {partner_a})
            check('partner A no private notes', 'SECRET-' not in json.dumps(pa_view, ensure_ascii=False))
            pa.get(f'/project-logistics/orders/{order_b}', 404)
            pa.get(f'/project-logistics/orders/{order_c}', 404)
            detail = pa.get(f'/project-logistics/orders/{order_a}')
            check('partner A detail no audit', detail['audit'], [])
            check('partner A detail private fields blank', not detail['project']['note'] and not detail['order']['note'])
            pa.post('/project-logistics/projects', command(code='FORBIDDEN', name='禁建', owner='X', department='X'),status=403)
            pa.post(f'/project-logistics/orders/{order_a}/actions', command(version=1, action='close',
                    occurred_at=moment(), reported_by='X', evidence='X'), status=403)
            pa.post(f'/project-logistics/orders/{order_a}/actions', command(version=1, action='accept',
                    occurred_at=moment(), reported_by='X', evidence='X'), status=403, csrf=False)
            pa.post(f'/project-logistics/orders/{order_a}/actions', command(version=1, action='accept',
                    occurred_at=moment(), reported_by='X', evidence='X'), status=403, origin='https://evil.example')
            pa.post(f'/project-logistics/orders/{order_a}/actions', command(version=1, action='accept',
                    occurred_at=moment(), reported_by='X', evidence='X'), status=403, client_header=False)
            pa.get('/project-logistics', status=401, expected_id=users['forwarder.b'])

            version = detail['order']['version']
            business_action(pa, order_a, version, 'accept')
            version = pa.get(f'/project-logistics/orders/{order_a}')['order']['version']
            reference = command(version=version, kind='house', issuer='演练货代A', value='QA-A-001', unit_id=None,
                                replaces_id=None, reason='')
            ref_path = f'/project-logistics/orders/{order_a}/references'
            first_ref = pa.post(ref_path, reference)
            check('command replay returns same result', pa.post(ref_path, reference)['id'], first_ref['id'])
            changed = {**reference, 'value': 'QA-A-002'}
            pa.post(ref_path, changed, status=409)
            owner.post(ref_path, reference, status=409)
            version = pa.get(f'/project-logistics/orders/{order_a}')['order']['version']
            business_action(pa, order_a, version, 'dispatch')
            event_rows = pa.get(f'/project-logistics/orders/{order_a}')['events']
            check('server actor is authenticated account', event_rows[-1]['actor'], users['forwarder.a'])
            pa_issue = pa.post(f'/project-logistics/orders/{order_a}/issues', command(
                version=pa.get(f'/project-logistics/orders/{order_a}')['order']['version'],
                title='第二件晚到', owner='模拟员工'))['id']
            pa.post(f'/project-logistics/orders/{order_a}/issues/{pa_issue}/resolve', command(
                version=pa.get(f'/project-logistics/orders/{order_a}')['order']['version'],
                resolution='绕过内部结案'), status=403)
            units = staff.get(f'/project-logistics/orders/{order_a}')['units']
            business_action(staff, order_a, staff.get(f'/project-logistics/orders/{order_a}')['order']['version'],
                            'receive', unit_ids=[units[0]['id']], receiver='模拟收货人')
            check('authorized employee confirms partial receipt', staff.get(f'/project-logistics/orders/{order_a}')['order']['status'], 'partial_delivered')
            business_action(staff, order_a, staff.get(f'/project-logistics/orders/{order_a}')['order']['version'],
                            'receive', unit_ids=[units[1]['id']], receiver='模拟收货人')
            check('authorized employee confirms all units', staff.get(f'/project-logistics/orders/{order_a}')['order']['status'], 'delivered')
            staff.post(f'/project-logistics/orders/{order_a}/actions', command(
                version=staff.get(f'/project-logistics/orders/{order_a}')['order']['version'],
                action='close', occurred_at=moment(), reported_by='模拟员工', evidence='不能越过异常'), status=422)
            staff.post(f'/project-logistics/orders/{order_a}/issues/{pa_issue}/resolve', command(
                version=staff.get(f'/project-logistics/orders/{order_a}')['order']['version'],
                resolution='第二件已到，无短少'))
            business_action(staff, order_a, staff.get(f'/project-logistics/orders/{order_a}')['order']['version'], 'close')
            closed = staff.get(f'/project-logistics/orders/{order_a}')
            check('employee closes order after issue resolution', closed['order']['status'], 'closed')
            check('employee close audit records login actor', next(a for a in closed['audit'] if a['action']=='transport_close')['data']['actor'], users['staff.qa'])
            check('partner B sees B order only', {o['id'] for o in pb.get('/project-logistics')['orders']}, {order_b})

            staff_export, pa_export, pb_export = (x.get('/project-logistics-export') for x in (staff, pa, pb))
            check('staff export scope', {o['id'] for o in staff_export['records']['orders']}, {order_a, order_b})
            check('A export scope', {o['id'] for o in pa_export['records']['orders']}, {order_a})
            check('B export scope', {o['id'] for o in pb_export['records']['orders']}, {order_b})
            check('partner export no audit', pa_export['audit'], [])
            check('partner export no private notes', 'SECRET-' not in json.dumps(pa_export, ensure_ascii=False))
            admin = owner.get('/admin')
            pa_grant = next(g['id'] for g in admin['grants'] if g['user_id'] == users['forwarder.a'] and g['resource_id'] == order_a)
            owner.delete('/grants/' + pa_grant)
            check('revoke removes A order', pa.get('/project-logistics')['orders'], [])
            pa.get(f'/project-logistics/orders/{order_a}', 404)
            check('revoke removes export', pa.get('/project-logistics-export')['records']['orders'], [])
            pa.post(f'/project-logistics/orders/{order_a}/actions', command(version=1, action='note',
                    occurred_at=moment(), reported_by='X', evidence='X'), status=404)

            owner.put('/users/' + users['forwarder.b'] + '/active', {'active': False})
            pb.get('/me', 401)
            outsider.post('/login', {'username': 'forwarder.b', 'password': 'Changed-Account-2026!'}, status=401)
            owner.put('/users/' + users['forwarder.b'] + '/active', {'active': True})
            pb.login('forwarder.b', 'Changed-Account-2026!')
            check('reactivated account needs new login', pb.get('/me')['user']['active'])

            request_d = request(project_a, '改派与取消', 1)
            order_d = order(request_d, 1, partner_a, 1)
            owner.post('/grants', {'user_id': users['forwarder.a'], 'kind': 'order', 'resource_id': order_d})
            business_action(owner, order_d, 1, 'reassign', partner_id=partner_b)
            check('reassign revokes old grant', order_d not in {g['resource_id'] for g in owner.get('/admin')['grants'] if g['user_id'] == users['forwarder.a']})
            pa.get(f'/project-logistics/orders/{order_d}', 404)
            owner.post('/grants', {'user_id': users['forwarder.b'], 'kind': 'order', 'resource_id': order_d})
            business_action(owner, order_d, owner.get(f'/project-logistics/orders/{order_d}')['order']['version'], 'cancel')
            check('cancel revokes new grant', order_d not in {g['resource_id'] for g in owner.get('/admin')['grants'] if g['user_id'] == users['forwarder.b']})
            pb.get(f'/project-logistics/orders/{order_d}', 404)
            check('cancel releases allocation', next(r for r in owner.get('/project-logistics')['requests'] if r['id'] == request_d)['allocated_count'], 0)

            # Two independent clients submit the same demand version at the same time.
            concurrent_request = request(project_b, '并发分配一件', 1)
            clients = [Client(), Client()]
            for client in clients:
                client.login('owner.qa', 'Temporary-Owner-2026!')
            barrier = threading.Barrier(2)
            def allocate(client):
                barrier.wait()
                return client.call('POST', '/project-logistics/orders', command(request_id=concurrent_request,
                    request_version=1, partner_id=partner_a, mode='air', carrier='模拟', owner='并发验收', unit_count=1))[0]
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(allocate,clients))
            check('concurrent demand allocation accepts one and conflicts one', sorted(statuses), [200,409])
            concurrent_state = owner.get('/project-logistics')
            check('concurrent allocation never exceeds one unit', next(r for r in concurrent_state['requests'] if r['id']==concurrent_request)['allocated_count'], 1)
            check('concurrent allocation creates exactly one order', len([o for o in concurrent_state['orders'] if o['request_id']==concurrent_request]), 1)

            # A fresh process and fresh SQL connection must see durable accounts and business rows.
            stop(process)
            process = boot(log)
            check('restart creates a different native server process', SERVER_PIDS[-1] != SERVER_PIDS[-2])
            check('schema survives process restart', outsider.get('/status')['setup_required'], False)
            check('session and project survive process restart',
                  {p['id'] for p in owner.get('/project-logistics')['projects']}, {project_a, project_b})
            check('revoked scope survives process restart', pa.get('/project-logistics')['orders'], [])
            status = 'passed'
    finally:
        stop(process)
        REPORT.write_text(json.dumps({'result': status, 'checks': len(CHECKS), 'items': CHECKS,
                                      'database': str(DATABASE), 'log': str(LOG), 'native_server_pids': SERVER_PIDS}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'result': status, 'checks': len(CHECKS), 'report': str(REPORT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
