"""Virtual app-day clock for multi-day load simulation (round 3, T6: V1).

Harness-only: imports production modules but changes none. Production code
is untouched — every seam below is pinned with ``unittest.mock.patch`` from
this harness module, active only inside :func:`virtual_day`, and restored on
exit (verified by the round-3 proof tests).

Why: ``tools.load_sim.multiday.run_multiday_fidelity`` replays each
simulated day through the REAL routers, but the router paths read the REAL
today (quota reserves, streak touches, report dates), so all 60 simulated
days collapse onto one real app-day: word-query quotas cap after day 1 and
grade-path streak touches overwrite the harness's explicit-date touches.
The virtual clock pins the production date seams to the simulated day ISO
for the duration of one simulated day, so each simulated day runs as its
own app-day and the long run accumulates across virtual days.

Pinned seams (exactly these; ``hasattr``-guarded so a production refactor
fails loudly instead of silently skipping a seam):
- ``config._app_today`` — quota-status reads (``users.get_quota_status``),
  ``scheduling.word_query_usage_text`` (both late-import it per call, so
  patching the owner covers them).
- ``services.utils.formatting._app_today`` — display baseline ``_app_date``.
- ``services.scheduling._today_str`` — session quota keys
  (``_session_key``/``consume``/``release``/``budget``).
- ``handlers.study_handler._app_today`` — ``session_reports.session_date``
  display field written by the completion path fidelity replays.
- ``handlers.study_handler._today_str`` — same function object as the
  scheduling one, re-bound at handler import; patched separately.
- ``handlers.user._app_today`` — grammar-tip usage display.
- ``bot._app_today`` — entry-point namespace binding (same owner function).
- ``services.db.schema._today`` — ``_current_daily_count`` quota reads.
- ``services.db.users._today`` — ``reserve/release_word_query``,
  ``reserve/release_grammar_tip``, ``touch_streak`` (the grade/query router
  paths call it without ``today_iso``), learning-stats ``due``.
- ``services.db.words._today`` — ``next_review`` writes, due checks.
- ``services.db.cost_tracking._today`` — ``llm_requests`` dating (90-day
  purge window is wider than the 60-virtual-day span, so nothing purges
  either way).
- ``services.db._today`` — ``add_grammar_tip`` dating.

Deliberately NOT pinned (documented, not an oversight):
- ``services.db.sessions._today`` — only feeds the stale-session purge
  cutoff, which stays on the real clock so the existing anchor-based R4
  edge expectations hold verbatim; no fidelity write path needs it (probe
  session rows use explicit ``session_date``).
- ``services.scheduling.purge_old_session_slot_keys`` internals (reads
  ``datetime.now`` directly) — transient per-day keys only; the long-run
  checks need just the next-day key empty, which holds either way.
- All UTC processing metadata (``_utc_now``, ``created_at``,
  ``graded_at``, ``expires_at``) per AGENTS.md section 5.
- UTC/TTL purges (review-events 90d, session-reports retention,
  query-result expiry) — unaffected inside a 60-virtual-day window.
- ``handlers.admin_stats._today`` — admin paths are never replayed.

Date-edge LOGIC stays proven by the existing R4 probe tests (kept, not
deleted); the virtual clock only lets the long run accumulate.
"""

from __future__ import annotations

import datetime
from contextlib import ExitStack, contextmanager
from unittest.mock import patch


def _parse_day_iso(day_iso: str) -> datetime.date:
    """Validate ``day_iso`` eagerly so a bad ISO fails before patching."""
    return datetime.date.fromisoformat(day_iso)


@contextmanager
def virtual_day(day_iso: str):
    """Pin all production date seams to ``day_iso`` (harness-only).

    Usage::

        with virtual_day("2026-07-08"):
            ...  # every router call sees 2026-07-08 as app-today

    All patches are reverted on exit, even on exception.
    """
    day = _parse_day_iso(day_iso)
    iso = day.isoformat()

    targets: list[tuple[str, object]] = [
        ("config._app_today", lambda: iso),
        ("services.utils.formatting._app_today", lambda: iso),
        ("services.scheduling._today_str", lambda: iso),
        ("handlers.study_handler._app_today", lambda: iso),
        ("handlers.study_handler._today_str", lambda: iso),
        ("handlers.user._app_today", lambda: iso),
        ("bot._app_today", lambda: iso),
        ("services.db.schema._today", lambda: day),
        ("services.db.users._today", lambda: day),
        ("services.db.words._today", lambda: day),
        ("services.db.cost_tracking._today", lambda: day),
        ("services.db._today", lambda: day),
    ]
    patches = []
    with ExitStack() as stack:
        for target, new in targets:
            module_name, _, attr = target.rpartition(".")
            module = __import__(module_name, fromlist=[attr])
            if not hasattr(module, attr):
                raise AttributeError(
                    f"virtual_day seam vanished: {target} "
                    "(production refactored the date seam; "
                    "update tools/load_sim/virtual_clock.py instead of "
                    "touching production)"
                )
            patches.append(stack.enter_context(patch.object(module, attr, new)))
        _ = patches  # entered for effect; restoration is the stack's job
        yield iso
