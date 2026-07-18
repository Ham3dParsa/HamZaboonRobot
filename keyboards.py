from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from catalog import GOALS, LANGUAGES, LEVELS, language_label

BTN_TODAY_CARD = "🃏 فلش‌کارت امروز"
BTN_ASK_WORD = "❓ پرسیدن یک واژه"
BTN_STATUS = "📊 وضعیت من"
BTN_GRAMMAR = "✍️ نکته‌ی گرامری"
BTN_CHANGE_LANG = "🌐 تغییر زبان"
BTN_CHANGE_GOAL = "🎯 تغییر هدف"
BTN_CHANGE_LEVEL = "📚 تنظیم سطح زبان"
BTN_CHANGE_PRESENTATION = "📝 تنظیم نمایش کارت"
BTN_ADMIN = "🛠 مدیریت ربات"
BTN_CANCEL = "❌ لغو"
BTN_BACK = "↩️ بازگشت"



def main_menu(is_owner: bool) -> ReplyKeyboardMarkup:
    rows = [
        [BTN_TODAY_CARD, BTN_GRAMMAR],
        [BTN_ASK_WORD],
        [BTN_STATUS, BTN_CHANGE_LEVEL],
        [BTN_CHANGE_LANG, BTN_CHANGE_GOAL],
        [BTN_CHANGE_PRESENTATION],
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


def presentation_settings_keyboard(
    current: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{'✅ ' if current == 'brief' else ''}خلاصه",
                    callback_data="presentation:set:brief",
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if current == 'detailed' else ''}کامل",
                    callback_data="presentation:set:detailed",
                ),
            ]
        ]
    )


def daily_card_keyboard(
    user_id: int,
    card_date: str,
    card_index: int,
    has_next: bool,
    callback_prefix: str = "daily:next",
    *,
    show_translations: bool = False,
) -> InlineKeyboardMarkup | None:
    if not has_next and not show_translations:
        return None
    translation_prefix = "review:prepare" if callback_prefix.startswith("review:") else "daily:prepare"
    buttons = []
    if show_translations:
        buttons.append(
            InlineKeyboardButton(
                "📝 Prepare translations",
                callback_data=f"{translation_prefix}:{user_id}:{card_date}:{card_index}",
            )
        )
    if has_next:
        buttons.append(
            InlineKeyboardButton(
                "➡️ کارت بعدی",
                callback_data=f"{callback_prefix}:{user_id}:{card_date}:{card_index}",
            )
        )
    return InlineKeyboardMarkup(
        [buttons]
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


def query_result_keyboard(
    token: str,
    lang: str | None = None,
    *,
    show_translations: bool = False,
) -> InlineKeyboardMarkup:
    label = "➕ افزودن به مرور"
    if lang:
        label = f"{label} ({language_label(lang)})"
    buttons = [
        InlineKeyboardButton(
            label,
            callback_data=f"query:add:{token}",
        )
    ]
    if show_translations:
        buttons.append(
            InlineKeyboardButton(
                "📝 Prepare translations",
                callback_data=f"query:prepare:{token}",
            )
        )
    return InlineKeyboardMarkup(
        [buttons]
    )


def srs_hidden_keyboard(user_id: int, word_id: int) -> InlineKeyboardMarkup:
    """Keyboard for the first (hidden) SRS reminder screen.

    Offers a pure-recall action and a reveal action. Recalling without revealing
    is a strong signal; revealing marks the review as "peeked" before the
    follow-up confirmation.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ یادم بود",
                    callback_data=f"srs:remember:{user_id}:{word_id}",
                ),
                InlineKeyboardButton(
                    "👁 افشای کارت کامل",
                    callback_data=f"srs:reveal:{user_id}:{word_id}",
                ),
            ]
        ]
    )


def srs_revealed_keyboard(user_id: int, word_id: int) -> InlineKeyboardMarkup:
    """Keyboard shown after the learner reveals the full card.

    Re-asks whether they truly recalled it before seeing the answer.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ بله، درست بود",
                    callback_data=f"srs:confirm:{user_id}:{word_id}",
                ),
                InlineKeyboardButton(
                    "🔁 نه، باز هم یادآوری کن",
                    callback_data=f"srs:again:{user_id}:{word_id}",
                ),
            ]
        ]
    )


