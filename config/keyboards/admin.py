from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from .constants import *  # noqa: F401,F403




# --- Admin – Cost Dashboard ---

# --- Admin – LLM Dashboard Filters ---



# --- Admin – AI Presets ---






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



def tts_cache_keyboard(current: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"📢 کانال کش: {current or '—'}", callback_data="admin:noop")],
        [InlineKeyboardButton("✏️ تنظیم کانال کش", callback_data="admin:tts_cache:set")],
        [InlineKeyboardButton("🗑 پاک کردن", callback_data="admin:tts_cache:clear")],
        [InlineKeyboardButton("🧪 تست", callback_data="admin:tts_cache:test")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")],
    ]
    return InlineKeyboardMarkup(rows)


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_ADMIN_STATS, callback_data="admin:stats"),
             InlineKeyboardButton(IBTN_PLAN, callback_data="admin:set_plan")],
            [InlineKeyboardButton(BTN_ADMIN_USER_MANAGE, callback_data="admin:user")],
            [InlineKeyboardButton(IBTN_ADMIN_AI, callback_data="admin:ai_settings")],
            [InlineKeyboardButton("💳 مدیریت پلن‌ها", callback_data="admin:plans"),
             InlineKeyboardButton(IBTN_ADMIN_COST, callback_data="admin:cost_dashboard")],
            [InlineKeyboardButton(IBTN_ADMIN_SETTINGS, callback_data="admin:show_settings"),
             InlineKeyboardButton("📋 سطح لاگ", callback_data="admin:log_level")],
            [InlineKeyboardButton(BTN_ADMIN_BROADCAST, callback_data="admin:broadcast"),
             InlineKeyboardButton(IBTN_USER_ACTIVITY_LOG, callback_data="admin:user_activity_log")],
            [InlineKeyboardButton("💾 پشتیبان & بازیابی", callback_data="admin:backup_restore")],
            [InlineKeyboardButton("🎙 کش TTS", callback_data="admin:tts_cache")],
            [InlineKeyboardButton("🎛 نمایش کارت", callback_data="admin:display_toggles")],
            [InlineKeyboardButton("🔧 حالت تعمیر", callback_data="admin:maintenance")],
        ]
    )



def backup_restore_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📤 پشتیبان الان", callback_data="admin:backup_restore:backup_now")],
        [InlineKeyboardButton("♻️ بازیابی", callback_data="admin:backup_restore:restore")],
        [InlineKeyboardButton("⚙️ تنظیم گروه آرشیو", callback_data="admin:backup_restore:set_archive")],
        [InlineKeyboardButton("🗑 پاک کردن آرشیو", callback_data="admin:backup_restore:clear_archive")],
        [InlineKeyboardButton("✅ تست آرشیو", callback_data="admin:backup_restore:test_archive")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")],
    ]
    return InlineKeyboardMarkup(rows)


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
        [InlineKeyboardButton("📈 فعالیت", callback_data="admin:stats:activity"),
         InlineKeyboardButton("📚 درگیری یادگیری", callback_data="admin:stats:learning")],
        [InlineKeyboardButton("📈 رشد و بازگشت", callback_data="admin:stats:growth"),
         InlineKeyboardButton("📤 خروجی CSV", callback_data="admin:stats:export")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")],
    ])



def stats_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به آمار", callback_data="admin:stats")],
    ])


def user_management_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="admin:user:search")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")],
    ])


def user_profile_keyboard(user_id: int, blocked: bool) -> InlineKeyboardMarkup:
    block_label = "✅ رفع مسدودی" if blocked else "🚫 مسدود کردن"
    block_cb = f"admin:user:unblock:{user_id}" if blocked else f"admin:user:block:{user_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 تغییر پلن", callback_data=f"admin:user:plan:{user_id}"),
         InlineKeyboardButton("✉️ پیام به کاربر", callback_data=f"admin:user:msg:{user_id}")],
        [InlineKeyboardButton(block_label, callback_data=block_cb)],
        [InlineKeyboardButton("♻️ ریست پیشرفت", callback_data=f"admin:user:reset:{user_id}")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:user")],
    ])


def user_reset_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، ریست شود", callback_data=f"admin:user:reset_confirm:{user_id}")],
        [InlineKeyboardButton("❌ انصراف", callback_data=f"admin:user:reset_cancel:{user_id}")],
    ])


