from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from .catalog import GOALS, LANGUAGES, LEVELS, language_label

BTN_STUDY_SESSION = "📚 شروع مطالعه امروز"
BTN_ASK_WORD = "❓ پرسیدن یک واژه"
BTN_SETTINGS = "⚙️ تنظیمات و پروفایل من"
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
IBTN_CLOSE = "❌ بستن"
IBTN_BACK_TO_SETTINGS = "↩️ بازگشت به تنظیمات"

# --- Presentation ---
IBTN_BRIEF = "خلاصه"
IBTN_DETAILED = "کامل"

# --- Daily Cards & Review ---

# --- SRS 4-Grade (Review: recall-based) ---
IBTN_SRS_AGAIN_REVIEW = "یادم نیامد ⭕"
IBTN_SRS_HARD_REVIEW = "به سختی یادم اومد 🟡"
IBTN_SRS_GOOD_REVIEW = "خوب بود 🟢"
IBTN_SRS_EASY_REVIEW = "خیلی آسون 🟣"

# --- SRS 4-Grade (First-Exposure: familiarity-based) ---
IBTN_SRS_AGAIN_FE = "کاملاً ناآشناام 🟥"
IBTN_SRS_HARD_FE = "کمی آشناام 🟨"
IBTN_SRS_GOOD_FE = "آشنایی خوب 🟩"
IBTN_SRS_EASY_FE = "کاملاً بلدم 🟪"
IBTN_SRS_REVEAL = "👁 نمایش پاسخ"
IBTN_SRS_DELETE = "🗑 حذف از مطالعه"
IBTN_SRS_DELETE_CONFIRM = "✅ بله، حذف شود"
IBTN_SRS_DELETE_CANCEL = "❌ انصراف"

# --- Query / Word Lookup ---
IBTN_ADD_TO_REVIEW = "ذخیره برای مطالعه"
IBTN_REMOVE_FROM_REVIEW = "حذف از نشست‌های مطالعه"
IBTN_QUERY_DUP_NEW = "درخواست جدید (مصرف سهمیه)"
IBTN_QUERY_DUP_REUSE = "بازیابی کارت پیشین (رایگان)"
IBTN_QUERY_DUP_CANCEL = "انصراف / بازگشت به منو"

# --- Pronunciation ---
IBTN_PRONOUNCE = "🔊 شیدن واژه"

# --- Admin – General ---
IBTN_ADMIN_AI = "🤖 تنظیمات AI"
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

# --- Admin – AI Settings ---
IBTN_AI_PRESETS = "🤖 پیش‌تنظیم‌های AI"
IBTN_AI_TEST = "🧪 تست اتصال"
IBTN_AI_CUSTOM_TEST = "🔬 تست سفارشی (Wizard)"
IBTN_AI_FALLBACK = "🔄 پیش‌تنظیم پشتیبان (Fallback)"
IBTN_FALLBACK_CHAIN = "⛓️ زنجیره فال‌بک"

# --- Admin – AI Presets ---
IBTN_ACTIVATE = "🎯 فعال کردن"
IBTN_ACTIVATE_THIS = "🎯 فعال کردن این پیش‌تنظیم"
IBTN_DEACTIVATE = "⛔ غیرفعال کردن"
IBTN_EDIT = "✏️ ویرایش"
IBTN_DELETE = "🗑 حذف"
IBTN_DELETE_CONFIRM = "✅ بله، حذف کن"
IBTN_DELETE_CANCEL = "❌ انصراف"
IBTN_DUPLICATE = "📑 کپی (Duplicate)"
IBTN_ADD_CUSTOM = "➕ افزودن پیش‌تنظیم سفارشی"
IBTN_SAVE_PRESET = "✅ ذخیره پیش‌تنظیم"
IBTN_DETACH_GROUP = "🚫 حذف از گروه"

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
IBTN_FIELD_IS_EMERGENCY = "🛡️ پریست اضطراری"
IBTN_FIELD_NAME = "✏️ نام پریست"
IBTN_FIELD_INPUT_COST = "💵 هزینه ورودی ($/1M توکن)"
IBTN_FIELD_OUTPUT_COST = "💵 هزینه خروجی ($/1M توکن)"
IBTN_FIELD_IN_FALLBACK_CHAIN = "⛓️ حضور در زنجیره فال‌بک"
IBTN_FIELD_GROUP_LABEL = "🏷️ برچسب گروه"
IBTN_DISCARD_ALL = "🗑️ دور ریختن همه تغییرات"
IBTN_SAVE_CONFIRM = "✅ بله، ذخیره کن"
IBTN_SAVE_CANCEL = "❌ لغو ذخیره"

