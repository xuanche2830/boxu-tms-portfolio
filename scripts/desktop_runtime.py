"""Windows runtime: independent storage and one service per local space."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Literal
from urllib.parse import urlparse
from urllib.request import urlopen
from uuid import uuid4
import webbrowser
from backend.version import APP_VERSION

Mode = Literal['demo', 'work']


def resource_root() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def user_data_root() -> Path:
    override = os.environ.get('TMS_DESKTOP_DATA_ROOT')
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        raise RuntimeError('找不到 Windows 用户资料目录，请检查 LOCALAPPDATA。')
    return Path(local) / 'BoxuTMS'


def workspace_directory(mode: Mode) -> Path:
    legacy = os.environ.get('TMS_DESKTOP_DEMO_DATA_DIR')
    if mode == 'demo' and legacy:
        return Path(legacy).expanduser().resolve()
    return user_data_root() / mode


def configure_environment(data: Path, mode: Mode, port: int, *, desktop: bool) -> None:
    os.environ.update({
        'TMS_DATA_DIR': str(data.resolve()),
        'TMS_COLLAB_DEMO': '1' if mode == 'demo' else '0',
        'TMS_COLLAB_PORT': str(port),
        'TMS_COLLAB_DEMO_PORT': str(port if mode == 'demo' else 8769),
        'TMS_COLLAB_WORK_PORT': str(port if mode == 'work' else 8768),
        'TMS_COLLAB_BACKUP_DIR': str(data / 'backups'),
        'TMS_DESKTOP_RUNTIME': '1' if desktop else '0',
    })
    if mode == 'demo' or desktop:
        os.environ.pop('TMS_COLLAB_DATABASE_URL', None)


def choose_port(mode: Mode, requested: int | None = None) -> int:
    preferred = requested if requested is not None else (8769 if mode == 'demo' else 8768)
    if not 1 <= preferred <= 65535:
        raise ValueError('端口应在 1 到 65535 之间。')
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', preferred))
            return preferred
        except OSError:
            if requested is not None:
                raise RuntimeError(f'端口 {preferred} 已被占用，请选择另一个端口。') from None
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


@dataclass(frozen=True)
class RunningSpace:
    url: str
    instance: str
    mode: Mode


def running_space(data: Path, mode: Mode) -> RunningSpace | None:
    """Check an exact instance marker before reusing an existing local service."""
    try:
        record = json.loads((data / 'desktop-runtime.json').read_text('utf-8'))
        parsed = urlparse(record['url'])
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
                or parsed.path != '/collaboration' or not parsed.port
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            return None
        with urlopen(f'http://127.0.0.1:{parsed.port}/api/health', timeout=1) as response:
            health = json.load(response)
        if (health.get('application') != 'harbor-tms-collaboration'
                or health.get('desktop_instance') != record['instance']
                or health.get('demo') is not (mode == 'demo')):
            return None
        return RunningSpace(record['url'], record['instance'], mode)
    except (OSError, ValueError, KeyError, TypeError):
        return None


class WorkspaceLease:
    """An OS byte lock prevents two desktop services opening the same workspace."""
    def __init__(self, data: Path):
        self.data = data
        self.handle = None

    def __enter__(self):
        import msvcrt
        self.data.mkdir(parents=True, exist_ok=True)
        self.handle = (self.data / 'desktop-runtime.lock').open('a+b')
        if self.handle.tell() == 0:
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.handle.close()
            self.handle = None
            raise RuntimeError('此空间已经启动，请回到已有窗口打开页面。') from None
        return self

    def __exit__(self, *_):
        if self.handle:
            self.handle.close()


def serve_space(mode: Mode, requested_port: int | None = None, *, open_browser: bool = True) -> None:
    root = resource_root()
    if not (root / 'web/index.html').is_file() or not (root / 'migrations/env.py').is_file():
        raise RuntimeError('程序资源不完整，请重新下载并解压完整使用包。')
    data = workspace_directory(mode)
    with WorkspaceLease(data):
        port = choose_port(mode, requested_port)
        configure_environment(data, mode, port, desktop=True)
        instance = uuid4().hex
        os.environ['TMS_DESKTOP_INSTANCE'] = instance
        url = f'http://127.0.0.1:{port}/collaboration'
        (data / 'desktop-runtime.json').write_text(
            json.dumps({'url': url, 'instance': instance, 'mode': mode}), 'utf-8')
        logs = data / 'logs'
        logs.mkdir(exist_ok=True)
        from logging.handlers import RotatingFileHandler
        logging.basicConfig(
            level=logging.INFO,
            handlers=[RotatingFileHandler(logs / 'application.log', maxBytes=2_000_000,
                                          backupCount=2, encoding='utf-8')],
            format='%(asctime)s %(levelname)s %(message)s', force=True)
        # Backend initialization reads the environment; import only after selecting storage.
        from backend.collaboration import app
        import uvicorn
        if open_browser:
            from threading import Thread
            Thread(target=open_when_ready, args=(data, mode), daemon=True).start()
        uvicorn.run(app, host='127.0.0.1', port=port, log_config=None, log_level='warning')


def open_when_ready(data: Path, mode: Mode) -> None:
    for _ in range(120):
        running = running_space(data, mode)
        if running:
            webbrowser.open(running.url)
            return
        time.sleep(0.25)


def restore_space(archive: Path) -> None:
    data = workspace_directory('work')
    with WorkspaceLease(data):
        configure_environment(data, 'work', 8768, desktop=True)
        from backend import collab_backup, collab_database
        collab_backup.read_backup(archive)  # Verify the file before creating a target schema.
        engine = collab_database.make_engine()
        try:
            collab_database.migrate(engine)
            collab_backup.restore_backup(engine, archive)
        finally:
            engine.dispose()


def server_command(mode: Mode) -> list[str]:
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--server', '--mode', mode, '--no-browser']
    return [sys.executable, str(resource_root() / 'scripts/desktop_app.py'),
            '--server', '--mode', mode, '--no-browser']


def start_space(mode: Mode) -> subprocess.Popen:
    return subprocess.Popen(server_command(mode), cwd=str(resource_root()),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        # A one-file build uses a bootloader parent and an application child.
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=15)
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=15)
