from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from .catalog import GOALS, LANGUAGES, LEVELS, language_label

BTN_TODAY_CARD = "🃏 فلش‌کارت امروز"
BTN_ASK_WORD = "❓ پرسیدن یک واژه"
BTN_STATUS = "📊 وضعیت من"
BTN_GRAMMAR = "✍️ نکته‌ی گرامری"
BTN_CHANGE_LANG = "🌐 تغییر زبان"
BTN_CHANGE_GOAL = "🎯 تغییر هدف"
BTN_CHANGE_LEVEL = "📚 تنظیم سطح زبان"
BTN_CHANGE_PRESENTATION = "📝 تنظیم نمایش کارت"
BTN_ADMIN = "🛠 مدیریت ربات"
BTN_ADMIN_STATS = "📈 آمار کاربران"
BTN_ADMIN_BROADCAST = "📣 ارسال پیام همگانی"
BTN_ADMIN_SET_PLAN = "💳 تنظیم پلن کاربر"
BTN_CANCEL = "❌ لغو"
BTN_BACK = "↩️ بازگشت"


# =============================================================================
# Inline Button Labels (IBTN_*)
# -----------------------------------------------------------------------------
# Central registry for all inline keyboard label strings.  Change a label
# once here and every key that uses it stays in sync automatically.
# Organised by functional area; prefix is IBTN_ (Inline ButtoN).
# =============================================================================

# --- Navigation / Generic ---
IBTN_BACK = "↩️ بازگشت"
IBTN_CANCEL = "❌ لغو"
IBTN_CANCEL_EDIT = "↩️ انصراف"
IBTN_BACK_TO_PANEL = "↩️ بازگشت به پنل اصلی"

# --- Presentation ---
IBTN_BRIEF = "خلاصه"
IBTN_DETAILED = "کامل"

# --- Daily Cards & Review ---
IBTN_TRANSLATIONS = "✦ ترجمه مثال‌ها"
IBTN_NEXT_CARD = "➡️ کارت بعدی"
IBTN_REVIEW_CARDS = "📚 مرور کارت‌ها"
IBTN_REVIEW_MENU = "📚 منوی مرور"
IBTN_NEWER = "⬅️ جدیدتر"
IBTN_OLDER = "قدیمی‌تر ➡️"
IBTN_NO_CARDS = "فعلاً کارتی نیست"

# --- SRS (Spaced Repetition) ---
IBTN_REMEMBERED = "✅ یادم بود"
IBTN_REVEAL = "👁 افشای کارت کامل"
IBTN_CONFIRM_CORRECT = "✅ بله، درست بود"
IBTN_REMIND_AGAIN = "🔁 نه، باز هم یادآوری کن"
IBTN_TOMORROW_AGAIN = "↩️ فردا دوباره"

# --- Query / Word Lookup ---
IBTN_ADD_TO_REVIEW = "➕ افزودن به مرور"

# --- Pronunciation ---
IBTN_PRONOUNCE = "🔊 تلفظ"

# --- Admin – General ---
IBTN_ADMIN_AI = "🤖 تنظیمات AI"
IBTN_ADMIN_PHONETICS = "🗣 تنظیم تلفظ"
IBTN_ADMIN_COST = "💰 مدیریت هزینه‌ها"
IBTN_ADMIN_SETTINGS = "⚙️ تنظیمات فعلی"
IBTN_PLAN = "💳 تنظیم پلن"
IBTN_USER_ACTIVITY_LOG = "👤 لاگ فعالیت کاربر"

# --- Admin – Cost Dashboard ---
IBTN_LLM_COST = "💰 داشبورد هزینه LLM"
IBTN_LLM_PRICING = "💱 تنظیم قیمت LLM"

# --- Admin – LLM Dashboard Filters ---
IBTN_RECENT = "Recent Requests"
IBTN_HIDE_RECENT = "Hide Recent Requests"
IBTN_MTD = "MTD"
IBTN_LAST_7 = "Last 7 days"
IBTN_ALL_TIME = "All time"
IBTN_FILTER_PLAN = "Plan"
IBTN_FILTER_USER = "User"
IBTN_FILTER_KIND = "Request kind"
IBTN_FILTER_MODEL = "Model"
IBTN_FILTER_STATUS = "Status"
IBTN_CLEAR_FILTERS = "Clear filters"
IBTN_REFRESH = "Refresh"
IBTN_ALL = "All"
IBTN_FREE = "Free"
IBTN_SILVER = "Silver"
IBTN_GOLD = "Gold"

