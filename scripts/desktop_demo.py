"""Double-clickable, loopback-only launcher for the synthetic collaboration demo."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
from threading import Thread
import time
from urllib.request import urlopen
import webbrowser


def resource_root() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)  # PyInstaller's bundled, read-only resources.
    return Path(__file__).resolve().parents[1]


def demo_data_dir() -> Path:
    override = os.environ.get('TMS_DESKTOP_DEMO_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get('LOCALAPPDATA')
    if not local_app_data:
        raise RuntimeError('找不到 Windows 本地用户资料目录 LOCALAPPDATA')
    return Path(local_app_data) / 'BoxuTMS' / 'demo'


def free_port(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def choose_port(requested: int | None) -> int:
    if requested is not None:
        if not 1 <= requested <= 65535 or not free_port(requested):
            raise RuntimeError(f'本机端口 {requested} 不可用')
        return requested
    if free_port(8769):
        return 8769
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def open_when_ready(port: int, pid: int) -> None:
    health_url = f'http://127.0.0.1:{port}/api/health'
    for _ in range(120):
        try:
            with urlopen(health_url, timeout=1) as response:
                health = json.load(response)
            if health.get('pid') == pid and health.get('demo') is True:
                webbrowser.open(f'http://127.0.0.1:{port}/collaboration')
                return
        except (OSError, ValueError, TimeoutError):
            pass
        time.sleep(0.25)
    print('浏览器未自动打开，请复制下方地址手动访问。', flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description='泊序本机合成演示')
    parser.add_argument('--port', type=int, help='指定本机端口；默认优先使用 8769')
    parser.add_argument('--no-browser', action='store_true', help='只启动服务，不自动打开浏览器')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('此启动器只供 Windows 使用')

    root = resource_root()
    if not (root / 'web' / 'index.html').is_file() or not (root / 'migrations' / 'env.py').is_file():
        raise RuntimeError('程序资源不完整，请重新下载发行版')
    data = demo_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    port = choose_port(args.port)
    os.environ['TMS_DATA_DIR'] = str(data)
    os.environ['TMS_COLLAB_DEMO'] = '1'
    os.environ['TMS_COLLAB_PORT'] = str(port)
    os.environ['TMS_COLLAB_DEMO_PORT'] = str(port)
    os.environ['TMS_COLLAB_WORK_PORT'] = '8768'
    os.environ['TMS_COLLAB_BACKUP_DIR'] = str(data / 'backups')
    os.environ.pop('TMS_COLLAB_DATABASE_URL', None)

    from backend.collaboration import app
    import uvicorn

    url = f'http://127.0.0.1:{port}/collaboration'
    print('泊序 · 合成演示', flush=True)
    print('页面：' + url, flush=True)
    print('练习资料：' + str(data), flush=True)
    print('仅本机可访问。关闭此窗口即可停止服务；再次启动可继续练习。', flush=True)
    if not args.no_browser:
        Thread(target=open_when_ready, args=(port, os.getpid()), daemon=True).start()
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('泊序启动失败：' + str(exc), file=sys.stderr, flush=True)
        if getattr(sys, 'frozen', False) and sys.stdin.isatty():
            input('按回车退出…')
        raise
