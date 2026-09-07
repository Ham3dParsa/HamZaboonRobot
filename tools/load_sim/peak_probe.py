"""Peak-window concurrent probe (T12, hybrid H1-H3).

Harness-only, zero production change: imports production modules but changes
none. Zero real AI tokens — replay uses the driver's replay-wide patient
fakes (same patch discipline as ``tools.load_sim.timeline``).

Takes the top overlap windows from the :func:`timeline.scan_top_windows`
pre-scan plus the three edge herds (``plan_mix.edge_scenarios``: gamer_herd /
mass_resume / hour_boundary_thunder) and re-replays each window's events
CONCURRENTLY under a bounded semaphore (default 20, hard cap 50) against the
same snapshot DB state, sampling ``db_busy_retries``, per-event txn latency,
and loop-lag inside vs outside windows. Reports per-window pressure metrics
(timestamp, participants, busy-retry rate, txn p95) plus an overlap histogram
(active events-per-minute distribution).

Replay mechanics are REUSED, never re-declared: per-event replay delegates to
``timeline._replay_grade/_replay_query/_replay_save/_replay_settings/
_replay_complete`` (real routers, replay-wide mocks, virtual-clock day
scoping). Concurrency notes (documented, not invented handler behavior):

- Fixture setup (create user, lang/goal, level, plan, onboarded) runs
  SEQUENTIALLY once for the union of users — scaffolding, not measured.
- Each window replays under its own replay-wide AI patch with per-window
  counters, so ``db_busy_retries`` attributes cleanly per window. Windows run
  sequentially (never nested patches on process globals); concurrency lives
  INSIDE one window via ``asyncio.Semaphore`` + ``asyncio.gather``.
- A window spanning a day boundary replays one ``virtual_day`` group at a
  time (the virtual clock pins process-global date seams, so groups stay
  sequential); events inside a group run concurrently.
- ``SESSION_COMPLETE`` events replay SEQUENTIALLY after their group's
  concurrent phase (they consume the ``last_grade`` context the concurrent
  grades populate; a complete whose grade fell outside the window is a
  no-op, exactly as in the sequential replay).
- ``last_grade`` key writes are per-key atomic under CPython's GIL; no lock
  is taken around the concurrent grade calls so the probe measures real
  contention, not harness serialization.
"""

from __future__ import annotations

import asyncio
import math
import random
import time

# Bounded-semaphore band for the concurrent probe (ticket-specified).
PROBE_MIN_CONCURRENCY = 20
PROBE_MAX_CONCURRENCY = 50

# Sequential baseline slice cap (CI-sanity; same spirit as driver batching).
BASELINE_CAP = 25

# Overlap-histogram bucket (one minute: active events per minute).
HISTOGRAM_BUCKET_S = 60.0


def _p95(values: list[float]) -> float:
    """Nearest-rank p95 (``0.0`` when empty; mirrors driver/resources rank)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return float(ordered[idx])


def _p50(values: list[float]) -> float:
    """Nearest-rank p50 (``0.0`` when empty)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(0.50 * len(ordered)) - 1))
    return float(ordered[idx])


def window_events(
    events: list[dict], start: float, window_s: float
) -> list[dict]:
    """Events with ``vtime`` inside ``[start, start + window_s]`` (pure)."""
    if window_s <= 0:
        raise ValueError(f"window_s must be positive, got {window_s!r}")
    ordered = sorted(events, key=lambda e: (e["vtime"], e["seq"]))
    return [
        e
        for e in ordered
        if float(start) <= float(e["vtime"]) <= float(start) + window_s
    ]