# --- Admin – LLM Kind / Status Values ---
IBTN_KIND_DAILY = "daily_batch"
IBTN_KIND_CUSTOM = "custom_word"
IBTN_KIND_GRAMMAR = "grammar_tip"
IBTN_STATUS_SUCCESS = "success"
IBTN_STATUS_FAIL_BILLED = "billed fail"
IBTN_STATUS_FAIL_ZERO = "zero-cost fail"

# --- Admin – LLM Pricing ---
IBTN_INPUT_PRICE = "input $/1M"
IBTN_OUTPUT_PRICE = "output $/1M"
IBTN_USD_TOMAN = "USD→تومان"
IBTN_PRICE_BACK = "بازگشت"

# --- Admin – Phonetic Settings ---
IBTN_IPA = "IPA"
IBTN_PERSIAN = "Persian"

# --- Admin – AI Settings ---
IBTN_AI_PRESETS = "🤖 پیش‌تنظیم‌های AI"
IBTN_AI_TEST = "🧪 تست اتصال"
IBTN_AI_CUSTOM_TEST = "🔬 تست سفارشی (Wizard)"
IBTN_AI_FALLBACK = "🔄 پیش‌تنظیم پشتیبان (Fallback)"
IBTN_FALLBACK_CHAIN = "⛓️ زنجیره فال‌بک"

# --- Admin – AI Presets ---
IBTN_ACTIVATE = "✅ فعال کردن"
IBTN_ACTIVATE_THIS = "✅ فعال کردن این پیش‌تنظیم"
IBTN_EDIT = "✏️ ویرایش"
IBTN_DELETE = "🗑 حذف"
IBTN_EDIT_FORK = "✏️ ویرایش (fork)"
IBTN_EDIT_COPY = "✏️ ویرایش (ایجاد کپی سفارشی)"
IBTN_ADD_CUSTOM = "➕ افزودن پیش‌تنظیم سفارشی"
IBTN_SAVE_PRESET = "✅ ذخیره پیش‌تنظیم"

# --- Admin – AI Fallback ---
IBTN_RESET_PRIMARY = "🔄 بازنشانی به Primary (Manual)"

# --- Admin – Custom Test Wizard ---
IBTN_CURRENT_CONFIG = "🎯 Current Config"
IBTN_CANDIDATE = "🧪 Candidate Preset"
IBTN_COMPARE_AB = "⚖️ Compare A/B"
IBTN_CANCEL_WIZARD = "↩️ انصراف"

# --- Admin – Pending Changes ---

# --- Admin – Preset Edit Fields ---
IBTN_FIELD_BASE_URL = "🌐 Base URL"
IBTN_FIELD_MODEL = "🤖 Model"
IBTN_FIELD_API_KEY = "🔑 API Key"
IBTN_FIELD_BATCH_SIZE = "📦 Batch Size"
IBTN_FIELD_CONCURRENCY = "⚡ Concurrency"
IBTN_FIELD_RPM = "🚀 RPM Limit"
IBTN_FIELD_TIMEOUT = "⏱ Timeout (s)"
IBTN_FIELD_TEMPERATURE = "🌡 Temperature"
IBTN_FIELD_MAX_TOKENS = "📝 Max Tokens"
IBTN_FIELD_MAX_TPM = "🔢 حد توکن در دقیقه (TPM)"
IBTN_FIELD_DAILY_REQ = "📊 سقف درخواست روزانه"
IBTN_FIELD_IS_EMERGENCY = "🚨 پریست اضطراری"
IBTN_FIELD_NAME = "✏️ نام پریست"
IBTN_FIELD_INPUT_COST = "💵 هزینه ورودی ($/1M توکن)"
IBTN_FIELD_OUTPUT_COST = "💵 هزینه خروجی ($/1M توکن)"
IBTN_FIELD_IN_FALLBACK_CHAIN = "⛓️ حضور در زنجیره فال‌بک"
IBTN_FIELD_GROUP_LABEL = "🏷️ برچسب گروه"
IBTN_DISCARD_ALL = "🗑️ دور ریختن همه تغییرات"
IBTN_SAVE_CONFIRM = "✅ بله، ذخیره کن"
IBTN_SAVE_CANCEL = "❌ لغو ذخیره"


