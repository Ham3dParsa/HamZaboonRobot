import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# این‌ها فقط مقادیر پیش‌فرضِ اولیه‌اند؛ بعد از اجرای اول، مالک می‌تواند
# از داخل خود ربات (پنل مدیریت) مدل/آدرس/کلید را عوض کند و آن مقادیر
# در دیتابیس ذخیره و جایگزین این پیش‌فرض‌ها می‌شوند.
DEFAULT_AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.gapgpt.app/v1")
DEFAULT_AI_API_KEY = os.getenv("AI_API_KEY", "")
DEFAULT_AI_MODEL = os.getenv("AI_MODEL", "gapgpt-qwen-3.6")

DB_PATH = os.getenv("DB_PATH", "hamzaban.db")
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Tehran")


def _parse_clock(value: str, default: str) -> int:
    raw = value or default
    try:
        hour_text, minute_text = raw.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (AttributeError, ValueError):
        raise ValueError(f"invalid clock value {raw!r}; expected HH:MM") from None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"invalid clock value {raw!r}; expected HH:MM")
    return hour * 60 + minute


def _clock_setting(name: str, default: str, legacy_name: str) -> int:
    value = os.getenv(name)
    if value is not None:
        return _parse_clock(value, default)
    legacy_value = os.getenv(legacy_name)
    if legacy_value is not None:
        return int(legacy_value)
    return _parse_clock(default, default)


DEFAULT_ACTIVE_START_MINUTE = _clock_setting(
    "ACTIVE_WINDOW_START", "08:00", "ACTIVE_START_MINUTE"
)
DEFAULT_ACTIVE_END_MINUTE = _clock_setting(
    "ACTIVE_WINDOW_END", "21:00", "ACTIVE_END_MINUTE"
)
DEFAULT_PREFERRED_DELIVERY_MINUTE = _clock_setting(
    "PREFERRED_DELIVERY_TIME", "09:00", "PREFERRED_DELIVERY_MINUTE"
)
SRS_REMINDER_MINUTE = (
    _parse_clock(os.getenv("SRS_REMINDER_TIME", "10:00"), "10:00")
    if os.getenv("SRS_REMINDER_TIME") is not None
    else int(os.getenv("SRS_SEND_HOUR", "10")) * 60
)
MIN_SESSIONS = int(os.getenv("MIN_SESSIONS", "3"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "6"))
TARGET_CARDS_PER_SESSION = int(os.getenv("TARGET_CARDS_PER_SESSION", "3"))
SCHEDULER_SLOT_MINUTES = int(os.getenv("SCHEDULER_SLOT_MINUTES", "30"))
SCHEDULER_BUCKET_CAPACITY = int(os.getenv("SCHEDULER_BUCKET_CAPACITY", "4"))
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
SESSION_CARD_DELAY_SECONDS = float(os.getenv("SESSION_CARD_DELAY_SECONDS", "0.3"))
DELIVERY_MAX_ATTEMPTS = int(os.getenv("DELIVERY_MAX_ATTEMPTS", "5"))
DELIVERY_RETRY_BASE_SECONDS = float(
    os.getenv("DELIVERY_RETRY_BASE_SECONDS", "60")
)
CONNECTION_HEALTH_INTERVAL_SECONDS = float(
    os.getenv("CONNECTION_HEALTH_INTERVAL_SECONDS", "60")
)
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


def effective_daily_allowance(
    plan: str,
    optional_user_limit: int | None = None,
    bypass_limits: bool = False,
) -> int:
    plan_limit = daily_card_count_for_plan(effective_plan(plan, bypass_limits))
    if optional_user_limit is None or optional_user_limit <= 0:
        return plan_limit
    return min(plan_limit, optional_user_limit)