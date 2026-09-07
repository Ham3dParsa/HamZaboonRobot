"""60-day multi-day load simulation (locked plan scale/plan-load-sim-60day, T1).

Harness-only: imports production modules but changes none. Zero real AI
tokens — no router/AI calls here at all; per-day activity is pure
``plan_mix`` draws, and the only production paths touched are real SQLite
writes plus the real nightly purge functions (imported, not reimplemented).

Rules (owner-locked):
- R1 day loop: :func:`run_multiday` / :func:`run_60day` drive a fixed cohort
  (default 200 users, seed) across N simulated days. Every iteration carries
  an explicit app-day ISO string into the paths that read today (streak via
  ``touch_streak_in_txn(today_iso=...)``, session rows via
  ``save_study_session(session_date=...)``, quota keys via explicit
  date-suffixed settings keys). The real clock is read ONCE to anchor the
  final simulated day to the real app-tz today (so the real nightly cutoffs
  behave as in production); production date helpers are never patched and
  never modified. Day arithmetic uses the app's own ``APP_TZ``.
- R2 cohort: the same users persist across days (stable ``user_id`` set from
  one :func:`plan_mix.sample_workload` draw — plan/persona fixed per user);
  attendance, queries, and abandon/resume evolve with the day count via
  :func:`plan_mix.attend_prob` / :func:`sample_session_outcome` (fluctuating
  21-day wave included). Per-day totals are tracked; :func:`project_cost`
  scales a cohort figure to a population with documented arithmetic.
- R3 nightly: between simulated days :func:`run_nightly` calls the REAL
  nightly purge steps (``services.retention`` order, each sync callable with
  its ``deadline`` kwarg — none needs a live scheduler context; the nightly
  job's ``context`` arg is unused by the job itself) plus a backup stand-in
  (no upload; records that backup ran). DB file bytes per day come from
  ``tools.load_sim.resources.db_file_sizes`` into a growth-curve list.
- R4 edges: :func:`run_multiday` plants probe sessions with explicit dates
  and checks, across every day edge, that expired sessions purge (no resume),
  the always-active probe streak increments, the gapped probe streak resets
  per the midnight rule, and next-day quota keys start empty. Violations are
  collected (never raised mid-loop) so the smoke test asserts zero.

Round-2 T4 (full-fidelity day mode, harness-only, zero production change):
- F1: :func:`run_fidelity_day` / :func:`run_multiday_fidelity` replay each
  active user-day through the REAL routers with the driver's journey
  machinery (grade via ``bot.callback_router``, word query via
  ``bot.text_router``, save taps via ``services.word_query.toggle_save``,
  settings via ``bot.text_router``), ordered by the 24h spread
  (:func:`plan_mix.sample_day_start_hours`). The fast pure-draws
  :func:`run_multiday` stays the CI default; fidelity is gated behind an
  explicit flag/call so CI stays fast.
- F2: patient word-query mock lives in ``tools.load_sim.driver``
  (:func:`driver.make_patient_replay_ai_fakes`, ``PATIENT_FAST_SCALE``);
  fidelity uses it, so p50 ~1.5s / p95 ~8s shape holds at scale 1.0.
- F3: 24h spread with a small midnight mass lives in ``plan_mix``
  (``NIGHT_OWL_PROB``); fidelity replays users ascending by earliest start
  hour (deterministic ``user_id`` tie-break).
- F4: the full 60-day fidelity run is measurement-only (slow, skipped in CI
  by default); CI proves the path with a tiny fidelity miniature.

Round-3 T6 (virtual clock + growth attribution + fidelity resources;
harness-only, zero production change):
- V1: each fidelity day runs inside ``tools.load_sim.virtual_clock.virtual_day``
  (in-harness ``unittest.mock`` pinning of the production date seams, restored
  on exit). Router paths that read the real today (word-query quota reserves,
  grade/query streak touches, report dates, session quota keys) therefore see
  the simulated day ISO, so quotas reset per virtual day and streaks
  accumulate across virtual days instead of collapsing onto one real day.
  Nightly purges and UTC metadata stay on real rails; date-edge LOGIC stays
  proven by the existing R4 probe tests (kept, not deleted).
- V2: per-table row counts (``saved_words``, ``review_events``,
  ``query_results``, ``session_reports``, ``llm_requests``,
  ``study_sessions``, ``ledger`` = ``session_grade_ledger``) plus file bytes
  snapshotted at virtual days 1, 7, 14, 30, 45, 60 (``growth_by_table``).
- V3: the fidelity run records ``fidelity_resources`` (RSS delta, CPU
  seconds, full p50/p90/p95/p99/max for grade latencies + loop-lag) via the
  existing ``tools.load_sim.resources`` probes.
"""

from __future__ import annotations

import datetime
import hashlib
import random

