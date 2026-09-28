"""Shared pinned-paths store for the factory web consoles (T06).

Single owner of ``<DATA_ROOT>/webui/pinned_paths.json`` (OQ-4: one
shared factory file — all consoles/worktrees see the same pins).
Pure path helpers + atomic JSON persistence; no Flask imports, so the
server stays a thin caller.

Entries: ``{name, path, kind}`` with ``kind`` in ``dir|file``. Paths
are validated under the factory data root OR under an existing browse
root (the caller passes both — this module never resolves roots
itself, so there is exactly one resolver per root kind). Writes are
atomic tmp+replace with fsync; DELETE matches by exact name only (no
destructive cascade).
"""

from __future__ import annotations

import json
import os

PIN_FILE_REL = os.path.join("webui", "pinned_paths.json")
PIN_KINDS = ("dir", "file")


def pins_path(data_root: str) -> str:
    """Absolute pins-file path under ``data_root`` (never creates dirs)."""
    return os.path.join(str(data_root or ""), PIN_FILE_REL)


def _inside(candidate: str, root: str) -> bool:
    """True when abspath ``candidate`` is ``root`` or below it."""
    try:
        cand_abs = os.path.abspath(candidate)
        root_abs = os.path.abspath(root)
    except (OSError, ValueError, TypeError):
        return False
    try:
        return os.path.commonpath([root_abs, cand_abs]) == root_abs
    except (OSError, ValueError):
        return False


def load_pins(data_root: str) -> list:
    """Read the shared pins list (missing/corrupt → ``[]``, never raises)."""
    path = pins_path(data_root)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    pins = payload.get("pins") if isinstance(payload, dict) else None
    if not isinstance(pins, list):
        return []
    clean = []
    for row in pins:
        if not isinstance(row, dict):
            continue
        name, path_value, kind = (row.get("name"), row.get("path"),
                                  row.get("kind"))
        if (isinstance(name, str) and name.strip()
                and isinstance(path_value, str) and path_value.strip()
                and kind in PIN_KINDS):
            clean.append({"name": name.strip(),
                          "path": path_value.strip(), "kind": kind})
    return clean


def _atomic_write_json(path: str, payload: dict) -> None:
    """Atomic tmp+replace JSON write with fsync (raises OSError on failure)."""
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def save_pins(data_root: str, pins: list) -> list:
    """Persist ``pins`` atomically; returns the stored list."""
    stored = [{"name": str(p["name"]).strip(),
               "path": str(p["path"]).strip(),
               "kind": p["kind"]} for p in pins]
    _atomic_write_json(pins_path(data_root), {"pins": stored})
    return stored


def validate_pin_path(path_value: str, kind: str, data_root: str,
                       extra_roots=None) -> str:
    """Validate a pin target; returns the abspath or raises ValueError.

    Allowed when the abspath sits under ``data_root`` or under one of
    ``extra_roots`` (existing browse roots passed by the caller), and
    the target exists with the matching ``kind`` (dir→isdir,
    file→isfile).
    """
    if kind not in PIN_KINDS:
        raise ValueError("kind must be one of %s" % "/".join(PIN_KINDS))
    raw = str(path_value or "").strip()
    if not raw:
        raise ValueError("path is required")
    cand_abs = os.path.abspath(raw)
    roots = [str(data_root or "").strip()]
    for root in (extra_roots or []):
        try:
            label = root.get("path") if isinstance(root, dict) else root
        except Exception:
            continue
        if isinstance(label, str) and label.strip():
            roots.append(label.strip())
    allowed = any(r and _inside(cand_abs, r) for r in roots if r)
    if not allowed:
        raise ValueError("path is outside the data root and browse roots")
    if kind == "dir" and not os.path.isdir(cand_abs):
        raise ValueError("not a directory: %s" % raw)
    if kind == "file" and not os.path.isfile(cand_abs):
        raise ValueError("not a file: %s" % raw)
    return cand_abs


def add_pin(data_root: str, name: str, path_value: str, kind: str,
            extra_roots=None) -> dict:
    """Add (or rename-update) a pin; persists and returns the entry."""
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("name is required")
    resolved = validate_pin_path(path_value, kind, data_root,
                                 extra_roots=extra_roots)
    pins = [p for p in load_pins(data_root) if p["name"] != clean_name]
    entry = {"name": clean_name, "path": resolved, "kind": kind}
    pins.append(entry)
    save_pins(data_root, pins)
    return entry


def remove_pin(data_root: str, name: str) -> bool:
    """Remove the pin with the exact ``name``; True when one was removed."""
    clean_name = str(name or "").strip()
    if not clean_name:
        return False
    pins = load_pins(data_root)
    kept = [p for p in pins if p["name"] != clean_name]
    if len(kept) == len(pins):
        return False
    save_pins(data_root, kept)
    return True
