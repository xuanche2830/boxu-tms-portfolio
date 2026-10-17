"""Run portable HTTP suites on disposable databases and random loopback ports."""
from pathlib import Path
import argparse
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('suite', choices=['all', 'business', 'imports', 'evidence', 'demo'], default='all', nargs='?')
args = p.parse_args()
for suite in (['business', 'imports', 'evidence', 'demo'] if args.suite == 'all' else [args.suite]):
    print('Running ' + suite, flush=True)
    result = subprocess.run([sys.executable, str(ROOT/'tests'/f'test_{suite}.py')], cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)
print('Selected suites passed. Local reports are in .test-runs/.')