from config import APP_TZ
from tools.load_sim.plan_mix import (
    attend_prob,
    sample_session_outcome,
    sample_workload,
)
from tools.load_sim.resources import db_file_sizes
from tools.load_sim.virtual_clock import virtual_day

DEFAULT_COHORT_N = 200
DEFAULT_DAYS = 60

# V2 growth-attribution milestones (1-based virtual days) and tables.
# Display names are exactly the ticket's names; "ledger" maps to the real
# ``session_grade_ledger`` table.
GROWTH_MILESTONES: tuple[int, ...] = (1, 7, 14, 30, 45, 60)
GROWTH_TABLES: tuple[tuple[str, str], ...] = (
    ("saved_words", "saved_words"),
    ("review_events", "review_events"),
    ("query_results", "query_results"),
    ("session_reports", "session_reports"),
    ("llm_requests", "llm_requests"),
    ("study_sessions", "study_sessions"),
    ("ledger", "session_grade_ledger"),
)


def collect_growth_snapshot(db, db_path: str) -> dict:
    """Snapshot per-table row counts + file bytes (V2, harness-only).

    Reads ``COUNT(*)`` per :data:`GROWTH_TABLES` display name (table names
    come from the static allowlist above, never from input) plus
    ``db_file_sizes``. A missing/unreadable table reports ``0`` so a
    pre-migration DB never fails the long run. Returns
    ``{"tables": {display: count}, "db_bytes": int, "wal_bytes": int}``.
    """
    tables: dict[str, int] = {}
    try:
        with db.get_conn() as conn:
            for display, real in GROWTH_TABLES:
                try:
                    row = conn.execute(
                        f"SELECT COUNT(*) AS cnt FROM {real}"
                    ).fetchone()
                    tables[display] = int(row["cnt"] or 0) if row else 0
                except Exception:
                    tables[display] = 0
    except Exception:
        for display, _real in GROWTH_TABLES:
            tables.setdefault(display, 0)
    db_bytes, wal_bytes = db_file_sizes(db_path)
    return {"tables": tables, "db_bytes": db_bytes, "wal_bytes": wal_bytes}

# Probe users appended after the cohort (stable ids, never collide with the
# driver's own BASE range users since the cohort owns BASE..BASE+n-1).
_PROBE_ALWAYS_USER_ID = 950000
_PROBE_GAP_USER_ID = 950001
_PROBE_SESSION_USER_ID = 950002
_PROBE_QUOTA_USER_ID = 950003


def sim_day_iso(day: int, days: int, anchor_today_iso: str) -> str:
    """ISO app-day for simulated ``day`` (0-based) of a ``days``-day run.

    Pure date math in whole app-tz days: the final simulated day equals the
    anchor (the real app-tz today in production runs), so earlier simulated
    days sit in the past exactly as elapsed days would.
    """
    anchor = datetime.date.fromisoformat(anchor_today_iso)
    return (anchor + datetime.timedelta(days=day - (days - 1))).isoformat()


def _anchor_today_iso() -> str:
    """Read the real app-tz today once (harness anchor; production untouched)."""
    return datetime.datetime.now(APP_TZ).date().isoformat()


def build_cohort(
    n: int = DEFAULT_COHORT_N,
    seed: int = 0,
    plan_limits: dict | None = None,
) -> list[dict]:
    """Build the fixed cohort: one stable identity per user.

    A single :func:`sample_workload` draw fixes each user's ``user_id``,
    plan, and persona for the whole run; only daily activity evolves.
    """
    from tools.load_sim.driver import _BASE_USER_ID

    workload = sample_workload(n=n, seed=seed, plan_limits=plan_limits)
    return [
        {
            "user_id": _BASE_USER_ID + i,
            "plan": spec["plan"],
            "persona": spec["persona"],
            "sessions": spec["sessions"],
            "queries": spec["queries"],
        }
        for i, spec in enumerate(workload)
    ]


