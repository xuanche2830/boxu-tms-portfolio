"""Local maintenance entry. Connection strings are read from environment only."""
import argparse
import json
import sys
from .collab_database import make_engine, migrate, revision
from .collab_backup import create_backup, read_backup, restore_backup
from .db import DATA


def main():
    parser = argparse.ArgumentParser(description='泊序协同库迁移与恢复；连接使用 TMS_COLLAB_DATABASE_URL')
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('upgrade')
    subs.add_parser('status')
    backup = subs.add_parser('backup')
    backup.add_argument('--directory', default=str(DATA / 'backups' / 'collaboration'))
    for name in ('verify', 'restore'):
        sub = subs.add_parser(name)
        sub.add_argument('--file', required=True)
    args = parser.parse_args()
    if args.command == 'verify':
        _, result = read_backup(args.file)
        print(json.dumps({'result': 'verified', **result}, ensure_ascii=False, indent=2))
        return
    engine = make_engine()
    try:
        if args.command == 'upgrade':
            result = {'revision': migrate(engine)}
        elif args.command == 'backup':
            result = create_backup(engine, args.directory)
        elif args.command == 'restore':
            result = restore_backup(engine, args.file)
        else:
            with engine.connect() as connection:
                result = {'dialect': engine.dialect.name, 'revision': revision(connection)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Driver errors can embed connection credentials or data. Keep terminal errors bounded.
        print(str(error) if isinstance(error, (ValueError, RuntimeError)) else '数据库操作失败，请检查连接、文件及约束；未输出连接凭据。', file=sys.stderr)
        sys.exit(1)
