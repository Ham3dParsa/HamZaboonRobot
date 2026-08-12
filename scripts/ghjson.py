#!/usr/bin/env python3
"""Parse JSON from stdin, tolerating a UTF-8 BOM (PowerShell redirect artifact).

Usage:
  gh api ... | python scripts/ghjson.py                  # pretty-print full JSON
  gh api ... | python scripts/ghjson.py .body            # extract a dotted path
  gh api ... | python scripts/ghjson.py comments[0].body # array-index support
  gh api ... | python scripts/ghjson.py title            # extract a top-level key

PowerShell prepends a UTF-8 BOM to piped `gh` output, so a plain
`json.load(sys.stdin)` raises JSONDecodeError. This helper decodes with
`utf-8-sig` and needs no third-party dependencies.
"""
import json
import sys


def _split_path(path: str) -> list[str]:
    """Split a dotted path into segments, keeping ``[index]`` suffixes attached.

    Example: ``comments[0].body`` -> ``["comments[0]", "body"]``.
    """
    parts: list[str] = []
    buf = ""
    for ch in path:
        if ch == ".":
            if buf:
                parts.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        parts.append(buf)
    return parts


def _apply_segment(node, seg: str):
    if "[" not in seg:
        return node[seg]
    if not seg.endswith("]") or seg.count("[") != seg.count("]"):
        raise ValueError(f"unclosed or unbalanced bracket in path segment {seg!r}")
    name, rest = seg.split("[", 1)
    if name:
        node = node[name]
    for idx_str in rest.rstrip("]").split("]["):
        try:
            idx = int(idx_str)
        except ValueError:
            raise ValueError(f"invalid array index {idx_str!r} in path segment {seg!r}")
        try:
            node = node[idx]
        except (IndexError, TypeError) as exc:
            raise type(exc)(f"index {idx} out of range in {seg!r}: {exc}")
    return node


def _navigate(data, path: str):
    node = data
    for seg in _split_path(path):
        node = _apply_segment(node, seg)
    return node


def main() -> None:
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        print(
            "ghjson: no input on stdin (expected JSON from `gh api ...`)",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        print(f"ghjson: stdin is not valid UTF-8: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"ghjson: stdin is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) > 1:
        path = sys.argv[1].lstrip(".")
        try:
            node = _navigate(data, path) if path else data
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            print(f"ghjson: path {path!r}: {exc}", file=sys.stderr)
            sys.exit(1)
        if isinstance(node, (dict, list)):
            print(json.dumps(node, ensure_ascii=False, indent=2))
        else:
            print(node)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