def _day_rng(seed: int, day: int, user_id: int) -> random.Random:
    """Deterministic per-(seed, day, user) stream (stable under any order)."""
    digest = hashlib.md5(f"{seed}:{day}:{user_id}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "little"))


def simulate_day(cohort: list[dict], day: int, seed: int) -> dict:
    """Pure per-day activity draw for the cohort on simulated ``day``.

    Returns per-day totals plus the active ``user_ids`` set (callers apply
    the real streak/quota writes with the explicit day ISO).
    """
    from tools.load_sim.plan_mix import _PERSONA_PARAMS

    active_ids: list[int] = []
    sessions = 0
    queries = 0
    abandons = 0
    resumes = 0
    for user in cohort:
        rng = _day_rng(seed, day, user["user_id"])
        if rng.random() >= attend_prob(user["persona"], day):
            continue
        active_ids.append(user["user_id"])
        sessions += int(user["sessions"])
        params = _PERSONA_PARAMS[user["persona"]]
        queries += rng.randint(int(params["q_lo"]), int(params["q_hi"]))
        abandoned, resume = sample_session_outcome(user["persona"], day, rng)
        if abandoned:
            abandons += 1
            if resume is not None:
                resumes += 1
    return {
        "day": day,
        "active": len(active_ids),
        "sessions": sessions,
        "queries": queries,
        "abandons": abandons,
        "resumes": resumes,
        "user_ids": active_ids,
    }


def project_cost(
    cohort_value: float, cohort_n: int, population_n: int
) -> float:
    """Scale a cohort-measured figure to a population (pure arithmetic).

    ``projected = cohort_value * (population_n / cohort_n)`` — linear
    scaling documented as an upper-bound planning estimate (assumes the
    cohort mix represents the population; bursty edges are not modeled).
    """
    if cohort_n <= 0:
        raise ValueError(f"cohort_n must be positive, got {cohort_n!r}")
    return float(cohort_value) * (population_n / cohort_n)


def run_nightly() -> dict:
    """Run one nightly sweep: REAL purge steps in retention order + backup stub.

    Every step comes from ``services.retention._steps()`` (imported, never
    reimplemented); the backup stand-in records that backup ran without any
    upload. Returns ``{"purges": {name: result}, "backup": {...}}``.
    """
    import time

    from services.retention import _steps

    purges: dict[str, object] = {}
    for name, fn in _steps():
        try:
            purges[name] = fn(
                deadline=time.monotonic() + 30.0,
            )
        except TypeError:
            purges[name] = fn()
        except Exception as exc:  # harness records, never hides a purge error
            purges[name] = f"FAILED: {exc!r}"
    backup = {"ran": True, "uploaded": False}
    return {"purges": purges, "backup": backup}


def run_multiday(
    n: int = DEFAULT_COHORT_N,
    seed: int = 0,
    db_path=None,
    days: int = DEFAULT_DAYS,
    plan_limits: dict | None = None,
    anchor_today_iso: str | None = None,
) -> dict:
    """Drive the fixed cohort across ``days`` simulated days on ``db_path``.

    Per day: pure activity draw, real streak touches for active users with
    the explicit day ISO, probe session/quota plants, then (between days)
    the real nightly purges + backup stand-in + DB-bytes probe. Returns
    per-day totals, the growth curve, backup runs, and edge violations.
    """
    from services import db
    from services.db import schema as db_schema
    from services.db.sessions import load_study_session, save_study_session
    from services.db.users import touch_streak_in_txn

    if not isinstance(db_path, str) or not db_path:
        raise ValueError(
            "run_multiday requires a db_path SQLite file string "
            f"(got {db_path!r}); refusing to poison DB_PATH with None."
        )
    if days < 1:
        raise ValueError(f"days must be >= 1, got {days!r}")

    prev_db = db.DB_PATH
    prev_schema = db_schema.DB_PATH
    db.DB_PATH = db_path
    db_schema.DB_PATH = db_path
    db.init_db()
    try:
        return _run_multiday(
            n,
            seed,
            db,
            days,
            plan_limits,
            anchor_today_iso or _anchor_today_iso(),
            load_study_session,
            save_study_session,
            touch_streak_in_txn,
        )
    finally:
        db.DB_PATH = prev_db
        db_schema.DB_PATH = prev_schema


def _run_multiday(
    n: int,
    seed: int,
    db,
    days: int,
    plan_limits: dict | None,
    anchor_iso: str,
    load_study_session,
    save_study_session,
    touch_streak_in_txn,
) -> dict:
    cohort = build_cohort(n=n, seed=seed, plan_limits=plan_limits)
    for user in cohort:
        db.create_user_if_needed(user["user_id"], f"multiday{user['user_id']}")
        try:
            db.set_plan(user["user_id"], user["plan"])
        except ValueError:
            pass
    for probe_id in (
        _PROBE_ALWAYS_USER_ID,
        _PROBE_GAP_USER_ID,
        _PROBE_SESSION_USER_ID,
        _PROBE_QUOTA_USER_ID,
    ):
        db.create_user_if_needed(probe_id, f"multiday{probe_id}")

    isos = [sim_day_iso(d, days, anchor_iso) for d in range(days)]
    day_totals: list[dict] = []
    growth_curve_bytes: list[int] = []
    growth_by_table: list[dict] = []
    backup_runs: list[dict] = []
    violations: list[str] = []
    gap_day = days // 2  # the one day the gap probe sits out

    for day, today_iso in enumerate(isos):
        totals = simulate_day(cohort, day, seed)
        with db.transaction() as conn:
            for user_id in totals["user_ids"]:
                touch_streak_in_txn(conn, user_id, today_iso=today_iso)
            touch_streak_in_txn(conn, _PROBE_ALWAYS_USER_ID, today_iso=today_iso)
            if day != gap_day:
                touch_streak_in_txn(conn, _PROBE_GAP_USER_ID, today_iso=today_iso)
        # Probe plants with explicit dates: one session row + one quota key.
        save_study_session(_PROBE_SESSION_USER_ID, today_iso, "{}")
        db.set_setting(
            f"sessions_used_{_PROBE_QUOTA_USER_ID}_{today_iso}", "1"
        )
        day_totals.append(
            {k: v for k, v in totals.items() if k != "user_ids"}
            | {"day_iso": today_iso}
        )

        if day < days - 1:
            nightly = run_nightly()
            backup_runs.append(
                {"day": day, "day_iso": today_iso, **nightly["backup"]}
            )
            # R4 edge checks across this day edge (explicit-date expectations):
            # the real purge keeps yesterday+today (real cutoffs) and drops
            # older session rows — an expired session must not resume.
            keep_from = (
                datetime.date.fromisoformat(anchor_iso)
                - datetime.timedelta(days=1)
            ).isoformat()
            row = load_study_session(_PROBE_SESSION_USER_ID)
            if today_iso < keep_from and row is not None:
                violations.append(
                    f"day {day}: expired session row survived purge "
                    f"({today_iso} < {keep_from})"
                )
            if today_iso >= keep_from and row is None:
                violations.append(
                    f"day {day}: live session row purged too early "
                    f"({today_iso} >= {keep_from})"
                )
            next_iso = isos[day + 1]
            if (
                db.get_setting(
                    f"sessions_used_{_PROBE_QUOTA_USER_ID}_{next_iso}", ""
                )
                != ""
            ):
                violations.append(
                    f"day {day}: next-day quota key already used ({next_iso})"
                )
        db_bytes, _wal_bytes = db_file_sizes(db.DB_PATH)
        growth_curve_bytes.append(db_bytes)
        if (day + 1) in GROWTH_MILESTONES:  # V2: 1-based milestone days
            snap = collect_growth_snapshot(db, db.DB_PATH)
            growth_by_table.append(
                {"day_n": day + 1, "day_iso": today_iso, **snap}
            )

    # End-of-run edge assertions (real production reads, explicit dates):
    with db.transaction() as conn:
        always = conn.execute(
            "SELECT streak, last_active_date FROM users WHERE user_id=?",
            (_PROBE_ALWAYS_USER_ID,),
        ).fetchone()
        gapped = conn.execute(
            "SELECT streak, last_active_date FROM users WHERE user_id=?",
            (_PROBE_GAP_USER_ID,),
        ).fetchone()
    if always is None or always["streak"] != days:
        violations.append(
            f"always-active probe streak={always['streak'] if always else None}, "
            f"want {days}"
        )
    want_gap = days - gap_day - 1
    if gapped is None or gapped["streak"] != want_gap:
        violations.append(
            f"gapped probe streak={gapped['streak'] if gapped else None}, "
            f"want {want_gap} (reset after day-{gap_day} gap)"
        )

    return {
        "total": n,
        "seed": seed,
        "days": days,
        "anchor_today_iso": anchor_iso,
        "day_totals": day_totals,
        "growth_curve_bytes": growth_curve_bytes,
        "growth_by_table": growth_by_table,
        "backup_runs": backup_runs,
        "violations": violations,
        "cohort_user_ids": [u["user_id"] for u in cohort],
    }


def run_60day(
    n: int = DEFAULT_COHORT_N,
    seed: int = 0,
    db_path=None,
    plan_limits: dict | None = None,
    anchor_today_iso: str | None = None,
) -> dict:
    """Sixty-day run (thin wrapper over :func:`run_multiday`, ``days=60``)."""
    return run_multiday(
        n=n,
        seed=seed,
        db_path=db_path,
        days=DEFAULT_DAYS,
        plan_limits=plan_limits,
        anchor_today_iso=anchor_today_iso,
    )


# ---------------------------------------------------------------------------
# Full-fidelity day mode (round-2 T4: F1-F4). Harness-only, zero production
# change, zero real AI tokens (patient fakes via the driver, same guards).
# ---------------------------------------------------------------------------

# Per-active-user settings-tap probability in fidelity replay (mirrors the
# arrival-v2 journey mix where ~5% of users take the settings journey).
FIDELITY_SETTINGS_TAP_P = 0.05


def _fidelity_alpha(i: int) -> str:
    """Two-letter suffix for ``i`` (letters only, matches driver words)."""
    return chr(97 + (i // 26) % 26) + chr(97 + i % 26)


def fidelity_word(day: int, user_pos: int, q_idx: int) -> str:
    """Unique alphabetic query word for one fidelity query (pure).

    ``"fid" + 3 x 2-letter groups`` encodes ``(day, user_pos, q_idx)`` in
    letters only, so the word validator accepts it and every query stays a
    fresh (non-duplicate) ask. Deterministic, no RNG consumed.
    """
    return f"fid{_fidelity_alpha(day)}{_fidelity_alpha(user_pos)}{_fidelity_alpha(q_idx)}"


def fidelity_grade_word(day: int, user_pos: int) -> str:
    """Unique alphabetic saved word for one fidelity grade (pure)."""
    return f"fdg{_fidelity_alpha(day)}{_fidelity_alpha(user_pos)}"


def fidelity_actions_for_day(
    cohort: list[dict],
    day: int,
    seed: int,
    query_cap: int | None = None,
    settings_tap_p: float = FIDELITY_SETTINGS_TAP_P,
) -> tuple[list[dict], dict]:
    """Plan one fidelity day's router replays (pure, no I/O; F1+F3).

    Continues each user's deterministic ``_day_rng(seed, day, user_id)``
    stream with the EXACT draw order of :func:`simulate_day` (attend check,
    query-count draw, abandon/resume draw) so the active set and pure totals
    match the fast mode; then draws the 24h start hours
    (:func:`plan_mix.sample_day_start_hours`) and the settings tap. Returns
    ``(actions, totals)`` where ``actions`` is ordered ascending by earliest
    start hour (``user_id`` tie-break) and ``totals`` mirrors
    :func:`simulate_day` counts plus ``first_hours`` for order assertions.
    One representative grade per active user-day (abandon draw decides
    full ``grade 4`` vs partial ``grade 3``); per-card grading cost is
    measured by the driver peak-slice suites, not here.
    """
    from tools.load_sim.plan_mix import (
        _PERSONA_PARAMS,
        attend_prob,
        sample_day_start_hours,
        sample_session_outcome,
    )

    actions: list[dict] = []
    active_ids: list[int] = []
    sessions = 0
    queries = 0
    abandons = 0
    resumes = 0
    for pos, user in enumerate(cohort):
        rng = _day_rng(seed, day, user["user_id"])
        if rng.random() >= attend_prob(user["persona"], day):
            continue
        active_ids.append(user["user_id"])
        sessions += int(user["sessions"])
        params = _PERSONA_PARAMS[user["persona"]]
        n_queries = rng.randint(int(params["q_lo"]), int(params["q_hi"]))
        queries += n_queries
        abandoned, resume = sample_session_outcome(user["persona"], day, rng)
        if abandoned:
            abandons += 1
            if resume is not None:
                resumes += 1
        hours = sample_day_start_hours(user["persona"], user["sessions"], rng)
        settings_tap = rng.random() < settings_tap_p
        replay_queries = n_queries if query_cap is None else min(n_queries, query_cap)
        actions.append(
            {
                "user_id": user["user_id"],
                "user_pos": pos,
                "plan": user["plan"],
                "persona": user["persona"],
                "sessions": int(user["sessions"]),
                "queries": n_queries,
                "replay_queries": replay_queries,
                "abandoned": abandoned,
                "resume_hours_later": resume,
                "start_hours": hours,
                "first_hour": min(hours) if hours else 12,
                "settings_tap": settings_tap,
            }
        )
    actions.sort(key=lambda a: (a["first_hour"], a["user_id"]))
    totals = {
        "day": day,
        "active": len(active_ids),
        "sessions": sessions,
        "queries": queries,
        "abandons": abandons,
        "resumes": resumes,
        "user_ids": active_ids,
        "first_hours": [a["first_hour"] for a in actions],
    }
    return actions, totals


async def run_fidelity_day(
    cohort: list[dict],
    day: int,
    seed: int,
    *,
    day_iso: str,
    patient: bool = True,
    fast_scale: float | None = None,
    query_cap: int | None = None,
    save_tap_p: float | None = None,
    settings_tap_p: float = FIDELITY_SETTINGS_TAP_P,
) -> dict:
    """Replay one simulated day through the REAL routers (F1+F2, async).

    Assumes ``DB_PATH`` already points at the run's SQLite file (owned by
    :func:`run_multiday_fidelity`). For each planned action (ascending start
    hour): one representative grade via ``bot.callback_router``
    (``srs:fe:<grade>``, full ``4`` or partial ``3``; full grades also drive
    the real session-completion report path), then ``replay_queries`` word
    queries via ``bot.text_router`` (``awaiting="ask_word"``), a fraction of
    which tap save-for-review via the real
    ``services.word_query.toggle_save``, plus a settings tap for
    ``settings_tap`` users. AI uses the patient fake (F2) when
    ``patient=True`` (``fast_scale`` overrides ``PATIENT_FAST_SCALE``), else
    the driver's fast fake. Same zero-token patch discipline as the driver:
    one replay-wide patch of the bot-namespace seam, providers never run.
    Returns per-day fidelity metrics (counters + replayed counts +
    ``grade_latencies_ms`` for the V3 percentiles).
    """
    import threading
    import time
    from unittest.mock import AsyncMock, patch

    import bot
    from config.keyboards import BTN_SETTINGS
    from services import db
    from services import word_query as word_query_svc
    from tools.load_sim import driver as _driver

    if save_tap_p is None:
        save_tap_p = _driver.PATIENT_SAVE_TAP_P

    actions, totals = fidelity_actions_for_day(
        cohort, day, seed, query_cap=query_cap, settings_tap_p=settings_tap_p
    )
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
    }
    sessions_replayed = 0
    queries_replayed = 0
    errors = 0
    grade_latencies: list[float] = []  # V3: per-grade router ms for percentiles
    rng_master = _day_rng(seed, day, 0xF1DE1)

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
    send_rng = _day_rng(seed ^ 0x5EED, day, 0xD1E1)

    async def _replay_action(action: dict) -> None:
        nonlocal sessions_replayed, queries_replayed, errors
        user_id = action["user_id"]
        pos = action["user_pos"]
        try:
            # One representative grade for the day's attendance.
            grade = 3 if action["abandoned"] else 4
            word = fidelity_grade_word(day, pos)
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
            else:
                word_id = row["id"]
                update = _driver._callback_update(
                    user_id, f"srs:fe:{grade}:{user_id}:{word_id}"
                )
                ctx = _driver._make_context(send_rng, counters)

                async def _do_grade():
                    await bot.callback_router(update, ctx)

                _t_grade = time.perf_counter()  # V3: grade latency probe
                await _driver._with_db_retry(_do_grade, counters)
                grade_latencies.append(
                    (time.perf_counter() - _t_grade) * 1000.0
                )
                try:
                    if db.is_word_graded(user_id, word_id, "first_exposure"):
                        counters["real_grades"] += 1
                except Exception:
                    counters["grade_check_failed"] += 1
                sessions_replayed += 1
                if not action["abandoned"]:
                    from handlers.study_handler import (
                        SessionState,
                        advance_session,
                    )
                    from services.db.session_reports import list_recent_reports

                    state = SessionState(
                        nodes=[],
                        total_cards=1,
                        tier3_context={},
                        study_msg_id=200000 + day * 1000 + pos,
                        plan=action["plan"],
                        graded_word_ids=[word_id],
                        before_stability={},
                    )
                    ctx.user_data["current_session"] = state

                    async def _do_advance():
                        await advance_session(update, ctx)

                    await _driver._with_db_retry(_do_advance, counters)
                    entries = list_recent_reports(user_id)
                    if not entries or all(e.total != 1 for e in entries):
                        counters["report_loss"] += 1
            # Word queries in hour order, each a fresh word.
            for q in range(action["replay_queries"]):
                qword = fidelity_word(day, pos, q)
                before_row = db.get_user(user_id)
                before = 0
                try:
                    before = (before_row["words_asked_today"] or 0) if before_row else 0
                except (KeyError, IndexError, TypeError):
                    before = 0
                update = _driver._text_update(user_id, qword)
                ctx = _driver._make_context(send_rng, counters)
                ctx.user_data["awaiting"] = "ask_word"

                async def _do_query():
                    await bot.text_router(update, ctx)

                await _driver._with_db_retry(_do_query, counters)
                queries_replayed += 1
                after_row = db.get_user(user_id)
                after = 0
                try:
                    after = (after_row["words_asked_today"] or 0) if after_row else 0
                except (KeyError, IndexError, TypeError):
                    after = 0
                if after - before > 1:
                    counters["quota_double_spend"] += 1
                # Save-for-review tap on a fraction of delivered queries.
                if rng_master.random() < save_tap_p:
                    row = db.find_unexpired_query(user_id, qword, "en")
                    if isinstance(row, dict):
                        token = row.get("token")
                    elif row is not None:
                        try:
                            token = row["token"]
                        except (KeyError, IndexError, TypeError):
                            token = None
                    else:
                        token = None
                    if token:
                        counters["save_taps"] += 1
                        try:
                            result = await word_query_svc.toggle_save(
                                token, user_id
                            )
                            if getattr(result, "kind", None) == "ok":
                                counters["save_tap_ok"] += 1
                        except Exception:
                            pass
            if action["settings_tap"]:
                update = _driver._text_update(user_id, BTN_SETTINGS)
                ctx = _driver._make_context(send_rng, counters)

                async def _do_settings():
                    await bot.text_router(update, ctx)

                await _driver._with_db_retry(_do_settings, counters)
                counters["settings_replayed"] += 1
        except Exception:
            errors += 1

    with (
        patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)),
        patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()),
        patch.object(bot, "_call_ai_limited", new=fake_step),
        patch.object(bot, "_prepare_cached_card", new=fake_prep),
        patch.object(word_query_svc, "ask", new=ask_spy),
    ):
        for action in actions:
            await _replay_action(action)

    _ = time.perf_counter()  # keep shape parallel to driver (no latency claim)
    return {
        "day": day,
        "day_iso": day_iso,
        "mode": "fidelity",
        "patient": patient,
        "active": totals["active"],
        "sessions": totals["sessions"],
        "queries": totals["queries"],
        "sessions_replayed": sessions_replayed,
        "queries_replayed": queries_replayed,
        "errors": errors,
        "grade_latencies_ms": list(grade_latencies),
        "first_hours": totals["first_hours"],
        **counters,
    }


