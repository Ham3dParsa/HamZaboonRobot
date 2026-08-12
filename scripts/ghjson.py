#!/usr/bin/env python3
"""Parse JSON from stdin, tolerating a UTF-8 BOM (PowerShell redirect artifact).

Usage:
  gh api ... | python scripts/ghjson.py            # pretty-print full JSON
  gh api ... | python scripts/ghjson.py .body      # extract a dotted path
  gh api ... | python scripts/ghjson.py title      # extract a top-level key

PowerShell prepends a UTF-8 BOM to piped `gh` output, so a plain
`json.load(sys.stdin)` raises JSONDecodeError. This helper decodes with
`utf-8-sig` and needs no third-party dependencies.
"""
import json
import sys


def main() -> None:
    raw = sys.stdin.buffer.read()
    text = raw.decode("utf-8-sig")
    data = json.loads(text)

    if len(sys.argv) > 1:
        path = sys.argv[1].lstrip(".")
        node = data
        if path:
            for part in path.split("."):
                node = node[part]
        if isinstance(node, (dict, list)):
            print(json.dumps(node, ensure_ascii=False, indent=2))
        else:
            print(node)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