def main_menu(is_owner: bool) -> ReplyKeyboardMarkup:
    rows = [
        [BTN_TODAY_CARD, BTN_GRAMMAR],
        [BTN_ASK_WORD],
        [BTN_STATUS, BTN_CHANGE_LEVEL],
        [BTN_CHANGE_LANG, BTN_CHANGE_GOAL],
        [BTN_CHANGE_PRESENTATION],
    ]
    if is_owner:
        rows.append([BTN_ADMIN_STATS, BTN_ADMIN_SET_PLAN])
        rows.append([BTN_ADMIN_BROADCAST])
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
                    f"{'✅ ' if current == 'brief' else ''}{IBTN_BRIEF}",
                    callback_data="presentation:set:brief",
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if current == 'detailed' else ''}{IBTN_DETAILED}",
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
    show_pronounce: bool = False,
) -> InlineKeyboardMarkup | None:
    if not has_next and not show_translations and not show_pronounce:
        return None
    translation_prefix = "review:prepare" if callback_prefix.startswith("review:") else "daily:prepare"
    buttons = []
    if show_translations:
        buttons.append(
            InlineKeyboardButton(
                IBTN_TRANSLATIONS,
                callback_data=f"{translation_prefix}:{user_id}:{card_date}:{card_index}",
            )
        )
    if has_next:
        buttons.append(
            InlineKeyboardButton(
                IBTN_NEXT_CARD,
                callback_data=f"{callback_prefix}:{user_id}:{card_date}:{card_index}",
            )
        )
    rows = [buttons] if buttons else []
    if show_pronounce:
        rows.append([
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:d:{user_id}:{card_date}:{card_index}",
            )
        ])
    return InlineKeyboardMarkup(rows)


def daily_review_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(IBTN_REVIEW_CARDS, callback_data="review:menu")],
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
                InlineKeyboardButton(IBTN_NEWER, callback_data=f"review:page:{page - 1}")
            )
        nav_buttons.append(InlineKeyboardButton(IBTN_REVIEW_MENU, callback_data="review:menu"))
        if page + 1 < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(IBTN_OLDER, callback_data=f"review:page:{page + 1}")
            )
        buttons.append(nav_buttons)
    return InlineKeyboardMarkup(buttons or [[InlineKeyboardButton(IBTN_NO_CARDS, callback_data="review:noop")]])


def query_result_keyboard(
    token: str,
    lang: str | None = None,
    *,
    show_translations: bool = False,
    show_pronounce: bool = False,
) -> InlineKeyboardMarkup:
    label = IBTN_ADD_TO_REVIEW
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
                IBTN_TRANSLATIONS,
                callback_data=f"query:prepare:{token}",
            )
        )
    rows = [buttons]
    if show_pronounce:
        rows.append([
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:q:{token}",
            )
        ])
    return InlineKeyboardMarkup(rows)


def srs_hidden_keyboard(
    user_id: int,
    word_id: int,
    *,
    show_pronounce: bool = False,
) -> InlineKeyboardMarkup:
    """Keyboard for the first (hidden) SRS reminder screen.

    Offers a pure-recall action and a reveal action. Recalling without revealing
    is a strong signal; revealing marks the review as "peeked" before the
    follow-up confirmation.
    """
    rows = []
    if show_pronounce:
        rows.append([
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:s:{user_id}:{word_id}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            IBTN_REMEMBERED,
            callback_data=f"srs:remember:{user_id}:{word_id}",
        ),
        InlineKeyboardButton(
            IBTN_REVEAL,
            callback_data=f"srs:reveal:{user_id}:{word_id}",
        ),
    ])
    return InlineKeyboardMarkup(rows)


