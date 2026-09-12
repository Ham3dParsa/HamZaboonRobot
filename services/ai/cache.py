"""Generic thread-safe TTL cache for AI hot-path reads (REF5-T5).

Verbatim home of the ``ai_read_cache.ReadCache`` pattern (moved, not
redesigned): double-checked TTL reads on ``time.monotonic()``, per-key
invalidation, and a ``reset()`` test/restart seam. ``services/ai/ai_read_cache``
keeps the chain/cost-profile facade (same names, TTLs, and loader defaults)
so existing callers keep working unchanged.

Zero AI-volume delta: no prompts, no provider calls, no timeouts.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    """Minimal generic TTL map: ``get`` loads once per TTL, ``invalidate`` busts one key."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[Any, float]] = {}

    def get(self, key: str, loader: Callable[[], Any], *, ttl: float) -> Any:
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry is not None and now - entry[1] < ttl:
            return entry[0]
        with self._lock:
            now = time.monotonic()
            entry = self._entries.get(key)
            if entry is None or now - entry[1] >= ttl:
                value = loader()
                self._entries[key] = (value, now)
                return value
            return entry[0]

    def invalidate(self, key: str) -> None:
        """Drop one cached key so the next read refetches it."""
        with self._lock:
            self._entries.pop(key, None)

    def reset(self) -> None:
        """Drop all cached values (test/restart seam)."""
        with self._lock:
            self._entries.clear()
