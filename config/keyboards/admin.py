from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from .constants import *  # noqa: F401,F403
from config.catalog import GOALS, LANGUAGES, LEVELS, language_label




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
            [InlineKeyboardButton(BTN_ADMIN_USER_MANAGE, callback_data="admin:user"),
              InlineKeyboardButton("📤 خروجی CSV کاربران", callback_data="admin:stats:export")],
            [InlineKeyboardButton("💾 پشتیبان", callback_data="admin:backup"),
             InlineKeyboardButton("♻️ بازیابی", callback_data="admin:restore")],
            [InlineKeyboardButton("🎛 نمایش کارت", callback_data="admin:display_toggles")],
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



# ---------------------------------------------------------------------------
# User management (issue #stats-users)
# ---------------------------------------------------------------------------


def user_management_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="admin:user:search")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back")],
    ])


def user_profile_keyboard(user_id: int, blocked: bool) -> InlineKeyboardMarkup:
    """Action keyboard for a user-profile card.

    The block/unblock label flips on the current ``blocked`` state, and the
    change-plan button reuses the existing ``admin:set_plan`` write path (the
    admin types ``user_id plan``), keeping a single plan-write seam.
    """
    block_label = "✅ رفع بلاک" if blocked else "🚫 بلاک کردن"
    block_action = "admin:user:unblock" if blocked else "admin:user:block"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 تغییر پلن", callback_data=f"admin:user:plan:{user_id}")],
        [InlineKeyboardButton(block_label, callback_data=f"{block_action}:{user_id}")],
        [InlineKeyboardButton("♻️ ریست پیشرفت", callback_data=f"admin:user:reset:{user_id}")],
        [InlineKeyboardButton("↩️ بازگشت به مدیریت کاربر", callback_data="admin:user")],
    ])


def user_reset_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Two-step confirm for the irreversible progress reset (R5)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، ریست شود", callback_data=f"admin:user:reset_confirm:{user_id}")],
        [InlineKeyboardButton("❌ انصراف", callback_data=f"admin:user:reset_cancel:{user_id}")],
    ])