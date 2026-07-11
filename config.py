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

FREE_DAILY_CARD_COUNT = int(os.getenv("FREE_DAILY_CARD_COUNT", "3"))
SILVER_DAILY_CARD_COUNT = int(os.getenv("SILVER_DAILY_CARD_COUNT", "12"))
GOLD_DAILY_CARD_COUNT = int(os.getenv("GOLD_DAILY_CARD_COUNT", "30"))
OWNER_BYPASS_LIMITS = os.getenv("OWNER_BYPASS_LIMITS", "true").lower() in {"1", "true", "yes"}

SUPPORTED_LANGS = {
    "en": "انگلیسی",
    "es": "اسپانیایی",
    "ar": "عربی",
    "fr": "فرانسوی",
    "de": "آلمانی",
}

GOALS = {
    "general": "عمومی",
    "konkur": "کنکور",
    "toefl": "تافل",
}

LEVELS = {
    "beginner": "مبتدی",
    "intermediate": "متوسط",
    "advanced": "پیشرفته",
}

LEVEL_CEFR = {
    "beginner": "A1/A2",
    "intermediate": "B1/B2",
    "advanced": "C1/C2",
}

DEFAULT_LEVEL = "beginner"

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