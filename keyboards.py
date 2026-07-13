from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from catalog import GOALS, LANGUAGES, LEVELS, language_label

BTN_TODAY_CARD = "🃏 فلش‌کارت امروز"
BTN_ASK_WORD = "❓ پرسیدن یک واژه"
BTN_STATUS = "📊 وضعیت من"
BTN_GRAMMAR = "✍️ نکته‌ی گرامری"
BTN_CHANGE_LANG = "🌐 تغییر زبان"
BTN_CHANGE_GOAL = "🎯 تغییر هدف"
BTN_CHANGE_LEVEL = "📚 تنظیم سطح زبان"
BTN_ADMIN = "🛠 مدیریت ربات"
BTN_CANCEL = "❌ لغو"
BTN_BACK = "↩️ بازگشت"



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
    callback_prefix: str = "daily:next",
) -> InlineKeyboardMarkup | None:
    if not has_next:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➡️ کارت بعدی",
                    callback_data=f"{callback_prefix}:{user_id}:{card_date}:{card_index}",
                )
            ]
        ]
    )


def daily_review_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📚 مرور کارت‌ها", callback_data="review:menu")],
        ]
    )


def daily_review_dates_keyboard(
    dates: list[str],
    *,
    page: int = 0,
    total_pages: int = 1,
) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(date, callback_data=f"review:date:{date}")]
        for date in dates
    ]
    nav_buttons = []
    if total_pages > 1:
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("⬅️ جدیدتر", callback_data=f"review:page:{page - 1}")
            )
        nav_buttons.append(InlineKeyboardButton("📚 منوی مرور", callback_data="review:menu"))
        if page + 1 < total_pages:
            nav_buttons.append(
                InlineKeyboardButton("قدیمی‌تر ➡️", callback_data=f"review:page:{page + 1}")
            )
        buttons.append(nav_buttons)
    return InlineKeyboardMarkup(buttons or [[InlineKeyboardButton("فعلاً کارتی نیست", callback_data="review:noop")]])


def query_result_keyboard(token: str, lang: str | None = None) -> InlineKeyboardMarkup:
    label = "➕ افزودن به مرور"
    if lang:
        label = f"{label} ({language_label(lang)})"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"query:add:{token}",
                )
            ]
        ]
    )


def srs_review_keyboard(user_id: int, word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ یادم بود",
                    callback_data=f"srs:remember:{user_id}:{word_id}",
                ),
                InlineKeyboardButton(
                    "↩️ فردا دوباره",
                    callback_data=f"srs:again:{user_id}:{word_id}",
                ),
            ]
        ]
    )


def awaiting_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[BTN_BACK, BTN_CANCEL]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def awaiting_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("↩️ بازگشت", callback_data="flow:back"),
                InlineKeyboardButton("❌ لغو", callback_data="flow:cancel"),
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
