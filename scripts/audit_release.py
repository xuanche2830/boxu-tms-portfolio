"""Check the exact staged file list before any public push. Never reads ignored data."""
from pathlib import Path
import re
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
result = subprocess.run(['git', 'ls-files', '--cached', '-z'], cwd=root,
                        capture_output=True, check=True)
names = [p for p in result.stdout.decode('utf-8', 'surrogateescape').split('\0') if p]
blocked_parts = {'data', '.test-runs', '.venv', 'node_modules', '__pycache__'}
blocked_names = {'.local-runtime.json', '.env'}
markers = ['C:' + '\\Users\\', 'C:' + '/Users/', 'PRIVATE ' + 'KEY-----', 'gh' + 'p_', 'github_' + 'pat_']
email = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
mobile = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')
errors = []


def inspect_text(name, content):
    if any(marker in content for marker in markers):
        errors.append(name + ': local path or credential marker')
    if email.search(content) or mobile.search(content):
        errors.append(name + ': email address or mobile number')


for name in names:
    path = root / name
    if any(part in blocked_parts for part in Path(name).parts) or Path(name).name in blocked_names:
        errors.append(name + ': runtime/private path')
        continue
    if not path.is_file():
        errors.append(name + ': missing staged file')
        continue
    if path.suffix.lower() in {'.sqlite', '.db', '.log', '.pid'}:
        errors.append(name + ': runtime file')
    if path.suffix.lower() in {'.py', '.ps1', '.md', '.txt', '.json', '.ts', '.tsx', '.css', '.html', '.yaml', '.yml', '.toml', '.csv', '.java', '.in', '.svg'}:
        inspect_text(name, path.read_text(encoding='utf-8', errors='replace'))
    if path.suffix.lower() == '.xlsx':
        with zipfile.ZipFile(path) as book:
            for member in book.namelist():
                if member.endswith(('.xml', '.rels')):
                    inspect_text(name + ':' + member, book.read(member).decode('utf-8', 'replace'))
    if path.suffix.lower() in {'.jpg', '.jpeg'}:
        data = path.read_bytes()
        position = 2
        while position + 4 <= len(data) and data[position] == 255:
            marker = data[position + 1]
            position += 2
            if marker in {216, 217, 218}:
                break
            length = int.from_bytes(data[position:position + 2], 'big')
            if marker in {225, 226, 227, 228, 237, 254}:
                errors.append(name + ': embedded JPEG metadata')
            position += length

history = subprocess.run(['git', 'log', '--all', '--format=%ae%n%ce'], cwd=root,
                         capture_output=True, text=True, check=True)
for address in set(history.stdout.splitlines()):
    if address and not address.endswith('@users.noreply.github.com'):
        errors.append('Git commit history: non-private author/committer email')

print(f'Checked {len(names)} tracked files and reachable commit metadata; findings: {len(errors)}')
for item in errors:
    print(' - ' + item)
sys.exit(bool(errors))

