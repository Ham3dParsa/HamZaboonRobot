"""Session state store — codec + save/load/clear + lifecycle (REF4-T3/T4).

Single owner of the ``SessionState`` shape and its JSON codec plus the
``SessionState``-aware save/load/clear wrappers, moved verbatim from
``handlers/study_handler.py:78-244`` (T3). REF4-T4 adds the pure lifecycle
steps moved verbatim from the handler's ``advance_session`` + ``_gather``:
``pop_next``/``rollback_pop`` (pop→clear-freeze + rollback),
``push_tier3``/``rollback_tier3_push`` (tier-3 append + rollback), and
``gather_word_records`` (saved-words + ``recent_events(per_word=2)`` record
build with its ``parse_iso_utc``/``to_app_tz_date``/``interval_days``
helpers). The low-level JSON row I/O stays in
``services/db/sessions.py`` (pure row reads/writes); the saved-word/event
row I/O stays in ``services/db/words.py`` / ``services/db/reviews.py``.
``handlers/study_handler.py`` keeps thin delegates so existing import
paths (``srs_handler``, ``tools/load_sim/*``, tests) keep working.

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
from datetime import datetime, timezone

from config import APP_TZ
from services.db.reviews import recent_events_for_words
from services.db.sessions import (
    clear_study_session,
    invalidate_stale_study_session,
    load_study_session,
    save_study_session,
)
from services.db.words import get_saved_words_by_ids
from services.session import SessionNode
from services.session.summary import WordReviewRecord
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


# ---------------------------------------------------------------------------
# Lifecycle — pure advance steps + gather (REF4-T4, moved verbatim)
# ---------------------------------------------------------------------------

# Saved (revealed, prompt_type, prompt_word_id) triple stashed before the
# advance clears the freeze, restored verbatim on rollback.
FrozenSave = tuple[bool, "str | None", "int | None"]


def pop_next(state: SessionState) -> "tuple[SessionNode | None, FrozenSave]":
    """Pop the head node and clear the freeze for the next card.

    Verbatim order from ``advance_session``: stash freeze, pop head (None
    when empty), then clear ``revealed``/``active_prompt_*`` so the next
    ``_build`` sets them for the new word. Pure sync — the caller keeps
    the ``to_thread`` build, Telegram edit, and persist-or-rollback order.
    """
    saved: FrozenSave = (
        state.revealed,
        state.active_prompt_type,
        state.active_prompt_word_id,
    )
    popped = state.nodes.pop(0) if state.nodes else None
    state.revealed = False
    state.active_prompt_type = None
    state.active_prompt_word_id = None
    return popped, saved


def rollback_pop(
    state: SessionState,
    popped: "SessionNode | None",
    saved: FrozenSave,
) -> None:
    """Restore a popped node + freeze after a failed edit (verbatim)."""
    if popped is not None:
        state.nodes.insert(0, popped)
    state.revealed, state.active_prompt_type, state.active_prompt_word_id = saved


def push_tier3(state: SessionState, node: SessionNode) -> None:
    """Append a tier-3 node and bump the card total (verbatim)."""
    state.nodes.append(node)
    state.total_cards += 1


def rollback_tier3_push(state: SessionState) -> None:
    """Undo a tier-3 append (verbatim)."""
    state.nodes.pop()
    state.total_cards -= 1


def parse_iso_utc(value: str):
    """Parse an ISO-8601 UTC timestamp, tolerating a trailing ``Z`` suffix.

    Verbatim from the handler (Python 3.10 ``fromisoformat`` rejects ``Z``).
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def to_app_tz_date(iso_utc: str | None) -> str | None:
    """Convert a stored UTC ISO timestamp to the app-tz ``YYYY-MM-DD`` date.

    Verbatim from the handler: summary labels compare against the app day,
    so per-word ``prior``/``next`` dates must be app-tz dates. None for a
    missing/unparseable timestamp.
    """
    if not iso_utc:
        return None
    try:
        dt = parse_iso_utc(iso_utc)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(APP_TZ).date().isoformat()


def interval_days(word_row) -> float | None:
    """Scheduled interval in days from next_review_at back to last_review_at.

    Verbatim from the handler (``word_row`` is a subscriptable saved_words
    row; either timestamp may be NULL).
    """
    try:
        last = word_row["last_review_at"]
        nxt = word_row["next_review_at"]
    except (KeyError, IndexError, TypeError):
        return None
    if not last or not nxt:
        return None
    try:
        last_dt = parse_iso_utc(last)
        nxt_dt = parse_iso_utc(nxt)
    except (TypeError, ValueError):
        return None
    seconds = (nxt_dt - last_dt).total_seconds()
    return round(max(0.0, seconds) / 86400, 1)


def gather_word_records(
    state: SessionState, user_id: int
) -> list[WordReviewRecord]:
    """Assemble WordReviewRecords for the session's graded words (verbatim).

    Saved-words + ``recent_events(per_word=2)`` only — no new queries.
    Activity type + grade come from the newest review_events row per word;
    the prior review date is the second-newest row; before-stability comes
    from the Phase-2 snapshot.
    """
    word_ids = list(state.graded_word_ids)
    if not word_ids:
        return []
    rows = {row["id"]: row for row in get_saved_words_by_ids(word_ids, user_id)}
    events = recent_events_for_words(word_ids, user_id, per_word=2)
    records: list[WordReviewRecord] = []
    for wid in word_ids:
        wr = rows.get(wid)
        if wr is None:
            continue
        evs = events.get(wid) or []
        current = evs[0] if evs else None
        prior = evs[1] if len(evs) > 1 else None
        records.append(
            WordReviewRecord(
                word_id=wid,
                word=wr["word"],
                activity_type=(
                    current["activity_type"] if current else "srs_review"
                ),
                stability_before=state.before_stability.get(wid),
                stability_after=(
                    wr["stability"] if wr["stability"] is not None else None
                ),
                prior_review_date=to_app_tz_date(
                    prior["created_at"] if prior else None
                ),
                grade=current["grade"] if current else None,
                interval_days=interval_days(wr),
                next_review_date=to_app_tz_date(wr["next_review_at"]),
                difficulty=(
                    wr["difficulty"] if wr["difficulty"] is not None else None
                ),
            )
        )
    return records


__all__ = [
    "SessionState",
    "clear_session",
    "gather_word_records",
    "interval_days",
    "is_valid_prompt_type",
    "load_session",
    "parse_iso_utc",
    "pop_next",
    "push_tier3",
    "rollback_pop",
    "rollback_tier3_push",
    "save_session",
    "state_from_json",
    "state_to_json",
    "to_app_tz_date",
]
