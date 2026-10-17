# -*- mode: python ; coding: utf-8 -*-
"""Windows one-file build. Only synthetic demo resources are bundled."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).resolve().parent
resources = [ROOT / 'web' / 'index.html']
resources += [path for path in (ROOT / 'web' / 'assets').rglob('*') if path.is_file()]
resources += [path for path in (ROOT / 'migrations').rglob('*.py') if '__pycache__' not in path.parts]
resources += [ROOT / 'reference' / name for name in (
    'field-dictionary.json', 'business-rules.json', 'location-master.json', 'import-contract.json'
)]
datas = [(str(path), str(path.parent.relative_to(ROOT))) for path in resources]

analysis = Analysis(
    [str(ROOT / 'scripts' / 'desktop_demo.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        *collect_submodules('uvicorn', on_error='warn'),
        'sqlalchemy.dialects.sqlite.pysqlite',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'psycopg', 'tkinter'],
    noarchive=False,
)
bundle = PYZ(analysis.pure)
exe = EXE(
    bundle,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name='Boxu-Demo-Windows-x64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
