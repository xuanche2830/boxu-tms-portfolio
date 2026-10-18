"""Collect installed dependency notices for the binary distribution."""
from importlib import metadata
from pathlib import Path
import re
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    names = [line.split('==')[0] for line in (root / 'requirements.txt').read_text().splitlines()
             if line.strip() and not line.startswith('#')]
    sections = ['Third-party notices for the Windows distribution. Some packages are build-only.']
    for name in [*names, 'PyInstaller']:
        dist = metadata.distribution(name)
        sections.append(f'\n===== {dist.metadata["Name"]} {dist.version} =====\n')
        files = [file for file in dist.files or []
                 if re.search(r'(^|/)(licen[cs]e[^/]*|copying[^/]*|notice[^/]*)$', str(file), re.I)]
        if files:
            sections.extend(Path(dist.locate_file(file)).read_text('utf-8', errors='replace') for file in files)
        else:
            sections.append(dist.metadata.get('License', 'See the package upstream license.'))
            sections.extend(dist.metadata.get_all('Project-URL', []))
    for file in [Path(sys.base_prefix) / 'LICENSE.txt',
                 Path(sys.base_prefix) / 'tcl/tcl8.6/license.terms',
                 Path(sys.base_prefix) / 'tcl/tk8.6/license.terms']:
        if file.is_file():
            sections.extend([f'\n===== Python distribution: {file.name} =====\n', file.read_text('utf-8', errors='replace')])
    for package in ['react', 'react-dom', 'lucide-react']:
        for filename in ['LICENSE', 'LICENSE.md']:
            file = root / 'frontend/node_modules' / package / filename
            if file.is_file():
                sections.extend([f'\n===== {package} =====\n', file.read_text('utf-8')])
                break
        else:
            raise RuntimeError(f'Install frontend dependencies before packaging: missing {package} license')
    Path(sys.argv[1]).write_text('\n'.join(sections), 'utf-8')


if __name__ == '__main__':
    main()
