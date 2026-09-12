"""Thin kind-dispatched quota facade (REF4-T1).

Maps ``kind in {word, grammar_tip, session_slot}`` to the owning store
(``users`` columns vs ``settings`` key) and delegates to the verbatim bodies:

- ``word`` / ``grammar_tip`` — owned by ``services/db/users.py``
  (``can_ask_word`` / ``reserve_word_query`` / ``release_word_query``,
  ``can_ask_grammar_tip`` / ``reserve_grammar_tip`` / ``release_grammar_tip``).
- ``session_slot`` — owned by ``services/scheduling.py``
  (``consume_session_slot`` / ``release_session_slot``; the ``can`` hint reads
  ``daily_session_budget``).

Rules preserved from the owners: ``can_*`` is a non-atomic read-only hint and
is never merged with the ``reserve_*`` / ``consume_*`` atomic gate; ``release``
stays same-day-clamped (never negative); no ``await`` inside any transaction
(this module is fully synchronous — callers wrap it in ``asyncio.to_thread``
as before). No SQL lives here. Additive only: existing import paths keep
working; nothing was moved.
"""

from __future__ import annotations

# Per-kind named aliases — plain re-exports of the verbatim bodies (same
# objects, not copies), so the SQL stays single-sourced in its owner module.
from services.db.users import (
    can_ask_grammar_tip,
    can_ask_word,
    release_grammar_tip,
    release_word_query,
    reserve_grammar_tip,
    reserve_word_query,
)
from services.scheduling import (
    consume_session_slot,
    daily_session_budget,
    release_session_slot,
)

__all__ = [
    "QUOTA_KINDS",
    "KIND_STORAGE",
    "can",
    "reserve",
    "consume",
    "release",
    "can_ask_word",
    "reserve_word_query",
    "release_word_query",
    "can_ask_grammar_tip",
    "reserve_grammar_tip",
    "release_grammar_tip",
    "consume_session_slot",
    "release_session_slot",
    "daily_session_budget",
]

QUOTA_KINDS: tuple[str, str, str] = ("word", "grammar_tip", "session_slot")

# kind -> owning store. Word/grammar quotas live in users-table column pairs;
# session slots live in the settings key sessions_used_{user_id}_{YYYY-MM-DD}.
KIND_STORAGE: dict[str, dict[str, str]] = {
    "word": {
        "store": "users",
        "count_column": "words_asked_today",
        "date_column": "words_asked_date",
    },
    "grammar_tip": {
        "store": "users",
        "count_column": "grammar_tips_asked_today",
        "date_column": "grammar_tips_asked_date",
    },
    "session_slot": {
        "store": "settings",
        "key_pattern": "sessions_used_{user_id}_{YYYY-MM-DD}",
    },
}


def _require_limit(kind: str, daily_limit: int | None) -> int:
    if daily_limit is None:
        raise ValueError(
            f"kind={kind!r} requires an explicit daily_limit "
            "(derive it from the user's plan; no silent default)"
        )
    return daily_limit


def _check_kind(kind: str) -> str:
    if kind not in KIND_STORAGE:
        raise ValueError(
            f"unknown quota kind={kind!r}; expected one of {', '.join(QUOTA_KINDS)}"
        )
    return kind


def can(
    kind: str,
    user_id: int,
    *,
    daily_limit: int | None = None,
    plan: str = "free",
    bypass_limits: bool = False,
) -> bool:
    """Non-atomic hint: True when quota *appears* available (read-only).

    Never a gate — always follow with reserve()/consume() and honor its
    verdict. For ``session_slot`` the hint is ``daily_session_budget``
    remaining > 0.
    """
    _check_kind(kind)
    if kind == "word":
        return can_ask_word(
            user_id, _require_limit(kind, daily_limit),
            bypass_limits=bypass_limits,
        )
    if kind == "grammar_tip":
        return can_ask_grammar_tip(
            user_id, _require_limit(kind, daily_limit),
            bypass_limits=bypass_limits,
        )
    return daily_session_budget(user_id, plan)["remaining"] > 0


def reserve(
    kind: str,
    user_id: int,
    *,
    daily_limit: int | None = None,
    plan: str = "free",
    bypass_limits: bool = False,
) -> bool:
    """Atomic gate: reserve one unit or return False when exhausted.

    The check and the increment share the owner's single transaction.
    """
    _check_kind(kind)
    if kind == "word":
        return reserve_word_query(
            user_id, _require_limit(kind, daily_limit),
            bypass_limits=bypass_limits,
        )
    if kind == "grammar_tip":
        return reserve_grammar_tip(
            user_id, _require_limit(kind, daily_limit),
            bypass_limits=bypass_limits,
        )
    return consume_session_slot(user_id, plan)


def consume(
    kind: str,
    user_id: int,
    *,
    daily_limit: int | None = None,
    plan: str = "free",
    bypass_limits: bool = False,
) -> bool:
    """Session verb for the same atomic gate as reserve().

    ``reserve`` and ``consume`` route identically; both names exist so each
    domain reads naturally (word/grammar reserve, sessions consume).
    """
    return reserve(
        kind, user_id,
        daily_limit=daily_limit, plan=plan, bypass_limits=bypass_limits,
    )


def release(kind: str, user_id: int) -> None:
    """Roll back one unit; same-day-clamped, never negative, idempotent."""
    _check_kind(kind)
    if kind == "word":
        release_word_query(user_id)
    elif kind == "grammar_tip":
        release_grammar_tip(user_id)
    else:
        release_session_slot(user_id)
