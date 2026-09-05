"""Session scheduling — daily session quotas per plan.

Quota is stored in the settings table as:
    sessions_used_{user_id}_{date} = "<integer>"

A session is one invocation of handle_study_start(). Quota is consumed
once at the top of handle_study_start(), before build_session_list().
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta

from config import APP_TZ
from services.db import get_conn, get_setting
from services.db.schema import transaction

logger = logging.getLogger(__name__)

_app_tz = APP_TZ

# ---- Per-user sliding-window rate guard (Phase 01, plan-27) ----
# Lightweight in-memory memory-only guard for costly actions (5/10s).
# No DB transaction across await; pure deque per (user_id, action).
# Memory-only: resets on restart (documented tradeoff); no settings persistence.
# Atomicity: sync prune+check+append is atomic under _rate_lock (threading.Lock)
# and the outer per-user asyncio.Lock in bot.py serializes same-user callbacks.
# Phase 02 polish: split srs_grade into srs_grade_review / srs_grade_first.
_RATE_WINDOW_SECONDS: float = 10.0
_RATE_LIMIT: int = 5
THROTTLE_TEXT = "⏳ لطفاً کمی صبر کنید و دوباره تلاش کنید."

# Per-action limits (all 5/10s now; hook for future settings-driven tuning).
_RATE_LIMITS: dict[str, int] = {
    "study_start": 5,
    "query_ask": 5,
    "grammar_tip": 5,
    "srs_grade_review": 5,
    "srs_grade_first": 5,
    # Backward compat: legacy "srs_grade" bucket still honoured (tests + old callers).
    "srs_grade": 5,
}


def _limit_for(action: str) -> int:
    return _RATE_LIMITS.get(action, _RATE_LIMIT)

# In-memory buckets: (user_id, action) -> deque of timestamps (float epoch UTC)
_buckets: dict[tuple[int, str], deque[float]] = {}
_rate_lock = threading.Lock()


def _now_ts(now: float | datetime | None) -> float:
    if now is None:
        return time.time()  # UTC epoch
    if isinstance(now, datetime):
        # Use UTC timestamp for metadata consistency (AGENTS.md §5)
        return now.timestamp()
    return float(now)


def _prune(bucket: deque[float], now_ts: float) -> None:
    cutoff = now_ts - _RATE_WINDOW_SECONDS
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()


def _clear_rate_buckets() -> None:
    """Test helper: clear all in-memory rate buckets."""
    with _rate_lock:
        _buckets.clear()


def _today_str() -> str:
    return datetime.now(_app_tz).date().isoformat()


def _session_key(user_id: int) -> str:
    return f"sessions_used_{user_id}_{_today_str()}"


def _get_used(user_id: int) -> int:
    raw = get_setting(_session_key(user_id), "0")
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 0


def _max_sessions_for_plan(plan: str) -> int:
    """Return the plan's daily session budget (max_sessions) from the DB.

    Missing/deactivated plans fall back to the free-plan value.
    """
    from config import max_sessions_for_plan as _db_max_sessions
    return _db_max_sessions(plan)


def daily_session_budget(user_id: int, plan: str) -> dict:
    total = _max_sessions_for_plan(plan)
    used = _get_used(user_id)
    return {
        "total": total,
        "remaining": max(0, total - used),
        "used": used,
        "plan": plan,
    }


def consume_session_slot(user_id: int, plan: str = "free") -> bool:
    """Atomically check quota and increment usage if under limit.

    Returns True if a slot was consumed (session may proceed).
    Returns False if quota exceeded (session must not start).
    """
    limit = _max_sessions_for_plan(plan)
    key = _session_key(user_id)
    with transaction() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        try:
            used = int(row["value"]) if row else 0
        except (ValueError, TypeError):
            used = 0
        if used >= limit:
            logger.info(
                "session quota exceeded user_id=%s used=%s limit=%s",
                user_id, used, limit,
            )
            return False
        new_val = str(used + 1)
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, new_val),
        )
    logger.debug(
        "consume_session_slot user_id=%s used=%s->%s limit=%s",
        user_id, used, used + 1, limit,
    )
    return True


def release_session_slot(user_id: int) -> None:
    """Decrement session usage (rollback on error or empty session)."""
    key = _session_key(user_id)
    with transaction() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        try:
            used = int(row["value"]) if row else 0
        except (ValueError, TypeError):
            used = 0
        if used <= 0:
            return
        new_val = str(used - 1)
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, new_val),
        )
    logger.debug(
        "release_session_slot user_id=%s used=%s->%s",
        user_id, used, used - 1,
    )


# Strict shape of a per-day quota key: sessions_used_{user_id}_{YYYY-MM-DD}.
# Anything else (other settings, malformed keys) is never touched by the purge.
_SLOT_KEY_RE = re.compile(r"^sessions_used_(\d+)_(\d{4}-\d{2}-\d{2})$")


def purge_old_session_slot_keys(*, batch: int = 500, deadline: float | None = None) -> int:
    """Delete per-day session quota keys older than yesterday (nightly-safe).

    Keeps today's and yesterday's keys (app-tz dates); only quota reads today's
    key (``_session_key``/``_get_used``), so older keys have no live reader.
    DELETE-only, in chunks of ``batch`` keys with each chunk in its own short
    ``transaction()``. Stops chunking at ``deadline`` (monotonic) when set.
    Function only — no scheduler wiring (per T1 contract).
    Returns the number of keys deleted.
    """
    keep_from = (datetime.now(_app_tz).date() - timedelta(days=1)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key FROM settings WHERE key LIKE 'sessions_used\\_%' ESCAPE '\\'"
        ).fetchall()
    stale = [
        r["key"]
        for r in rows
        if (m := _SLOT_KEY_RE.match(r["key"])) and m.group(2) < keep_from
    ]
    deleted = 0
    for i in range(0, len(stale), batch):
        if deadline is not None and time.monotonic() >= deadline:
            break
        chunk = stale[i:i + batch]
        with transaction() as conn:
            cur = conn.execute(
                f"DELETE FROM settings WHERE key IN ({','.join('?' * len(chunk))})",
                chunk,
            )
            deleted += cur.rowcount or 0
    if stale:
        logger.debug(
            "purge_old_session_slot_keys deleted=%s keep_from=%s",
            deleted, keep_from,
        )
    return deleted


def word_query_usage_text(row: dict) -> str:
    """Return today's word-query usage summary line for a users row.

    Single source for the learner-facing usage line (moved from
    services/utils/formatting.py to the scheduling domain per #22 —
    formatting stays pure escaping only). Reads the plan spec via
    ``daily_word_query_limit_for_plan``.
    """
    from config import _app_today, daily_word_query_limit_for_plan

    used = row["words_asked_today"] or 0
    if row["words_asked_date"] != _app_today():
        used = 0
    limit = daily_word_query_limit_for_plan(row["plan"] or "free")
    if limit < 0:
        return f"📊 استفاده امروز: {used} / نامحدود"
    remaining = max(limit - used, 0)
    return f"📊 استفاده امروز: {used}/{limit} · باقی‌مانده: {remaining}"


# ---- Public per-user rate guard API ----


def is_rate_limited(
    user_id: int, action: str, now: float | datetime | None = None
) -> bool:
    """Return True if user has hit the sliding-window limit for action (read-only)."""
    key = (user_id, action)
    limit = _limit_for(action)
    with _rate_lock:
        bucket = _buckets.get(key)
        if not bucket:
            return False
        _prune(bucket, _now_ts(now))
        if not bucket:
            _buckets.pop(key, None)
            return False
        return len(bucket) >= limit


def try_acquire_per_user_slot(
    user_id: int, action: str, now: float | datetime | None = None
) -> bool:
    """Atomic check+record: return True if slot acquired (allowed), False if throttled.

    Prunes, checks limit, and appends atomically under _rate_lock; outer
    per-user asyncio.Lock in bot.py serializes same-user callbacks.
    No HAMZABAN_TEST_MODE bypass — test isolation is via the autouse
    _per_user_rate_cleared fixture which clears _buckets before each test.
    """
    key = (user_id, action)
    ts = _now_ts(now)
    limit = _limit_for(action)
    with _rate_lock:
        bucket = _buckets.get(key)
        if bucket is None:
            bucket = deque()
            _buckets[key] = bucket
        _prune(bucket, ts)
        if len(bucket) >= limit:
            if not bucket:
                _buckets.pop(key, None)
            return False
        bucket.append(ts)
        return True


def record_per_user_action(
    user_id: int, action: str, now: float | datetime | None = None
) -> None:
    """Record an action occurrence (legacy, prefer try_acquire)."""
    key = (user_id, action)
    ts = _now_ts(now)
    with _rate_lock:
        bucket = _buckets.get(key)
        if bucket is None:
            bucket = deque()
            _buckets[key] = bucket
        _prune(bucket, ts)
        bucket.append(ts)


def check_per_user_rate(
    user_id: int, action: str, now: float | datetime | None = None
) -> bool:
    """Return True if allowed (not rate-limited). Does not record."""
    return not is_rate_limited(user_id, action, now=now)
