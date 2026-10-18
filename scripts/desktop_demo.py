"""Compatibility entry for the original demo command."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.desktop_runtime import serve_space

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='泊序独立演示')
    parser.add_argument('--port', type=int)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    serve_space('demo', args.port, open_browser=not args.no_browser)
