import logging

logger = logging.getLogger(__name__)

PLAN_SESSION_CONFIG: dict[str, int] = {
    "free": 1,
    "silver": 4,
    "gold": 10,
}


def daily_session_budget(user_id: int, plan: str) -> dict:
    total = PLAN_SESSION_CONFIG.get(plan, PLAN_SESSION_CONFIG["free"])
    return {
        "total": total,
        "remaining": total,
        "used": 0,
        "plan": plan,
    }


def consume_session_slot(user_id: int) -> bool:
    logger.debug("consume_session_slot(user_id=%s) — stub returning True", user_id)
    return True


def release_session_slot(user_id: int) -> None:
    logger.debug("release_session_slot(user_id=%s) — stub no-op", user_id)
