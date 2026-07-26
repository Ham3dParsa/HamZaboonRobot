import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

DEFAULT_AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.gapgpt.app/v1")
DEFAULT_AI_API_KEY = os.getenv("AI_API_KEY", "")
DEFAULT_AI_MODEL = os.getenv("AI_MODEL", "gapgpt-qwen-3.6")

DB_PATH = os.getenv("DB_PATH", "hamzaban.db")
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Tehran")



AI_MAX_CONCURRENCY = int(os.getenv("AI_MAX_CONCURRENCY", "2"))
AI_MAX_REQUESTS_PER_MINUTE = int(os.getenv("AI_MAX_REQUESTS_PER_MINUTE", "30"))
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.6"))
AI_MAX_OUTPUT_TOKENS = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "4096"))
AI_CARD_OUTPUT_FORMAT = os.getenv("AI_CARD_OUTPUT_FORMAT", "compact_json").strip().lower()
if AI_CARD_OUTPUT_FORMAT not in {"json", "compact_json"}:
    raise ValueError("AI_CARD_OUTPUT_FORMAT must be 'json' or 'compact_json'")
DEFAULT_PRESENTATION = os.getenv("DEFAULT_PRESENTATION", "detailed").strip().lower()
if DEFAULT_PRESENTATION not in {"brief", "detailed"}:
    raise ValueError("DEFAULT_PRESENTATION must be 'brief' or 'detailed'")
DEFAULT_PHONETIC_SHOW_IPA = os.getenv("PHONETIC_SHOW_IPA", "true").lower() in {
    "1",
    "true",
    "yes",
}
DEFAULT_PHONETIC_SHOW_PERSIAN = os.getenv("PHONETIC_SHOW_PERSIAN", "true").lower() in {
    "1",
    "true",
    "yes",
}
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

FREE_DAILY_CARD_LIMIT = int(
    os.getenv("FREE_DAILY_CARD_LIMIT", os.getenv("FREE_DAILY_CARD_COUNT", "3"))
)
SILVER_DAILY_CARD_LIMIT = int(
    os.getenv("SILVER_DAILY_CARD_LIMIT", os.getenv("SILVER_DAILY_CARD_COUNT", "12"))
)
GOLD_DAILY_CARD_LIMIT = int(
    os.getenv("GOLD_DAILY_CARD_LIMIT", os.getenv("GOLD_DAILY_CARD_COUNT", "30"))
)
FREE_DAILY_WORD_QUERY_LIMIT = int(
    os.getenv("FREE_DAILY_WORD_QUERY_LIMIT", os.getenv("FREE_DAILY_WORD_LIMIT", "3"))
)
SILVER_DAILY_WORD_QUERY_LIMIT = int(os.getenv("SILVER_DAILY_WORD_QUERY_LIMIT", "16"))
GOLD_DAILY_WORD_QUERY_LIMIT = int(os.getenv("GOLD_DAILY_WORD_QUERY_LIMIT", "40"))
OWNER_BYPASS_LIMITS = os.getenv("OWNER_BYPASS_LIMITS", "false").lower() in {
    "1",
    "true",
    "yes",
}

SESSION_SIZE_FREE = int(os.getenv("SESSION_SIZE_FREE", "5"))
SESSION_SIZE_SILVER = int(os.getenv("SESSION_SIZE_SILVER", "6"))
SESSION_SIZE_GOLD = int(os.getenv("SESSION_SIZE_GOLD", "7"))

PLANS = {
    "free": "رایگان",
    "silver": "نقره‌ای",
    "gold": "طلایی",
}
PREMIUM_PLANS = frozenset({"silver", "gold"})


def daily_card_count_for_plan(plan: str) -> int:
    return {
        "free": FREE_DAILY_CARD_LIMIT,
        "silver": SILVER_DAILY_CARD_LIMIT,
        "gold": GOLD_DAILY_CARD_LIMIT,
    }.get(plan, FREE_DAILY_CARD_LIMIT)


def daily_word_query_limit_for_plan(plan: str) -> int:
    return {
        "free": FREE_DAILY_WORD_QUERY_LIMIT,
        "silver": SILVER_DAILY_WORD_QUERY_LIMIT,
        "gold": GOLD_DAILY_WORD_QUERY_LIMIT,
    }.get(plan, FREE_DAILY_WORD_QUERY_LIMIT)


def effective_plan(plan: str, bypass_limits: bool = False) -> str:
    if bypass_limits:
        return "gold"
    return plan if plan in PLANS else "free"


def presentation_for_user(plan: str, preference: str | None) -> str:
    if plan not in PREMIUM_PLANS:
        return DEFAULT_PRESENTATION
    if preference not in {"brief", "detailed"}:
        return DEFAULT_PRESENTATION
    return preference


def get_user_session_size(plan: str) -> int:
    return {
        "free": SESSION_SIZE_FREE,
        "silver": SESSION_SIZE_SILVER,
        "gold": SESSION_SIZE_GOLD,
    }.get(plan, SESSION_SIZE_FREE)


def is_owner(user_id: int) -> bool:
    return OWNER_ID != 0 and user_id == OWNER_ID


def _app_today() -> str:
    from zoneinfo import ZoneInfo
    import datetime
    return datetime.datetime.now(ZoneInfo(APP_TIMEZONE)).date().isoformat()


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
    actual = PLANS.get(row["plan"] or "free", row["plan"] or "free")
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
