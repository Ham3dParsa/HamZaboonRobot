"""Nightly retention sweep (T3, plan-retention R7).

Single owner of the 03:30 APP_TIMEZONE purge run: calls the existing T1/T2
purge functions in cheapest-lock-first order, each in its own bounded batch
with a short yield between steps, stopping cleanly on overrun (leftover steps
run the next night). No purge logic lives here — only ordering + budget.

``bot.py`` wires :func:`nightly_retention_job` via ``run_daily`` at 03:30 and
pins the backup at 05:30, so full backups never land in the purge hour.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# Wall-clock budget for one nightly run; on overrun the remaining steps stop
# cleanly and run the next night (idempotent purges make this safe).
NIGHTLY_BUDGET_SECONDS = 600.0
# Short cooperative yield between steps so the event loop breathes.
_STEP_YIELD_SECONDS = 0.1

_NIGHTLY_LOCK = asyncio.Lock()


def _steps():
    """Build the ordered (name, sync_callable) purge steps (T3 ticket order).

    Built lazily so tests can patch purge functions before the job runs.
    Every callable takes no arguments (purge defaults carry the bounded
    batch); each runs via ``to_thread`` in its own short transactions —
    never a transaction held across an await.
    """
    from services import db
    from services import scheduling
    from services import tts_cache

    return (
        ("hourly_usage", db.prune_preset_hourly_usage),
        ("query_expired", db.cleanup_expired_query_results),
        ("session_reports", db.purge_expired_session_reports),
        ("config", db.prune_config_tests),
        ("llm", db.purge_old_llm_requests),
        ("reviews", db.prune_old_review_events),
        ("sessions", db.purge_stale_study_sessions),
        ("slots", scheduling.purge_old_session_slot_keys),
        ("tts", tts_cache.purge_tts_cache),
        ("grammar", db.purge_grammar_tips),
    )


#: Step names in nightly order (cheap-lock-first per locked ticket T3).
NIGHTLY_STEP_NAMES: tuple[str, ...] = (
    "hourly_usage",
    "query_expired",
    "session_reports",
    "config",
    "llm",
    "reviews",
    "sessions",
    "slots",
    "tts",
    "grammar",
)


async def nightly_retention_job(context) -> dict[str, object]:
    """Run one nightly purge sweep; return per-step outcomes + skipped steps.

    Run-once per night via ``run_daily`` (03:30 APP_TIMEZONE). Skips when a
    previous run is still holding the lock; checks the time budget before
    each step and stops cleanly on overrun for the next night.
    """
    if _NIGHTLY_LOCK.locked():
        logger.info("nightly retention skipped: previous run still active")
        return {"ran": [], "skipped": list(NIGHTLY_STEP_NAMES)}
    async with _NIGHTLY_LOCK:
        deadline = time.monotonic() + NIGHTLY_BUDGET_SECONDS
        ran: list[str] = []
        skipped: list[str] = []
        for name, fn in _steps():
            if time.monotonic() >= deadline:
                skipped.append(name)
                continue
            try:
                result = await asyncio.to_thread(fn)
                logger.info("nightly retention step %s done result=%r", name, result)
            except Exception:
                logger.exception("nightly retention step %s failed", name)
            ran.append(name)
            await asyncio.sleep(_STEP_YIELD_SECONDS)
        if skipped:
            logger.warning(
                "nightly retention overran budget; deferred to next night: %s",
                skipped,
            )
        return {"ran": ran, "skipped": skipped}