# --- Admin – Full Edit Wizard ---
IBTN_FULL_EDIT_WIZARD = "✏️ ویرایش کامل"
IBTN_FULL_EDIT_NEXT = "▶️ بعدی"
IBTN_FULL_EDIT_BACK = "↩️ قبلی"
IBTN_FULL_EDIT_SKIP = "⏭️ رد کردن"
IBTN_FULL_EDIT_CANCEL_WIZARD = "❌ انصراف از ویرایش"
IBTN_FULL_EDIT_SAVE_ALL = "✅ ذخیره همه تغییرات"

# --- Study – stale-card notice ---
IBTN_STUDY_INACTIVE = "⚠️ این پیام دیگر فعال نیست"

# --- Session Summary Report ---
IBTN_SUMMARY_DETAIL = "📋 جزئیات"
IBTN_SUMMARY_BACK = "↩️ بازگشت به خلاصه"
IBTN_SUMMARY_PREV = "◀️ قبلی"
IBTN_SUMMARY_NEXT = "بعدی ▶️"
IBTN_SUMMARY_LEGEND = "❓ راهنمای نمادها"
IBTN_SUMMARY_LEGEND_BACK = "↩️ بازگشت به واژه‌ها"
# R10: /reports reopen flow — back to the recent-reports list.
IBTN_REPORTS_BACK = "↩️ بازگشت به فهرست"

# --- Admin – Preset Group / Pagination ---
IBTN_VIEW_MODE_LINEAR = "📋 نمایش خطی"
IBTN_VIEW_MODE_GROUPED = "📁 نمایش گروهی"
IBTN_GROUP_BATCH_KEY = "🔑 آپدیت کلید این گروه"
IBTN_GROUP_SET_LABEL = "🏷️ نام‌گذاری گروه"
IBTN_GROUP_OPEN = "▶️ باز کردن گروه"
IBTN_PAGE_PREV = "◀️ صفحه قبل"
IBTN_PAGE_NEXT = "▶️ صفحه بعد"

# --- Admin – Fallback Chain ---
IBTN_RANK_JUMP = "🎯 رتبه دلخواه"
IBTN_CONSUMPTION_DETAILS = "📊 جزئیات مصرف همه"

# --- Admin – Help ---
IBTN_HELP_PRESETS = "❓ راهنمای پریست‌ها"
IBTN_HELP_FALLBACK = "❓ راهنمای زنجیره فال‌بک"


def main_menu(is_owner: bool) -> ReplyKeyboardMarkup:
    rows = [
        [BTN_STUDY_SESSION],
        [BTN_ASK_WORD],
        [BTN_SETTINGS],
    ]
    if is_owner:
        rows.append([BTN_ADMIN])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def study_start_keyboard() -> InlineKeyboardMarkup:
    """Single '📚 شروع مطالعه امروز' inline button for the nudge / menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(BTN_STUDY_SESSION, callback_data="study:start")],
    ])


def study_inactive_keyboard() -> InlineKeyboardMarkup:
    """Keyboard that replaces a stale study card's grade buttons.

    Pressing it triggers a 'this message is no longer active' popup, after
    which the stale message is deleted. Prevents grading an outdated card.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(IBTN_STUDY_INACTIVE, callback_data="study:inactive")],
    ])