def srs_revealed_keyboard(
    user_id: int,
    word_id: int,
    *,
    show_pronounce: bool = False,
) -> InlineKeyboardMarkup:
    """Keyboard shown after the learner reveals the full card.

    Re-asks whether they truly recalled it before seeing the answer.
    """
    rows = []
    if show_pronounce:
        rows.append([
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:s:{user_id}:{word_id}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            IBTN_CONFIRM_CORRECT,
            callback_data=f"srs:confirm:{user_id}:{word_id}",
        ),
        InlineKeyboardButton(
            IBTN_REMIND_AGAIN,
            callback_data=f"srs:again:{user_id}:{word_id}",
        ),
    ])
    return InlineKeyboardMarkup(rows)


def srs_review_keyboard(
    user_id: int,
    word_id: int,
    *,
    show_translations: bool = False,
    show_pronounce: bool = False,
) -> InlineKeyboardMarkup:
    review_buttons = [
        InlineKeyboardButton(
            IBTN_REMEMBERED,
            callback_data=f"srs:remember:{user_id}:{word_id}",
        ),
        InlineKeyboardButton(
            IBTN_TOMORROW_AGAIN,
            callback_data=f"srs:again:{user_id}:{word_id}",
        ),
    ]
    rows = []
    if show_translations:
        rows.append(
            [
                InlineKeyboardButton(
                    IBTN_TRANSLATIONS,
                    callback_data=f"srs:prepare:{user_id}:{word_id}",
                )
            ]
        )
    if show_pronounce:
        rows.append([
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:s:{user_id}:{word_id}",
            )
        ])
    rows.append(review_buttons)
    return InlineKeyboardMarkup(rows)


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
                InlineKeyboardButton(BTN_BACK, callback_data="flow:back"),
                InlineKeyboardButton(BTN_CANCEL, callback_data="flow:cancel"),
            ]
        ]
    )


def admin_awaiting_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("↩️ Back", callback_data="admin:back"),
                InlineKeyboardButton("❌ Cancel", callback_data="admin:cancel"),
            ]
        ]
    )


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_ADMIN_STATS, callback_data="admin:stats"),
             InlineKeyboardButton(IBTN_PLAN, callback_data="admin:set_plan")],
            [InlineKeyboardButton(IBTN_ADMIN_AI, callback_data="admin:ai_settings"),
             InlineKeyboardButton(IBTN_ADMIN_PHONETICS, callback_data="admin:phonetics")],
            [InlineKeyboardButton(IBTN_ADMIN_COST, callback_data="admin:cost_dashboard"),
             InlineKeyboardButton(IBTN_ADMIN_SETTINGS, callback_data="admin:show_settings")],
            [InlineKeyboardButton("📋 سطح لاگ", callback_data="admin:log_level"),
             InlineKeyboardButton(BTN_ADMIN_BROADCAST, callback_data="admin:broadcast")],
            [InlineKeyboardButton(IBTN_USER_ACTIVITY_LOG, callback_data="admin:user_activity_log")],
        ]
    )


def user_activity_keyboard(current_status: str) -> InlineKeyboardMarkup:
    """Inline keyboard showing USER_ACTIVITY log toggle with current status."""
    marker = "✅" if current_status == "on" else "☑️"
    status_fa = "روشن" if current_status == "on" else "خاموش"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{marker} لاگ فعالیت کاربر: {status_fa}", callback_data="admin:user_activity:toggle")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")],
    ])


def log_level_keyboard(current_level: str) -> InlineKeyboardMarkup:
    """Inline keyboard with one button per log level; marks the active one."""
    levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    rows = []
    for level in levels:
        marker = "✅ " if level == current_level else ""
        rows.append([InlineKeyboardButton(f"{marker}{level}", callback_data=f"admin:log_level:set:{level}")])
    rows.append([InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")])
    return InlineKeyboardMarkup(rows)


def admin_cost_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(IBTN_LLM_COST, callback_data="admin:llm_costs")],
            [InlineKeyboardButton(IBTN_LLM_PRICING, callback_data="admin:llm_pricing")],
            [InlineKeyboardButton(IBTN_BACK_TO_PANEL, callback_data="admin:back")],
        ]
    )


