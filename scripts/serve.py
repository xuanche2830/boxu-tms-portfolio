"""Standard Python entry point. Always bind to loopback; never delete demo work."""
import argparse
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description='泊序：本机项目物流协同')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--demo', action='store_true', help='合成演示（默认）')
    group.add_argument('--work', action='store_true', help='空白工作空间，需要自行建立负责人账号')
    p.add_argument('--port', type=int)
    p.add_argument('--fresh-demo', action='store_true', help='在新的独立目录生成演示，保留先前练习')
    args = p.parse_args()
    if sys.version_info < (3, 12):
        p.error('需要 Python 3.12 或更新版本')
    if args.work and args.fresh_demo:
        p.error('--fresh-demo 只能用于演示空间')
    demo = not args.work
    port = args.port if args.port is not None else (8769 if demo else 8768)
    if not 1 <= port <= 65535:
        p.error('端口应在 1 到 65535 之间')
    if not (ROOT / 'web/index.html').is_file():
        p.error('缺少前端构建，请先按 README 构建 frontend')
    data = ROOT / 'data' / ('demo' if demo else 'work')
    if args.fresh_demo:
        data = ROOT / 'data/demo-sessions' / uuid4().hex[:12]
    os.environ['TMS_DATA_DIR'] = str(data)
    os.environ['TMS_COLLAB_DEMO'] = '1' if demo else '0'
    os.environ['TMS_COLLAB_PORT'] = str(port)
    os.environ['TMS_COLLAB_DEMO_PORT'] = str(port if demo else 8769)
    os.environ['TMS_COLLAB_WORK_PORT'] = str(8768 if demo else port)
    os.environ['TMS_COLLAB_BACKUP_DIR'] = str(data / 'backups')
    if demo:
        os.environ.pop('TMS_COLLAB_DATABASE_URL', None)
    sys.path.insert(0, str(ROOT))
    import uvicorn
    print(f'泊序 {"合成演示" if demo else "工作空间"}: http://127.0.0.1:{port}/collaboration', flush=True)
    print('仅本机可访问；Ctrl+C 停止。数据目录：' + str(data), flush=True)
    uvicorn.run('backend.collaboration:app', host='127.0.0.1', port=port)


if __name__ == '__main__':
    main()