def lang_inline_keyboard(*, back_to_settings: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(option.name_fa, callback_data=f"lang:{option.code}")]
        for option in LANGUAGES.values()
    ]
    if back_to_settings:
        buttons.append([InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")])
    return InlineKeyboardMarkup(buttons)


def goal_inline_keyboard(*, back_to_settings: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(option.name_fa, callback_data=f"goal:{option.code}")]
        for option in GOALS.values()
    ]
    if back_to_settings:
        buttons.append([InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")])
    return InlineKeyboardMarkup(buttons)


def level_inline_keyboard(*, back_to_settings: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                f"{option.name_fa} ({option.cefr})",
                callback_data=f"level:{option.code}",
            )
        ]
        for option in LEVELS.values()
    ]
    if back_to_settings:
        buttons.append([InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")])
    return InlineKeyboardMarkup(buttons)


def presentation_settings_keyboard(
    current: str,
    *,
    back_to_settings: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
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
    if back_to_settings:
        rows.append([InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")])
    return InlineKeyboardMarkup(rows)


def settings_inline_keyboard(lang: str, goal: str, level: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🌐 زبان: {lang}", callback_data="settings:lang"),
            InlineKeyboardButton(f"🎯 هدف: {goal}", callback_data="settings:goal"),
        ],
        [
            InlineKeyboardButton(f"📚 سطح: {level}", callback_data="settings:level"),
            InlineKeyboardButton("📝 نوع نمایش کارت", callback_data="settings:presentation"),
        ],
        [
            InlineKeyboardButton("👤 وضعیت اشتراک و آمار", callback_data="settings:status"),
        ],
        [
            InlineKeyboardButton(IBTN_CLOSE, callback_data="settings:close"),
        ],
    ])


def settings_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(IBTN_BACK_TO_SETTINGS, callback_data="settings:back")]
    ])


def query_result_keyboard(
    token: str,
    lang: str | None = None,
    *,
    saved: bool = False,
) -> InlineKeyboardMarkup:
    label = IBTN_REMOVE_FROM_REVIEW if saved else IBTN_ADD_TO_REVIEW
    if lang:
        label = f"{label} ({language_label(lang)})"
    buttons = [
        InlineKeyboardButton(
            label,
            callback_data=f"query:add:{token}",
        )
    ]
    rows = [
        buttons,
        [
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:q:{token}",
            )
        ],
    ]
    return InlineKeyboardMarkup(rows)


def query_duplicate_keyboard(token: str) -> InlineKeyboardMarkup:
    """Retrieve-vs-new choice with an exit, when a repeated word is asked (R7b).

    ``query:dup:new`` re-runs the ask (quota + AI); ``query:dup:reuse`` re-renders
    the stored prior card for free; ``query:dup:cancel`` returns to the menu so the
    learner always has an exit.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                IBTN_QUERY_DUP_NEW,
                callback_data=f"query:dup:new:{token}",
            ),
            InlineKeyboardButton(
                IBTN_QUERY_DUP_REUSE,
                callback_data=f"query:dup:reuse:{token}",
            ),
        ],
        [
            InlineKeyboardButton(
                IBTN_QUERY_DUP_CANCEL,
                callback_data="query:dup:cancel",
            ),
        ],
    ])


def get_review_keyboard(
    user_id: int,
    word_id: int,
) -> InlineKeyboardMarkup:
    """Returns 4-grade review keyboard (recall-based labels).

    Layout (2×2 grid + pronounce row):
    [ یادم نیامد ⭕ ] [ به سختی یادم اومد 🟡 ]
    [ خوب بود 🟢 ] [ خیلی راحت بود 🟣 ]
    [ 🔊 تلفظ ]
    """
    rows = [
        [
            InlineKeyboardButton(
                IBTN_SRS_AGAIN_REVIEW,
                callback_data=f"srs:1:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_SRS_HARD_REVIEW,
                callback_data=f"srs:2:{user_id}:{word_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                IBTN_SRS_GOOD_REVIEW,
                callback_data=f"srs:3:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_SRS_EASY_REVIEW,
                callback_data=f"srs:4:{user_id}:{word_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:s:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_SRS_DELETE,
                callback_data=f"srs:delete:{user_id}:{word_id}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def get_srs_front_keyboard(
    user_id: int,
    word_id: int,
) -> InlineKeyboardMarkup:
    """Returns the staged-reveal front keyboard for a regular review card.

    The learner first reads the hidden front-stage prompt, then taps the reveal
    action to open the back stage + grade buttons (#338 §2B). The delete row is
    deferred to Phase 3 (#338 P3-T2).
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                IBTN_SRS_REVEAL,
                callback_data=f"srs:reveal:{user_id}:{word_id}",
            )
        ],
    ])


