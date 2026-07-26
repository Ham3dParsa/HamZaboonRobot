from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

from config import APP_TIMEZONE, get_user_session_size, daily_card_count_for_plan
from services import db
from services.ai import ai
from services.ai.llm_services import _call_ai_limited
from services.ai.prompts import daily_batch_system_prompt

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
        await _fill_tier3(nodes, remaining, user_id, target_lang, goal, level, plan)

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


async def _fill_tier3(
    nodes: list[SessionNode],
    remaining: int,
    user_id: int,
    target_lang: str,
    goal: str,
    level: str,
    plan: str,
) -> None:
    today = datetime.datetime.now(ZoneInfo(APP_TIMEZONE)).date().isoformat()
    cap = daily_card_count_for_plan(plan)
    used = db.count_daily_cards(user_id, today)
    ai_budget = max(0, cap - used)
    gen_count = min(remaining, ai_budget)
    if gen_count < 1:
        logger.info("Tier 3 skipped: no AI budget (cap=%d used=%d)", cap, used)
        return

    prompt = daily_batch_system_prompt(target_lang, goal, level, gen_count)
    try:
        new_cards = await asyncio.to_thread(
            _call_ai_limited,
            ai.ask_batch,
            prompt,
            gen_count,
            user_id=user_id,
            plan=plan,
            request_kind="session_batch",
        )
    except Exception as exc:
        logger.warning("Tier 3 AI generation failed for user_id=%s: %s", user_id, exc)
        return

    today_cards_used = 0
    for card_dict in new_cards:
        if len(nodes) >= remaining:
            break
        try:
            validated = ai.validate_card(card_dict)
        except Exception:
            logger.warning("Tier 3 card validation skipped for user_id=%s", user_id)
            continue
        if not isinstance(validated, dict):
            continue
        word = (validated.get("word") or "").strip()
        if not word:
            continue
        db.add_saved_word(user_id, word, target_lang, validated)
        card_index = today_cards_used
        db.add_daily_card(user_id, today, card_index, validated, provenance="session_batch")
        today_cards_used += 1
        nodes.append(SessionNode(
            activity_type="vocab_card",
            source_tier=3,
            card_data=validated,
            source_id=None,
        ))

    logger.info(
        "Tier 3 generated %d cards for user_id=%s (budget=%d)",
        today_cards_used,
        user_id,
        gen_count,
    )


def _parse_card_data(row) -> dict | None:
    raw = row["card_data"]
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None
