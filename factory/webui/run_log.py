"""Append-only run log (R5): one owner for all cabins/steps.

Single source for ``{ts, level, event, detail}`` JSONL + ``tail(n)``.
Mechanical + arbiter workers use it now; screening wires later.
No Flask imports; file I/O only (best-effort reads, atomic appends).
"""

from __future__ import annotations

import datetime
import json
import os


class RunLog:
    """Append-only JSONL log at ``path`` (``{ts, level, event, detail}``)."""

    def __init__(self, path):
        self.path = str(path or "")

    def append(self, level, event, detail=""):
        """Append one record (best-effort, never raises)."""
        if not self.path:
            return
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            rec = {
                "ts": datetime.datetime.now(
                    datetime.timezone.utc).isoformat(),
                "level": str(level or "info"),
                "event": str(event or ""),
                "detail": str(detail or ""),
            }
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError):
            pass

    def tail(self, n=50):
        """Last ``n`` records (newest last; unreadable lines skipped)."""
        try:
            limit = int(n)
        except (TypeError, ValueError):
            limit = 50
        if limit <= 0:
            limit = 50
        try:
            with open(self.path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
        return out