def srs_review_keyboard(
    user_id: int,
    word_id: int,
    *,
    show_translations: bool = False,
) -> InlineKeyboardMarkup:
    review_buttons = [
        InlineKeyboardButton(
            "✅ یادم بود",
            callback_data=f"srs:remember:{user_id}:{word_id}",
        ),
        InlineKeyboardButton(
            "↩️ فردا دوباره",
            callback_data=f"srs:again:{user_id}:{word_id}",
        ),
    ]
    rows = []
    if show_translations:
        rows.append(
            [
                InlineKeyboardButton(
                    "📝 Prepare translations",
                    callback_data=f"srs:prepare:{user_id}:{word_id}",
                )
            ]
        )
    rows.append(review_buttons)
    return InlineKeyboardMarkup(
        rows
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
            [InlineKeyboardButton("🗣 تنظیم تلفظ", callback_data="admin:phonetics")],
            [InlineKeyboardButton("💰 داشبورد هزینه LLM", callback_data="admin:llm_costs")],
            [InlineKeyboardButton("💱 تنظیم قیمت LLM", callback_data="admin:llm_pricing")],
            [InlineKeyboardButton("🤖 تغییر مدل AI", callback_data="admin:set_model")],
            [InlineKeyboardButton("🌐 تغییر Base URL", callback_data="admin:set_base_url")],
            [InlineKeyboardButton("🔑 تغییر API Key", callback_data="admin:set_api_key")],
            [InlineKeyboardButton("📣 ارسال پیام همگانی", callback_data="admin:broadcast")],
            [InlineKeyboardButton("⚙️ تنظیمات فعلی", callback_data="admin:show_settings")],
        ]
    )


def phonetic_settings_keyboard(current: dict[str, bool]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{'✅ ' if current.get('ipa') else ''}IPA",
                    callback_data="admin:phonetics:ipa",
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if current.get('persian') else ''}Persian",
                    callback_data="admin:phonetics:persian",
                ),
            ],
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")],
        ]
    )


def llm_cost_dashboard_keyboard(detail: bool = False) -> InlineKeyboardMarkup:
    recent_label = "Hide Recent Requests" if detail else "Recent Requests"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("MTD", callback_data="llm:range:mtd"),
                InlineKeyboardButton("Last 7 days", callback_data="llm:range:7d"),
                InlineKeyboardButton("All time", callback_data="llm:range:all"),
            ],
            [
                InlineKeyboardButton("Plan", callback_data="llm:set:plan"),
                InlineKeyboardButton("User", callback_data="llm:set:user"),
                InlineKeyboardButton("Request kind", callback_data="llm:set:kind"),
                InlineKeyboardButton("Model", callback_data="llm:set:model"),
            ],
            [
                InlineKeyboardButton("Status", callback_data="llm:set:status"),
                InlineKeyboardButton("Clear filters", callback_data="llm:clear"),
                InlineKeyboardButton("Refresh", callback_data="llm:refresh"),
            ],
            [
                InlineKeyboardButton(recent_label, callback_data="llm:recent"),
            ],
        ]
    )


def llm_cost_plan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("All", callback_data="llm:plan:all"),
                InlineKeyboardButton("Free", callback_data="llm:plan:free"),
                InlineKeyboardButton("Silver", callback_data="llm:plan:silver"),
                InlineKeyboardButton("Gold", callback_data="llm:plan:gold"),
            ]
        ]
    )


def llm_cost_kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("All", callback_data="llm:kind:all"),
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
                InlineKeyboardButton("All", callback_data="llm:status:all"),
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