async def run_multiday_fidelity(
    n: int = 8,
    seed: int = 0,
    db_path=None,
    days: int = 2,
    plan_limits: dict | None = None,
    anchor_today_iso: str | None = None,
    patient: bool = True,
    fast_scale: float | None = None,
    query_cap: int | None = None,
    save_tap_p: float | None = None,
) -> dict:
    """Drive the fixed cohort across ``days`` simulated days with full router replay.

    Same day loop, probe plants, nightly purges, growth curve, and R4 edge
    checks as :func:`run_multiday`, except each active user-day additionally
    replays through the real routers via :func:`run_fidelity_day` (F1: grade
    + word queries + save taps + settings, F2: patient AI fake, F3: 24h
    replay order). Measurement-only at 60 days (slow — skipped in CI by
    default per F4); CI uses a tiny miniature (few users, few days).
    Router side-effects on cohort users carry the VIRTUAL day's dates
    (round-3 T6: each day runs inside ``virtual_day``), so quotas reset per
    virtual day and streaks accumulate; the R4 edge assertions read the
    date-pinned probe users exactly as before. Returns the
    :func:`run_multiday` shape plus ``mode="fidelity"``, per-day
    ``fidelity_days`` metrics, V2 ``growth_by_table`` milestone snapshots,
    and V3 ``fidelity_resources``.
    """
    from services import db
    from services.db import schema as db_schema
    from services.db.sessions import load_study_session, save_study_session
    from services.db.users import touch_streak_in_txn

    if not isinstance(db_path, str) or not db_path:
        raise ValueError(
            "run_multiday_fidelity requires a db_path SQLite file string "
            f"(got {db_path!r}); refusing to poison DB_PATH with None."
        )
    if days < 1:
        raise ValueError(f"days must be >= 1, got {days!r}")

    prev_db = db.DB_PATH
    prev_schema = db_schema.DB_PATH
    db.DB_PATH = db_path
    db_schema.DB_PATH = db_path
    db.init_db()
    try:
        import bot as _bot

        prev_offline = _bot._telegram_offline
        _bot._telegram_offline = False
        try:
            return await _run_multiday_fidelity(
                n,
                seed,
                db,
                days,
                plan_limits,
                anchor_today_iso or _anchor_today_iso(),
                load_study_session,
                save_study_session,
                touch_streak_in_txn,
                patient,
                fast_scale,
                query_cap,
                save_tap_p,
            )
        finally:
            _bot._telegram_offline = prev_offline
    finally:
        db.DB_PATH = prev_db
        db_schema.DB_PATH = prev_schema


