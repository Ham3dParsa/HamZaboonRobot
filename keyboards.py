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
            [InlineKeyboardButton("💰 داشبورد هزینه LLM", callback_data="admin:llm_costs")],
            [InlineKeyboardButton("💱 تنظیم قیمت LLM", callback_data="admin:llm_pricing")],
            [InlineKeyboardButton("🤖 تغییر مدل AI", callback_data="admin:set_model")],
            [InlineKeyboardButton("🌐 تغییر Base URL", callback_data="admin:set_base_url")],
            [InlineKeyboardButton("🔑 تغییر API Key", callback_data="admin:set_api_key")],
            [InlineKeyboardButton("📣 ارسال پیام همگانی", callback_data="admin:broadcast")],
            [InlineKeyboardButton("⚙️ تنظیمات فعلی", callback_data="admin:show_settings")],
        ]
    )


def llm_cost_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("امروز", callback_data="llm:range:today"),
                InlineKeyboardButton("7d", callback_data="llm:range:7d"),
                InlineKeyboardButton("30d", callback_data="llm:range:30d"),
                InlineKeyboardButton("MTD", callback_data="llm:range:mtd"),
            ],
            [
                InlineKeyboardButton("پلن", callback_data="llm:set:plan"),
                InlineKeyboardButton("کاربر", callback_data="llm:set:user"),
                InlineKeyboardButton("نوع درخواست", callback_data="llm:set:kind"),
                InlineKeyboardButton("مدل", callback_data="llm:set:model"),
            ],
            [
                InlineKeyboardButton("وضعیت", callback_data="llm:set:status"),
                InlineKeyboardButton("پاک‌کردن فیلترها", callback_data="llm:clear"),
                InlineKeyboardButton("تازه‌سازی", callback_data="llm:refresh"),
            ],
            [
                InlineKeyboardButton("نمای جزئی", callback_data="llm:recent"),
            ],
        ]
    )


def llm_cost_plan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("همه", callback_data="llm:plan:all"),
                InlineKeyboardButton("رایگان", callback_data="llm:plan:free"),
                InlineKeyboardButton("نقره‌ای", callback_data="llm:plan:silver"),
                InlineKeyboardButton("طلایی", callback_data="llm:plan:gold"),
            ]
        ]
    )


def llm_cost_kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("همه", callback_data="llm:kind:all"),
                InlineKeyboardButton("daily_batch", callback_data="llm:kind:daily_batch"),
                InlineKeyboardButton("custom_word", callback_data="llm:kind:custom_word"),
                InlineKeyboardButton("grammar_tip", callback_data="llm:kind:grammar_tip"),
            ]
        ]
    )


def llm_cost_status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("همه", callback_data="llm:status:all"),
                InlineKeyboardButton("success", callback_data="llm:status:success"),
                InlineKeyboardButton("billed fail", callback_data="llm:status:failure_billed"),
                InlineKeyboardButton("zero-cost fail", callback_data="llm:status:failure_zero_cost"),
            ]
        ]
    )


def llm_cost_pricing_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("input $/1M", callback_data="llm:pricing:set_input"),
                InlineKeyboardButton("output $/1M", callback_data="llm:pricing:set_output"),
                InlineKeyboardButton("USD→تومان", callback_data="llm:pricing:set_rate"),
            ],
            [
                InlineKeyboardButton("بازگشت", callback_data="llm:pricing:back"),
            ],
        ]
    )