def phonetic_settings_keyboard(current: dict[str, bool]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{'✅ ' if current.get('ipa') else ''}{IBTN_IPA}",
                    callback_data="admin:phonetics:ipa",
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if current.get('persian') else ''}{IBTN_PERSIAN}",
                    callback_data="admin:phonetics:persian",
                ),
            ],
            [InlineKeyboardButton(BTN_BACK, callback_data="admin:back")],
        ]
    )


def llm_cost_dashboard_keyboard(detail: bool = False) -> InlineKeyboardMarkup:
    recent_label = IBTN_HIDE_RECENT if detail else IBTN_RECENT
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(IBTN_MTD, callback_data="llm:range:mtd"),
                InlineKeyboardButton(IBTN_LAST_7, callback_data="llm:range:7d"),
                InlineKeyboardButton(IBTN_ALL_TIME, callback_data="llm:range:all"),
            ],
            [
                InlineKeyboardButton(IBTN_FILTER_PLAN, callback_data="llm:set:plan"),
                InlineKeyboardButton(IBTN_FILTER_USER, callback_data="llm:set:user"),
                InlineKeyboardButton(IBTN_FILTER_KIND, callback_data="llm:set:kind"),
                InlineKeyboardButton(IBTN_FILTER_MODEL, callback_data="llm:set:model"),
            ],
            [
                InlineKeyboardButton(IBTN_FILTER_STATUS, callback_data="llm:set:status"),
                InlineKeyboardButton(IBTN_CLEAR_FILTERS, callback_data="llm:clear"),
                InlineKeyboardButton(IBTN_REFRESH, callback_data="llm:refresh"),
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
                InlineKeyboardButton(IBTN_ALL, callback_data="llm:plan:all"),
                InlineKeyboardButton(IBTN_FREE, callback_data="llm:plan:free"),
                InlineKeyboardButton(IBTN_SILVER, callback_data="llm:plan:silver"),
                InlineKeyboardButton(IBTN_GOLD, callback_data="llm:plan:gold"),
            ]
        ]
    )


def llm_cost_kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(IBTN_ALL, callback_data="llm:kind:all"),
                InlineKeyboardButton(IBTN_KIND_DAILY, callback_data="llm:kind:daily_batch"),
                InlineKeyboardButton(IBTN_KIND_CUSTOM, callback_data="llm:kind:custom_word"),
                InlineKeyboardButton(IBTN_KIND_GRAMMAR, callback_data="llm:kind:grammar_tip"),
            ]
        ]
    )


def llm_cost_status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(IBTN_ALL, callback_data="llm:status:all"),
                InlineKeyboardButton(IBTN_STATUS_SUCCESS, callback_data="llm:status:success"),
                InlineKeyboardButton(IBTN_STATUS_FAIL_BILLED, callback_data="llm:status:failure_billed"),
                InlineKeyboardButton(IBTN_STATUS_FAIL_ZERO, callback_data="llm:status:failure_zero_cost"),
            ]
        ]
    )


def llm_cost_pricing_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(IBTN_INPUT_PRICE, callback_data="llm:pricing:set_input"),
                InlineKeyboardButton(IBTN_OUTPUT_PRICE, callback_data="llm:pricing:set_output"),
                InlineKeyboardButton(IBTN_USD_TOMAN, callback_data="llm:pricing:set_rate"),
            ],
            [
                InlineKeyboardButton(IBTN_PRICE_BACK, callback_data="llm:pricing:back"),
            ],
        ]
    )


# ---------- AI Settings / Presets Keyboards ----------