def overlap_histogram(
    events: list[dict], bucket_s: float = HISTOGRAM_BUCKET_S
) -> dict:
    """Active-events-per-minute distribution over a timeline (pure).

    Buckets ``[min_vtime, max_vtime]`` into ``bucket_s``-second slots and
    reports ``per_minute_counts`` plus nearest-rank ``p50``/``p95``/``max``
    over the bucket counts. Empty input reports zero buckets.
    """
    if bucket_s <= 0:
        raise ValueError(f"bucket_s must be positive, got {bucket_s!r}")
    if not events:
        return {
            "bucket_s": float(bucket_s),
            "buckets": 0,
            "per_minute_counts": [],
            "p50": 0.0,
            "p95": 0.0,
            "max": 0,
            "total": 0,
        }
    vtimes = sorted(float(e["vtime"]) for e in events)
    lo = vtimes[0]
    n_buckets = int((vtimes[-1] - lo) // bucket_s) + 1
    counts = [0] * n_buckets
    for v in vtimes:
        counts[int((v - lo) // bucket_s)] += 1
    return {
        "bucket_s": float(bucket_s),
        "buckets": n_buckets,
        "per_minute_counts": counts,
        "p50": _p50([float(c) for c in counts]),
        "p95": _p95([float(c) for c in counts]),
        "max": max(counts),
        "total": len(vtimes),
    }


def compile_edge_peaks(
    n_edge: int = 8,
    seed: int = 0,
    anchor_today_iso: str | None = None,
    days: int = 2,
    plan_limits: dict | None = None,
) -> dict:
    """Compile one timeline per edge herd and take each peak window (pure+compile).

    For each of the three ``plan_mix.EDGE_SCENARIOS`` herds, builds the named
    edge workload (:func:`plan_mix.edge_scenarios`), maps it to a timeline
    cohort (user ids offset past the driver's ``_BASE_USER_ID`` range so
    edge cohorts never collide with a main cohort on the same snapshot DB),
    compiles via :func:`timeline.compile_timeline`, and keeps the top-1
    pre-scan window. Returns ``{scenario: {"events", "window"}}``
    (``"window"`` is ``None`` when the edge timeline is empty).
    """
    from tools.load_sim.driver import _BASE_USER_ID
    from tools.load_sim.plan_mix import EDGE_SCENARIOS, edge_scenarios
    from tools.load_sim.timeline import compile_timeline, scan_top_windows

    if n_edge < 1:
        raise ValueError(f"n_edge must be >= 1, got {n_edge!r}")
    if days < 1:
        raise ValueError(f"days must be >= 1, got {days!r}")
    peaks: dict[str, dict] = {}
    for idx, name in enumerate(EDGE_SCENARIOS):
        workload = edge_scenarios(
            name, n=n_edge, seed=seed + idx, plan_limits=plan_limits
        )
        cohort = [
            {
                "user_id": _BASE_USER_ID + 50000 + idx * 10000 + i,
                "plan": spec["plan"],
                "persona": spec["persona"],
                "sessions": spec["sessions"],
                "cards_per_session": spec.get("cards_per_session", 3),
            }
            for i, spec in enumerate(workload)
        ]
        edge_events = compile_timeline(
            cohort,
            days=days,
            seed=seed + idx,
            anchor_today_iso=anchor_today_iso,
        )
        wins = scan_top_windows(edge_events, top_k=1)
        peaks[name] = {
            "events": edge_events,
            "window": wins[0] if wins else None,
        }
    return peaks


async def run_peak_probe(
    main_events: list[dict],
    db_path,
    seed: int,
    *,
    concurrency: int = PROBE_MIN_CONCURRENCY,
    window_s: float | None = None,
    top_k: int | None = None,
    patient: bool = True,
    fast_scale: float | None = None,
    edge_events: dict | None = None,
    baseline_cap: int = BASELINE_CAP,
) -> dict:
    """Concurrently probe peak overlap windows against one snapshot DB.

    ``main_events`` is a compiled timeline; its top-``top_k`` pre-scan
    windows plus the top-1 window of each ``edge_events`` entry
    (``{scenario: events | {"events": events}}``) each replay CONCURRENTLY
    under ``asyncio.Semaphore(concurrency)`` (clamped to 1..50; the
    ticket band is 20-50). A same-sized sequential slice of events OUTSIDE
    every probed window replays as the ``baseline`` (loop-lag + txn latency
    inside vs outside). Returns ``{"windows", "baseline",
    "overlap_histogram", "concurrency", "window_s"}``; per-window entries
    carry ``source`` (``"prescan_top{i}"`` or the scenario name),
    ``window_start_vtime``/``day_iso``/``count``, ``participants``,
    ``events_probed``, ``errors``, ``db_busy_retries``,
    ``busy_retry_rate``, ``txn_p95_ms``/``txn_p50_ms``,
    ``loop_lag_p95_ms``, and ``max_inflight`` (concurrency proof).
    """
    from services import db
    from services.db import schema as db_schema
    from tools.load_sim.timeline import (
        OVERLAP_TOP_K,
        OVERLAP_WINDOW_S,
        scan_top_windows,
    )

    if not isinstance(db_path, str) or not db_path:
        raise ValueError(
            "run_peak_probe requires a db_path SQLite file string "
            f"(got {db_path!r}); refusing to poison DB_PATH with None."
        )
    concurrency = max(1, min(int(concurrency), PROBE_MAX_CONCURRENCY))
    window_s = OVERLAP_WINDOW_S if window_s is None else float(window_s)
    top_k = OVERLAP_TOP_K if top_k is None else int(top_k)
    if window_s <= 0:
        raise ValueError(f"window_s must be positive, got {window_s!r}")
    if top_k < 1:
        raise ValueError(f"top_k must be >= 1, got {top_k!r}")

    ordered = sorted(main_events, key=lambda e: (e["vtime"], e["seq"]))
    top_windows = scan_top_windows(ordered, window_s=window_s, top_k=top_k)

    edge_map: dict[str, list[dict]] = {}
    for name, payload in (edge_events or {}).items():
        if isinstance(payload, dict) and "events" in payload:
            edge_map[str(name)] = list(payload["events"])
        else:
            edge_map[str(name)] = list(payload)  # type: ignore[arg-type]

    targets: list[tuple[str, dict, list[dict]]] = []
    for i, win in enumerate(top_windows):
        targets.append(
            (f"prescan_top{i}", win, window_events(ordered, win["window_start_vtime"], window_s))
        )
    for name, evts in edge_map.items():
        ev = sorted(evts, key=lambda e: (e["vtime"], e["seq"]))
        wins = scan_top_windows(ev, window_s=window_s, top_k=1)
        if wins:
            targets.append(
                (name, wins[0], window_events(ev, wins[0]["window_start_vtime"], window_s))
            )

    covered: set[int] = set()
    for _, win, _ in targets:
        lo, hi = win["window_start_vtime"], win["window_start_vtime"] + window_s
        for e in ordered:
            if lo <= float(e["vtime"]) <= hi:
                covered.add(int(e["seq"]))
    outside = [e for e in ordered if int(e["seq"]) not in covered]
    baseline_events = outside[: max(0, int(baseline_cap))]

    prev_db = db.DB_PATH
    prev_schema = db_schema.DB_PATH
    import bot

    prev_offline = bot._telegram_offline
    db.DB_PATH = db_path
    db_schema.DB_PATH = db_path
    db.init_db()
    bot._telegram_offline = False
    try:
        # Fixture setup once for the union of users (sequential scaffolding).
        seen: dict[int, dict] = {}
        for event in ordered:
            uid = int(event["user_id"])
            if uid not in seen:
                seen[uid] = {
                    "plan": str(event.get("plan", "free")),
                    "persona": str(event.get("persona", "average")),
                }
        for evts in edge_map.values():
            for event in evts:
                uid = int(event["user_id"])
                if uid not in seen:
                    seen[uid] = {
                        "plan": str(event.get("plan", "free")),
                        "persona": str(event.get("persona", "average")),
                    }
        for uid, meta in seen.items():
            db.create_user_if_needed(uid, f"peakprobe{uid}")
            db.set_user_lang_goal(uid, "en", "general")
            db.set_user_level(uid, "beginner")
            try:
                db.set_plan(uid, meta["plan"])
            except ValueError:
                pass
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE users SET onboarded=1 WHERE user_id=?", (uid,)
                )

        windows: list[dict] = []
        for source, win, evts in targets:
            if not evts:
                continue
            probed = await _probe_window_concurrent(
                evts, seed, concurrency, patient, fast_scale
            )
            participants = len({int(e["user_id"]) for e in evts})
            n = max(1, probed["events_probed"])
            windows.append(
                {
                    "source": source,
                    "window_start_vtime": win["window_start_vtime"],
                    "day_iso": win["day_iso"],
                    "count": win["count"],
                    "participants": participants,
                    "events_probed": probed["events_probed"],
                    "errors": probed["errors"],
                    "db_busy_retries": probed["db_busy_retries"],
                    "busy_retry_rate": probed["db_busy_retries"] / n,
                    "txn_p95_ms": _p95(probed["txn_ms"]),
                    "txn_p50_ms": _p50(probed["txn_ms"]),
                    "loop_lag_p95_ms": probed["loop_lag_p95_ms"],
                    "max_inflight": probed["max_inflight"],
                }
            )
        baseline_probed = await _probe_window_sequential(
            baseline_events, seed, patient, fast_scale
        )
        n_base = max(1, baseline_probed["events_probed"])
        baseline = {
            "events_probed": baseline_probed["events_probed"],
            "errors": baseline_probed["errors"],
            "db_busy_retries": baseline_probed["db_busy_retries"],
            "busy_retry_rate": baseline_probed["db_busy_retries"] / n_base,
            "txn_p95_ms": _p95(baseline_probed["txn_ms"]),
            "txn_p50_ms": _p50(baseline_probed["txn_ms"]),
            "loop_lag_p95_ms": baseline_probed["loop_lag_p95_ms"],
        }
    finally:
        db.DB_PATH = prev_db
        db_schema.DB_PATH = prev_schema
        bot._telegram_offline = prev_offline
    return {
        "concurrency": concurrency,
        "window_s": window_s,
        "windows": windows,
        "baseline": baseline,
        "overlap_histogram": overlap_histogram(ordered),
    }


async def _probe_window_concurrent(
    events: list[dict],
    seed: int,
    concurrency: int,
    patient: bool,
    fast_scale: float | None,
) -> dict:
    """Replay one window's events concurrently under a semaphore."""
    import threading
    from unittest.mock import AsyncMock, patch

    import bot
    from config.keyboards import BTN_SETTINGS
    from tools.load_sim import driver as _driver
    from tools.load_sim.resources import p95_ms
    from tools.load_sim.resources import lag_probe_loop
    from tools.load_sim.timeline import (
        _replay_complete,
        _replay_grade,
        _replay_query,
        _replay_save,
        _replay_settings,
    )
    from tools.load_sim.virtual_clock import virtual_day

    ordered = sorted(events, key=lambda e: (e["vtime"], e["seq"]))
    counters = {
        "telegram_429": 0,
        "telegram_retries": 0,
        "db_busy_retries": 0,
        "ai_timeouts": 0,
        "ai_error": 0,
        "word_query_ok": 0,
        "quota_double_spend": 0,
        "report_loss": 0,
        "real_grades": 0,
        "card_lookup_miss": 0,
        "grade_check_failed": 0,
        "save_taps": 0,
        "save_tap_ok": 0,
        "settings_replayed": 0,
        "sessions_completed": 0,
        "sessions_abandoned": 0,
        "sessions_resumed": 0,
    }
    txn_ms: list[float] = []
    grade_latencies: list[float] = []
    stats = {"errors": 0, "probed": 0}
    last_grade: dict = {}
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    in_flight = 0
    max_inflight = 0

    lock = threading.Lock()
    if patient:
        fake_step, fake_prep = _driver.make_patient_replay_ai_fakes(
            seed=seed,
            counters=counters,
            lock=lock,
            fast_scale=(
                _driver.PATIENT_FAST_SCALE if fast_scale is None else fast_scale
            ),
        )
    else:
        fake_step, fake_prep = _driver._make_replay_ai_fakes(
            seed=seed, counters=counters, ai_override=None, lock=lock
        )
    ask_spy = _driver._make_ask_spy(counters, lock)
    from services import word_query as word_query_svc

    groups: dict[str, list[dict]] = {}
    for event in ordered:
        groups.setdefault(str(event["day_iso"]), []).append(event)

    lag_samples: list[float] = []
    lag_stop = asyncio.Event()
    lag_task = asyncio.create_task(lag_probe_loop(lag_stop, 0.05, lag_samples))
    try:
        with (
            patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)),
            patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()),
            patch.object(bot, "_call_ai_limited", new=fake_step),
            patch.object(bot, "_prepare_cached_card", new=fake_prep),
            patch.object(word_query_svc, "ask", new=ask_spy),
        ):
            for day_iso in sorted(groups.keys()):
                with virtual_day(day_iso):
                    day_events = groups[day_iso]
                    deferred = [
                        e for e in day_events if str(e["kind"]) == "SESSION_COMPLETE"
                    ]
                    live = [
                        e for e in day_events if str(e["kind"]) != "SESSION_COMPLETE"
                    ]

                    async def _one(event: dict) -> None:
                        nonlocal in_flight, max_inflight
                        async with sem:
                            in_flight += 1
                            max_inflight = max(max_inflight, in_flight)
                            t0 = time.perf_counter()
                            try:
                                kind = str(event["kind"])
                                uid = int(event["user_id"])
                                rng = random.Random(
                                    (seed * 1000003 + int(event.get("seq", 0)))
                                    & 0x7FFFFFFF
                                )
                                if kind == "GRADE":
                                    async def _do_grade():
                                        await _replay_grade(
                                            event, uid, rng, counters, last_grade,
                                            patient, grade_latencies, t0,
                                        )

                                    await _driver._with_db_retry(_do_grade, counters)
                                elif kind == "QUERY_SUBMIT":
                                    async def _do_query():
                                        await _replay_query(event, uid, rng, counters)

                                    await _driver._with_db_retry(_do_query, counters)
                                elif kind == "SAVE_TAP":
                                    async def _do_save():
                                        await _replay_save(event, uid, counters)

                                    await _driver._with_db_retry(_do_save, counters)
                                elif kind == "SETTINGS_TAP":
                                    async def _do_settings():
                                        await _replay_settings(
                                            event, uid, rng, counters, BTN_SETTINGS
                                        )

                                    await _driver._with_db_retry(_do_settings, counters)
                                elif kind == "ABANDON":
                                    counters["sessions_abandoned"] += 1
                                elif kind == "RESUME":
                                    counters["sessions_resumed"] += 1
                                elif kind == "SESSION_START":
                                    pass  # ordered marker; latency still recorded
                                else:  # unknown kinds never fail the sim
                                    pass
                                stats["probed"] += 1
                            except Exception:  # noqa: BLE001 - harness records
                                stats["errors"] += 1
                                stats["probed"] += 1
                            finally:
                                txn_ms.append((time.perf_counter() - t0) * 1000.0)
                                in_flight -= 1

                    if live:
                        await asyncio.gather(*(_one(e) for e in live))
                    for event in deferred:
                        t0 = time.perf_counter()
                        try:
                            await _driver._with_db_retry(
                                lambda ev=event: _replay_complete(
                                    ev, int(ev["user_id"]), counters, last_grade
                                ),
                                counters,
                            )
                            counters["sessions_completed"] += 1
                            stats["probed"] += 1
                        except Exception:  # noqa: BLE001 - harness records
                            stats["errors"] += 1
                            stats["probed"] += 1
                        finally:
                            txn_ms.append((time.perf_counter() - t0) * 1000.0)
    finally:
        lag_stop.set()
        await lag_task
    return {
        "events_probed": stats["probed"],
        "errors": stats["errors"],
        "db_busy_retries": counters["db_busy_retries"],
        "txn_ms": txn_ms,
        "loop_lag_p95_ms": p95_ms(lag_samples),
        "max_inflight": max_inflight,
    }


