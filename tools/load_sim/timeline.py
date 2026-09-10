"""Discrete-event arrival timeline: compiler + sequential replay (T11, hybrid H1-H3).

Harness-only, zero production change: imports production modules but changes
none. Zero real AI tokens — replay uses the driver's replay-wide patient
fakes (same patch discipline as ``tools.load_sim.driver`` / ``multiday``).

Hybrid mapping (locked plan scale/plan-load-sim-60day round 6, GATE LOCKED):
- Proposal A (single discrete-event timeline, no calibration layer):
  :func:`compile_timeline` turns a cohort + day span + seed into one sorted
  event list with virtual timestamps; :func:`run_timeline_replay` consumes it
  in timestamp order through the existing driver journey machinery (real
  routers, replay-wide mocks, virtual-clock day scoping). Idle spans are
  jumped (no sleeping) by grouping on ``day_iso`` and entering one
  ``virtual_day`` per group.
- Proposal B (analytic peak-window selection plus edge oversampling):
  :func:`scan_top_windows` is the analytic pre-scan — sliding-window overlap
  counts over the compiled timeline, returning top windows with counts so a
  later capacity run can aim its concurrency at the true peaks. Edge
  oversampling itself stays where it lives: ``plan_mix.edge_scenarios``
  (gamer_herd / mass_resume / hour_boundary_thunder); nothing here duplicates
  it.

Compiler rules (H1):
- Pure: no DB, no router, no clock reads except the explicit
  ``anchor_today_iso`` input (defaults once to the real app-tz today, exactly
  like :func:`multiday.run_multiday`).
- Persona behavior is REUSED, never re-declared: attendance
  (:func:`plan_mix.attend_prob`, fluctuating 21-day wave included), abandon +
  resume delays (:func:`plan_mix.sample_session_outcome`), midnight-mass start
  hours (:func:`plan_mix.sample_day_start_hours`), query counts (persona
  ``q_lo``/``q_hi``), save-tap rate (``driver.PATIENT_SAVE_TAP_P``), and
  settings-tap rate (``multiday.FIDELITY_SETTINGS_TAP_P``).
- Deterministic per (seed, day, user): each user-day draws from
  ``multiday._day_rng(seed, day, user_id)`` with a fixed draw order.
- Think gaps between card grades are uniform 10-46s
  (``THINK_LO_S``/``THINK_HI_S`` — new ticket constants, no existing source).
- Midnight crossing is derived per event: ``eff_day``/``day_iso`` come from
  the event's virtual timestamp, so a late start plus a hours-later resume
  lands on the next day's ISO. RESUME events therefore routinely cross
  midnight; hour 06 stays start-free (inherited from the night-owl sampler).
- Partial completion and quota underuse EMERGE from the persona draws: each
  session flips its own abandon coin, so a 5-session user completes 3-4 on a
  trough day and every query/save draw follows the persona ranges.
"""

from __future__ import annotations

import datetime
import hashlib
import random

# Think-gap bounds for GRADE events (ticket-specified, no existing source).
THINK_LO_S = 10.0
THINK_HI_S = 46.0

EVENT_KINDS: tuple[str, ...] = (
    "SESSION_START",
    "GRADE",
    "SESSION_COMPLETE",
    "ABANDON",
    "RESUME",
    "QUERY_SUBMIT",
    "SAVE_TAP",
    "SETTINGS_TAP",
)

# Overlap pre-scan defaults: 15-minute sliding window, top 5 peaks.
OVERLAP_WINDOW_S = 900.0
OVERLAP_TOP_K = 5

# Gap pushed between back-to-back same-user sessions (seconds, uniform).
_SESSION_GAP_LO_S = 60.0
_SESSION_GAP_HI_S = 600.0

# Query spacing after the day's last session (seconds, uniform).
_QUERY_GAP_LO_S = 120.0
_QUERY_GAP_HI_S = 1800.0


