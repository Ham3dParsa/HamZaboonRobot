"""3-tier priority session assembly: due SRS -> first-exposure -> new AI cards.

Architecture decisions (locked, see docs/plans/fsrs/plan_fsrs_migration_v2.md):
- build_session() is the internal, pure, fully-lazy 3-tier generator.
  Useful for isolated testing of assembly logic.
- build_session_list() is the handler-facing entry point.
  Materializes Tiers 1+2 into a list. Deliberately stops short of Tier 3
  per consultant recommendation: Tier 3 refill happens as a direct
  on-demand call from the Telegram handler, not from a persisted generator.
- generate_tier3_node() is a stub returning None until Phase 2.
"""

from __future__ import annotations

import logging
from typing import Any, Generator

from services.db import (
    due_words_for_user,
    get_pre_first_exposure_words,
)

logger = logging.getLogger(__name__)


def build_session(
    user_id: int,
    target_lang: str | None = None,
    goal: str | None = None,
    level: str | None = None,
    plan: str = "free",
    max_nodes: int = 5,
) -> Generator[Any, None, None]:
    """Internal generator: yields SessionNode in 3-tier priority order.

    Tier 1: Due SRS review words (next_review <= today)
    Tier 2: Pre-first-exposure saved words
    Tier 3: New AI-generated cards (lazy via generate_tier3_node)

    Stops after max_nodes yielded across all tiers.
    """
    from services.session import SessionNode

    yield_count = 0

    # Tier 1: Due SRS words
    due = due_words_for_user(user_id) or []
    for row in due:
        if yield_count >= max_nodes:
            return
        yield_count += 1
        yield SessionNode(
            activity_type="srs_review",
            source_tier=1,
            card_data={"word": row["word"]},
            source_id=row["id"],
            activity_meta={"user_id": user_id, "target_lang": target_lang},
            grade_policy_ref="srs_review",
        )

    # Tier 2: Pre-first-exposure words
    fe = get_pre_first_exposure_words(user_id) or []
    for row in fe:
        if yield_count >= max_nodes:
            return
        yield_count += 1
        yield SessionNode(
            activity_type="first_exposure",
            source_tier=2,
            card_data={"word": row["word"]},
            source_id=row["id"],
            activity_meta={"user_id": user_id, "target_lang": target_lang},
            grade_policy_ref="first_exposure",
        )

    # Tier 3: New AI cards (lazy)
    if yield_count < max_nodes:
        remaining = max_nodes - yield_count
        for _ in range(remaining):
            node = generate_tier3_node(user_id, target_lang, goal, level, plan)
            if node is None:
                break
            yield_count += 1
            yield node


def build_session_list(
    user_id: int,
    target_lang: str | None = None,
    goal: str | None = None,
    level: str | None = None,
    plan: str = "free",
    max_nodes: int = 5,
) -> tuple[list[Any], dict[str, Any]]:
    """Handler-facing entry point. Materializes Tiers 1+2, returns tier3_context.

    Returns:
        tuple[list[SessionNode], dict]:
            - nodes: materialized Tier 1 + Tier 2 session nodes
            - tier3_context: params for the handler to call generate_tier3_node()
              later. Always a dict (never None). Empty dict means no tier3
              config is needed (user has hit daily budget, or no more cards).
    """
    from services.session import SessionNode

    nodes: list[Any] = []

    # Materialize Tier 1
    due = due_words_for_user(user_id) or []
    for row in due:
        if len(nodes) >= max_nodes:
            break
        nodes.append(SessionNode(
            activity_type="srs_review",
            source_tier=1,
            card_data={"word": row["word"]},
            source_id=row["id"],
            activity_meta={"user_id": user_id, "target_lang": target_lang},
            grade_policy_ref="srs_review",
        ))

    # Materialize Tier 2
    if len(nodes) < max_nodes:
        fe = get_pre_first_exposure_words(user_id) or []
        for row in fe:
            if len(nodes) >= max_nodes:
                break
            nodes.append(SessionNode(
                activity_type="first_exposure",
                source_tier=2,
                card_data={"word": row["word"]},
                source_id=row["id"],
                activity_meta={"user_id": user_id, "target_lang": target_lang},
                grade_policy_ref="first_exposure",
            ))

    # Build tier3_context — always a dict, never None
    remaining = max_nodes - len(nodes)
    tier3_context: dict[str, Any] = {}
    if remaining > 0:
        tier3_context = {
            "user_id": user_id,
            "target_lang": target_lang,
            "goal": goal,
            "level": level,
            "plan": plan,
            "remaining_slots": remaining,
        }

    return nodes, tier3_context


def generate_tier3_node(
    user_id: int,
    target_lang: str | None = None,
    goal: str | None = None,
    level: str | None = None,
    plan: str | None = None,
    remaining_slots: int | None = None,
) -> Any:
    """Generate a single new AI card node. Stub: returns None.

    Called by the Telegram handler when Tiers 1+2 are exhausted.
    Phase 2 implements real AI generation.
    """
    logger.debug("generate_tier3_node stub called for user_id=%s", user_id)
    return None
