import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

DEFAULT_AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.gapgpt.app/v1")
DEFAULT_AI_API_KEY = os.getenv("AI_API_KEY", "")
DEFAULT_AI_MODEL = os.getenv("AI_MODEL", "gapgpt-qwen-3.6")

# Fernet master key for encrypting API keys at rest (Phase 5, R11/F2). Must be
# a valid 32-byte url-safe base64 Fernet key (see `.env.example`). When unset,
# API-key encryption is fail-closed: keys cannot be encrypted or decrypted.
AI_MASTER_KEY = os.getenv("AI_MASTER_KEY", "")

DB_PATH = os.getenv("DB_PATH", "hamzaban.db")
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Tehran")



AI_MAX_CONCURRENCY = int(os.getenv("AI_MAX_CONCURRENCY", "2"))
AI_MAX_REQUESTS_PER_MINUTE = int(os.getenv("AI_MAX_REQUESTS_PER_MINUTE", "30"))
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))
ASK_WORD_AI_TIMEOUT_SECONDS = float(os.getenv("ASK_WORD_AI_TIMEOUT_SECONDS", "60"))
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.6"))
AI_MAX_OUTPUT_TOKENS = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "4096"))
AI_CARD_OUTPUT_FORMAT = os.getenv("AI_CARD_OUTPUT_FORMAT", "compact_json").strip().lower()
if AI_CARD_OUTPUT_FORMAT not in {"json", "compact_json"}:
    raise ValueError("AI_CARD_OUTPUT_FORMAT must be 'json' or 'compact_json'")
DEFAULT_PRESENTATION = os.getenv("DEFAULT_PRESENTATION", "detailed").strip().lower()
if DEFAULT_PRESENTATION not in {"brief", "detailed"}:
    raise ValueError("DEFAULT_PRESENTATION must be 'brief' or 'detailed'")
LLM_INPUT_COST_USD_PER_MILLION = float(
    os.getenv("LLM_INPUT_COST_USD_PER_MILLION", "0.25")
)
LLM_OUTPUT_COST_USD_PER_MILLION = float(
    os.getenv("LLM_OUTPUT_COST_USD_PER_MILLION", "1.5")
)
USD_TO_TOMAN_RATE = float(os.getenv("USD_TO_TOMAN_RATE", "180000"))
TELEGRAM_MAX_CONCURRENCY = int(os.getenv("TELEGRAM_MAX_CONCURRENCY", "4"))

CONNECTION_HEALTH_INTERVAL_SECONDS = float(
    os.getenv("CONNECTION_HEALTH_INTERVAL_SECONDS", "30")
)

_LOG_LEVEL_RAW = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOG_LEVEL = _LOG_LEVEL_RAW if _LOG_LEVEL_RAW in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO"
COST = 25
USER_ACTIVITY = 26
if CONNECTION_HEALTH_INTERVAL_SECONDS <= 0:
    raise ValueError("CONNECTION_HEALTH_INTERVAL_SECONDS must be positive")

OWNER_BYPASS_LIMITS = os.getenv("OWNER_BYPASS_LIMITS", "false").lower() in {
    "1",
    "true",
    "yes",
}

# Canonical plan name -> learner-facing label (Rule 2; the DB display_name is
# authoritative at runtime for admin-edited labels, but this map provides the
# stable code-name fallback and set membership).
PLANS = {
    "free": "رایگان",
    "bronze": "برنزی",
    "silver": "نقره‌ای",
    "gold": "طلایی",
    "emerald": "زمردی",
}
PREMIUM_PLANS = frozenset({"silver", "gold", "emerald"})


def _plan_spec(plan: str) -> dict:
    """Return the armed plan spec dict.

    Thin delegate to ``plans.plan_spec``, the single owner of per-plan quota
    semantics (R5). R2/R7: a missing or deactivated plan resolves to 'free'.
    """
    from services.db.plans import plan_spec
    return plan_spec(plan)


def max_sessions_for_plan(plan: str) -> int:
    return int(_plan_spec(plan).get("max_sessions") or 1)


def cards_per_session_for_plan(plan: str) -> int:
    return int(_plan_spec(plan).get("cards_per_session") or 1)


def plan_display_name(plan: str) -> str:
    display = _plan_spec(plan).get("display_name")
    return display or PLANS.get(plan, plan)


def daily_card_count_for_plan(plan: str) -> int:
    return max_sessions_for_plan(plan) * cards_per_session_for_plan(plan)


def daily_word_query_limit_for_plan(plan: str) -> int:
    return int(_plan_spec(plan).get("query_quota") or 0)


def effective_plan(plan: str, bypass_limits: bool = False) -> str:
    from services.db.plans import effective_plan as _effective_plan
    return _effective_plan(plan, bypass_limits)


def presentation_for_user(plan: str, preference: str | None) -> str:
    from services.db.plans import is_premium
    if not is_premium(plan):
        return DEFAULT_PRESENTATION
    if preference not in {"brief", "detailed"}:
        return DEFAULT_PRESENTATION
    return preference


def is_owner(user_id: int) -> bool:
    return OWNER_ID != 0 and user_id == OWNER_ID


def _resolve_app_tz():
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    import datetime as _dt
    try:
        return ZoneInfo(APP_TIMEZONE)
    except (ZoneInfoNotFoundError, KeyError):
        import logging as _log
        _log.getLogger(__name__).warning(
            "APP_TIMEZONE=%r not found in tz database; falling back to UTC", APP_TIMEZONE,
        )
        return _dt.timezone.utc


APP_TZ = _resolve_app_tz()


def _app_today() -> str:
    import datetime
    return datetime.datetime.now(APP_TZ).date().isoformat()


def _user_presentation(row) -> str:
    if not row:
        return DEFAULT_PRESENTATION
    return presentation_for_user(
        row["plan"] or "free",
        row["presentation_preference"],
    )


def _user_plan(row) -> str:
    return effective_plan(row["plan"] or "free", OWNER_BYPASS_LIMITS and is_owner(row["user_id"]))


def _user_plan_label(row) -> str:
    actual = plan_display_name(row["plan"] or "free")
    if OWNER_BYPASS_LIMITS and is_owner(row["user_id"]):
        return f"{actual} (دسترسی مالک)"
    return actual


def effective_daily_allowance(
    plan: str,
    optional_user_limit: int | None = None,
    bypass_limits: bool = False,
) -> int:
    plan_limit = daily_card_count_for_plan(effective_plan(plan, bypass_limits))
    if optional_user_limit is None or optional_user_limit <= 0:
        return plan_limit
    return min(plan_limit, optional_user_limit)