def ai_settings_keyboard() -> InlineKeyboardMarkup:
    """Main AI settings panel."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(IBTN_AI_PRESETS, callback_data="admin:ai_presets")],
            [InlineKeyboardButton(IBTN_AI_TEST, callback_data="admin:ai_test_connection")],
            [InlineKeyboardButton(IBTN_AI_CUSTOM_TEST, callback_data="admin:ai_custom_test")],
            [InlineKeyboardButton(IBTN_AI_FALLBACK, callback_data="admin:ai_fallback")],
            [InlineKeyboardButton(IBTN_FALLBACK_CHAIN, callback_data="admin:fallback_chain")],
            [InlineKeyboardButton(IBTN_BACK_TO_PANEL, callback_data="admin:back")],
        ]
    )


def ai_presets_list_keyboard(presets: list[dict], active_name: str) -> InlineKeyboardMarkup:
    """List presets with activate/edit/delete buttons."""
    rows = []
    for p in presets:
        name = p["name"]
        is_active = "✅ " if name == active_name else ""
        is_custom = p.get("is_custom", 0)
        label = f"{is_active}{name}"
        if is_custom:
            label += " (custom)"
        rows.append([
            InlineKeyboardButton(label, callback_data=f"admin:ai_preset:view:{name}"),
        ])
        # Action buttons row
        action_row = []
        if name != active_name:
            action_row.append(InlineKeyboardButton(IBTN_ACTIVATE, callback_data=f"admin:ai_preset:activate:{name}"))
        if is_custom:
            action_row.append(InlineKeyboardButton(IBTN_EDIT, callback_data=f"admin:ai_preset:edit:{name}"))
            action_row.append(InlineKeyboardButton(IBTN_DELETE, callback_data=f"admin:ai_preset:delete:{name}"))
        else:
            action_row.append(InlineKeyboardButton(IBTN_EDIT_FORK, callback_data=f"admin:ai_preset:edit:{name}"))
        if action_row:
            rows.append(action_row)
    rows.append([InlineKeyboardButton(IBTN_ADD_CUSTOM, callback_data="admin:ai_preset:add")])
    rows.append([InlineKeyboardButton(BTN_BACK, callback_data="admin:ai_settings")])
    return InlineKeyboardMarkup(rows)


def ai_preset_view_keyboard(preset: dict, active_name: str) -> InlineKeyboardMarkup:
    """View/edit a specific preset."""
    name = preset["name"]
    is_custom = preset.get("is_custom", 0)
    rows = []
    if name != active_name:
        rows.append([InlineKeyboardButton(IBTN_ACTIVATE_THIS, callback_data=f"admin:ai_preset:activate:{name}")])
    if is_custom:
        rows.append([InlineKeyboardButton(IBTN_EDIT, callback_data=f"admin:ai_preset:edit:{name}")])
        rows.append([InlineKeyboardButton(IBTN_DELETE, callback_data=f"admin:ai_preset:delete:{name}")])
    else:
        rows.append([InlineKeyboardButton(IBTN_EDIT_COPY, callback_data=f"admin:ai_preset:edit:{name}")])
    rows.append([InlineKeyboardButton(BTN_BACK, callback_data="admin:ai_presets")])
    return InlineKeyboardMarkup(rows)


def ai_preset_edit_keyboard(preset_name: str, preset: dict | None = None) -> InlineKeyboardMarkup:
    """Keyboard for editing a preset field-by-field."""
    fields = [
        ("base_url", IBTN_FIELD_BASE_URL),
        ("model", IBTN_FIELD_MODEL),
        ("api_key", IBTN_FIELD_API_KEY),
        ("daily_batch_size", IBTN_FIELD_BATCH_SIZE),
        ("max_concurrency", IBTN_FIELD_CONCURRENCY),
        ("max_rpm", IBTN_FIELD_RPM),
        ("timeout_seconds", IBTN_FIELD_TIMEOUT),
        ("temperature", IBTN_FIELD_TEMPERATURE),
        ("max_output_tokens", IBTN_FIELD_MAX_TOKENS),
        ("max_tpm", IBTN_FIELD_MAX_TPM),
        ("max_daily_req", IBTN_FIELD_DAILY_REQ),
        ("is_emergency", IBTN_FIELD_IS_EMERGENCY),
        ("name", IBTN_FIELD_NAME),
        ("input_cost_per_million", IBTN_FIELD_INPUT_COST),
        ("output_cost_per_million", IBTN_FIELD_OUTPUT_COST),
        ("in_fallback_chain", IBTN_FIELD_IN_FALLBACK_CHAIN),
        ("group_label", IBTN_FIELD_GROUP_LABEL),
    ]
    rows = []
    for key, label in fields:
        current = preset.get(key, "") if preset else ""
        display = current
        if key == "api_key" and current:
            display = (current[:6] + "…" + current[-4:]) if len(current) > 12 else "***"
        suffix = f": {display}" if display else ""
        rows.append([
            InlineKeyboardButton(f"{label}{suffix}", callback_data=f"admin:ai_preset:edit_field:{preset_name}:{key}"),
        ])
    rows.append([InlineKeyboardButton(IBTN_DISCARD_ALL, callback_data=f"admin:ai_preset:discard_all:{preset_name}")])
    rows.append([InlineKeyboardButton(IBTN_SAVE_PRESET, callback_data=f"admin:ai_preset:save:{preset_name}")])
    rows.append([InlineKeyboardButton(IBTN_CANCEL_EDIT, callback_data=f"admin:ai_preset:view:{preset_name}")])
    return InlineKeyboardMarkup(rows)


def ai_fallback_keyboard(primary: str, fallback: str, active: str) -> InlineKeyboardMarkup:
    """Fallback configuration panel."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"Primary: {primary}", callback_data="admin:ai_fallback:set_primary")],
            [InlineKeyboardButton(f"Fallback: {fallback}", callback_data="admin:ai_fallback:set_fallback")],
            [InlineKeyboardButton(IBTN_RESET_PRIMARY, callback_data="admin:ai_fallback:reset")],
            [InlineKeyboardButton(BTN_BACK, callback_data="admin:ai_settings")],
        ]
    )


