"""Check the delivered app outside the repository, using synthetic local data only."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.desktop_runtime import APP_VERSION, stop_process


class Client:
    def __init__(self, base):
        self.base = base
        self.identity = None
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, data=None, expected=200):
        headers = {'Content-Type': 'application/json', 'X-TMS-Client': 'collaboration-v1'}
        if self.identity:
            headers.update({'X-CSRF-Token': self.identity['csrf'], 'X-Expected-User': self.identity['user']['id']})
        request = Request(self.base + '/api/collab' + path, method=method, headers=headers,
                          data=json.dumps(data).encode() if method != 'GET' else None)
        try:
            response = self.opener.open(request, timeout=15)
        except HTTPError as error:
            response = error
        result = json.load(response)
        if response.status != expected:
            raise AssertionError(f'{method} {path}: expected {expected}, got {response.status}: {result}')
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', type=Path)
    args = parser.parse_args()
    reports = ROOT / '.test-runs'
    reports.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='desktop-', dir=reports))
    if args.executable:
        portable = work / 'independent-app'
        portable.mkdir()
        executable = portable / 'Boxu-Windows-x64.exe'
        shutil.copy2(args.executable.resolve(), executable)
        command = [str(executable)]
    else:
        command = [sys.executable, str(ROOT / 'scripts/desktop_app.py')]
    environment = {key: value for key, value in os.environ.items() if not key.startswith('TMS_')}
    environment['TMS_DESKTOP_DATA_ROOT'] = str(work / 'original')
    if args.executable:
        for key in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'TCL_LIBRARY', 'TK_LIBRARY'):
            environment.pop(key, None)
        windows = os.environ.get('SystemRoot', r'C:\Windows')
        environment['PATH'] = str(Path(windows) / 'System32') + os.pathsep + windows
    processes = []
    checks = []

    def check(name, actual):
        if not actual:
            raise AssertionError(name)
        checks.append(name)

    def run(arguments, env=environment):
        return subprocess.run(command + arguments, cwd=work, env=env,
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=90,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def start(mode, env=environment, *, auto_port=False):
        arguments = ['--server', '--mode', mode, '--no-browser']
        if not auto_port:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                arguments += ['--port', str(probe.getsockname()[1])]
        process = subprocess.Popen(command + arguments, cwd=work, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        processes.append(process)
        descriptor = Path(env['TMS_DESKTOP_DATA_ROOT']) / mode / 'desktop-runtime.json'
        for _ in range(160):
            if process.poll() is not None:
                error = descriptor.parent / 'startup-error.log'
                raise AssertionError(error.read_text('utf-8') if error.is_file() else 'desktop process exited early')
            try:
                record = json.loads(descriptor.read_text('utf-8'))
                base = record['url'].removesuffix('/collaboration')
                with urlopen(base + '/api/health', timeout=1) as response:
                    health = json.load(response)
                if health['desktop_instance'] == record['instance']:
                    check('release identity ' + mode, health['version'] == APP_VERSION)
                    with urlopen(base + '/collaboration', timeout=5) as response:
                        check('page available ' + mode, response.status == 200)
                    return process, Client(base)
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.3)
        raise TimeoutError('desktop service readiness timed out')

    outcome = 'failed'
    try:
        check('graphical launcher and bundled guide initialize', run(['--launcher-check']).returncode == 0)
        check('launcher check creates no work database', not (work / 'original/work/collaboration.sqlite').exists())
        demo_process, demo = start('demo')
        check('demo explicitly isolated', demo.call('GET', '/status')['demo'] is True)
        for role in ('owner', 'employee', 'partner'):
            demo.identity = demo.call('POST', '/demo-login', {'role': role})
            check('demo role ' + role, demo.identity['user']['role'] == role)
            check('six synthetic orders ' + role, len(demo.call('GET', '/project-logistics')['orders']) == 6)

        work_process, client = start('work')
        status = client.call('GET', '/status')
        check('new independent workspace needs setup', status['setup_required'] and not status['demo'] and status['desktop'])
        client.call('GET', '/project-logistics', expected=401)
        checks.append('anonymous work read refused')
        client.call('POST', '/demo-login', {'role': 'owner'}, expected=404)
        checks.append('work cannot use demo identity')
        credentials = {'username': 'desktop.owner', 'password': 'Synthetic-Owner-2026!'}
        client.identity = client.call('POST', '/setup', {**credentials, 'company': '合成桌面验收', 'display_name': '合成负责人'})
        check('work starts without demo projects', client.call('GET', '/project-logistics')['projects'] == [])
        project = client.call('POST', '/project-logistics/projects', {
            'command_id': str(uuid4()), 'code': 'LOCAL-ACCEPTANCE', 'name': '合成本机项目',
            'owner': '合成人员', 'department': '合成部门', 'note': ''})
        check('independent work write', bool(project['id']))
        check('duplicate service refused', run(['--server', '--mode', 'work', '--no-browser']).returncode != 0)
        check('original service survives duplicate start', client.call('GET', '/status')['desktop'])
        backup = client.call('POST', '/maintenance/backups', {})
        archive = work / 'original/work/backups' / backup['file']
        check('portable backup created', archive.is_file())
        stop_process(work_process)
        work_process, client = start('work')
        check('setup persists after restart', not client.call('GET', '/status')['setup_required'])
        client.identity = client.call('POST', '/login', credentials)
        check('business data persists after restart', client.call('GET', '/project-logistics')['projects'][0]['id'] == project['id'])
        stop_process(work_process)
        check('restore refuses existing business data', run(['--restore-file', str(archive)]).returncode != 0)
        restored_environment = {**environment, 'TMS_DESKTOP_DATA_ROOT': str(work / 'restored')}
        check('restore succeeds into new empty space', run(['--restore-file', str(archive)], restored_environment).returncode == 0)
        _, restored = start('work', restored_environment)
        restored.call('GET', '/me', expected=401)
        checks.append('restored space requires fresh login')
        restored.identity = restored.call('POST', '/login', credentials)
        check('restored owner and project retained', restored.call('GET', '/project-logistics')['projects'][0]['id'] == project['id'])
        check('demo remains independent', len(demo.call('GET', '/project-logistics')['orders']) == 6)

        with socket.socket() as occupied:
            try:
                occupied.bind(('127.0.0.1', 8769))
                occupied.listen()
            except OSError:
                pass  # An existing app already supplies the occupied default-port condition.
            alternate_environment = {**environment, 'TMS_DESKTOP_DATA_ROOT': str(work / 'port-conflict')}
            _, alternate = start('demo', alternate_environment, auto_port=True)
            check('occupied default port falls back', ':8769' not in alternate.base)
        outcome = 'passed'
    finally:
        for process in processes:
            stop_process(process)
        (work / 'result.json').write_text(json.dumps({'result': outcome, 'checks': checks}, ensure_ascii=False, indent=2), 'utf-8')
    print(f'Desktop delivery: {outcome}; {len(checks)} checks. Reports: .test-runs/desktop-*/result.json')


if __name__ == '__main__':
    main()