def user_block_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله مسدود کن", callback_data=f"admin:user:block_confirm:{user_id}")],
        [InlineKeyboardButton("❌ لغو", callback_data=f"admin:user:block_cancel:{user_id}")],
    ])


def user_plan_confirm_keyboard(user_id: int, new_plan: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، تغییر بده", callback_data=f"admin:user:plan_confirm:{user_id}:{new_plan}")],
        [InlineKeyboardButton("❌ لغو", callback_data=f"admin:user:plan_cancel:{user_id}")],
    ])


def dm_preview_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید ارسال", callback_data=f"admin:user:msg_confirm:{user_id}")],
        [InlineKeyboardButton("✏️ ویرایش", callback_data=f"admin:user:msg_edit:{user_id}"),
         InlineKeyboardButton("❌ لغو", callback_data=f"admin:user:msg_cancel:{user_id}")],
    ])


def broadcast_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید همگانی", callback_data="admin:broadcast_confirm")],
        [InlineKeyboardButton("✏️ ویرایش", callback_data="admin:broadcast_edit"),
         InlineKeyboardButton("❌ لغو", callback_data="admin:broadcast_cancel")],
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



def _active_label(is_active: bool, text: str) -> str:
    """R6 helper — prepend ✅ when the button represents the active selection."""
    return f"✅ {text}" if is_active else text


def admin_cost_keyboard() -> InlineKeyboardMarkup:
    # R1: second button is now rate-only (IBTN_LLM_PRICING relabeled to
    # "💱 نرخ تبدیل USD→تومان"); llm_cost_pricing_keyboard below exposes only
    # the single USD→Toman rate button. Global input/output pricing removed.
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(IBTN_LLM_COST, callback_data="admin:llm_costs")],
            [InlineKeyboardButton(IBTN_LLM_PRICING, callback_data="admin:llm_pricing")],
            [InlineKeyboardButton(IBTN_BACK_TO_PANEL, callback_data="admin:back")],
        ]
    )