def ai_custom_test_wizard_keyboard(step: str, lang: str | None = None, goal: str | None = None, level: str | None = None, target: str | None = None) -> InlineKeyboardMarkup:
    """Keyboard for the custom test wizard."""
    rows = []
    if step == "lang":
        from catalog import LANGUAGES
        for code, opt in LANGUAGES.items():
            rows.append([InlineKeyboardButton(opt.name_fa, callback_data=f"admin:ai_custom_test:lang:{code}")])
    elif step == "goal":
        from catalog import GOALS
        for code, opt in GOALS.items():
            rows.append([InlineKeyboardButton(opt.name_fa, callback_data=f"admin:ai_custom_test:goal:{code}")])
    elif step == "level":
        from catalog import LEVELS
        for code, opt in LEVELS.items():
            rows.append([InlineKeyboardButton(f"{opt.name_fa} ({opt.cefr})", callback_data=f"admin:ai_custom_test:level:{code}")])
    elif step == "target":
        rows.append([InlineKeyboardButton(IBTN_CURRENT_CONFIG, callback_data="admin:ai_custom_test:target:current")])
        rows.append([InlineKeyboardButton(IBTN_CANDIDATE, callback_data="admin:ai_custom_test:target:candidate")])
        rows.append([InlineKeyboardButton(IBTN_COMPARE_AB, callback_data="admin:ai_custom_test:target:ab")])
    if step != "prompt":
        rows.append([InlineKeyboardButton(IBTN_CANCEL_WIZARD, callback_data="admin:ai_settings")])
    return InlineKeyboardMarkup(rows)


def fallback_chain_keyboard(chain: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for preset in chain:
        name = preset.get("name", "?")
        label = f"{'🚨 ' if preset.get('is_emergency') else '📊 '}{name}"
        if not preset.get("enabled", 1):
            label = f"🔴 {name} (غیرفعال)"
        cols = [
            InlineKeyboardButton("⬆", callback_data=f"admin:fallback:move_up:{name}"),
            InlineKeyboardButton("⬇", callback_data=f"admin:fallback:move_down:{name}"),
        ]
        toggle_label = "🟢 فعال" if preset.get("enabled", 1) else "🔴 غیرفعال"
        cols.append(InlineKeyboardButton(toggle_label, callback_data=f"admin:fallback:toggle:{name}"))
        if not preset.get("is_emergency"):
            cols.append(InlineKeyboardButton("🚨 اضطراری", callback_data=f"admin:fallback:set_emergency:{name}"))
        rows.append([InlineKeyboardButton(label, callback_data="admin:noop")])
        rows.append(cols)
    rows.append([InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")])
    return InlineKeyboardMarkup(rows)
