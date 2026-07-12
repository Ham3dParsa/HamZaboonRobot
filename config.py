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
DAILY_SEND_HOUR = int(os.getenv("DAILY_SEND_HOUR", "9"))
SRS_SEND_HOUR = int(os.getenv("SRS_SEND_HOUR", "10"))
FREE_DAILY_WORD_LIMIT = int(os.getenv("FREE_DAILY_WORD_LIMIT", "3"))
DEFAULT_ACTIVE_START_MINUTE = int(os.getenv("ACTIVE_START_MINUTE", "480"))
DEFAULT_ACTIVE_END_MINUTE = int(os.getenv("ACTIVE_END_MINUTE", "1260"))
DEFAULT_PREFERRED_DELIVERY_MINUTE = int(
    os.getenv("PREFERRED_DELIVERY_MINUTE", str(DAILY_SEND_HOUR * 60))
)
MIN_SESSIONS = int(os.getenv("MIN_SESSIONS", "3"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "6"))
TARGET_CARDS_PER_SESSION = int(os.getenv("TARGET_CARDS_PER_SESSION", "3"))
SCHEDULER_SLOT_MINUTES = int(os.getenv("SCHEDULER_SLOT_MINUTES", "30"))
SCHEDULER_BUCKET_CAPACITY = int(os.getenv("SCHEDULER_BUCKET_CAPACITY", "4"))
AI_MAX_CONCURRENCY = int(os.getenv("AI_MAX_CONCURRENCY", "2"))
AI_MAX_REQUESTS_PER_MINUTE = int(os.getenv("AI_MAX_REQUESTS_PER_MINUTE", "30"))
TELEGRAM_MAX_CONCURRENCY = int(os.getenv("TELEGRAM_MAX_CONCURRENCY", "4"))
SESSION_CARD_DELAY_SECONDS = float(os.getenv("SESSION_CARD_DELAY_SECONDS", "0.3"))

FREE_DAILY_CARD_COUNT = int(os.getenv("FREE_DAILY_CARD_COUNT", "3"))
SILVER_DAILY_CARD_COUNT = int(os.getenv("SILVER_DAILY_CARD_COUNT", "12"))
GOLD_DAILY_CARD_COUNT = int(os.getenv("GOLD_DAILY_CARD_COUNT", "30"))
OWNER_BYPASS_LIMITS = os.getenv("OWNER_BYPASS_LIMITS", "true").lower() in {"1", "true", "yes"}

PLANS = {
    "free": "رایگان",
    "silver": "نقره‌ای",
    "gold": "طلایی",
}


def daily_card_count_for_plan(plan: str) -> int:
    return {
        "free": FREE_DAILY_CARD_COUNT,
        "silver": SILVER_DAILY_CARD_COUNT,
        "gold": GOLD_DAILY_CARD_COUNT,
    }.get(plan, FREE_DAILY_CARD_COUNT)


def effective_plan(plan: str, bypass_limits: bool = False) -> str:
    if bypass_limits:
        return "gold"
    return plan if plan in PLANS else "free"


def effective_daily_allowance(
    plan: str,
    optional_user_limit: int | None = None,
    bypass_limits: bool = False,
) -> int:
    plan_limit = daily_card_count_for_plan(effective_plan(plan, bypass_limits))
    if optional_user_limit is None or optional_user_limit <= 0:
        return plan_limit
    return min(plan_limit, optional_user_limit)