def _alpha(i: int) -> str:
    """Two-letter suffix for ``i`` (letters only, validator-safe)."""
    j = int(i) % 676
    return chr(97 + (j // 26) % 26) + chr(97 + j % 26)


def grade_word(day: int, user_pos: int, session_idx: int, card_idx: int) -> str:
    """Unique alphabetic word for one timeline GRADE event (pure)."""
    return f"tlg{_alpha(day)}{_alpha(user_pos)}{_alpha(session_idx)}{_alpha(card_idx)}"


def query_word(day: int, user_pos: int, query_idx: int) -> str:
    """Unique alphabetic word for one timeline QUERY_SUBMIT event (pure)."""
    return f"tlq{_alpha(day)}{_alpha(user_pos)}{_alpha(query_idx)}"


def _event_rng(seed: int, day: int, user_id: int) -> random.Random:
    """Deterministic per-(seed, day, user) stream (stable under any order)."""
    digest = hashlib.md5(f"{seed}:{day}:{user_id}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "little"))


def compile_timeline(
    cohort: list[dict],
    days: int,
    seed: int,
    anchor_today_iso: str | None = None,
    plan_limits: dict | None = None,
) -> list[dict]:
    """Compile one sorted discrete-event timeline (pure, no DB/router).

    ``cohort`` is :func:`multiday.build_cohort` rows
    (``user_id``/``plan``/``persona``/``sessions``, optional
    ``cards_per_session`` — otherwise resolved per plan via
    :func:`plan_mix.resolve_plan_limits`). Emits per active user-day:
    per-session ``SESSION_START`` + one ``GRADE`` per card (10-46s think
    gaps) + ``SESSION_COMPLETE`` (or ``ABANDON`` now + ``RESUME`` hours
    later, possibly next day), then ``QUERY_SUBMIT`` events (a ``SAVE_TAP``
    trailing a share of them) and an occasional ``SETTINGS_TAP``. Output is
    sorted by ``(vtime, seq)``; every event carries ``day_iso`` derived from
    its own virtual timestamp.
    """
    from tools.load_sim.multiday import sim_day_iso
    from tools.load_sim.plan_mix import (
        _PERSONA_PARAMS,
        attend_prob,
        resolve_plan_limits,
        sample_day_start_hours,
        sample_session_outcome,
    )

    from tools.load_sim.driver import PATIENT_SAVE_TAP_P
    from tools.load_sim.multiday import FIDELITY_SETTINGS_TAP_P

    if days < 1:
        raise ValueError(f"days must be >= 1, got {days!r}")
    if anchor_today_iso is None:
        from config import APP_TZ

        anchor_today_iso = datetime.datetime.now(APP_TZ).date().isoformat()
    else:
        datetime.date.fromisoformat(anchor_today_iso)  # validate eagerly

    limits = resolve_plan_limits(plan_limits)
    events: list[dict] = []
    seq = 0

    def _emit(
        kind: str,
        user_id: int,
        persona: str,
        plan: str,
        day: int,
        t_abs: float,
        **extra,
    ) -> None:
        nonlocal seq
        eff_day = int(t_abs // 86400)
        events.append(
            {
                "kind": kind,
                "user_id": user_id,
                "persona": persona,
                "plan": plan,
                "day": day,
                "eff_day": eff_day,
                "day_iso": sim_day_iso(eff_day, days, anchor_today_iso),
                "vtime": float(t_abs),
                "t_sec": float(t_abs - eff_day * 86400),
                "crossed_midnight": eff_day != day,
                "seq": seq,
                **extra,
            }
        )
        seq += 1

    for pos, user in enumerate(cohort):
        user_id = int(user["user_id"])
        persona = str(user["persona"])
        plan = str(user["plan"])
        sessions_planned = max(1, int(user.get("sessions", 1)))
        cards = user.get("cards_per_session")
        if cards is None:
            cards = limits.get(plan, limits["free"])["cards"]
        cards = max(1, int(cards))
        for day in range(days):
            rng = _event_rng(seed, day, user_id)
            if rng.random() >= attend_prob(persona, day):
                continue  # absent this day: underuse emerges, no events
            params = _PERSONA_PARAMS[persona]
            n_queries = rng.randint(int(params["q_lo"]), int(params["q_hi"]))
            hours = sample_day_start_hours(persona, sessions_planned, rng)
            settings_tap = rng.random() < FIDELITY_SETTINGS_TAP_P
            prev_end: float | None = None
            for s in range(sessions_planned):
                base = day * 86400 + hours[s] * 3600 + rng.randint(0, 3599)
                if prev_end is not None:
                    base = max(
                        base,
                        prev_end
                        + rng.uniform(_SESSION_GAP_LO_S, _SESSION_GAP_HI_S),
                    )
                abandoned, resume_h = sample_session_outcome(
                    persona, day, rng
                )
                _emit(
                    "SESSION_START",
                    user_id,
                    persona,
                    plan,
                    day,
                    base,
                    session_idx=s,
                )
                t = base
                for c in range(cards):
                    gap = rng.uniform(THINK_LO_S, THINK_HI_S)
                    t += gap
                    _emit(
                        "GRADE",
                        user_id,
                        persona,
                        plan,
                        day,
                        t,
                        session_idx=s,
                        card_idx=c,
                        think_gap_s=gap,
                        grade=3 if abandoned else 4,
                        word=grade_word(day, pos, s, c),
                    )
                end = t + 1.0
                if abandoned:
                    _emit(
                        "ABANDON",
                        user_id,
                        persona,
                        plan,
                        day,
                        end,
                        session_idx=s,
                    )
                    delay_h = resume_h if resume_h is not None else 3.0
                    _emit(
                        "RESUME",
                        user_id,
                        persona,
                        plan,
                        day,
                        end + float(delay_h) * 3600.0,
                        session_idx=s,
                        resume_hours=float(delay_h),
                    )
                else:
                    _emit(
                        "SESSION_COMPLETE",
                        user_id,
                        persona,
                        plan,
                        day,
                        end,
                        session_idx=s,
                    )
                prev_end = end
            if prev_end is not None:
                tq = prev_end
                for q in range(n_queries):
                    tq += rng.uniform(_QUERY_GAP_LO_S, _QUERY_GAP_HI_S)
                    word = query_word(day, pos, q)
                    _emit(
                        "QUERY_SUBMIT",
                        user_id,
                        persona,
                        plan,
                        day,
                        tq,
                        query_idx=q,
                        word=word,
                    )
                    if rng.random() < PATIENT_SAVE_TAP_P:
                        _emit(
                            "SAVE_TAP",
                            user_id,
                            persona,
                            plan,
                            day,
                            tq + rng.uniform(5.0, 60.0),
                            query_idx=q,
                            word=word,
                        )
            if settings_tap:
                _emit(
                    "SETTINGS_TAP",
                    user_id,
                    persona,
                    plan,
                    day,
                    day * 86400 + rng.randint(0, 86399),
                )

    events.sort(key=lambda e: (e["vtime"], e["seq"]))
    return events


def scan_top_windows(
    events: list[dict],
    window_s: float = OVERLAP_WINDOW_S,
    top_k: int = OVERLAP_TOP_K,
) -> list[dict]:
    """Analytic overlap pre-scan over a compiled timeline (pure, Proposal B).

    Sliding window of ``window_s`` seconds anchored at each event: counts
    events with ``vtime`` inside ``[start, start + window_s]`` (two-pointer,
    O(n log n) for the sort + O(n) scan). Returns the top ``top_k`` windows
    as ``[{"window_start_vtime", "day_iso", "count"}]`` sorted by count
    descending (earliest start breaks ties), so a capacity run can aim
    concurrency at the true peaks. Empty input returns ``[]``.
    """
    if window_s <= 0:
        raise ValueError(f"window_s must be positive, got {window_s!r}")
    if top_k < 1:
        raise ValueError(f"top_k must be >= 1, got {top_k!r}")
    if not events:
        return []
    ordered = sorted(events, key=lambda e: (e["vtime"], e["seq"]))
    vtimes = [float(e["vtime"]) for e in ordered]
    scored: list[tuple[int, float, str]] = []
    j = 0
    n = len(ordered)
    for i in range(n):
        if j < i:
            j = i
        while j < n and vtimes[j] - vtimes[i] <= window_s:
            j += 1
        scored.append((j - i, vtimes[i], str(ordered[i]["day_iso"])))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "window_start_vtime": start,
            "day_iso": day_iso,
            "count": count,
        }
        for count, start, day_iso in scored[:top_k]
    ]


async def run_timeline_replay(
    events: list[dict],
    db_path,
    seed: int,
    patient: bool = True,
    fast_scale: float | None = None,
) -> dict:
    """Sequentially replay a compiled timeline through the real routers.

    Consumes ``events`` in ``(vtime, seq)`` order grouped by ``day_iso`` —
    each group runs inside one ``virtual_day`` (the virtual clock JUMPS
    across idle spans; nothing sleeps). Router-bearing kinds replay through
    the existing driver machinery (``GRADE`` via ``bot.callback_router``
    ``srs:fe``, ``QUERY_SUBMIT`` via ``bot.text_router`` ask-word,
    ``SAVE_TAP`` via the real ``toggle_save``, ``SETTINGS_TAP`` via
    ``bot.text_router``); lifecycle markers (``SESSION_START`` /
    ``SESSION_COMPLETE`` / ``ABANDON`` / ``RESUME``) are ordered markers,
    with ``SESSION_COMPLETE`` additionally driving the real
    session-completion report path. One replay-wide AI patch (patient fake
    when ``patient``); per-event latencies plus the driver/fidelity journey
    counters are recorded. ``violations`` collects per-event exceptions
    (empty on a clean run); ``top_windows`` carries the pre-scan output.
    """
    import bot
    from services import db
    from services.db import schema as db_schema

    if not isinstance(db_path, str) or not db_path:
        raise ValueError(
            "run_timeline_replay requires a db_path SQLite file string "
            f"(got {db_path!r}); refusing to poison DB_PATH with None."
        )

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
    latencies: dict[str, list[float]] = {}
    grade_latencies: list[float] = []
    errors = 0
    violations: list[str] = []
    replayed = 0

    prev_db = db.DB_PATH
    prev_schema = db_schema.DB_PATH
    prev_offline = bot._telegram_offline
    db.DB_PATH = db_path
    db_schema.DB_PATH = db_path
    db.init_db()
    bot._telegram_offline = False
    try:
        result = await _replay_ordered(
            ordered,
            seed,
            counters,
            latencies,
            grade_latencies,
            violations,
            patient,
            fast_scale,
        )
        errors, replayed = result
    finally:
        db.DB_PATH = prev_db
        db_schema.DB_PATH = prev_schema
        bot._telegram_offline = prev_offline
    return {
        "events_total": len(ordered),
        "events_replayed": replayed,
        "errors": errors,
        "violations": violations,
        "latencies_ms": latencies,
        "grade_latencies_ms": list(grade_latencies),
        "days": sorted({str(e["day_iso"]) for e in ordered}),
        "top_windows": scan_top_windows(ordered),
        **counters,
    }


async def _replay_ordered(
    ordered: list[dict],
    seed: int,
    counters: dict,
    latencies: dict[str, list[float]],
    grade_latencies: list[float],
    violations: list[str],
    patient: bool,
    fast_scale: float | None,
) -> tuple[int, int]:
    """Replay ``ordered`` events grouped by day under one virtual day each."""
    import threading
    import time
    from unittest.mock import AsyncMock, patch

    import bot
    from config.keyboards import BTN_SETTINGS
    from services import db
    from services import word_query as word_query_svc
    from tools.load_sim import driver as _driver
    from tools.load_sim.multiday import _day_rng
    from tools.load_sim.virtual_clock import virtual_day

    errors = 0
    replayed = 0

    # Phase 1 — fixture setup, sequential (same writes as the fidelity path).
    seen: dict[int, dict] = {}
    for event in ordered:
        uid = int(event["user_id"])
        if uid not in seen:
            seen[uid] = {
                "plan": str(event.get("plan", "free")),
                "persona": str(event.get("persona", "average")),
            }
    for uid, meta in seen.items():
        db.create_user_if_needed(uid, f"timeline{uid}")
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

    # Group by virtual day: the clock jumps, never sleeps, across idle spans.
    groups: dict[str, list[dict]] = {}
    for event in ordered:
        groups.setdefault(str(event["day_iso"]), []).append(event)
    day_isos = sorted(groups.keys())

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

    # Last grade context per session feeds the SESSION_COMPLETE report path.
    last_grade: dict[tuple[int, int, int], dict] = {}

    with (
        patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)),
        patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()),
        patch.object(bot, "_call_ai_limited", new=fake_step),
        patch.object(bot, "_prepare_cached_card", new=fake_prep),
        patch.object(word_query_svc, "ask", new=ask_spy),
    ):
        for group_idx, day_iso in enumerate(day_isos):
            send_rng = _day_rng(seed ^ 0x5EED, group_idx, 0xD1E1)
            with virtual_day(day_iso):
                for event in groups[day_iso]:
                    kind = str(event["kind"])
                    uid = int(event["user_id"])
                    t0 = time.perf_counter()
                    try:
                        if kind == "GRADE":
                            await _replay_grade(
                                event, uid, send_rng, counters, last_grade,
                                patient, grade_latencies, t0,
                            )
                        elif kind == "QUERY_SUBMIT":
                            await _replay_query(
                                event, uid, send_rng, counters,
                            )
                        elif kind == "SAVE_TAP":
                            await _replay_save(event, uid, counters)
                        elif kind == "SETTINGS_TAP":
                            await _replay_settings(
                                event, uid, send_rng, counters, BTN_SETTINGS,
                            )
                        elif kind == "SESSION_COMPLETE":
                            await _replay_complete(
                                event, uid, counters, last_grade,
                            )
                            counters["sessions_completed"] += 1
                        elif kind == "ABANDON":
                            counters["sessions_abandoned"] += 1
                        elif kind == "RESUME":
                            counters["sessions_resumed"] += 1
                        elif kind == "SESSION_START":
                            pass  # ordered marker; latency still recorded
                        else:  # unknown kinds never fail the sim
                            pass
                        replayed += 1
                    except Exception as exc:  # noqa: BLE001 - harness records
                        errors += 1
                        violations.append(
                            f"event {event.get('seq')} {kind} "
                            f"user {uid}: {exc!r}"
                        )
                    finally:
                        latencies.setdefault(kind, []).append(
                            (time.perf_counter() - t0) * 1000.0
                        )
    return errors, replayed


