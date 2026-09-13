"""Database layer — thin re-export facade over submodules (REF2-T5).

All persistence bodies live in leaf modules; this package only re-exports so
``from services import db`` / ``from services.db import ...`` call sites keep
working byte-identically. Leaf modules import from ``services.db.schema``
directly, never from this facade (leaf-import law).
"""

# ---------------------------------------------------------------------------
# Imports from config
# ---------------------------------------------------------------------------
from config import DB_PATH

# ---------------------------------------------------------------------------
# Re-export from submodules
# ---------------------------------------------------------------------------
from services.db.schema import (
    get_conn,
    transaction,
    maintenance,
    is_maintenance,
    _LEGACY_DAILY_TABLES,
    init_db,
    _check_test_mode_guard,
    _guard_destructive_op,
    _app_timezone,
    _today,
    _utc_now,
    normalize_word,
    _current_daily_count,
    _can_consume_daily_count,
    _init_ai_presets_table,
    _init_config_tests_table,
    _init_plans_table,
)

from services.db.plans import (
    get_plan,
    list_plans,
    valid_plan_name,
    upsert_plan,
    set_plan_active,
)

from services.db.users import (
    get_user,
    get_display_toggles,
    get_quota_status,
    create_user_if_needed,
    update_user_full_name,
    set_user_lang_goal,
    set_user_level,
    set_presentation_preference,
    set_user_lang,
    set_user_goal,
    set_display_toggle,
    set_display_toggle_forced,
    touch_streak,
    touch_streak_in_txn,
    can_ask_word,
    reserve_word_query,
    release_word_query,
    can_ask_grammar_tip,
    reserve_grammar_tip,
    release_grammar_tip,
    all_active_users,
    count_users,
    count_users_overview,
    count_users_grouped,
    count_active_users_since,
    count_saved_words_total,
    count_llm_requests_since,
    set_plan,
    find_user,
    set_user_blocked,
    reset_user_blocked,
    CARD_TYPES,
    CARD_MODES,
    CARD_MODE_GATES,
    DEFAULT_CARD_MODE,
    DEFAULT_CARD_MODE_GATE,
    resolve_card_mode,
    resolve_card_mode_gate,
    card_mode_available,
    set_user_card_mode,
    set_plan_card_mode,
    set_global_card_mode,
    set_card_mode_gate,
    count_new_users_since,
    count_users_created_before,
    count_retained_users,
    count_review_events_total,
    count_study_sessions_total,
    count_first_exposure_completion,
    get_user_learning_stats,
    get_top_users_by_streak,
    reset_user_progress,
    export_users_csv,
)

from services.db.words import (
    add_saved_word,
    toggle_review_word,
    update_saved_word_fields,
    due_words_for_user,
    get_saved_word,
    get_saved_words_by_ids,
    get_pre_first_exposure_words,
    delete_saved_word,
    grade_word_review,
    grade_first_exposure,
    reset_expired_pending_reviews,
    GradeResult,
)

from services.db.sessions import (
    save_study_session,
    load_study_session,
    clear_study_session,
    mark_word_graded,
    is_word_graded,
    clear_session_grades,
    invalidate_stale_study_session,
    purge_stale_study_sessions,
)

from services.db.session_reports import (
    REPORT_WINDOW_DAYS,
    LoadedReport,
    ReportEntry,
    list_recent_reports,
    load_report,
    purge_expired_session_reports,
    save_session_report,
)

from services.db.query_results import (
    _QUERY_RESULTS_CAP,
    _enforce_query_results_cap,
    _normalize_query_text,
    _query_result_expired,
    cleanup_expired_query_results,
    clear_query_result_saved,
    create_query_result,
    find_unexpired_query,
    find_unexpired_query_by_word,
    get_query_result,
    mark_query_result_saved,
    update_query_result_fields,
)

from services.db.reviews import (
    REVIEW_OUTCOMES,
    count_review_events_for_card,
    insert_review_event,
    prune_old_review_events,
    recent_events_for_words,
)

from services.db.settings import (
    get_bool_setting,
    get_display_toggle_defaults,
    get_llm_cost_profile,
    get_maintenance_message,
    get_setting,
    is_maintenance_mode,
    set_bool_setting,
    set_display_toggle_defaults,
    set_llm_cost_profile,
    set_maintenance_message,
    set_maintenance_mode,
    set_setting,
    DEFAULT_MAINTENANCE_MESSAGE,
)

from services.db.display_toggles import (
    DisplayToggleService,
    get_effective,
    get_global_defaults,
    set_global_defaults,
    set_user_toggle,
    set_forced,
)


# ---------------------------------------------------------------------------
# LLM request tracking
# ---------------------------------------------------------------------------
from services.db.cost_tracking import (
    add_llm_request,
    breakdown_llm_requests,
    breakdown_llm_requests_preset_kind,
    count_breakdown_groups,
    count_breakdown_preset_kind_groups,
    daily_costs_grouped,
    delete_llm_requests,
    purge_old_llm_requests,
    recent_llm_requests,
    rollup_request_count_since,
    summarize_llm_requests,
)

# ---------------------------------------------------------------------------
# AI presets
# ---------------------------------------------------------------------------
from services.db.preset_registry import (
    activate_preset,
    clear_group_label,
    clone_preset,
    delete_group_key,
    delete_preset,
    get_active_preset,
    get_active_preset_name,
    get_enabled_presets_ordered,
    get_fallback_chain_presets,
    get_fallback_status,
    get_group_key,
    get_group_labels,
    get_hourly_usage,
    get_hourly_usage_many,
    get_preset,
    get_preset_cost,
    get_presets,
    increment_consecutive_failures,
    increment_hourly_usage,
    insert_preset_at_rank,
    NoActivePresetError,
    prune_preset_hourly_usage,
    reindex_preset_priority,
    rename_group_label,
    reset_consecutive_failures,
    resolve_preset_key,
    set_fallback_active,
    set_group_key,
    set_preset,
    set_preset_api_key_batch,
    set_preset_emergency,
    set_preset_enabled,
    set_preset_group_label_batch,
    set_preset_priority,
)

# ---------- API-key encryption at rest (Phase 5) ----------
from services.db.key_crypto import (
    MasterKeyRequiredError,
    decrypt_secret,
    encrypt_for_storage,
    encrypt_secret,
    mask_key,
)

from services.db.legacy_aux import (
    _config_tests_prune_due,
    add_grammar_tip,
    log_config_test,
    prune_config_tests,
    purge_grammar_tips,
    recent_grammar_tip_titles,
)


# ---------- Backup / Restore (thin re-export; bodies in services/db/backup.py) ----------
from services.db.backup import (
    _RESTORE_CORE_TABLES,
    _STORAGE_SQLITE_CODES,
    _is_storage_error,
    export_db_bytes,
    import_db_bytes,
)