def llm_cost_dashboard_keyboard(
    detail: bool = False,
    active_range: str = "mtd",
    breakdown: str = "preset",
    currency: str = "both",
    view: str = "overview",
    breakdown_page: int = 0,
    recent_page: int = 0,
    show_projection: bool = False,
    breakdown_total_pages: int = 1,
    recent_total_pages: int = 1,
) -> InlineKeyboardMarkup:
    """Cost hub — view tabs + range + breakdown + pager + currency cycle.

    Backward compat: ``llm_cost_dashboard_keyboard(bool)`` still works; new
    callers pass ``view``/``breakdown_page``/``recent_page``/``show_projection``.
    Active markers use ✅.
    """
    active_range = str(active_range or "mtd").lower()
    breakdown = str(breakdown or "preset").lower()
    currency = str(currency or "both").lower()
    view = str(view or ("recent" if detail else "overview")).lower()
    if view not in {"overview", "breakdown", "recent"}:
        view = "overview"
    breakdown_page = max(0, int(breakdown_page or 0))
    recent_page = max(0, int(recent_page or 0))
    breakdown_total_pages = max(1, int(breakdown_total_pages or 1))
    recent_total_pages = max(1, int(recent_total_pages or 1))

    # — View tabs (always) — segmented control
    tabs_row = [
        InlineKeyboardButton(_active_label(view == "overview", "Overview"), callback_data="llm:view:overview"),
        InlineKeyboardButton(_active_label(view == "breakdown", "Breakdown"), callback_data="llm:view:breakdown"),
        InlineKeyboardButton(_active_label(view == "recent", "Recent"), callback_data="llm:view:recent"),
        InlineKeyboardButton("❓", callback_data="llm:legend"),
    ]

    # — Range row (5 options) → 3 rows × 2 cols
    _range_opts: list[tuple[str, str]] = [
        ("Today", "today"),
        ("7d", "7d"),
        ("30d", "30d"),
        ("MTD", "mtd"),
        ("All", "all"),
    ]
    range_rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(_range_opts), 2):
        chunk = _range_opts[i : i + 2]
        row = [
            InlineKeyboardButton(
                _active_label(val == active_range, label),
                callback_data=f"llm:range:{val}",
            )
            for label, val in chunk
        ]
        range_rows.append(row)

    # — Breakdown tabs (only on breakdown view) → 3 rows × 2 cols
    breakdown_rows: list[list[InlineKeyboardButton]] = []
    if view == "breakdown":
        _breakdown_opts: list[tuple[str, str]] = [
            ("By Preset", "preset"),
            ("By Plan", "plan"),
            ("By Kind", "kind"),
            ("By Model", "model"),
            ("By User", "user"),
            ("By Preset×Kind", "preset_kind"),
        ]
        for i in range(0, len(_breakdown_opts), 2):
            chunk = _breakdown_opts[i : i + 2]
            row = [
                InlineKeyboardButton(
                    _active_label(val == breakdown, label),
                    callback_data=f"llm:breakdown:{val}",
                )
                for label, val in chunk
            ]
            breakdown_rows.append(row)

    # — Pager row (only when needed)
    pager_row: list[list[InlineKeyboardButton]] = []
    if view == "breakdown" and breakdown_total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if breakdown_page > 0:
            nav.append(InlineKeyboardButton("◀", callback_data=f"llm:page:breakdown:{breakdown_page - 1}"))
        else:
            nav.append(InlineKeyboardButton("·", callback_data="llm:noop"))
        nav.append(InlineKeyboardButton(f"{breakdown_page + 1}/{breakdown_total_pages}", callback_data="llm:noop"))
        if breakdown_page + 1 < breakdown_total_pages:
            nav.append(InlineKeyboardButton("▶", callback_data=f"llm:page:breakdown:{breakdown_page + 1}"))
        else:
            nav.append(InlineKeyboardButton("·", callback_data="llm:noop"))
        pager_row.append(nav)
    elif view == "recent" and recent_total_pages > 1:
        nav = []
        if recent_page > 0:
            nav.append(InlineKeyboardButton("◀", callback_data=f"llm:page:recent:{recent_page - 1}"))
        else:
            nav.append(InlineKeyboardButton("·", callback_data="llm:noop"))
        nav.append(InlineKeyboardButton(f"{recent_page + 1}/{recent_total_pages}", callback_data="llm:noop"))
        if recent_page + 1 < recent_total_pages:
            nav.append(InlineKeyboardButton("▶", callback_data=f"llm:page:recent:{recent_page + 1}"))
        else:
            nav.append(InlineKeyboardButton("·", callback_data="llm:noop"))
        pager_row.append(nav)

    # — Currency cycle + projection + controls
    cur_label = {"usd": "USD", "toman": "Toman", "both": "Both"}[currency] if currency in {"usd", "toman", "both"} else "Both"
    controls_rows: list[list[InlineKeyboardButton]] = []
    # first controls row: currency cycle + projection toggle (overview MTD only)
    first_row = [InlineKeyboardButton(f"💱 {cur_label}", callback_data="llm:currency:cycle")]
    if view == "overview":
        proj_label = "📈 Hide" if show_projection else "📈 Show"
        first_row.append(InlineKeyboardButton(proj_label, callback_data="llm:projection"))
    first_row.append(InlineKeyboardButton(IBTN_REFRESH, callback_data="llm:refresh"))
    controls_rows.append(first_row)
    controls_rows.append(
        [
            InlineKeyboardButton(IBTN_CLEAR_FILTERS, callback_data="llm:clear"),
            InlineKeyboardButton(IBTN_BACK_TO_PANEL, callback_data="admin:cost_dashboard"),
        ]
    )

    return InlineKeyboardMarkup(
        [
            [tabs_row[0], tabs_row[1], tabs_row[2], tabs_row[3]],
            *range_rows,
            *breakdown_rows,
            *pager_row,
            *controls_rows,
        ]
    )