async def _replay_grade(
    event: dict,
    user_id: int,
    send_rng,
    counters: dict,
    last_grade: dict,
    patient: bool,
    grade_latencies: list[float],
    t0: float,
) -> None:
    """Seed one saved word and grade it via the real callback router."""
    import time

    import bot
    from services import db
    from tools.load_sim import driver as _driver

    word = str(event.get("word") or f"timelinegrade{event.get('seq')}")
    grade = int(event.get("grade", 4))
    card = _driver.patient_card_for(word) if patient else dict(
        _driver.CANNED_CARD
    )
    if not patient:
        card["word"] = word
    db.add_saved_word(user_id, word, "en", card)
    from services.db.schema import normalize_word

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM saved_words "
            "WHERE user_id=? AND lang=? AND normalized_word=?",
            (user_id, "en", normalize_word(word)),
        ).fetchone()
    if row is None or row["id"] is None:
        counters["card_lookup_miss"] += 1
        return
    word_id = row["id"]
    update = _driver._callback_update(
        user_id, f"srs:fe:{grade}:{user_id}:{word_id}"
    )
    ctx = _driver._make_context(send_rng, counters)

    async def _do_grade():
        await bot.callback_router(update, ctx)

    await _driver._with_db_retry(_do_grade, counters)
    grade_latencies.append((time.perf_counter() - t0) * 1000.0)
    try:
        if db.is_word_graded(user_id, word_id, "first_exposure"):
            counters["real_grades"] += 1
    except Exception:
        counters["grade_check_failed"] += 1
    last_grade[(user_id, int(event.get("day", 0)), int(event.get("session_idx", 0)))] = {
        "update": update,
        "ctx": ctx,
        "word_id": word_id,
        "plan": str(event.get("plan", "free")),
        "seq": int(event.get("seq", 0)),
    }


