"""Custom-word query orchestration core (deep module).

Owns the full word-query flow behind a small, Telegram-free interface:

- ``ask``          : validate -> reserve quota -> AI card (2-step pipeline) -> persist -> result
- ``prepare``      : re-run card preparation (translations) and persist back, returning the
                     enriched card for the handler to re-render with translations_prepared=True
- ``toggle_save``  : idempotently save/remove the word in the review box

This module has NO Telegram imports. It composes ``services/db`` functions and
``services.utils.validation``; it composes but does not duplicate them (Rule 6).
All Telegram threading / rate-limiter / deadline machinery is injected by the
handler as ``generate_card`` / ``prepare_card`` callables (Rules 1 and 5), so
the service stays pure orchestration and remains unit-testable with fakes.

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

    kinds: ``ok | invalid_input | quota_exhausted | ai_timeout | ai_error | card_prep_error``
    """

    kind: str
    token: Optional[str] = None
    card_data: Optional[dict] = None
    show_pronounce: Optional[bool] = None
    show_translations: bool = True
    usage_text: Optional[str] = None
    error_key: Optional[str] = None


@dataclass(frozen=True)
class PrepareResult:
    """Outcome of a ``prepare`` (translations re-render).

    kinds: ``ok | expired | not_found | card_prep_error``
    """

    kind: str
    token: Optional[str] = None
    card_data: Optional[dict] = None
    lang: Optional[str] = None
    show_translations: bool = True
    show_pronounce: bool = True
    saved: bool = False
    user_row: Optional[dict] = None


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
        result_data = None

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


async def prepare(token: str, user_id: int, *, prepare_card: Callable[..., Awaitable[dict]]) -> PrepareResult:
    """Re-run card preparation (translations) for the query behind ``token``.

    ``prepare_card`` is an injected async callable (handler-provided) that wraps
    ``services.ai.llm_services._prepare_cached_card`` with a ``persist_patch``
    writing prepared translations back to the query_results row.

    Returns the enriched card so the handler re-renders with
    ``translations_prepared=True``. ``show_translations=False`` matches current
    behavior (translations are rendered as part of the prepared card, not a toggle).
    """
    row = db.get_query_result(token, user_id=user_id)
    if not row:
        return PrepareResult(kind="expired")

    user_row = db.get_user(user_id)
    if not user_row:
        return PrepareResult(kind="not_found")

    try:
        saved = bool(row["saved_at"])
    except (KeyError, IndexError, TypeError):
        saved = bool(row.get("saved_at", False)) if isinstance(row, dict) else False
    try:
        card = json.loads(row["result_json"])
    except (TypeError, json.JSONDecodeError):
        card = None

    try:
        card = await prepare_card(
            card,
            lang=row["lang"],
            user_id=user_id,
            plan=user_row["plan"] or "free",
            source="custom_word",
            persist_patch=lambda patch: db.update_query_result_fields(token, user_id, patch),
        )
    except CardPreparationError:
        return PrepareResult(kind="card_prep_error")

    show_pronounce = db.should_show_pronounce(user_id, user_row)
    return PrepareResult(
        kind="ok",
        token=row["token"],
        card_data=card,
        lang=row["lang"],
        show_translations=False,
        show_pronounce=show_pronounce,
        saved=saved,
        user_row=user_row,
    )


async def ask(
    user_id: int,
    text: str,
    *,
    lang: str,
    level: str,
    plan: str,
    generate_card: Callable[..., Awaitable[dict]],
) -> AskResult:
    """Full word-query flow: validate -> reserve quota -> AI card -> persist.

    ``generate_card`` is an injected async callable (handler-provided) that
    wraps the 2-step AI pipeline (``ai.ask_card`` then ``_prepare_cached_card``),
    owning thread offload, rate-limiting and the deadline. It must raise
    ``asyncio.TimeoutError``, ``CardPreparationError``, or a generic Exception.

    The AI card's output format (compact vs full JSON) is read from the
    environment setting ``AI_CARD_OUTPUT_FORMAT`` inside this module, matching
    current behavior. On-screen presentation (brief/detailed) stays handler-side.

    Quota pairing: reserved on entry; released on every AI-pipeline failure
    kind owned here. A post-``ok`` send failure is the handler's responsibility
    (it releases quota itself on an undelivered card).
    """
    error_key = validate_word_query(text, lang)
    if error_key:
        return AskResult(kind="invalid_input", error_key=error_key)

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

    query_token = db.create_query_result(
        user_id,
        text,
        data.get("word", text),
        lang,
        data,
    )
    db.touch_streak(user_id)

    usage_row = db.get_user(user_id)
    show_pronounce = db.should_show_pronounce(user_id, usage_row)
    return AskResult(
        kind="ok",
        token=query_token,
        card_data=data,
        show_pronounce=show_pronounce,
        show_translations=True,
        usage_text=_format_usage(usage_row, limit),
    )