def llm_legend_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("« بازگشت", callback_data="llm:refresh")]])



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
    # R1: global pricing removed — only USD→Toman rate remains. Input/output
    # prices are per-preset (IBTN_INPUT_PRICE/OUTPUT_PRICE stay for
    # ai_preset_edit) and must not appear here.
    return InlineKeyboardMarkup(
        [
            [
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
    # Single source: order derived from PRESET_FIELDS (R3); labels map here.
    # Adding a field to PRESET_FIELDS automatically shows it here without a
    # second manual list.
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
        ("priority", IBTN_FIELD_PRIORITY),
        ("input_cost_per_million", IBTN_FIELD_INPUT_COST),
        ("output_cost_per_million", IBTN_FIELD_OUTPUT_COST),
        ("in_fallback_chain", IBTN_FIELD_IN_FALLBACK_CHAIN),
        ("group_label", IBTN_FIELD_GROUP_LABEL),
        ("reasoning_effort", IBTN_FIELD_REASONING),
        # `enabled` intentionally omitted — toggled via dedicated enable/disable
        # action (services/db/preset_registry.set_preset_enabled), not free-text
        # edit_field (would be silently dropped on save).
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


def reports_days_keyboard(grouped: dict[str, list]) -> InlineKeyboardMarkup:
    """Two-level top: one button per jalali day (R1,R2,R4)."""
    import re as _re

    from services.utils.formatting import jalali_day_label, to_persian_digits as _tpd

    rows: list[list[InlineKeyboardButton]] = []
    _iso_re = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
    # Sort ISO day keys DESC; non-ISO fallback keys last
    def _day_sort_key(k: str):
        return (1, k) if _iso_re.match(k) else (0, k)

    for day_key in sorted(grouped.keys(), key=_day_sort_key, reverse=True):
        entries = grouped[day_key]
        if not entries:
            continue
        # Fallback bucket (no ISO date) — emit direct detail buttons, no day drill-down
        if not _iso_re.match(day_key):
            for e in entries:
                rows.append([InlineKeyboardButton(f"📄 گزارش #{e.report_id}", callback_data=f"reports:detail:{e.report_id}:0")])
            continue
        # label uses first entry's created_at for jalali day
        first_iso = getattr(entries[0], "created_at", "") or ""
        # fallback to session_date if needed
        if not first_iso:
            first_iso = getattr(entries[0], "session_date", "") or ""
        label_day = jalali_day_label(first_iso) if first_iso else day_key
        # count Persian digits
        count_label = _tpd(len(entries))
        text = f"📅 {label_day} — {count_label} نشست"
        if len(entries) == 1:
            cb = f"reports:detail:{entries[0].report_id}:0"
        else:
            cb = f"reports:day:{day_key}"
        rows.append([InlineKeyboardButton(text, callback_data=cb)])
    return InlineKeyboardMarkup(rows)


def reports_day_keyboard(day_key: str, entries: list) -> InlineKeyboardMarkup:
    """Second level: one button per session sorted ASC for per-day numbering (R3,R8)."""
    from services.utils.formatting import jalali_time_label, parse_iso_to_app_tz, to_persian_digits as _tpd

    # sort ASC by actual Tehran time — consistent tuple key to avoid datetime/str mix (Kilo)
    def _sort_key(e):
        iso = getattr(e, "created_at", "") or ""
        dt = parse_iso_to_app_tz(iso)
        if dt is not None:
            return (0, dt)
        return (1, iso)

    sorted_entries = sorted(entries, key=_sort_key)
    rows: list[list[InlineKeyboardButton]] = []
    for idx, entry in enumerate(sorted_entries, 1):
        iso = getattr(entry, "created_at", "") or ""
        time_label = jalali_time_label(iso) if iso else "—"
        total = getattr(entry, "total", 0) or 0
        reviewed = getattr(entry, "reviewed_count", 0) or 0
        learned = getattr(entry, "learned_count", 0) or 0
        base = f"🕝 {time_label} — نشست {_tpd(idx)} · {_tpd(total)} واژه"
        extra_parts: list[str] = []
        if reviewed:
            extra_parts.append(f"{_tpd(reviewed)} مرور")
        if learned:
            extra_parts.append(f"{_tpd(learned)} تازه")
        extra = f" ({' · '.join(extra_parts)})" if extra_parts else ""
        text = base + extra
        rows.append([InlineKeyboardButton(text, callback_data=f"reports:detail:{entry.report_id}:0")])
    rows.append([InlineKeyboardButton(IBTN_REPORTS_BACK_TO_DAYS, callback_data="reports:back")])
    return InlineKeyboardMarkup(rows)


def reports_list_keyboard(entries) -> InlineKeyboardMarkup:
    """Backward compat flat list — delegates to grouped view for new code.

    Kept for wiring tests; new handler uses reports_days_keyboard.
    """
    # Build grouped dict for compat path: group by APP_TZ day (single source)
    from services.utils.formatting import reports_jalali_group_key

    grouped: dict[str, list] = {}
    for e in entries:
        iso = getattr(e, "created_at", "") or getattr(e, "session_date", "") or ""
        key = reports_jalali_group_key(iso) or getattr(e, "session_date", "") or str(e.report_id)
        grouped.setdefault(key, []).append(e)
    if grouped:
        return reports_days_keyboard(grouped)
    # fallback flat when no created_at (legacy)
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
