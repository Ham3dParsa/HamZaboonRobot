"""v3 Pull-Based Smart Session Engine.

Core scaffolding for the 3-Tier Priority Queue session generator.
Phase 2 implementation — currently a scaffold with TODO stubs.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Activity Registry (future extensibility)
# ---------------------------------------------------------------------------

ACTIVITY_REGISTRY: dict[str, Any] = {}


def register_activity(activity_type: str, handler: Any) -> None:
    """Register a handler for a polymorphic activity type."""
    ACTIVITY_REGISTRY[activity_type] = handler


# ---------------------------------------------------------------------------
# Session Node
# ---------------------------------------------------------------------------


class SessionNode:
    """A single node in a study session.

    Each node represents one activity unit (flashcard, quiz, etc.).
    The scheduling engine is agnostic to activity_type.
    """

    def __init__(
        self,
        activity_type: str,
        source_tier: int,
        card_data: dict,
        activity_meta: dict | None = None,
        source_id: int | None = None,
    ) -> None:
        self.activity_type = activity_type
        self.source_tier = source_tier
        self.card_data = card_data
        self.activity_meta = activity_meta or {}
        self.source_id = source_id


# ---------------------------------------------------------------------------
# 3-Tier Priority Queue
# ---------------------------------------------------------------------------


async def generate_v3_session(
    user_id: int,
    target_lang: str,
    goal: str,
    level: str,
    plan: str,
) -> dict:
    """Generate a pull-based study session (up to 5 nodes).

    Fills slots via 3-Tier Priority:
        Tier 1: Overdue SRS cards (interval_idx >= 0, next_review <= today)
        Tier 2: Pre-graduation saved words (interval_idx = -1)
        Tier 3: New AI-generated cards

    Returns a session dict with 'nodes' (list of SessionNode) and metadata.
    """
    # TODO: Implement Tier 1 — fetch overdue SRS cards scoped by (user_id, target_lang)
    # TODO: Implement Tier 2 — fetch pre-graduation saved words
    # TODO: Implement Tier 3 — generate new AI cards for remaining slots
    # TODO: Persist session and nodes to smart_study_sessions + session_nodes tables
    # TODO: Consume one session quota slot

    logger.info(
        "generate_v3_session called (stub) user_id=%s target_lang=%s",
        user_id,
        target_lang,
    )
    return {
        "user_id": user_id,
        "target_lang": target_lang,
        "nodes": [],
        "slot_count": 0,
        "activity_types": [],
    }
