"""Tier order registry — read-only view over the due queue (REF4-T5).

Single owner of the tier-1 → tier-2 iteration consumed by BOTH the build
path (``assembly.build_session_list``, ex ``assembly.py:45-72``) and the
refill path (``srs_handler._next_due_node``, ex ``srs_handler.py:692-722``),
moved verbatim in one PR so the two sites can never diverge (queue jumps).

Rules preserved from both bodies:

- Input order is consumed verbatim — ``due_words_for_user`` already returns
  rows sorted by ``_row_priority_key`` (``words.py:216-283``); this module
  never re-sorts.
- Tier 1 (due ``srs_review``) is exhausted before tier 2 (pre-first-exposure
  ``first_exposure``); a future tier-3 source is appended after both, at the
  ``remaining_slots`` point the caller computes.
- ``exclude_ids`` (the refill's in-session ``session_ids``) skips
  already-seen cards in both tiers; the fresh build passes none.
- Node construction (``SessionNode`` kwargs, ``activity_meta`` shape,
  ``grade_policy_ref``) is identical in both sites.
- No DB, no ``today``, no Telegram imports: callers keep their fetch calls
  (``due_words_for_user`` unbounded; ``get_pre_first_exposure_words`` with
  the caller's ``remaining`` limit) so query boundaries are unchanged.

Additive only: ``assembly.build_session_list`` and
``srs_handler._next_due_node`` keep their signatures and become thin
callers; ``assembly`` keeps re-exporting ``due_words_for_user`` /
``get_pre_first_exposure_words`` so existing patch paths keep working.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from services.session import SessionNode

__all__ = [
    "build_tier12_nodes",
    "iter_tier_candidates",
    "make_tier_node",
    "next_tier_node",
]

# Candidate quadruple: (row, activity_type, source_tier, grade_policy_ref).
TierCandidate = tuple[Any, str, int, str]


def iter_tier_candidates(
    due_rows: Iterable[Any] | None,
    fe_rows: Iterable[Any] | None,
    exclude_ids: Iterable[int] = (),
) -> Iterator[TierCandidate]:
    """Yield tier-1 then tier-2 candidates in input order, skipping excluded.

    Verbatim merge of the build loops and the refill ``_candidates``
    generator: tier 1 (due review) first, then tier 2 (first exposure).
    ``exclude_ids`` is the refill's in-session ``session_ids`` set; the
    fresh build passes none.
    """
    excluded = (
        exclude_ids
        if isinstance(exclude_ids, (set, frozenset))
        else set(exclude_ids)
    )
    for row in (due_rows or []):
        if row["id"] not in excluded:
            yield row, "srs_review", 1, "srs_review"
    for row in (fe_rows or []):
        if row["id"] not in excluded:
            yield row, "first_exposure", 2, "first_exposure"


def make_tier_node(
    row: Any,
    activity_type: str,
    source_tier: int,
    grade_policy_ref: str,
    user_id: int,
    target_lang: str | None,
) -> SessionNode:
    """Build the SessionNode both sites constructed inline (verbatim kwargs)."""
    return SessionNode(
        activity_type=activity_type,
        source_tier=source_tier,
        card_data={"word": row["word"]},
        source_id=row["id"],
        activity_meta={"user_id": user_id, "target_lang": target_lang},
        grade_policy_ref=grade_policy_ref,
    )


def build_tier12_nodes(
    user_id: int,
    target_lang: str | None,
    max_nodes: int,
    due_rows: Iterable[Any] | None,
    fe_rows: Iterable[Any] | None,
) -> list[SessionNode]:
    """Materialize up to ``max_nodes`` tier-1 → tier-2 nodes (build verbatim).

    Caps the merged iteration at ``max_nodes`` exactly like the build loops'
    ``if len(nodes) >= max_nodes: break`` guards.
    """
    nodes: list[SessionNode] = []
    for row, activity_type, source_tier, grade_policy in iter_tier_candidates(
        due_rows, fe_rows
    ):
        if len(nodes) >= max_nodes:
            break
        nodes.append(
            make_tier_node(
                row, activity_type, source_tier, grade_policy,
                user_id, target_lang,
            )
        )
    return nodes


def next_tier_node(
    user_id: int,
    target_lang: str | None,
    exclude_ids: Iterable[int],
    due_rows: Iterable[Any] | None,
    fe_rows: Iterable[Any] | None,
) -> SessionNode | None:
    """Return the highest-priority not-yet-in-session card, or None.

    Refill verbatim: the first candidate past ``exclude_ids`` wins.
    """
    for row, activity_type, source_tier, grade_policy in iter_tier_candidates(
        due_rows, fe_rows, exclude_ids
    ):
        return make_tier_node(
            row, activity_type, source_tier, grade_policy,
            user_id, target_lang,
        )
    return None
