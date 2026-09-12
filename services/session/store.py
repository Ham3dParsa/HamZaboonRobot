"""Session state store — codec + save/load/clear (REF4-T3).

Single owner of the ``SessionState`` shape and its JSON codec plus the
``SessionState``-aware save/load/clear wrappers, moved verbatim from
``handlers/study_handler.py:78-244``. The low-level JSON row I/O stays in
``services/db/sessions.py`` (pure row reads/writes); this module owns the
dataclass shape and (de)serialization. ``handlers/study_handler.py`` keeps
thin ``_state_*``/``_persist*``/``_restore*`` delegates so existing import
paths (``srs_handler``, ``tools/load_sim/*``, tests) keep working; external
call sites are unchanged (handler migration is REF4-T4).

Rules preserved from the handler bodies: ``before_stability`` int/float
coercion, ``SessionNode(**node)`` kwargs, revealed/prompt validation
(invalid enum clears prompt + reveal; stray revealed without a prompt is
cleared; word_id coerced to int), legacy missing ``session_date`` means
``""``, corrupt/empty payloads invalidate (load returns None and clears
the row). ``_frozen_for_word`` stays with the render seam in the handler.
``today`` is caller-side and required: save/load never resolve the app-day
themselves (no midnight-straddle inside the store). Zero Telegram imports.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

from services.db.sessions import (
    clear_study_session,
    invalidate_stale_study_session,
    load_study_session,
    save_study_session,
)
from services.session import SessionNode
from services.utils.formatting import SRS_PROMPT_TYPES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session state — stored in context.user_data['current_session']
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    nodes: list[SessionNode]
    total_cards: int
    tier3_context: dict
    study_msg_id: int | None
    plan: str
    graded_word_ids: list[int] = field(default_factory=list)
    # Pre-grade stability per word_id, captured on first render so the
    # session summary can show the before->after stability delta (Phase 2).
    before_stability: dict[int, float] = field(default_factory=dict)
    # Frozen staged front presentation for the active card (Phase freeze-prompt-reveal R1/R2).
    # Persists prompt choice + revealed flip so resume/restart never re-rolls or flips.
    revealed: bool = False
    active_prompt_type: str | None = None
    active_prompt_word_id: int | None = None
    # Explicit app-day stamp set only at fresh-build time (T1, issues 619/622).
    # Never auto-filled: missing/legacy means "".
    session_date: str = ""


# ---------------------------------------------------------------------------
# Codec + save/load/clear — restart-safe session recovery (Bug 1)
# ---------------------------------------------------------------------------


def state_to_json(state: SessionState) -> str:
    """Serialize a session state to a JSON string for the study_sessions row."""
    return json.dumps(
        {
            "nodes": [asdict(node) for node in state.nodes],
            "total_cards": state.total_cards,
            "tier3_context": state.tier3_context,
            "study_msg_id": state.study_msg_id,
            "plan": state.plan,
            "graded_word_ids": state.graded_word_ids,
            "before_stability": state.before_stability,
            "revealed": state.revealed,
            "active_prompt_type": state.active_prompt_type,
            "active_prompt_word_id": state.active_prompt_word_id,
            "session_date": state.session_date,
        }
    )


def is_valid_prompt_type(value: str | None) -> bool:
    """Single seam for prompt enum validation (kilo 132).

    Keeps corrupt/future DB values from crashing the render seam.
    """
    return isinstance(value, str) and value in SRS_PROMPT_TYPES


def state_from_json(raw: str) -> SessionState:
    """Rebuild a SessionState from its JSON serialization."""
    data = json.loads(raw)
    raw_prompt_wid = data.get("active_prompt_word_id")
    try:
        prompt_wid = int(raw_prompt_wid) if raw_prompt_wid is not None else None
    except (TypeError, ValueError):
        prompt_wid = None
    raw_prompt = data.get("active_prompt_type")
    prompt_type = raw_prompt if is_valid_prompt_type(raw_prompt) else None
    # A stray revealed without a matching prompt is meaningless — clear both
    if prompt_type is None and prompt_wid is not None:
        prompt_wid = None
    revealed = bool(data.get("revealed", False)) and prompt_type is not None and prompt_wid is not None
    return SessionState(
        nodes=[SessionNode(**node) for node in data["nodes"]],
        total_cards=data["total_cards"],
        tier3_context=data["tier3_context"],
        study_msg_id=data["study_msg_id"],
        plan=data["plan"],
        graded_word_ids=data.get("graded_word_ids") or [],
        before_stability={
            int(k): float(v)
            for k, v in (data.get("before_stability") or {}).items()
        },
        revealed=revealed,
        active_prompt_type=prompt_type,
        active_prompt_word_id=prompt_wid,
        session_date=data.get("session_date") or "",
    )


def save_session(user_id: int, state: SessionState, today: str) -> None:
    """Persist the active session keyed by the caller's app-day (Rule 1/2).

    ``today`` is the already-computed app-day from the caller — required, so
    the row date can never differ from the caller's day (W1
    midnight-straddle fix). The store never resolves the day itself.
    """
    save_study_session(user_id, today, state_to_json(state))


def clear_session(user_id: int) -> None:
    clear_study_session(user_id)


def load_session(user_id: int, today: str) -> SessionState | None:
    """Load a same-day persisted session after a restart, or None.

    Rule 2: a persisted session whose date is not ``today`` is discarded
    (the row is cleared) so the user starts a fresh session with normal
    quota flow. Corrupt/empty payloads invalidate the same way.
    """
    row = load_study_session(user_id)
    if row is None:
        return None
    session_date, state_json = row
    if session_date != today:
        invalidate_stale_study_session(user_id)
        return None
    try:
        state = state_from_json(state_json)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.exception(
            "corrupt persisted study session user_id=%s", user_id
        )
        invalidate_stale_study_session(user_id)
        return None
    if not state.nodes:
        invalidate_stale_study_session(user_id)
        return None
    return state


__all__ = [
    "SessionState",
    "clear_session",
    "is_valid_prompt_type",
    "load_session",
    "save_session",
    "state_from_json",
    "state_to_json",
]
