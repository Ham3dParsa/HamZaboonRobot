from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from catalog import GOALS, LANGUAGES, LEVELS

BTN_TODAY_CARD = "🃏 فلش‌کارت امروز"
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
        [BTN_ASK_WORD],
        [BTN_STATUS, BTN_CHANGE_LEVEL],
        [BTN_CHANGE_LANG, BTN_CHANGE_GOAL],
    ]
    if is_owner:
        rows.append([BTN_ADMIN])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def lang_inline_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(option.name_fa, callback_data=f"lang:{option.code}")]
        for option in LANGUAGES.values()
    ]
    return InlineKeyboardMarkup(buttons)


def goal_inline_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(option.name_fa, callback_data=f"goal:{option.code}")]
        for option in GOALS.values()
    ]
    return InlineKeyboardMarkup(buttons)


def level_inline_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                f"{option.name_fa} ({option.cefr})",
                callback_data=f"level:{option.code}",
            )
        ]
        for option in LEVELS.values()
    ]
    return InlineKeyboardMarkup(buttons)


def daily_card_keyboard(
    user_id: int,
    card_date: str,
    card_index: int,
    has_next: bool,
) -> InlineKeyboardMarkup | None:
    if not has_next:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➡️ کارت بعدی",
                    callback_data=f"daily:next:{user_id}:{card_date}:{card_index}",
                )
            ]
        ]
    )


def query_result_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ افزودن به مرور",
                    callback_data=f"query:add:{token}",
                )
            ]
        ]
    )


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
