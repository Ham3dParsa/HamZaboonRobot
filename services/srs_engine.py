from __future__ import annotations

import json
import logging
from typing import Any

from config import get_user_session_size
from services import db

logger = logging.getLogger(__name__)

ACTIVITY_REGISTRY: dict[str, Any] = {}


def register_activity(activity_type: str, handler: Any) -> None:
    ACTIVITY_REGISTRY[activity_type] = handler


class SessionNode:
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


async def generate_v3_session(
    user_id: int,
    target_lang: str,
    goal: str,
    level: str,
    plan: str,
) -> dict:
    session_size = get_user_session_size(plan)
    nodes: list[SessionNode] = []

    tier1 = db.due_words_for_user(user_id)
    for row in tier1:
        if len(nodes) >= session_size:
            break
        card_data = _parse_card_data(row)
        if card_data is None:
            continue
        nodes.append(SessionNode(
            activity_type="vocab_card",
            source_tier=1,
            card_data=card_data,
            source_id=row["id"],
        ))

    if len(nodes) < session_size:
        tier2 = db.get_queried_backlog_words(user_id)
        for row in tier2:
            if len(nodes) >= session_size:
                break
            card_data = _parse_card_data(row)
            if card_data is None:
                continue
            nodes.append(SessionNode(
                activity_type="vocab_card",
                source_tier=2,
                card_data=card_data,
                source_id=row["id"],
            ))

    remaining = session_size - len(nodes)
    if remaining > 0:
        logger.info(
            "generate_v3_session Tier 3 stub: would generate %d cards for user_id=%s",
            remaining,
            user_id,
        )

    logger.info(
        "generate_v3_session complete user_id=%s session_size=%d filled=%d",
        user_id,
        session_size,
        len(nodes),
    )

    return {
        "user_id": user_id,
        "target_lang": target_lang,
        "session_size": session_size,
        "nodes": nodes,
        "slot_count": len(nodes),
        "activity_types": list({n.activity_type for n in nodes}),
    }


def _parse_card_data(row) -> dict | None:
    raw = row["card_data"]
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None
