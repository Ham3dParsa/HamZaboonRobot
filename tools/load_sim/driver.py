"""100-user load-simulation driver (locked plan scale/plan-load-sim-100, T1).

Replays ``n`` synthetic users from :func:`tools.load_sim.plan_mix.sample_workload`
through the REAL routers (``bot.callback_router`` / ``bot.text_router``) against
a real SQLite file at ``db_path``, with a mocked Telegram ``Context.bot``
(``AsyncMock`` send 2-8ms, 1-2% HTTP 429 with ``retry_after`` 0.01-0.05s) and a
mocked AI step (canned card JSON after a short sleep, 2% ``TimeoutError``).

NOTE: grade-path p95 here measures harness overhead plus mock sleeps, not
production Telegram/AI latency — the sleeps are ms-scale harness stand-ins so
the 100-user suite stays fast with no timeout. Telegram 429s still route
through the real production retry path (real ``RetryAfter`` raised, real
retry with its ``retry_after`` sleep) and are counted as ``telegram_429`` /
``telegram_retries``; the locked R4 gates (p95 < 800ms etc.) are unchanged.

Tool-only: imports production modules but changes none. Zero real AI tokens —
the AI steps (``bot._call_ai_limited`` / ``bot._prepare_cached_card``) are
patched ONCE per replay with word-parameterized fakes (a single replay-wide
patch, never per-task: concurrent enter/exit on process globals raced and
restored the wrong mock mid-replay), and ``services.word_query.ask`` is
wrapped replay-wide with an outcome-kind counting spy; ``services.ai``
providers never run.

Journey mapping (documented, no invented handler behavior):
- ``full_session``: seed one saved word, grade it first-exposure via the REAL
  ``bot.callback_router`` (``srs:fe:<grade>:<user_id>:<word_id>`` — standalone
  grade, no session needed), then drive report creation through the REAL
  session completion path (``advance_session`` on a completing single-card
  ``SessionState``, then reload via ``list_recent_reports``; missing reload
  counts as ``report_loss``).
- ``partial``: same grade path with grade 3, no report (abandoned session).
- ``word_query``: REAL ``bot.text_router`` with ``awaiting="ask_word"`` and a
  unique alphabetic word; quota delta must be 0 (AI timeout → released) or 1.
- ``settings``: REAL ``bot.text_router`` with the main-menu settings button.
- ``idle``: no router call, ~0ms latency.

``bot_mock`` / ``ai_mock`` are optional overrides (``None`` builds the spec'd
mocks above). Users run SEQUENTIALLY (deterministic per seed, no SQLite
lock contention); Telegram 429s are retried by the shared production retry
path with their real ``retry_after`` sleeps, counted as ``telegram_retries``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import random
import sqlite3
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import RetryAfter

from tools.load_sim.plan_mix import edge_scenarios, sample_workload

logger = logging.getLogger(__name__)

CANNED_CARD = {
    "word": "hello",
    "phonetic": "/həˈloʊ/",
    "fa_meaning": "سلام",
    "fa_explanation": "برای سلام کردن.",
    "examples": ["Hello!"],
    "example_translations": ["سلام!"],
    "synonyms": [],
    "antonyms": [],
    "grammar_tip": "",
}

_BASE_USER_ID = 900000
_SEND_LO_S = 0.002
_SEND_HI_S = 0.008
_RETRY_AFTER_LO_S = 0.01
_RETRY_AFTER_HI_S = 0.05
_P429 = 0.015  # 1.5% — inside the locked 1-2% band
_AI_TIMEOUT_P = 0.02

# Patient word-query mock (locked plan scale/plan-load-sim-60day round 2, F2).
# Real learner queries wait on the AI pipeline: p50 ~1.5s, p95 ~8s, with a
# small timeout rate. The replay scales every sampled delay by
# ``PATIENT_FAST_SCALE`` (documented FAST factor) so CI miniatures stay fast
# while the SHAPE (lognormal, mu=ln(1.5), sigma=1.0 → p50 1.5s, p95 ~7.8s)
# is measured at scale 1.0. A fraction ``PATIENT_SAVE_TAP_P`` of delivered
# queries taps save-for-review via the real ``services.word_query.toggle_save``.
_PATIENT_P50_S = 1.5
_PATIENT_P95_S = 8.0
_PATIENT_TIMEOUT_P = 0.03
PATIENT_FAST_SCALE = 0.01
PATIENT_SAVE_TAP_P = 0.30
_PATIENT_MU = 0.4054651081081644  # ln(1.5) → lognormal median 1.5s
_PATIENT_SIGMA = 1.0  # p95 = exp(mu + 1.645*sigma) ≈ 7.8s

# Realistic card fixtures shaped like real AI cards: every entry carries the
# full card schema (word, phonetic, fa_meaning, explanation, examples with
# translations, synonyms, grammar tip). The patient fake clones one template
# per queried word (word field overridden) so downstream persistence and
# rendering see production-shaped payloads. Zero real AI tokens — canned only.
PATIENT_CARDS: list[dict] = [
    {
        "word": "resilient",
        "phonetic": "/rɪˈzɪl.jənt/",
        "fa_meaning": "انعطاف‌پذیر؛ تاب‌آور",
        "fa_explanation": "کسی یا چیزی که بعد از سختی سریع به حالت عادی برمی‌گردد.",
        "examples": [
            "She is resilient after every failure.",
            "A resilient team adapts to change.",
        ],
        "example_translations": [
            "او بعد از هر شکستی تاب‌آور است.",
            "یک تیم تاب‌آور با تغییر سازگار می‌شود.",
        ],
        "synonyms": ["tough", "adaptable"],
        "antonyms": ["fragile"],
        "grammar_tip": "صفت است: قبل از اسم می‌آید (a resilient child).",
    },
    {
        "word": "hesitate",
        "phonetic": "/ˈhez.ɪ.teɪt/",
        "fa_meaning": "تردید کردن؛ درنگ کردن",
        "fa_explanation": "وقتی مطمئن نیستی و قبل از عمل مکث می‌کنی.",
        "examples": [
            "Don't hesitate to ask for help.",
            "He hesitated before answering.",
        ],
        "example_translations": [
            "برای کمک خواستن تردید نکن.",
            "او قبل از جواب دادن درنگ کرد.",
        ],
        "synonyms": ["pause", "waver"],
        "antonyms": [],
        "grammar_tip": "با مصدر با to می‌آید: hesitate to decide.",
    },
    {
        "word": "brilliant",
        "phonetic": "/ˈbrɪl.jənt/",
        "fa_meaning": "درخشان؛ بسیار باهوش",
        "fa_explanation": "هم برای نور درخشان و هم برای هوش زیاد به کار می‌رود.",
        "examples": [
            "She has a brilliant idea.",
            "The stars look brilliant tonight.",
        ],
        "example_translations": [
            "او یک ایده درخشان دارد.",
            "ستاره‌ها امشب درخشان به نظر می‌رسند.",
        ],
        "synonyms": ["bright", "clever"],
        "antonyms": ["dull"],
        "grammar_tip": "صفت است: هم برای اشیا هم انسان (a brilliant student).",
    },
]

# 5k peak-slice replay bounds (locked plan scale/plan-load-sim-5k, T1).
_5K_MAX_CONCURRENCY = 50
_5K_BATCH_SIZE = 200
_5K_STAGGER_S = 0.01
_5K_LAG_INTERVAL_S = 0.05


def _p95_ms(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return ordered[idx]


_CPU_NOTE = (
    "process cpu_times delta around the replay, attributed per journey "
    "kind by wall-time share (exact under sequential replay; proportional "
    "estimate under concurrent replay); cpu_total_ms None means no process "
    "CPU source was available (psutil + resource both absent)"
)


def _cpu_total_ms(start_s: float | None, end_s: float | None) -> float | None:
    """CPU ms consumed between two :func:`cpu_process_seconds` samples."""
    if start_s is None or end_s is None:
        return None
    return max(0.0, (end_s - start_s) * 1000.0)


def _cpu_ms_per_journey(
    cpu_total_ms: float | None, latencies: dict[str, list[float]]
) -> dict[str, float]:
    """Attribute replay-total CPU ms to journey kinds by wall-time share.

    Process ``cpu_times`` is process-wide (no per-task isolation), so
    per-kind values split the replay total proportionally to each kind's
    summed wall latency. Thread-safe: inputs are merged single-threaded
    (sequential loop / ordered gather merge); this function only reads.
    Returns ``{}`` when CPU accounting was unavailable.
    """
    if cpu_total_ms is None:
        return {}
    sums = {j: sum(v) for j, v in latencies.items()}
    total = sum(sums.values())
    if total <= 0:
        return {j: 0.0 for j in sums}
    return {j: cpu_total_ms * s / total for j, s in sums.items()}


def _words_asked(db, user_id: int) -> int:
    row = db.get_user(user_id)
    if row is None:
        return 0
    try:
        return row["words_asked_today"] or 0
    except (KeyError, IndexError, TypeError):
        return 0


def _live_plan_limits(db) -> dict | None:
    """Read sessions/cards-per-session per plan from the live plans table.

    Returns ``{code: {"sessions": s, "cards": c}}`` for plan_mix (R1 input),
    or ``None`` when unreadable so plan_mix falls back to its DB-seed mirror.
    """
    try:
        rows = db.list_plans(active_only=True) or db.list_plans()
    except Exception:
        return None
    limits: dict = {}
    try:
        for row in rows:
            limits[row["name"]] = {
                "sessions": int(row["max_sessions"]),
                "cards": int(row["cards_per_session"]),
            }
    except (KeyError, TypeError, ValueError):
        return None
    return limits or None


def _arrival_summary(workload: list[dict]) -> dict:
    """Summarize arrival metadata (personas, sessions, abandons, queries)."""
    personas: dict[str, int] = {}
    sessions_total = 0
    abandoned = 0
    resumed = 0
    queries_total = 0
    for user in workload:
        personas[user.get("persona", "?")] = personas.get(user.get("persona", "?"), 0) + 1
        sessions_total += int(user.get("sessions", 1))
        if user.get("abandoned"):
            abandoned += 1
        if user.get("resume_hours_later") is not None:
            resumed += 1
        queries_total += int(user.get("queries", 0))
    return {
        "sessions_total": sessions_total,
        "personas": personas,
        "abandoned": abandoned,
        "resumed": resumed,
        "queries_total": queries_total,
    }


def _alpha_suffix(i: int) -> str:
    return chr(97 + (i // 26) % 26) + chr(97 + i % 26)


def _text_update(user_id: int, text: str):
    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.message = message
    update.effective_message = message
    update.callback_query = None
    return update


def _callback_update(user_id: int, data: str):
    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = user_id
    update.callback_query = query
    update.callback_query.data = data
    update.effective_message = MagicMock()
    return update


def _make_send(rng: random.Random, counters: dict):
    async def _send(*args, **kwargs):
        await asyncio.sleep(rng.uniform(_SEND_LO_S, _SEND_HI_S))
        if rng.random() < _P429:
            counters["telegram_429"] += 1
            counters["telegram_retries"] += 1
            raise RetryAfter(rng.uniform(_RETRY_AFTER_LO_S, _RETRY_AFTER_HI_S))
        msg = MagicMock()
        msg.message_id = rng.randint(1, 10**9)
        return msg

    return _send


def _make_context(rng: random.Random, counters: dict, send=None):
    send = send or _make_send(rng, counters)
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock(side_effect=send)
    ctx.bot.edit_message_text = AsyncMock(side_effect=send)
    ctx.bot.edit_message_reply_markup = AsyncMock(side_effect=send)
    ctx.bot.send_chat_action = AsyncMock()
    return ctx


def _make_replay_ai_fakes(*, seed: int, counters: dict, ai_override, lock):
    """Build the single replay-wide AI fake pair (no per-task global patching).

    One ``(fake_step, fake_prep)`` pair is patched onto ``bot`` for the whole
    replay, so concurrent journeys never enter/exit per-task ``patch.object``
    on process globals (nested enter/exit restored the wrong mock mid-replay
    and exposed the real provider). The step fake reads the queried word from
    the call args (``generate_card`` passes it as ``user_prompt``) and answers
    a canned card for THAT word; the 2% ``TimeoutError`` draw uses a
    per-(seed, user, word) RNG so it stays deterministic under any task
    interleaving. Counter bumps take ``lock`` (the step runs in worker threads
    via ``asyncio.to_thread``).
    """
    if callable(ai_override):
        return ai_override, ai_override

    def _draw_rng(user_id, word: str) -> random.Random:
        digest = hashlib.md5(
            f"{seed}:{user_id}:{word}".encode("utf-8")
        ).digest()
        return random.Random(int.from_bytes(digest[:8], "little"))

    def fake_step(function, *args, deadline=None, **kwargs):
        user_id = kwargs.get("user_id")
        word = kwargs.get("user_prompt")
        if not isinstance(word, str) or not word:
            maybe_card = args[0] if args else None
            if isinstance(maybe_card, dict) and maybe_card.get("word"):
                word = str(maybe_card["word"])
            else:
                word = "hello"
        draw = _draw_rng(user_id, word)
        time.sleep(draw.uniform(0.010, 0.030))
        if draw.random() < _AI_TIMEOUT_P:
            with lock:
                counters["ai_timeouts"] += 1
            raise asyncio.TimeoutError("simulated AI timeout")
        canned = dict(CANNED_CARD)
        canned["word"] = word
        return canned

    def fake_prep(data, **kwargs):
        return dict(data)

    return fake_step, fake_prep


def patient_delay_seconds(rng: random.Random) -> float:
    """Sample one unscaled patient word-query delay in seconds (pure).

    Lognormal(mu=ln(1.5), sigma=1.0): median 1.5s, p95 ~7.8s (documents the
    locked p50 ~1.5s / p95 ~8s shape). Callers scale by ``PATIENT_FAST_SCALE``
    for practical runtimes; distribution tests measure this function at
    scale 1.0 so the FAST factor never hides a shape regression.
    """
    return float(rng.lognormvariate(_PATIENT_MU, _PATIENT_SIGMA))


def patient_card_for(word: str, rng: random.Random | None = None) -> dict:
    """Return a production-shaped canned card for ``word`` (pure, no I/O).

    Clones one :data:`PATIENT_CARDS` template (index from the word hash, so
    the choice never consumes the caller's RNG stream) and overrides the
    ``word`` field. Shape matches the real AI card schema the validators
    accept; zero real AI tokens.
    """
    digest = hashlib.md5(str(word).encode("utf-8")).digest()
    template = PATIENT_CARDS[int.from_bytes(digest[:2], "little") % len(PATIENT_CARDS)]
    card = dict(template)
    card["word"] = word
    card["examples"] = list(template["examples"])
    card["example_translations"] = list(template["example_translations"])
    card["synonyms"] = list(template["synonyms"])
    card["antonyms"] = list(template.get("antonyms", []))
    return card


def make_patient_replay_ai_fakes(
    *,
    seed: int,
    counters: dict,
    lock,
    fast_scale: float = PATIENT_FAST_SCALE,
):
    """Build the patient word-query AI fake pair (F2, zero real AI tokens).

    Same replay-wide patching discipline as :func:`_make_replay_ai_fakes`
    (one shared pair per replay, per-(seed, user, word) deterministic draws).
    The step fake sleeps ``patient_delay_seconds(draw) * fast_scale`` then
    answers :func:`patient_card_for` for THAT word; with probability
    ``_PATIENT_TIMEOUT_P`` it raises ``asyncio.TimeoutError`` (counted as
    ``ai_timeouts``) instead. Only the bot-namespace seam is patched by the
    caller; providers never run.
    """
    if fast_scale <= 0:
        raise ValueError(f"fast_scale must be positive, got {fast_scale!r}")

    def _draw_rng(user_id, word: str) -> random.Random:
        digest = hashlib.md5(
            f"{seed}:{user_id}:{word}".encode("utf-8")
        ).digest()
        return random.Random(int.from_bytes(digest[:8], "little"))

    def fake_step(function, *args, deadline=None, **kwargs):
        user_id = kwargs.get("user_id")
        word = kwargs.get("user_prompt")
        if not isinstance(word, str) or not word:
            maybe_card = args[0] if args else None
            if isinstance(maybe_card, dict) and maybe_card.get("word"):
                word = str(maybe_card["word"])
            else:
                word = "hello"
        draw = _draw_rng(user_id, word)
        if draw.random() < _PATIENT_TIMEOUT_P:
            with lock:
                counters["ai_timeouts"] += 1
            raise asyncio.TimeoutError("simulated patient AI timeout")
        delay_s = patient_delay_seconds(draw) * fast_scale
        time.sleep(max(0.0, delay_s))
        return patient_card_for(word, draw)

    def fake_prep(data, **kwargs):
        return dict(data)

    return fake_step, fake_prep


def _make_ask_spy(counters: dict, lock):
    """Build a replay-wide ``services.word_query.ask`` wrapper counting kinds.

    Delegates to the real ``ask``; records ``word_query_ok`` for delivered
    cards and ``ai_error`` for provider failures, so the flow test can tell
    faithful mock deliveries apart from real-path errors. Patched once per
    replay (one shared wrapper object — no per-task patch state to race).
    ``bot`` resolves ``word_query.ask`` on the module at call time, so
    patching the service attribute intercepts the handler path.
    """
    from services import word_query as word_query_svc

    real_ask = word_query_svc.ask

    async def ask_spy(user_id, text, *, generate_card, skip_duplicate=False):
        result = await real_ask(
            user_id,
            text,
            generate_card=generate_card,
            skip_duplicate=skip_duplicate,
        )
        kind = getattr(result, "kind", None)
        if kind == "ok":
            with lock:
                counters["word_query_ok"] += 1
        elif kind == "ai_error":
            with lock:
                counters["ai_error"] += 1
        return result

    return ask_spy


async def _with_db_retry(fn, counters: dict, attempts: int = 3):
    last = None
    for attempt in range(attempts):
        try:
            return await fn()
        except sqlite3.OperationalError as exc:
            text = str(exc).lower()
            if "locked" in text or "busy" in text:
                counters["db_busy_retries"] += 1
                await asyncio.sleep(0.05 * (attempt + 1))
                last = exc
                continue
            raise
    if last is not None:
        raise last
    raise RuntimeError("load_sim db retry called with attempts=0")


async def _with_db_retry_sync(op, counters: dict, attempts: int = 3):
    """Retry a SYNC db op across SQLite locked/busy, counting busy retries.

    Each attempt runs via ``asyncio.to_thread`` so concurrent journeys never
    block the event loop on a contended SQLite file; counter bumps stay on
    the loop thread (same ``db_busy_retries`` semantics as
    :func:`_with_db_retry`). Non-locked ``OperationalError`` re-raises
    immediately for the caller's own handling.
    """
    last = None
    for attempt in range(attempts):
        try:
            return await asyncio.to_thread(op)
        except sqlite3.OperationalError as exc:
            text = str(exc).lower()
            if "locked" in text or "busy" in text:
                counters["db_busy_retries"] += 1
                await asyncio.sleep(0.05 * (attempt + 1))
                last = exc
                continue
            raise
    if last is not None:
        raise last
    raise RuntimeError("load_sim db retry called with attempts=0")


async def run_load(n, seed, db_path, bot_mock=None, ai_mock=None, workload_override=None) -> dict:
    """Replay ``n`` synthetic users (seed ``seed``) against ``db_path``.

    Returns a metrics dict with per-journey latencies (ms) plus counters:
    ``telegram_429``, ``telegram_retries``, ``db_busy_retries``,
    ``ai_timeouts``, ``ai_error``, ``word_query_ok``, ``quota_double_spend``,
    ``report_loss``, ``plan_fallbacks``, ``real_grades``,
    ``card_lookup_miss``, ``grade_check_failed``.

    Arrival-v2: the workload is sampled with the LIVE plans-table limits
    (R1 input to plan_mix); ``workload_override`` (e.g. an edge_scenarios
    workload from :func:`run_edge_scenario`) replays as-is instead.
    """
    import bot
    from services import db
    from services.db import schema as db_schema

    prev_db = db.DB_PATH
    prev_schema = db_schema.DB_PATH
    prev_offline = bot._telegram_offline
    db.DB_PATH = db_path
    db_schema.DB_PATH = db_path
    db.init_db()
    bot._telegram_offline = False
    try:
        return await _run(n, seed, bot, db, bot_mock, ai_mock, workload_override)
    finally:
        db.DB_PATH = prev_db
        db_schema.DB_PATH = prev_schema
        bot._telegram_offline = prev_offline


async def run_edge_scenario(
    scenario: str,
    n: int,
    seed: int,
    db_path,
    bot_mock=None,
    ai_mock=None,
    plan_limits=None,
    workload_override=None,
) -> dict:
    """Replay one R3 named edge scenario; returns the run_load metrics.

    The edge workload is built with the LIVE plans-table limits (or the
    ``plan_limits`` override when given; ``workload_override`` replays
    as-is instead, mirroring :func:`run_load`) and every metric flows
    through the existing counters (plus ``scenario`` naming the edge and
    ``arrival`` summarizing its personas/sessions).
    """
    import bot
    from services import db
    from services.db import schema as db_schema

    prev_db = db.DB_PATH
    prev_schema = db_schema.DB_PATH
    prev_offline = bot._telegram_offline
    db.DB_PATH = db_path
    db_schema.DB_PATH = db_path
    db.init_db()
    bot._telegram_offline = False
    try:
        if workload_override is None:
            workload = edge_scenarios(
                scenario,
                n=n,
                seed=seed,
                plan_limits=(
                    plan_limits if plan_limits is not None else _live_plan_limits(db)
                ),
            )
        else:
            workload = workload_override
        metrics = await _run(n, seed, bot, db, bot_mock, ai_mock, workload)
        metrics["scenario"] = scenario
        return metrics
    finally:
        db.DB_PATH = prev_db
        db_schema.DB_PATH = prev_schema
        bot._telegram_offline = prev_offline


async def _run(n: int, seed: int, bot, db, bot_mock, ai_mock, workload_override=None) -> dict:
    from config.keyboards import BTN_SETTINGS

    rng = random.Random(seed)
    if workload_override is None:
        workload = sample_workload(
            n=n, seed=seed, plan_limits=_live_plan_limits(db)
        )
    else:
        workload = workload_override
    arrival = _arrival_summary(workload)
    counters = {
        "telegram_429": 0,
        "telegram_retries": 0,
        "db_busy_retries": 0,
        "ai_timeouts": 0,
        "ai_error": 0,
        "word_query_ok": 0,
        "quota_double_spend": 0,
        "report_loss": 0,
        "plan_fallbacks": 0,
        "real_grades": 0,
        "card_lookup_miss": 0,
        "grade_check_failed": 0,
    }
    latencies: dict[str, list[float]] = {}
    grade_latencies: list[float] = []
    errors = 0

    ai_override = ai_mock

    def _ctx():
        if isinstance(bot_mock, MagicMock):
            ctx = MagicMock()
            ctx.user_data = {}
            ctx.bot = bot_mock
            return ctx
        if bot_mock is not None and not callable(bot_mock):
            ctx = MagicMock()
            ctx.user_data = {}
            ctx.bot = bot_mock
            return ctx
        if callable(bot_mock):
            return _make_context(rng, counters, send=bot_mock)
        return _make_context(rng, counters)

    # Single replay-wide AI patch (never per-task: concurrent enter/exit on
    # process globals raced). Only the bot-namespace seam is patched; the
    # real services.ai.llm_services entry stays live so the flow test's
    # zero-token guard there fires loudly on any direct reach.
    ai_lock = threading.Lock()
    fake_step, fake_prep = _make_replay_ai_fakes(
        seed=seed, counters=counters, ai_override=ai_override, lock=ai_lock
    )
    ask_spy = _make_ask_spy(counters, ai_lock)
    from services import word_query as _word_query_svc

    from tools.load_sim.resources import (
        cpu_process_seconds,
        percentile_summary,
    )

    cpu_start_s = cpu_process_seconds()
    with (
        patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)),
        patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()),
        patch.object(bot, "_call_ai_limited", new=fake_step),
        patch.object(bot, "_prepare_cached_card", new=fake_prep),
        patch.object(_word_query_svc, "ask", new=ask_spy),
    ):
        for i, spec in enumerate(workload):
            user_id = _BASE_USER_ID + i
            journey = spec["journey"]
            t0 = time.perf_counter()
            graded = False
            try:
                db.create_user_if_needed(user_id, f"loadsim{i}")
                db.set_user_lang_goal(user_id, "en", "general")
                db.set_user_level(user_id, "beginner")
                try:
                    db.set_plan(user_id, spec["plan"])
                except ValueError:
                    counters["plan_fallbacks"] += 1
                    logger.warning(
                        "load_sim set_plan fallback user_id=%s plan=%s",
                        user_id,
                        spec.get("plan"),
                    )
                with db.transaction() as conn:
                    conn.execute(
                        "UPDATE users SET onboarded=1 WHERE user_id=?", (user_id,)
                    )

                if journey == "idle":
                    pass
                elif journey == "settings":
                    update = _text_update(user_id, BTN_SETTINGS)
                    ctx = _ctx()

                    async def _do_settings():
                        await bot.text_router(update, ctx)

                    await _with_db_retry(_do_settings, counters)
                elif journey == "word_query":
                    word = f"loadword{_alpha_suffix(i)}"
                    before = _words_asked(db, user_id)
                    update = _text_update(user_id, word)
                    ctx = _ctx()
                    ctx.user_data["awaiting"] = "ask_word"

                    async def _do_query():
                        await bot.text_router(update, ctx)

                    await _with_db_retry(_do_query, counters)
                    after = _words_asked(db, user_id)
                    if after - before > 1:
                        counters["quota_double_spend"] += 1
                elif journey in ("full_session", "partial"):
                    grade = 4 if journey == "full_session" else 3
                    word = f"gradeword{_alpha_suffix(i)}"
                    card = dict(CANNED_CARD)
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
                        logger.warning(
                            "load_sim card lookup miss user_id=%s word=%s",
                            user_id,
                            word,
                        )
                        continue
                    word_id = row["id"]
                    update = _callback_update(
                        user_id, f"srs:fe:{grade}:{user_id}:{word_id}"
                    )
                    ctx = _ctx()

                    async def _do_grade():
                        await bot.callback_router(update, ctx)

                    await _with_db_retry(_do_grade, counters)
                    try:
                        if db.is_word_graded(user_id, word_id, "first_exposure"):
                            counters["real_grades"] += 1
                    except sqlite3.Error:
                        counters["grade_check_failed"] += 1
                        logger.warning(
                            "load_sim grade check failed user_id=%s word_id=%s",
                            user_id,
                            word_id,
                        )
                    grade_latencies.append(
                        (time.perf_counter() - t0) * 1000.0
                    )
                    graded = True
                    if journey == "full_session":
                        from handlers.study_handler import (
                            SessionState,
                            _app_day_str,
                            advance_session,
                        )
                        from services.db.session_reports import (
                            list_recent_reports,
                        )

                        state = SessionState(
                            nodes=[],
                            total_cards=1,
                            tier3_context={},
                            study_msg_id=100000 + i,
                            plan=spec["plan"],
                            graded_word_ids=[word_id],
                            before_stability={},
                            # Same-day sim journey: stamp today so the
                            # day-boundary guard treats it as current.
                            session_date=_app_day_str(),
                        )
                        ctx.user_data["current_session"] = state
                        await advance_session(update, ctx)
                        entries = list_recent_reports(user_id)
                        if not entries or all(
                            e.total != 1 for e in entries
                        ):
                            counters["report_loss"] += 1
                else:  # unknown journey kinds never fail the sim
                    pass
            except Exception:
                errors += 1
                logger.exception(
                    "load_sim journey failed user_id=%s journey=%s",
                    user_id,
                    journey,
                )
            finally:
                dt_ms = (time.perf_counter() - t0) * 1000.0
                if journey not in ("full_session", "partial"):
                    latencies.setdefault(journey, []).append(dt_ms)
                else:
                    # grade latency already recorded above; on paths that
                    # never graded (lookup miss), use this run's own time
                    # instead of a stale previous grade.
                    latencies.setdefault(journey, []).append(
                        grade_latencies[-1]
                        if graded and grade_latencies
                        else dt_ms
                    )

    cpu_total_ms = _cpu_total_ms(cpu_start_s, cpu_process_seconds())
    total = max(1, n)
    grade_p95 = _p95_ms(grade_latencies)
    return {
        "total": n,
        "seed": seed,
        "errors": errors,
        "error_rate": errors / total,
        "latencies_ms": latencies,
        "grade_latencies_ms": list(grade_latencies),
        "grade_p95_ms": grade_p95,
        "grade_pct": percentile_summary(grade_latencies),
        "cpu_total_ms": cpu_total_ms,
        "cpu_ms_per_journey": _cpu_ms_per_journey(cpu_total_ms, latencies),
        "cpu_note": _CPU_NOTE,
        "telegram_429": counters["telegram_429"],
        "telegram_retries": counters["telegram_retries"],
        "db_busy_retries": counters["db_busy_retries"],
        "ai_timeouts": counters["ai_timeouts"],
        "ai_error": counters["ai_error"],
        "word_query_ok": counters["word_query_ok"],
        "quota_double_spend": counters["quota_double_spend"],
        "report_loss": counters["report_loss"],
        "plan_fallbacks": counters["plan_fallbacks"],
        "real_grades": counters["real_grades"],
        "card_lookup_miss": counters["card_lookup_miss"],
        "grade_check_failed": counters["grade_check_failed"],
        "journey_counts": {
            j: len(v) for j, v in latencies.items()
        },
        "personas": arrival["personas"],
        "arrival": arrival,
    }


async def run_load_5k(
    n=2800,
    seed=0,
    *,
    db_path,
    concurrency=_5K_MAX_CONCURRENCY,
    bot_mock=None,
    ai_mock=None,
    plan_limits=None,
    workload_override=None,
) -> dict:
    """Replay the peak slice (``n`` synthetic users, seed ``seed``) in staggered
    batches with bounded asyncio concurrency.

    Same mocked edges and counters as :func:`run_load` (mocked Telegram
    ``Context.bot`` sends with 1-2% 429s through the real retry path, canned
    card JSON with 2% ``TimeoutError`` via the SAME sync fake — blocking
    ``time.sleep`` kept so the mocked edge is identical; zero real AI
    tokens). Users run in batches of ``_5K_BATCH_SIZE`` with a
    ``_5K_STAGGER_S`` pause between batches; at most ``concurrency`` users run
    at once (``asyncio.Semaphore``). Arrival order is preserved per batch
    (``asyncio.gather`` returns in order; latency lists merge in index order).

    Returns the :func:`run_load` metrics plus ``concurrency``, ``batches``,
    ``txn_p95_ms``, and a ``resources`` dict (``rss_before``, ``rss_after``,
    ``rss_delta``, ``loop_lag_p95_ms``, ``db_bytes``, ``wal_bytes``,
    ``txn_p95_ms``) from ``tools.load_sim.resources`` probes taken around
    the replay.

    Two phases (documented): phase 1 does the identical per-user fixture
    setup ``run_load`` performs (create user, lang/goal, level, plan,
    onboarded) SEQUENTIALLY for all ``n`` users; phase 2 replays only the
    journeys concurrently. Setup is scaffolding, not measured behavior —
    the replay window (and every latency/counter) covers the production
    paths: grades, reports, word queries, settings. Per-user RNG
    (``seed``/index derived) keeps the run deterministic regardless of
    task interleaving.
    """
    import bot
    from services import db
    from services.db import schema as db_schema

    if not isinstance(db_path, str) or not db_path:
        raise ValueError(
            "run_load_5k requires a db_path SQLite file string "
            f"(got {db_path!r}); refusing to poison DB_PATH with None."
        )
    prev_db = db.DB_PATH
    prev_schema = db_schema.DB_PATH
    prev_offline = bot._telegram_offline
    db.DB_PATH = db_path
    db_schema.DB_PATH = db_path
    db.init_db()
    bot._telegram_offline = False
    try:
        return await _run_5k(
            n,
            seed,
            bot,
            db,
            bot_mock,
            ai_mock,
            db_path,
            concurrency,
            plan_limits,
            workload_override,
        )
    finally:
        db.DB_PATH = prev_db
        db_schema.DB_PATH = prev_schema
        bot._telegram_offline = prev_offline


async def _run_5k(
    n,
    seed,
    bot,
    db,
    bot_mock,
    ai_mock,
    db_path,
    concurrency,
    plan_limits=None,
    workload_override=None,
) -> dict:
    from config.keyboards import BTN_SETTINGS

    from tools.load_sim.resources import (
        db_file_sizes,
        lag_probe_loop,
        p95_ms,
        rss_bytes,
    )

    rng_seed = seed
    if workload_override is None:
        workload = sample_workload(
            n=n,
            seed=seed,
            plan_limits=(
                plan_limits if plan_limits is not None else _live_plan_limits(db)
            ),
        )
    else:
        workload = workload_override
    arrival_5k = _arrival_summary(workload)
    counters = {
        "telegram_429": 0,
        "telegram_retries": 0,
        "db_busy_retries": 0,
        "ai_timeouts": 0,
        "ai_error": 0,
        "word_query_ok": 0,
        "quota_double_spend": 0,
        "report_loss": 0,
        "plan_fallbacks": 0,
        "real_grades": 0,
        "card_lookup_miss": 0,
        "grade_check_failed": 0,
    }
    latencies: dict[str, list[float]] = {}
    grade_latencies: list[float] = []
    txn_timings: list[float] = []
    errors = 0

    ai_override = ai_mock
    sem = asyncio.Semaphore(max(1, concurrency))

    def _ctx_for(rng: random.Random):
        if isinstance(bot_mock, MagicMock):
            ctx = MagicMock()
            ctx.user_data = {}
            ctx.bot = bot_mock
            return ctx
        if bot_mock is not None and not callable(bot_mock):
            ctx = MagicMock()
            ctx.user_data = {}
            ctx.bot = bot_mock
            return ctx
        if callable(bot_mock):
            return _make_context(rng, counters, send=bot_mock)
        return _make_context(rng, counters)

    def _setup_one(i: int, spec: dict) -> None:
        user_id = _BASE_USER_ID + i
        db.create_user_if_needed(user_id, f"loadsim{i}")
        db.set_user_lang_goal(user_id, "en", "general")
        db.set_user_level(user_id, "beginner")
        try:
            db.set_plan(user_id, spec["plan"])
        except ValueError:
            counters["plan_fallbacks"] += 1
            logger.warning(
                "load_sim set_plan fallback user_id=%s plan=%s",
                user_id,
                spec.get("plan"),
            )
        with db.transaction() as conn:
            conn.execute(
                "UPDATE users SET onboarded=1 WHERE user_id=?", (user_id,)
            )

    async def _journey_one(i: int, spec: dict):
        rng = random.Random((rng_seed * 1000003 + i) & 0x7FFFFFFF)
        user_id = _BASE_USER_ID + i
        journey = spec["journey"]
        t0 = time.perf_counter()
        grade_ms: float | None = None
        try:
            if journey == "idle":
                pass
            elif journey == "settings":
                update = _text_update(user_id, BTN_SETTINGS)
                ctx = _ctx_for(rng)

                async def _do_settings():
                    await bot.text_router(update, ctx)

                await _with_db_retry(_do_settings, counters)
            elif journey == "word_query":
                word = f"loadword{_alpha_suffix(i)}"

                def _read_words_asked():
                    return _words_asked(db, user_id)

                before = await _with_db_retry_sync(_read_words_asked, counters)
                update = _text_update(user_id, word)
                ctx = _ctx_for(rng)
                ctx.user_data["awaiting"] = "ask_word"

                async def _do_query():
                    await bot.text_router(update, ctx)

                await _with_db_retry(_do_query, counters)
                after = await _with_db_retry_sync(_read_words_asked, counters)
                if after - before > 1:
                    counters["quota_double_spend"] += 1
            elif journey in ("full_session", "partial"):
                grade = 4 if journey == "full_session" else 3
                word = f"gradeword{_alpha_suffix(i)}"
                card = dict(CANNED_CARD)
                card["word"] = word
                # Concurrent journeys contend on one SQLite file: every
                # per-journey DB op below retries locked/busy via
                # _with_db_retry(_sync) instead of failing the journey.
                await _with_db_retry_sync(
                    lambda: db.add_saved_word(user_id, word, "en", card),
                    counters,
                )
                from services.db.schema import normalize_word

                def _lookup_card_id():
                    with db.get_conn() as conn:
                        return conn.execute(
                            "SELECT id FROM saved_words "
                            "WHERE user_id=? AND lang=? AND normalized_word=?",
                            (user_id, "en", normalize_word(word)),
                        ).fetchone()

                row = await _with_db_retry_sync(_lookup_card_id, counters)
                if row is None or row["id"] is None:
                    counters["card_lookup_miss"] += 1
                    logger.warning(
                        "load_sim card lookup miss user_id=%s word=%s",
                        user_id,
                        word,
                    )
                else:
                    word_id = row["id"]
                    update = _callback_update(
                        user_id, f"srs:fe:{grade}:{user_id}:{word_id}"
                    )
                    ctx = _ctx_for(rng)

                    async def _do_grade():
                        await bot.callback_router(update, ctx)

                    await _with_db_retry(_do_grade, counters)
                    try:
                        if await _with_db_retry_sync(
                            lambda: db.is_word_graded(
                                user_id, word_id, "first_exposure"
                            ),
                            counters,
                        ):
                            counters["real_grades"] += 1
                    except sqlite3.Error:
                        counters["grade_check_failed"] += 1
                        logger.warning(
                            "load_sim grade check failed user_id=%s word_id=%s",
                            user_id,
                            word_id,
                        )
                    grade_ms = (time.perf_counter() - t0) * 1000.0
                    if journey == "full_session":
                        from handlers.study_handler import (
                            SessionState,
                            _app_day_str,
                            advance_session,
                        )
                        from services.db.session_reports import (
                            list_recent_reports,
                        )

                        state = SessionState(
                            nodes=[],
                            total_cards=1,
                            tier3_context={},
                            study_msg_id=100000 + i,
                            plan=spec["plan"],
                            graded_word_ids=[word_id],
                            before_stability={},
                            # Same-day sim journey: stamp today so the
                            # day-boundary guard treats it as current.
                            session_date=_app_day_str(),
                        )
                        ctx.user_data["current_session"] = state

                        async def _do_advance():
                            await advance_session(update, ctx)

                        await _with_db_retry(_do_advance, counters)
                        entries = await _with_db_retry_sync(
                            lambda: list_recent_reports(user_id), counters
                        )
                        if not entries or all(
                            e.total != 1 for e in entries
                        ):
                            counters["report_loss"] += 1
            else:  # unknown journey kinds never fail the sim
                pass
        except Exception:
            logger.exception(
                "load_sim journey failed user_id=%s journey=%s",
                user_id,
                journey,
            )
            return (journey, (time.perf_counter() - t0) * 1000.0, None, True)
        return (journey, (time.perf_counter() - t0) * 1000.0, grade_ms, False)

    # Phase 1 — fixture setup, sequential (identical writes to run_load).
    # A failed setup counts an error and skips that user's journey, mirroring
    # run_load's per-user try/except (its finally still records the run time).
    setup_ok = [True] * n
    for i, spec in enumerate(workload):
        t0 = time.perf_counter()
        try:
            _setup_one(i, spec)
        except Exception:
            errors += 1
            setup_ok[i] = False
            logger.exception(
                "load_sim setup failed user_id=%s", _BASE_USER_ID + i
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0
            txn_timings.append(dt_ms)
            latencies.setdefault(spec["journey"], []).append(dt_ms)

    rss_before = rss_bytes()
    from tools.load_sim.resources import cpu_process_seconds, percentile_summary

    replay_wall_start = time.perf_counter()
    cpu_start_s = cpu_process_seconds()
    lag_samples: list[float] = []
    lag_stop = asyncio.Event()
    lag_task = asyncio.create_task(
        lag_probe_loop(lag_stop, _5K_LAG_INTERVAL_S, lag_samples)
    )
    batches = 0
    # Single replay-wide AI patch (never per-task: concurrent enter/exit on
    # process globals raced and restored the wrong mock mid-replay). The step
    # fake reads the queried word from the call args, so one shared pair
    # covers all concurrent word_query journeys; the ask spy counts
    # word_query_ok / ai_error replay-wide. Only the bot-namespace seam is
    # patched; the real services.ai.llm_services entry stays live so the flow
    # test's zero-token guard there fires loudly on any direct reach.
    ai_lock = threading.Lock()
    fake_step, fake_prep = _make_replay_ai_fakes(
        seed=seed, counters=counters, ai_override=ai_override, lock=ai_lock
    )
    ask_spy = _make_ask_spy(counters, ai_lock)
    from services import word_query as _word_query_svc

    try:
        with (
            patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)),
            patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()),
            patch.object(bot, "_call_ai_limited", new=fake_step),
            patch.object(bot, "_prepare_cached_card", new=fake_prep),
            patch.object(_word_query_svc, "ask", new=ask_spy),
        ):
            for bstart in range(0, n, _5K_BATCH_SIZE):
                if bstart > 0:
                    await asyncio.sleep(_5K_STAGGER_S)
                batches += 1
                chunk = [
                    (bstart + k, spec)
                    for k, spec in enumerate(workload[bstart:bstart + _5K_BATCH_SIZE])
                    if setup_ok[bstart + k]
                ]

                async def _bounded(idx: int, spec: dict):
                    async with sem:
                        return await _journey_one(idx, spec)

                # gather preserves input order: arrival order per batch.
                results = await asyncio.gather(
                    *(_bounded(idx, spec) for idx, spec in chunk)
                )
                for journey, dt_ms, grade_ms, failed in results:
                    if failed:
                        errors += 1
                    txn_timings.append(dt_ms)
                    if journey in ("full_session", "partial"):
                        if grade_ms is not None:
                            grade_latencies.append(grade_ms)
                            latencies.setdefault(journey, []).append(grade_ms)
                        else:
                            latencies.setdefault(journey, []).append(dt_ms)
                    else:
                        latencies.setdefault(journey, []).append(dt_ms)
    finally:
        lag_stop.set()
        await lag_task

    rss_after = rss_bytes()
    db_bytes, wal_bytes = db_file_sizes(db_path)
    txn_p95 = p95_ms(txn_timings)
    lag_p95 = p95_ms(lag_samples)
    cpu_total_ms = _cpu_total_ms(cpu_start_s, cpu_process_seconds())
    replay_wall_s = time.perf_counter() - replay_wall_start
    grade_pct = percentile_summary(grade_latencies)
    txn_pct = percentile_summary(txn_timings)
    loop_lag_pct = percentile_summary(lag_samples)
    cpu_split = _cpu_ms_per_journey(cpu_total_ms, latencies)

    total = max(1, n)
    grade_p95 = _p95_ms(grade_latencies)
    return {
        "total": n,
        "seed": seed,
        "errors": errors,
        "error_rate": errors / total,
        "latencies_ms": latencies,
        "grade_latencies_ms": list(grade_latencies),
        "grade_p95_ms": grade_p95,
        "grade_pct": grade_pct,
        "txn_pct": txn_pct,
        "loop_lag_pct": loop_lag_pct,
        "cpu_total_ms": cpu_total_ms,
        "cpu_ms_per_journey": cpu_split,
        "cpu_note": _CPU_NOTE,
        "replay_wall_s": replay_wall_s,
        "telegram_429": counters["telegram_429"],
        "telegram_retries": counters["telegram_retries"],
        "db_busy_retries": counters["db_busy_retries"],
        "ai_timeouts": counters["ai_timeouts"],
        "ai_error": counters["ai_error"],
        "word_query_ok": counters["word_query_ok"],
        "quota_double_spend": counters["quota_double_spend"],
        "report_loss": counters["report_loss"],
        "plan_fallbacks": counters["plan_fallbacks"],
        "real_grades": counters["real_grades"],
        "card_lookup_miss": counters["card_lookup_miss"],
        "grade_check_failed": counters["grade_check_failed"],
        "journey_counts": {
            j: len(v) for j, v in latencies.items()
        },
        "personas": arrival_5k["personas"],
        "arrival": arrival_5k,
        "concurrency": concurrency,
        "batches": batches,
        "txn_p95_ms": txn_p95,
        "resources": {
            "rss_before": rss_before,
            "rss_after": rss_after,
            "rss_delta": rss_after - rss_before,
            "loop_lag_p95_ms": lag_p95,
            "loop_lag_pct": loop_lag_pct,
            "db_bytes": db_bytes,
            "wal_bytes": wal_bytes,
            "txn_p95_ms": txn_p95,
            "txn_pct": txn_pct,
        },
    }
