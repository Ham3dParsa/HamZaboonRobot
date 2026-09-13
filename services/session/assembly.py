"""3-tier priority session assembly: due SRS -> first-exposure -> new AI cards.

Architecture decisions (locked, see docs/plans/fsrs/plan_fsrs_migration_v2.md):
- build_session_list() is the handler-facing entry point.
  Materializes Tiers 1+2 into a list. Deliberately stops short of Tier 3
  per consultant recommendation: Tier 3 refill happens as a direct
  on-demand call from the Telegram handler, not from a persisted generator.
- generate_tier3_node() is a stub returning None until Phase 2.
"""

from __future__ import annotations

import logging
from typing import Any

from services.db import (
    due_words_for_user,
    get_pre_first_exposure_words,
)

logger = logging.getLogger(__name__)


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
    from services.session.tier_registry import build_tier12_nodes

    # Materialize Tier 1 (due path stays unbounded; order verbatim from
    # due_words_for_user via the tier registry).
    due = due_words_for_user(user_id, target_lang) or []
    nodes = build_tier12_nodes(user_id, target_lang, max_nodes, due, [])

    # Materialize Tier 2 (verbatim guard: no tier-2 query when remaining=0;
    # the limit stays caller-side so the query boundary is unchanged).
    if len(nodes) < max_nodes:
        remaining = max_nodes - len(nodes)
        fe = get_pre_first_exposure_words(user_id, target_lang, limit=remaining) or []
        nodes = nodes + build_tier12_nodes(
            user_id, target_lang, remaining, [], fe
        )

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
