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
patched per journey with sync fakes, so ``services.ai`` providers never run.

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
import logging
import math
import random
import sqlite3
import time
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import RetryAfter

from tools.load_sim.plan_mix import sample_workload

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


def _p95_ms(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return ordered[idx]


def _words_asked(db, user_id: int) -> int:
    row = db.get_user(user_id)
    if row is None:
        return 0
    try:
        return row["words_asked_today"] or 0
    except (KeyError, IndexError, TypeError):
        return 0


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


async def run_load(n, seed, db_path, bot_mock=None, ai_mock=None) -> dict:
    """Replay ``n`` synthetic users (seed ``seed``) against ``db_path``.

    Returns a metrics dict with per-journey latencies (ms) plus counters:
    ``telegram_429``, ``telegram_retries``, ``db_busy_retries``,
    ``ai_timeouts``, ``quota_double_spend``, ``report_loss``,
    ``plan_fallbacks``, ``real_grades``, ``card_lookup_miss``,
    ``grade_check_failed``.
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
        return await _run(n, seed, bot, db, bot_mock, ai_mock)
    finally:
        db.DB_PATH = prev_db
        db_schema.DB_PATH = prev_schema
        bot._telegram_offline = prev_offline


async def _run(n: int, seed: int, bot, db, bot_mock, ai_mock) -> dict:
    from config.keyboards import BTN_SETTINGS

    rng = random.Random(seed)
    workload = sample_workload(n=n, seed=seed)
    counters = {
        "telegram_429": 0,
        "telegram_retries": 0,
        "db_busy_retries": 0,
        "ai_timeouts": 0,
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

    def _ai_pair(word: str):
        if callable(ai_override):
            step = ai_override
            prep = ai_override
        else:
            canned = dict(CANNED_CARD)
            canned["word"] = word

            def step(*args, **kwargs):
                time.sleep(rng.uniform(0.010, 0.030))
                if rng.random() < _AI_TIMEOUT_P:
                    counters["ai_timeouts"] += 1
                    raise asyncio.TimeoutError("simulated AI timeout")
                return dict(canned)

            def prep(data, **kwargs):
                return dict(data)

        return step, prep

    with (
        patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)),
        patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()),
    ):
        for i, spec in enumerate(workload):
            user_id = _BASE_USER_ID + i
            journey = spec["journey"]
            t0 = time.perf_counter()
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
                    step, prep = _ai_pair(word)
                    with (
                        patch.object(bot, "_call_ai_limited", new=step),
                        patch.object(bot, "_prepare_cached_card", new=prep),
                    ):

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
                    if journey == "full_session":
                        from handlers.study_handler import (
                            SessionState,
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
                    # grade latency already recorded above; keep the
                    # per-journey bucket aligned for reporting.
                    latencies.setdefault(journey, []).append(
                        grade_latencies[-1]
                        if grade_latencies
                        else dt_ms
                    )

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
        "telegram_429": counters["telegram_429"],
        "telegram_retries": counters["telegram_retries"],
        "db_busy_retries": counters["db_busy_retries"],
        "ai_timeouts": counters["ai_timeouts"],
        "quota_double_spend": counters["quota_double_spend"],
        "report_loss": counters["report_loss"],
        "plan_fallbacks": counters["plan_fallbacks"],
        "real_grades": counters["real_grades"],
        "card_lookup_miss": counters["card_lookup_miss"],
        "journey_counts": {
            j: len(v) for j, v in latencies.items()
        },
    }