async def _run_multiday_fidelity(
    n: int,
    seed: int,
    db,
    days: int,
    plan_limits: dict | None,
    anchor_iso: str,
    load_study_session,
    save_study_session,
    touch_streak_in_txn,
    patient: bool,
    fast_scale: float | None,
    query_cap: int | None,
    save_tap_p: float | None,
) -> dict:
    import asyncio
    import datetime

    from tools.load_sim.resources import (
        cpu_seconds,
        db_file_sizes,
        lag_probe_loop,
        percentiles_ms,
        rss_bytes,
    )

    cohort = build_cohort(n=n, seed=seed, plan_limits=plan_limits)
    for user in cohort:
        db.create_user_if_needed(user["user_id"], f"multiday{user['user_id']}")
        try:
            db.set_plan(user["user_id"], user["plan"])
        except ValueError:
            pass
        db.set_user_lang_goal(user["user_id"], "en", "general")
        db.set_user_level(user["user_id"], "beginner")
        with db.transaction() as conn:
            conn.execute(
                "UPDATE users SET onboarded=1 WHERE user_id=?", (user["user_id"],)
            )
    for probe_id in (
        _PROBE_ALWAYS_USER_ID,
        _PROBE_GAP_USER_ID,
        _PROBE_SESSION_USER_ID,
        _PROBE_QUOTA_USER_ID,
    ):
        db.create_user_if_needed(probe_id, f"multiday{probe_id}")

    isos = [sim_day_iso(d, days, anchor_iso) for d in range(days)]
    day_totals: list[dict] = []
    fidelity_days: list[dict] = []
    growth_curve_bytes: list[int] = []
    growth_by_table: list[dict] = []  # V2: milestone snapshots (days 1/7/14/30/45/60)
    backup_runs: list[dict] = []
    violations: list[str] = []
    gap_day = days // 2

    # V3: resource envelope around the whole fidelity run (existing probes).
    rss_before = rss_bytes()
    cpu_before = cpu_seconds()
    lag_samples: list[float] = []
    lag_stop = asyncio.Event()
    lag_task = asyncio.create_task(
        lag_probe_loop(lag_stop, 0.05, lag_samples)
    )
    try:
        for day, today_iso in enumerate(isos):
            # V1: the whole simulated day — harness streak touches, probe
            # plants, router replay, nightly — runs under the virtual app-day
            # so quotas reset and streaks accumulate per virtual day.
            with virtual_day(today_iso):
                totals = simulate_day(cohort, day, seed)
                with db.transaction() as conn:
                    for user_id in totals["user_ids"]:
                        touch_streak_in_txn(conn, user_id, today_iso=today_iso)
                    touch_streak_in_txn(conn, _PROBE_ALWAYS_USER_ID, today_iso=today_iso)
                    if day != gap_day:
                        touch_streak_in_txn(conn, _PROBE_GAP_USER_ID, today_iso=today_iso)
                save_study_session(_PROBE_SESSION_USER_ID, today_iso, "{}")
                db.set_setting(
                    f"sessions_used_{_PROBE_QUOTA_USER_ID}_{today_iso}", "1"
                )
                fidel = await run_fidelity_day(
                    cohort,
                    day,
                    seed,
                    day_iso=today_iso,
                    patient=patient,
                    fast_scale=fast_scale,
                    query_cap=query_cap,
                    save_tap_p=save_tap_p,
                )
                fidelity_days.append(fidel)
                day_totals.append(
                    {k: v for k, v in totals.items() if k != "user_ids"}
                    | {"day_iso": today_iso}
                )

                if day < days - 1:
                    nightly = run_nightly()
                    backup_runs.append(
                        {"day": day, "day_iso": today_iso, **nightly["backup"]}
                    )
                    keep_from = (
                        datetime.date.fromisoformat(anchor_iso)
                        - datetime.timedelta(days=1)
                    ).isoformat()
                    row = load_study_session(_PROBE_SESSION_USER_ID)
                    if today_iso < keep_from and row is not None:
                        violations.append(
                            f"day {day}: expired session row survived purge "
                            f"({today_iso} < {keep_from})"
                        )
                    if today_iso >= keep_from and row is None:
                        violations.append(
                            f"day {day}: live session row purged too early "
                            f"({today_iso} >= {keep_from})"
                        )
                    next_iso = isos[day + 1]
                    if (
                        db.get_setting(
                            f"sessions_used_{_PROBE_QUOTA_USER_ID}_{next_iso}", ""
                        )
                        != ""
                    ):
                        violations.append(
                            f"day {day}: next-day quota key already used ({next_iso})"
                        )
                db_bytes, _wal_bytes = db_file_sizes(db.DB_PATH)
                growth_curve_bytes.append(db_bytes)
                if (day + 1) in GROWTH_MILESTONES:  # V2: 1-based milestone days
                    snap = collect_growth_snapshot(db, db.DB_PATH)
                    growth_by_table.append(
                        {"day_n": day + 1, "day_iso": today_iso, **snap}
                    )
    finally:
        lag_stop.set()
        await lag_task
    rss_after = rss_bytes()
    cpu_after = cpu_seconds()

    all_grades: list[float] = []
    for fidel in fidelity_days:
        all_grades.extend(fidel.get("grade_latencies_ms", []))
    fidelity_resources = {
        "rss_before": rss_before,
        "rss_after": rss_after,
        "rss_delta": rss_after - rss_before,
        "cpu_seconds": max(0.0, cpu_after - cpu_before),
        "grade_ms": percentiles_ms(all_grades),
        "loop_lag_ms": percentiles_ms(lag_samples),
    }

    with db.transaction() as conn:
        always = conn.execute(
            "SELECT streak, last_active_date FROM users WHERE user_id=?",
            (_PROBE_ALWAYS_USER_ID,),
        ).fetchone()
        gapped = conn.execute(
            "SELECT streak, last_active_date FROM users WHERE user_id=?",
            (_PROBE_GAP_USER_ID,),
        ).fetchone()
    if always is None or always["streak"] != days:
        violations.append(
            f"always-active probe streak={always['streak'] if always else None}, "
            f"want {days}"
        )
    want_gap = days - gap_day - 1
    if gapped is None or gapped["streak"] != want_gap:
        violations.append(
            f"gapped probe streak={gapped['streak'] if gapped else None}, "
            f"want {want_gap} (reset after day-{gap_day} gap)"
        )

    return {
        "total": n,
        "seed": seed,
        "days": days,
        "mode": "fidelity",
        "patient": patient,
        "anchor_today_iso": anchor_iso,
        "day_totals": day_totals,
        "fidelity_days": fidelity_days,
        "growth_curve_bytes": growth_curve_bytes,
        "growth_by_table": growth_by_table,
        "fidelity_resources": fidelity_resources,
        "backup_runs": backup_runs,
        "violations": violations,
        "cohort_user_ids": [u["user_id"] for u in cohort],
    }