async def _probe_window_sequential(
    events: list[dict],
    seed: int,
    patient: bool,
    fast_scale: float | None,
) -> dict:
    """Replay a slice sequentially (outside-window baseline, same sampling)."""
    import threading
    from unittest.mock import AsyncMock, patch

    import bot
    from config.keyboards import BTN_SETTINGS
    from tools.load_sim import driver as _driver
    from tools.load_sim.resources import p95_ms
    from tools.load_sim.resources import lag_probe_loop
    from tools.load_sim.timeline import (
        _replay_complete,
        _replay_grade,
        _replay_query,
        _replay_save,
        _replay_settings,
    )
    from tools.load_sim.virtual_clock import virtual_day

    ordered = sorted(events, key=lambda e: (e["vtime"], e["seq"]))
    counters = {
        "telegram_429": 0,
        "telegram_retries": 0,
        "db_busy_retries": 0,
        "ai_timeouts": 0,
        "ai_error": 0,
        "word_query_ok": 0,
        "quota_double_spend": 0,
        "report_loss": 0,
        "real_grades": 0,
        "card_lookup_miss": 0,
        "grade_check_failed": 0,
        "save_taps": 0,
        "save_tap_ok": 0,
        "settings_replayed": 0,
        "sessions_completed": 0,
        "sessions_abandoned": 0,
        "sessions_resumed": 0,
    }
    txn_ms: list[float] = []
    grade_latencies: list[float] = []
    errors = 0
    probed = 0
    last_grade: dict = {}

    lock = threading.Lock()
    if patient:
        fake_step, fake_prep = _driver.make_patient_replay_ai_fakes(
            seed=seed,
            counters=counters,
            lock=lock,
            fast_scale=(
                _driver.PATIENT_FAST_SCALE if fast_scale is None else fast_scale
            ),
        )
    else:
        fake_step, fake_prep = _driver._make_replay_ai_fakes(
            seed=seed, counters=counters, ai_override=None, lock=lock
        )
    ask_spy = _driver._make_ask_spy(counters, lock)
    from services import word_query as word_query_svc

    groups: dict[str, list[dict]] = {}
    for event in ordered:
        groups.setdefault(str(event["day_iso"]), []).append(event)

    lag_samples: list[float] = []
    lag_stop = asyncio.Event()
    lag_task = asyncio.create_task(lag_probe_loop(lag_stop, 0.05, lag_samples))
    try:
        with (
            patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)),
            patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()),
            patch.object(bot, "_call_ai_limited", new=fake_step),
            patch.object(bot, "_prepare_cached_card", new=fake_prep),
            patch.object(word_query_svc, "ask", new=ask_spy),
        ):
            for day_iso in sorted(groups.keys()):
                with virtual_day(day_iso):
                    for event in groups[day_iso]:
                        kind = str(event["kind"])
                        uid = int(event["user_id"])
                        rng = random.Random(
                            (seed * 1000003 + int(event.get("seq", 0)))
                            & 0x7FFFFFFF
                        )
                        t0 = time.perf_counter()
                        try:
                            if kind == "GRADE":
                                async def _do_grade():
                                    await _replay_grade(
                                        event, uid, rng, counters, last_grade,
                                        patient, grade_latencies, t0,
                                    )

                                await _driver._with_db_retry(_do_grade, counters)
                            elif kind == "QUERY_SUBMIT":
                                async def _do_query():
                                    await _replay_query(event, uid, rng, counters)

                                await _driver._with_db_retry(_do_query, counters)
                            elif kind == "SAVE_TAP":
                                async def _do_save():
                                    await _replay_save(event, uid, counters)

                                await _driver._with_db_retry(_do_save, counters)
                            elif kind == "SETTINGS_TAP":
                                async def _do_settings():
                                    await _replay_settings(
                                        event, uid, rng, counters, BTN_SETTINGS
                                    )

                                await _driver._with_db_retry(_do_settings, counters)
                            elif kind == "SESSION_COMPLETE":
                                async def _do_complete():
                                    await _replay_complete(
                                        event, uid, counters, last_grade
                                    )

                                await _driver._with_db_retry(_do_complete, counters)
                                counters["sessions_completed"] += 1
                            elif kind == "ABANDON":
                                counters["sessions_abandoned"] += 1
                            elif kind == "RESUME":
                                counters["sessions_resumed"] += 1
                            elif kind == "SESSION_START":
                                pass  # ordered marker; latency still recorded
                            else:  # unknown kinds never fail the sim
                                pass
                            probed += 1
                        except Exception:  # noqa: BLE001 - harness records
                            errors += 1
                            probed += 1
                        finally:
                            txn_ms.append((time.perf_counter() - t0) * 1000.0)
    finally:
        lag_stop.set()
        await lag_task
    return {
        "events_probed": probed,
        "errors": errors,
        "db_busy_retries": counters["db_busy_retries"],
        "txn_ms": txn_ms,
        "loop_lag_p95_ms": p95_ms(lag_samples),
    }
