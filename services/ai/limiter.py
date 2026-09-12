"""Sync AI concurrency/rate limiter state for AI provider calls (REF5-T4).

Verbatim home of ``LimiterStore``, the prune throttle
(``_maybe_prune_hourly_usage``), the backoff predicate
(``_preset_in_backoff``) and the limiter constants previously defined in
``services/ai/llm_services.py``. This module owns the sync
``threading.BoundedSemaphore`` slots, the ``in_flight`` counter, the
mid-flight semaphore swap guard, the ``reset()`` test/restart seam, the
~1x/hour prune throttle (kept OFF the quota hot path) and the
failure-streak backoff window; ``services/ai/llm_services.py`` keeps thin
re-export aliases so existing callers keep working unchanged.

Stay-sync contract (ticket REF5-T4): NO async rewrite — the semaphore stays
a sync ``BoundedSemaphore`` acquired via executor threads, the caller
``deadline`` still bounds waits, and permits are always released onto the
captured instance. Owner decision (R13): ALL failures count toward the
streak, and after the window a preset recovers to the preferred target.

Zero AI-volume delta: no prompts, no new provider calls, timeouts untouched.
"""

import threading
import time
from collections import deque

from services import db


# Consecutive failures before a preset is temporarily sidelined (backoff), and
# the length of that backoff window. Owner decision (R13): ALL failures count
# (429, connection drop, timeout, etc.), and after the window a preset recovers
# so routing can return to the preferred/highest-priority target.
FAILURE_THRESHOLD = 3
BACKOFF_SECONDS = 60

# Prune-at-most-once-per-hour guard for the R13 hourly-usage window. Pruning
# is a write transaction; on the quota hot path this must not fire on every
# preset per request, so it is throttled to ~1x/hour per process.
_PRUNE_INTERVAL_SECONDS = 3600
_prune_lock = threading.Lock()
_last_hourly_prune: float = 0.0


class LimiterStore:
    """Explicit, injectable state for the AI limiter (R7/F7, BUG-5).

    Replaces the hidden ``_get_limiter_for_preset._states`` function-attribute
    dict. Limits (RPM/TPM/concurrency) are read **lazily from the preset on
    each acquisition** so admin edits apply immediately instead of only at the
    first request (BUG-5). State is keyed by preset name and is resettable in
    tests.
    """

    def __init__(self):
        self._states: dict[str, dict] = {}

    def limiter_for(self, preset: dict) -> dict:
        key = preset.get("name", "default")
        state = self._states.get(key)
        if state is None:
            capacity = self._max_concurrency(preset)
            state = {
                "slots": threading.BoundedSemaphore(capacity),
                "slots_capacity": capacity,
                "in_flight": 0,
                "request_times": deque(),
                "request_lock": threading.Lock(),
                "token_times": deque(),
                "token_lock": threading.Lock(),
                "consecutive_failures": 0,
                "backoff_until": 0.0,
            }
            self._states[key] = state
        else:
            # BUG-5: an admin edit to max_concurrency must take effect. We only
            # swap the semaphore when nothing is in flight, so we never release
            # a permit onto a detached instance and never let effective
            # concurrency overshoot the new limit mid-swap (the in-flight
            # permits live on the old semaphore). A shrink while requests are
            # in flight is deferred until they drain; the old (larger) limit
            # simply stays in effect briefly.
            desired = self._max_concurrency(preset)
            if desired != state["slots_capacity"] and state["in_flight"] == 0:
                state["slots"] = threading.BoundedSemaphore(desired)
                state["slots_capacity"] = desired
        return state

    def reset(self) -> None:
        """Drop all per-preset limiter state (test/restart seam)."""
        self._states.clear()

    @staticmethod
    def _max_concurrency(preset: dict) -> int:
        raw = preset.get("max_concurrency")
        return int(raw) if raw is not None else 2

    @staticmethod
    def _max_rpm(preset: dict) -> int:
        raw = preset.get("max_rpm")
        return int(raw) if raw is not None else 30

    @staticmethod
    def _max_tpm(preset: dict) -> int:
        raw = preset.get("max_tpm")
        return int(raw) if raw is not None else 0


# Module-level default store. Tests inject their own instance.
_limiter_store = LimiterStore()


def get_limiter_store() -> LimiterStore:
    """Return the module-level limiter store (injectable in tests)."""
    return _limiter_store


def _maybe_prune_hourly_usage():
    """Run the R13 prune at most once per hour per process."""
    global _last_hourly_prune
    now = time.monotonic()
    if now - _last_hourly_prune < _PRUNE_INTERVAL_SECONDS:
        return
    with _prune_lock:
        if now - _last_hourly_prune >= _PRUNE_INTERVAL_SECONDS:
            db.prune_preset_hourly_usage(hours_back=24)
            _last_hourly_prune = now


def _get_limiter_for_preset(preset: dict) -> dict:
    """Return (and lazily create) the limiter state dict for a preset."""
    return _limiter_store.limiter_for(preset)


def _preset_in_backoff(limiter: dict, now: float | None = None) -> bool:
    """True while a preset is temporarily sidelined after a failure streak."""
    if now is None:
        now = time.monotonic()
    return bool(limiter["backoff_until"]) and now < limiter["backoff_until"]
