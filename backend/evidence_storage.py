"""Opaque local file keys. This directory is never mounted as a static route."""
import base64
import hashlib
import os
from pathlib import Path
import re
from uuid import uuid4
from .db import DATA

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 2_850_000
MAX_ORDER_FILES = 30
TYPES = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}


def root_for(engine):
    if engine.dialect.name == 'sqlite':
        # Every SQLite database, including demo and acceptance files, gets its own directory.
        return Path(engine.url.database).resolve().with_suffix('.attachments')
    identity = f'{engine.url.host}:{engine.url.port}/{engine.url.database}'
    key = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return DATA / 'private-evidence' / ('postgresql-' + key)


def file_path(engine, key):
    if not re.fullmatch(r'[0-9a-f]{32}\.bin', key):
        raise ValueError('附件存储编号无效')
    root = root_for(engine).resolve()
    destination = root / key
    # Reject symlinks/reparse points resolving outside the private root.
    if destination.resolve().parent != root or destination.is_symlink():
        raise ValueError('附件路径无效')
    return destination


def validate_content(filename, content):
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('每件附件须为1字节至2 MiB，请压缩或拆分后上传')
    name = filename.strip()
    if not name or len(name) > 180 or any(c in name for c in '/\\:\x00\r\n') or name in ['.', '..'] or any(ord(c) < 32 for c in name):
        raise ValueError('文件名无效，请使用不含路径和控制字符的普通文件名')
    ext = Path(name).suffix.lower()
    mime = TYPES.get(ext)
    if not mime:
        raise ValueError('仅支持 PDF、PNG、JPG / JPEG 文件')
    valid = (ext == '.pdf' and content.startswith(b'%PDF-') and b'%%EOF' in content[-1024:]
             or ext == '.png' and content.startswith(b'\x89PNG\r\n\x1a\n') and content[12:16] == b'IHDR' and content[-8:-4] == b'IEND'
             or ext in ['.jpg', '.jpeg'] and content.startswith(b'\xff\xd8\xff') and content.endswith(b'\xff\xd9'))
    if not valid:
        raise ValueError('文件内容与扩展名不一致或文件不完整，请重新导出后上传')
    return name, mime


def write_file(engine, key, content):
    destination = file_path(engine, key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: no caller can overwrite an existing attachment.
    created = False
    try:
        with destination.open('xb') as stream:
            created = True
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return destination


def read_verified(engine, record):
    def attr(name):
        return record[name] if isinstance(record, dict) else getattr(record, name)
    path = file_path(engine, attr('storage_key'))
    if not path.is_file():
        raise ValueError('附件文件缺失，请保留数据库并从完整备份恢复附件')
    expected = attr('byte_size')
    if not isinstance(expected, int) or expected < 1 or expected > MAX_FILE_BYTES or path.stat().st_size != expected:
        raise ValueError('附件大小校验失败，请从完整备份恢复')
    with path.open('rb') as source:
        content = source.read(MAX_FILE_BYTES + 1)
    if len(content) != expected or hashlib.sha256(content).hexdigest() != attr('sha256'):
        raise ValueError('附件摘要校验失败，请从完整备份恢复')
    return content


def encode_snapshot(engine, records):
    return {r['storage_key']: base64.b64encode(read_verified(engine, r)).decode('ascii') for r in records}


def decode_snapshot(records, files):
    if not isinstance(files, dict) or set(files) != {r['storage_key'] for r in records} or len(files) != len(records):
        raise ValueError('备份附件清单与元数据不一致')
    decoded = {}
    for record in records:
        key = record['storage_key']
        if not re.fullmatch(r'[0-9a-f]{32}\.bin', key):
            raise ValueError('备份附件编号无效')
        try:
            content = base64.b64decode(files[key], validate=True)
        except (ValueError, TypeError):
            raise ValueError('备份附件编码无效')
        name, mime = validate_content(record['filename'], content)
        if mime != record['media_type'] or len(content) != record['byte_size'] or hashlib.sha256(content).hexdigest() != record['sha256']:
            raise ValueError('备份附件内容与摘要或大小不一致')
        decoded[key] = content
    return decoded


def key():
    return uuid4().hex + '.bin'
