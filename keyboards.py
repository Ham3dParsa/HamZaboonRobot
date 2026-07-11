from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from config import LEVELS, SUPPORTED_LANGS, GOALS

BTN_TODAY_CARD = "📇 واژه‌ی امروز"
BTN_ADD_WORD = "➕ ثبت واژه‌ی دلخواه"
BTN_ASK_WORD = "❓ پرسیدن یک واژه"
BTN_STATUS = "📊 وضعیت من"
BTN_GRAMMAR = "✍️ نکته‌ی گرامری"
BTN_CHANGE_LANG = "🌐 تغییر زبان"
BTN_CHANGE_GOAL = "🎯 تغییر هدف"
BTN_CHANGE_LEVEL = "📚 تنظیم سطح زبان"
BTN_ADMIN = "🛠 مدیریت ربات"



def main_menu(is_owner: bool) -> ReplyKeyboardMarkup:
    rows = [
        [BTN_TODAY_CARD, BTN_GRAMMAR],
        [BTN_ADD_WORD, BTN_ASK_WORD],
        [BTN_STATUS, BTN_CHANGE_LEVEL],
        [BTN_CHANGE_LANG, BTN_CHANGE_GOAL],
    ]
    if is_owner:
        rows.append([BTN_ADMIN])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def lang_inline_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(name, callback_data=f"lang:{code}")] for code, name in SUPPORTED_LANGS.items()]
    return InlineKeyboardMarkup(buttons)


def goal_inline_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(name, callback_data=f"goal:{code}")] for code, name in GOALS.items()]
    return InlineKeyboardMarkup(buttons)


def level_inline_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"{name} ({code})", callback_data=f"level:{code}")]
        for code, name in LEVELS.items()
    ]
    return InlineKeyboardMarkup(buttons)


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📈 آمار کاربران", callback_data="admin:stats")],
            [InlineKeyboardButton("💳 تنظیم پلن کاربر", callback_data="admin:set_plan")],
            [InlineKeyboardButton("🤖 تغییر مدل AI", callback_data="admin:set_model")],
            [InlineKeyboardButton("🌐 تغییر Base URL", callback_data="admin:set_base_url")],
            [InlineKeyboardButton("🔑 تغییر API Key", callback_data="admin:set_api_key")],
            [InlineKeyboardButton("📣 ارسال پیام همگانی", callback_data="admin:broadcast")],
            [InlineKeyboardButton("⚙️ تنظیمات فعلی", callback_data="admin:show_settings")],
        ]
    )
