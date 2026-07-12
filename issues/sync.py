#!/usr/bin/env python3
"""
Minimal sync helper for issues/data.json

Usage:
  python issues/sync.py export [out.json]    # copy issues/data.json to out.json or stdout
  python issues/sync.py import in.json       # replace issues/data.json with in.json (backup created)

This is a simple local helper — the `issues.html` runs purely in-browser and cannot
write repository files directly, so use this script to persist exports into the
repository `issues/data.json` file.
"""
import sys
import json
from pathlib import Path

BASE = Path(__file__).parent
DATA_PATH = BASE / 'data.json'

def export_to(path=None):
    if not DATA_PATH.exists():
        print('No data.json found at', DATA_PATH)
        return 1
    data = DATA_PATH.read_text(encoding='utf-8')
    if path:
        Path(path).write_text(data, encoding='utf-8')
        print('Exported to', path)
    else:
        print(data)
    return 0

def import_from(path):
    src = Path(path)
    if not src.exists():
        print('Input file not found:', path)
        return 1
    # backup
    if DATA_PATH.exists():
        bak = BASE / f'data.json.bak'
        bak.write_text(DATA_PATH.read_text(encoding='utf-8'), encoding='utf-8')
        print('Backup saved to', bak)
    # validate JSON
    txt = src.read_text(encoding='utf-8')
    try:
        parsed = json.loads(txt)
    except Exception as e:
        print('Invalid JSON:', e)
        return 2
    # Save
    DATA_PATH.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding='utf-8')
    print('Imported and saved to', DATA_PATH)
    return 0

def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == 'export':
        out = argv[2] if len(argv) > 2 else None
        return export_to(out)
    if cmd == 'import':
        if len(argv) < 3:
            print('Please provide input JSON file to import')
            return 1
        return import_from(argv[2])
    print('Unknown command:', cmd)
    return 1

if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