def get_srs_delete_confirm_keyboard(
    user_id: int,
    word_id: int,
) -> InlineKeyboardMarkup:
    """Returns the two-step delete confirm keyboard (Rule 3).

    [ ✅ بله، حذف شود ] [ ❌ انصراف ]
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                IBTN_SRS_DELETE_CONFIRM,
                callback_data=f"srs:delete:yes:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_SRS_DELETE_CANCEL,
                callback_data=f"srs:delete:no:{user_id}:{word_id}",
            ),
        ],
    ])


def get_first_exposure_keyboard(
    user_id: int,
    word_id: int,
) -> InlineKeyboardMarkup:
    """Returns 4-grade first-exposure keyboard (familiarity-based labels).

    Layout (2×2 grid + pronounce row):
    [ کاملاً ناآشناام 🟥 ] [ کمی آشناام 🟨 ]
    [ آشنایی خوب 🟩 ] [ کاملاً بلدمش 🟪 ]
    [ 🔊 تلفظ ]
    """
    rows = [
        [
            InlineKeyboardButton(
                IBTN_SRS_AGAIN_FE,
                callback_data=f"srs:fe:1:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_SRS_HARD_FE,
                callback_data=f"srs:fe:2:{user_id}:{word_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                IBTN_SRS_GOOD_FE,
                callback_data=f"srs:fe:3:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_SRS_EASY_FE,
                callback_data=f"srs:fe:4:{user_id}:{word_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                IBTN_PRONOUNCE,
                callback_data=f"tts:pronounce:s:{user_id}:{word_id}",
            ),
            InlineKeyboardButton(
                IBTN_SRS_DELETE,
                callback_data=f"srs:delete:{user_id}:{word_id}",
            ),
        ],
    ]
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
                InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back"),
                InlineKeyboardButton("❌ لغو", callback_data="admin:cancel"),
            ]
        ]
    )


def plan_manager_keyboard(plans: list[dict]) -> InlineKeyboardMarkup:
    """Admin plan-manager list: one row per plan with edit + active toggle."""
    rows = []
    for p in plans:
        marker = "✅" if p.get("is_active") else "⭕"
        label = f"{marker} {p.get('display_name')} ({p.get('name')})"
        rows.append([
            InlineKeyboardButton(label, callback_data=f"admin:plans:view:{p.get('name')}"),
            InlineKeyboardButton(IBTN_EDIT, callback_data=f"admin:plans:edit:{p.get('name')}"),
        ])
    rows.append([InlineKeyboardButton(IBTN_BACK_TO_PANEL, callback_data="admin:back")])
    return InlineKeyboardMarkup(rows)


def plan_view_keyboard(name: str, is_active: bool) -> InlineKeyboardMarkup:
    """Plan detail: full-edit wizard, activate/deactivate, back to list."""
    toggle_label = IBTN_DEACTIVATE if is_active else IBTN_ACTIVATE
    rows = [
        [InlineKeyboardButton(IBTN_FULL_EDIT_WIZARD, callback_data=f"admin:plans:edit:{name}")],
        [InlineKeyboardButton(toggle_label, callback_data=f"admin:plans:set_active:{name}")],
        [InlineKeyboardButton(IBTN_BACK, callback_data="admin:plans")],
    ]
    return InlineKeyboardMarkup(rows)


def plan_wizard_keyboard(name: str) -> InlineKeyboardMarkup:
    """Full-edit wizard navigation for a plan.

    Back re-shows the previous field; skip leaves the current field's DB
    value unchanged and advances. There is no redundant 'next' button —
    typing a value (or skipping) always advances.
    """
    buttons = [
        InlineKeyboardButton(IBTN_FULL_EDIT_BACK, callback_data=f"admin:plans:full_edit_back:{name}"),
        InlineKeyboardButton(IBTN_FULL_EDIT_SKIP, callback_data=f"admin:plans:full_edit_skip:{name}"),
        InlineKeyboardButton(IBTN_FULL_EDIT_CANCEL_WIZARD, callback_data=f"admin:plans:full_edit_cancel:{name}"),
    ]
    return InlineKeyboardMarkup([buttons])


def plan_wizard_summary_keyboard(name: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(IBTN_FULL_EDIT_SAVE_ALL, callback_data=f"admin:plans:full_edit_save:{name}"),
         InlineKeyboardButton(IBTN_FULL_EDIT_CANCEL_WIZARD, callback_data=f"admin:plans:full_edit_cancel:{name}")],
    ]
    return InlineKeyboardMarkup(rows)


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_ADMIN_STATS, callback_data="admin:stats"),
             InlineKeyboardButton(IBTN_PLAN, callback_data="admin:set_plan")],
            [InlineKeyboardButton(IBTN_ADMIN_AI, callback_data="admin:ai_settings")],
            [InlineKeyboardButton("💳 مدیریت پلن‌ها", callback_data="admin:plans"),
             InlineKeyboardButton(IBTN_ADMIN_COST, callback_data="admin:cost_dashboard")],
            [InlineKeyboardButton(IBTN_ADMIN_SETTINGS, callback_data="admin:show_settings"),
             InlineKeyboardButton("📋 سطح لاگ", callback_data="admin:log_level")],
            [InlineKeyboardButton(BTN_ADMIN_BROADCAST, callback_data="admin:broadcast"),
             InlineKeyboardButton(IBTN_USER_ACTIVITY_LOG, callback_data="admin:user_activity_log")],
            [InlineKeyboardButton("🔧 حالت تعمیر", callback_data="admin:maintenance")],
        ]
    )


def maintenance_keyboard(active: bool) -> InlineKeyboardMarkup:
    toggle_label = "🔧 فعال‌سازی حالت تعمیر" if not active else "🟢 حالت تعمیر فعال است — غیرفعال کن"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(toggle_label, callback_data="admin:maintenance:toggle")],
            [InlineKeyboardButton("✏️ ویرایش پیام حالت تعمیر", callback_data="admin:maintenance:edit")],
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")],
        ]
    )


def stats_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 نمای کلی", callback_data="admin:stats:overview"),
         InlineKeyboardButton("📊 پراکندگی", callback_data="admin:stats:distribution")],
        [InlineKeyboardButton("📈 فعالیت", callback_data="admin:stats:activity")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")],
    ])


def stats_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به آمار", callback_data="admin:stats")],
    ])


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
            [InlineKeyboardButton("🏷️ مدیریت گروه‌ها", callback_data="admin:ai_preset:group_manager")],
            [InlineKeyboardButton(IBTN_HELP_PRESETS, callback_data="admin:help:presets")],
            [InlineKeyboardButton(IBTN_BACK_TO_PANEL, callback_data="admin:back")],
        ]
    )


def ai_presets_list_keyboard(
    presets: list[dict],
    active_name: str,
    page: int = 0,
    total_pages: int = 1,
    view_mode: str = "linear",
    groups: list[dict] | None = None,
) -> InlineKeyboardMarkup:
    """List presets with activate/edit/delete buttons and view-mode toggle."""
    from services.utils.callback_codec import preset_token
    rows = []
    if view_mode == "grouped" and groups:
        for g in groups:
            label = g.get("label") or g.get("masked_key", "—")
            masked = g.get("masked_key", "")
            if g.get("label"):
                label = f"🏷️ {g['label']} ({masked})"
            group_row = [
                InlineKeyboardButton(
                    f"📁 {label} ({g['count']} preset)",
                    callback_data=f"admin:ai_preset:group:{g['key_hash']}",
                ),
            ]
            rows.append(group_row)
            action_row = [
                InlineKeyboardButton(IBTN_GROUP_BATCH_KEY, callback_data=f"admin:ai_preset:group_batch_key:{g['key_hash']}"),
                InlineKeyboardButton(IBTN_GROUP_SET_LABEL, callback_data=f"admin:ai_preset:group_set_label:{g['key_hash']}"),
            ]
            rows.append(action_row)
    else:
        for p in presets:
            name = p["name"]
            is_active = "✅ " if name == active_name else ""
            label = f"{is_active}{name}"
            rows.append([
                InlineKeyboardButton(label, callback_data=f"admin:ai_preset:view:{preset_token(name)}"),
            ])
            action_row = []
            if name != active_name:
                action_row.append(InlineKeyboardButton(IBTN_ACTIVATE, callback_data=f"admin:ai_preset:activate:{preset_token(name)}"))
            action_row.append(InlineKeyboardButton(IBTN_EDIT, callback_data=f"admin:ai_preset:edit:{preset_token(name)}"))
            action_row.append(InlineKeyboardButton(IBTN_DELETE, callback_data=f"admin:ai_preset:delete:{preset_token(name)}"))
            if action_row:
                rows.append(action_row)
        # Pagination
        if total_pages > 1:
            nav_row = []
            if page > 0:
                nav_row.append(InlineKeyboardButton(IBTN_PAGE_PREV, callback_data=f"admin:ai_preset:page:{page - 1}"))
            if page + 1 < total_pages:
                nav_row.append(InlineKeyboardButton(IBTN_PAGE_NEXT, callback_data=f"admin:ai_preset:page:{page + 1}"))
            if nav_row:
                rows.append(nav_row)
    # View mode toggle
    toggle_label = IBTN_VIEW_MODE_GROUPED if view_mode == "linear" else IBTN_VIEW_MODE_LINEAR
    toggle_mode = "grouped" if view_mode == "linear" else "linear"
    rows.append([InlineKeyboardButton(toggle_label, callback_data=f"admin:ai_preset:view_mode:{toggle_mode}")])
    rows.append([InlineKeyboardButton(IBTN_ADD_CUSTOM, callback_data="admin:ai_preset:add")])
    rows.append([InlineKeyboardButton(IBTN_BACK_TO_PANEL, callback_data="admin:ai_settings")])
    return InlineKeyboardMarkup(rows)


def ai_preset_view_keyboard(preset: dict, active_name: str) -> InlineKeyboardMarkup:
    """View/edit a specific preset."""
    from services.utils.callback_codec import preset_token
    name = preset["name"]
    rows = []
    if name != active_name:
        rows.append([InlineKeyboardButton(IBTN_ACTIVATE_THIS, callback_data=f"admin:ai_preset:activate:{preset_token(name)}")])
    rows.append([InlineKeyboardButton(IBTN_EDIT, callback_data=f"admin:ai_preset:edit:{preset_token(name)}")])
    rows.append([InlineKeyboardButton(IBTN_DELETE, callback_data=f"admin:ai_preset:delete:{preset_token(name)}")])
    rows.append([InlineKeyboardButton(IBTN_DUPLICATE, callback_data=f"admin:ai_preset:duplicate:{preset_token(name)}")])
    rows.append([InlineKeyboardButton(BTN_BACK, callback_data="admin:ai_presets")])
    return InlineKeyboardMarkup(rows)


def ai_preset_edit_keyboard(preset_name: str, preset: dict | None = None) -> InlineKeyboardMarkup:
    """Keyboard for editing a preset field-by-field."""
    from services.utils.callback_codec import alias_field, preset_token
    preset_ref = preset_token(preset_name)
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
            InlineKeyboardButton(f"{label}{suffix}", callback_data=f"admin:ai_preset:edit_field:{preset_ref}:{alias_field(key)}"),
        ])
    if preset and preset.get("group_label"):
        rows.append([
            InlineKeyboardButton(IBTN_DETACH_GROUP, callback_data=f"admin:ai_preset:detach_group:{preset_ref}"),
        ])
    rows.append([InlineKeyboardButton(IBTN_FULL_EDIT_WIZARD, callback_data=f"admin:ai_preset:full_edit:{preset_ref}")])
    rows.append([InlineKeyboardButton(IBTN_DISCARD_ALL, callback_data=f"admin:ai_preset:discard_all:{preset_ref}")])
    rows.append([InlineKeyboardButton(IBTN_SAVE_PRESET, callback_data=f"admin:ai_preset:save:{preset_ref}")])
    rows.append([InlineKeyboardButton(IBTN_CANCEL_EDIT, callback_data=f"admin:ai_preset:view:{preset_ref}")])
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


def fallback_chain_keyboard(chain: list[dict]) -> InlineKeyboardMarkup:
    from services.utils.callback_codec import preset_token
    rows = []
    for rank, preset in enumerate(chain, 1):
        name = preset.get("name", "?")
        emoji = "🛡️" if preset.get("is_emergency") else "📊"
        status_icon = "🟢" if preset.get("enabled", 1) else "⚫"
        row = [
            InlineKeyboardButton(f"{rank}. {emoji} {name} {status_icon}", callback_data="admin:noop"),
            InlineKeyboardButton("⬆", callback_data=f"admin:fallback:move_up:{preset_token(name)}"),
            InlineKeyboardButton("⬇", callback_data=f"admin:fallback:move_down:{preset_token(name)}"),
            InlineKeyboardButton(status_icon, callback_data=f"admin:fallback:toggle:{preset_token(name)}"),
            InlineKeyboardButton("🎯", callback_data=f"admin:fallback:rank:{preset_token(name)}"),
        ]
        if not preset.get("is_emergency"):
            row.append(InlineKeyboardButton("🛡️", callback_data=f"admin:fallback:set_emergency:{preset_token(name)}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(IBTN_CONSUMPTION_DETAILS, callback_data="admin:fallback:usage_details")])
    rows.append([InlineKeyboardButton(IBTN_HELP_FALLBACK, callback_data="admin:help:fallback_chain")])
    rows.append([InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")])
    return InlineKeyboardMarkup(rows)


def session_summary_keyboard(nonce: str) -> InlineKeyboardMarkup:
    """Summary view of the post-session report — a single 'جزئیات' button that
    opens the paged word list in the same message.

    ``nonce`` is the report identity; it is embedded in the callback data so a
    stale button from an older message is rejected.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            IBTN_SUMMARY_DETAIL, callback_data=f"session:summary:detail:{nonce}"
        )],
    ])


