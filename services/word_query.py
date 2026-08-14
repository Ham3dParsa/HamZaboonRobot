"""Custom-word query orchestration core (deep module).

Owns the full word-query flow behind a small, Telegram-free interface:

- ``ask``          : validate -> reserve quota -> AI card (2-step pipeline) -> persist -> result
- ``toggle_save``  : idempotently save/remove the word in the review box

This module has NO Telegram imports. It composes ``services/db`` functions and
``services.utils.validation``; it composes but does not duplicate them (Rule 6).
All Telegram threading / rate-limiter / deadline machinery is injected by the
handler as a ``generate_card`` callable (Rule 1), so the service stays pure
orchestration and remains unit-testable with fakes.

Quota pairing invariant (the #306 guarantee): every path that reserves must
release on failure. ``ask`` releases on each AI-pipeline failure kind it owns.
A post-``ok`` send failure is the handler's concern (it calls
``release_word_query`` itself), since only the handler can observe send success.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

from config import (
    AI_CARD_OUTPUT_FORMAT,
    OWNER_BYPASS_LIMITS,
    daily_word_query_limit_for_plan,
    is_owner,
)
from services import db
from services.ai import prompts
from services.utils.formatting import CardPreparationError, word_query_usage_text
from services.utils.validation import validate_word_query

# Learner-facing Persian strings owned by this service (single source).
_TOAST_SAVED = "در جعبه مرور ذخیره شد!"
_TOAST_REMOVED = "از جعبه مرور حذف شد!"
_MSG_EXPIRED = "این نتیجه منقضی شده یا در دسترس نیست."
_MSG_NOT_FOUND = "کاربر پیدا نشد."


@dataclass(frozen=True)
class AskResult:
    """Outcome of an ``ask``. ``kind`` drives the handler's reply branch.

    kinds: ``ok | duplicate | invalid_input | registration_required |
    quota_exhausted | ai_timeout | ai_error | card_prep_error | persist_error``

    ``duplicate`` (R7): a prior unexpired card exists; the handler offers the
    retrieve-vs-new choice. No quota reserved, no AI called.
    """

    kind: str
    token: Optional[str] = None
    card_data: Optional[dict] = None
    show_pronounce: Optional[bool] = None
    usage_text: Optional[str] = None
    error_key: Optional[str] = None


@dataclass(frozen=True)
class ToggleResult:
    """Outcome of a ``toggle_save``.

    kinds: ``ok | expired``. ``saved`` is True after adding to review, False after removing.
    """

    kind: str
    saved: bool = False
    message: str = ""
    token: Optional[str] = None
    lang: Optional[str] = None


def _format_usage(row: dict, limit: int) -> str:
    """Return the usage summary line for a user row, or fallback when absent."""
    if not row:
        return f"📊 استفاده امروز: 1/{limit}"
    return word_query_usage_text(row)


def _build_system_prompt(lang: str, level: str) -> str:
    """Build the custom-word system prompt matching bot.py's current call.

    The AI card's output-format decision (compact vs full JSON schema) comes
    from the environment setting ``AI_CARD_OUTPUT_FORMAT``, exactly as bot.py
    reads it today. The per-user display preference (brief/detailed) is
    on-screen only and stays handler-side.
    """
    return prompts.custom_word_system_prompt(
        lang,
        level,
        compact=(AI_CARD_OUTPUT_FORMAT == "compact_json"),
    )


async def toggle_save(token: str, user_id: int) -> ToggleResult:
    """Idempotently save or remove the word behind ``token`` for ``user_id``.

    Returns the new saved state and the learner-facing toast message. The
    handler rebuilds the keyboard (translations/pronounce) from user_data
    (Rule 3) — this service does not carry those flags.
    """
    row = db.get_query_result(token, user_id=user_id)
    if not row:
        return ToggleResult(kind="expired")

    try:
        result_data = json.loads(row["result_json"])
    except (TypeError, json.JSONDecodeError):
        logger.warning("corrupt result_json token=%s", token)
        return ToggleResult(kind="expired")

    state = db.toggle_review_word(user_id, row["word"], row["lang"], result_data)
    if state == "saved":
        db.mark_query_result_saved(token)
        message = _TOAST_SAVED
    else:
        db.clear_query_result_saved(token)
        message = _TOAST_REMOVED

    return ToggleResult(
        kind="ok",
        saved=(state == "saved"),
        message=message,
        token=row["token"],
        lang=row["lang"],
    )


def find_duplicate(user_id: int, text: str, lang: str) -> Optional[str]:
    """Return the token of a retrievable prior card, or ``None``.

    A prior card is the most recent unexpired query_result for the same user +
    lang + normalized ``text`` (R7a). Pure DB read (no quota, no AI); returns
    the token so the caller can offer retrieve-vs-new. Corrupt stored JSON is
    treated as no duplicate so the user can still ask fresh. The caller re-reads
    the row by token only when the learner actually taps a button, because the
    callback is stateless (it carries just the token).
    """
    row = db.find_unexpired_query(user_id, text, lang)
    if not row:
        return None
    try:
        json.loads(row["result_json"])
    except (TypeError, json.JSONDecodeError):
        logger.warning("corrupt result_json token=%s in find_duplicate", row["token"])
        return None
    return row["token"]


async def ask(
    user_id: int,
    text: str,
    *,
    generate_card: Callable[..., Awaitable[dict]],
    skip_duplicate: bool = False,
) -> AskResult:
    """Full word-query flow: registration guard -> validate -> reserve quota -> AI -> persist.

    ``generate_card`` is an injected async callable (handler-provided) that
    wraps the 2-step AI pipeline (``ai.ask_card`` then ``_prepare_cached_card``),
    owning thread offload, rate-limiting and the deadline. It must raise
    ``asyncio.TimeoutError``, ``CardPreparationError``, or a generic Exception.
    It receives ``lang`` and ``plan`` so the handler does not re-read the user row.

    The AI card's output format (compact vs full JSON) is read from the
    environment setting ``AI_CARD_OUTPUT_FORMAT`` inside this module, matching
    current behavior. On-screen presentation (brief/detailed) stays handler-side.

    Registration guard: the user's profile (target language, goal, level) must
    be complete before any quota is reserved or AI call is made; otherwise
    ``registration_required`` is returned and the handler points the learner to
    /start. This single check replaces scattered fallback defaults.

    Quota pairing: reserved on entry; released on every AI-pipeline failure
    kind owned here, and on any persistence failure after the AI succeeds. A
    post-``ok`` send failure is the handler's responsibility (it releases quota
    itself on an undelivered card). An unusable/empty AI card is never persisted
    (guards against wasting AI cost with no storable result).
    """
    user_row = db.get_user(user_id)
    if user_row is None:
        return AskResult(kind="registration_required")
    user_row = dict(user_row)
    if not user_row.get("target_lang") or not user_row.get("goal") or not user_row.get("level"):
        return AskResult(kind="registration_required")

    lang = user_row["target_lang"]
    level = user_row.get("level") or "beginner"
    plan = user_row.get("plan") or "free"

    error_key = validate_word_query(text, lang)
    if error_key:
        return AskResult(kind="invalid_input", error_key=error_key)

    dup = find_duplicate(user_id, text, lang)
    if dup is not None and not skip_duplicate:
        # R7: a prior unexpired card exists for this user+lang+word. Offer the
        # retrieve-vs-new choice WITHOUT reserving quota or calling AI. The
        # retrieve-vs-new "new" path sets skip_duplicate so the explicit fresh
        # ask is not re-bounced onto the same prior card.
        return AskResult(kind="duplicate", token=dup)

    limit = daily_word_query_limit_for_plan(plan)
    reserved = db.reserve_word_query(
        user_id,
        limit,
        bypass_limits=OWNER_BYPASS_LIMITS and is_owner(user_id),
    )
    if not reserved:
        return AskResult(kind="quota_exhausted")

    try:
        data = await generate_card(
            system_prompt=_build_system_prompt(lang, level),
            user_prompt=text,
            request_kind="custom_word",
            user_id=user_id,
            plan=plan,
            lang=lang,
        )
    except asyncio.TimeoutError:
        db.release_word_query(user_id)
        return AskResult(kind="ai_timeout")
    except CardPreparationError:
        db.release_word_query(user_id)
        return AskResult(kind="card_prep_error")
    except Exception:
        logger.exception("AI error in word_query.ask user_id=%s", user_id)
        db.release_word_query(user_id)
        return AskResult(kind="ai_error")

    if not isinstance(data, dict) or not data.get("word"):
        logger.warning(
            "empty/unusable AI card in word_query.ask user_id=%s word=%r",
            user_id,
            (data or {}).get("word"),
        )
        db.release_word_query(user_id)
        return AskResult(kind="persist_error")

    try:
        query_token = db.create_query_result(
            user_id,
            text,
            data.get("word", text),
            lang,
            data,
        )
        db.touch_streak(user_id)
    except Exception:
        logger.exception("persist failed in word_query.ask user_id=%s", user_id)
        db.release_word_query(user_id)
        return AskResult(kind="persist_error")

    usage_row = db.get_user(user_id)
    show_pronounce = db.should_show_pronounce(user_id, usage_row)
    return AskResult(
        kind="ok",
        token=query_token,
        card_data=data,
        show_pronounce=show_pronounce,
        usage_text=_format_usage(usage_row, limit),
    )