async def _replay_query(event: dict, user_id: int, send_rng, counters: dict) -> None:
    """Replay one word query via the real text router (fresh word)."""
    import bot
    from services import db
    from tools.load_sim import driver as _driver

    word = str(event.get("word") or f"timelinequery{event.get('seq')}")
    before_row = db.get_user(user_id)
    before = 0
    try:
        before = (before_row["words_asked_today"] or 0) if before_row else 0
    except (KeyError, IndexError, TypeError):
        before = 0
    update = _driver._text_update(user_id, word)
    ctx = _driver._make_context(send_rng, counters)
    ctx.user_data["awaiting"] = "ask_word"

    async def _do_query():
        await bot.text_router(update, ctx)

    await _driver._with_db_retry(_do_query, counters)
    after_row = db.get_user(user_id)
    after = 0
    try:
        after = (after_row["words_asked_today"] or 0) if after_row else 0
    except (KeyError, IndexError, TypeError):
        after = 0
    if after - before > 1:
        counters["quota_double_spend"] += 1


async def _replay_save(event: dict, user_id: int, counters: dict) -> None:
    """Tap save-for-review on a delivered query via the real toggle path."""
    from services import db
    from services import word_query as word_query_svc

    word = str(event.get("word") or "")
    row = db.find_unexpired_query(user_id, word, "en")
    if isinstance(row, dict):
        token = row.get("token")
    elif row is not None:
        try:
            token = row["token"]
        except (KeyError, IndexError, TypeError):
            token = None
    else:
        token = None
    if not token:
        return
    counters["save_taps"] += 1
    try:
        result = await word_query_svc.toggle_save(token, user_id)
        if getattr(result, "kind", None) == "ok":
            counters["save_tap_ok"] += 1
    except Exception:
        pass