def session_summary_detail_keyboard(
    page_index: int, total_pages: int, nonce: str
) -> InlineKeyboardMarkup:
    """Detail view of the report — prev/next page navigation + back to summary.

    ``page_index`` is 0-based; page navigation buttons are omitted on the
    first / last page respectively. ``nonce`` is threaded into every callback
    so stale buttons from an older message are rejected.
    """
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page_index > 0:
        nav.append(
            InlineKeyboardButton(
                IBTN_SUMMARY_PREV,
                callback_data=f"session:summary:page:{page_index - 1}:{nonce}",
            )
        )
    if page_index < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                IBTN_SUMMARY_NEXT,
                callback_data=f"session:summary:page:{page_index + 1}:{nonce}",
            )
        )
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(
            IBTN_SUMMARY_LEGEND,
            callback_data=f"session:summary:legend:{page_index}:{nonce}",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            IBTN_SUMMARY_BACK, callback_data=f"session:summary:back:{nonce}"
        ),
    ])
    return InlineKeyboardMarkup(rows)


def session_summary_legend_keyboard(page_index: int, nonce: str) -> InlineKeyboardMarkup:
    """Keyboard for the symbol-legend view — a single back button to the word
    page the legend was opened from. ``page_index`` is 0-based and threaded into
    the callback so back returns to the exact page (R8)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            IBTN_SUMMARY_LEGEND_BACK,
            callback_data=f"session:summary:page:{page_index}:{nonce}",
        )],
    ])


# ---------------------------------------------------------------------------
# R10: persistent post-session reports (/reports reopen flow)
# ---------------------------------------------------------------------------
# The reports flow reopens a persisted SessionReport by id, so these callbacks
# are id-based (no nonce). View `0` = summary overview; views `1..N` = detail
# pages of `report.pages`. Back returns to the recent-reports list.

def reports_list_keyboard(entries) -> InlineKeyboardMarkup:
    """List of recent reports — one button per report (R10-C).

    Each button opens the report's summary overview (`reports:detail:<id>:0`).
    """
    rows = [
        [InlineKeyboardButton(
            entry.session_date,
            callback_data=f"reports:detail:{entry.report_id}:0",
        )]
        for entry in entries
    ]
    return InlineKeyboardMarkup(rows)


def reports_summary_keyboard(report_id: int, can_detail: bool) -> InlineKeyboardMarkup:
    """Summary-overview keyboard for a reopened report (R10-F).

    The 'جزئیات' button is only rendered when the user holds the
    ``session_summary`` feature (Bronze+) or is the owner; free users see the
    overview and a back-to-list button only.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if can_detail:
        rows.append([
            InlineKeyboardButton(
                IBTN_SUMMARY_DETAIL,
                callback_data=f"reports:detail:{report_id}:1",
            ),
        ])
    rows.append([
        InlineKeyboardButton(IBTN_REPORTS_BACK, callback_data="reports:back"),
    ])
    return InlineKeyboardMarkup(rows)


def reports_detail_keyboard(
    report_id: int, detail_page: int, total_pages: int
) -> InlineKeyboardMarkup:
    """Detail-page keyboard for a reopened report.

    ``detail_page`` is the 1-based view (`1..total_pages`). Prev/next navigate
    detail pages; back-to-summary returns to view `0`.
    """
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if detail_page > 1:
        nav.append(
            InlineKeyboardButton(
                IBTN_SUMMARY_PREV,
                callback_data=f"reports:detail:{report_id}:{detail_page - 1}",
            )
        )
    if detail_page < total_pages:
        nav.append(
            InlineKeyboardButton(
                IBTN_SUMMARY_NEXT,
                callback_data=f"reports:detail:{report_id}:{detail_page + 1}",
            )
        )
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(
            IBTN_SUMMARY_BACK,
            callback_data=f"reports:detail:{report_id}:0",
        ),
    ])
    rows.append([
        InlineKeyboardButton(IBTN_REPORTS_BACK, callback_data="reports:back"),
    ])
    return InlineKeyboardMarkup(rows)