async def _replay_settings(
    event: dict, user_id: int, send_rng, counters: dict, settings_text: str
) -> None:
    """Replay one settings tap via the real text router."""
    import bot
    from tools.load_sim import driver as _driver

    _ = event
    update = _driver._text_update(user_id, settings_text)
    ctx = _driver._make_context(send_rng, counters)

    async def _do_settings():
        await bot.text_router(update, ctx)

    await _driver._with_db_retry(_do_settings, counters)
    counters["settings_replayed"] += 1


async def _replay_complete(
    event: dict, user_id: int, counters: dict, last_grade: dict
) -> None:
    """Drive the real session-completion report path for one session."""
    from handlers.study_handler import SessionState, _app_day_str, advance_session
    from services.db.session_reports import list_recent_reports
    from tools.load_sim import driver as _driver

    key = (user_id, int(event.get("day", 0)), int(event.get("session_idx", 0)))
    stored = last_grade.get(key)
    if stored is None:
        return
    state = SessionState(
        nodes=[],
        total_cards=1,
        tier3_context={},
        study_msg_id=300000 + int(event.get("seq", 0)),
        plan=str(event.get("plan", "free")),
        graded_word_ids=[stored["word_id"]],
        before_stability={},
        # Same-day sim journey: stamp today so the
        # day-boundary guard treats it as current.
        session_date=_app_day_str(),
    )
    stored["ctx"].user_data["current_session"] = state

    async def _do_advance():
        await advance_session(stored["update"], stored["ctx"])

    await _driver._with_db_retry(_do_advance, counters)
    entries = list_recent_reports(user_id)
    if not entries or all(e.total != 1 for e in entries):
        counters["report_loss"] += 1
