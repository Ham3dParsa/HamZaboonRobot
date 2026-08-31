"""Database layer — re-exports from submodules + non-SRS helpers."""

# ---------------------------------------------------------------------------
# Imports from config
# ---------------------------------------------------------------------------
from config import DB_PATH

import json
import datetime
import logging
import os
import secrets
import sqlite3
import stat
import tempfile
import shutil
from contextlib import closing

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
)

from services.db.session_reports import (
    REPORT_WINDOW_DAYS,
    LoadedReport,
    ReportEntry,
    list_recent_reports,
    load_report,
    save_session_report,
)


logger = logging.getLogger(__name__)
_RESTORE_CORE_TABLES = frozenset(
    {"users", "saved_words", "settings", "review_events", "llm_requests"}
)
# Stable SQLite primary result codes; Python 3.10 does not expose all of the
# corresponding sqlite3.SQLITE_* constants.
_STORAGE_SQLITE_CODES = frozenset(
    {
        7,   # SQLITE_NOMEM
        8,   # SQLITE_READONLY
        10,  # SQLITE_IOERR
        13,  # SQLITE_FULL
        14,  # SQLITE_CANTOPEN
    }
)


def _is_storage_error(exc: BaseException) -> bool:
    error_code = getattr(exc, "sqlite_errorcode", None)
    if error_code is not None and error_code & 0xFF in _STORAGE_SQLITE_CODES:
        return True
    return any(
        phrase in str(exc).lower()
        for phrase in ("disk is full", "i/o error", "readonly", "read-only")
    )

from services.db.reviews import (
    REVIEW_OUTCOMES,
    record_review_event,
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
# Query Results
# ---------------------------------------------------------------------------

def _query_result_expired(row) -> bool:
    return row is not None and row["expires_at"] <= _utc_now().isoformat()


def _normalize_query_text(text: str) -> str:
    """Normalize the dedup key exactly as saved words are normalized (R7a).

    Delegates to the single-source ``schema.normalize_word`` (A2-3 / R2) so the
    query-dedup key and ``saved_words.normalized_word`` always agree (NFC +
    casefold + whitespace-collapse). Used identically on insert and lookup so a
    prior card is found for case/Unicode variants instead of re-spending quota +
    AI.
    """
    return normalize_word(text)


def create_query_result(
    user_id: int,
    query_text: str,
    word: str,
    lang: str,
    result_data: dict,
    ttl_seconds: int = 30 * 24 * 60 * 60,
) -> str:
    token = secrets.token_hex(16)
    now = _utc_now()
    expires_at = now + datetime.timedelta(seconds=ttl_seconds)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO query_results("
            "token, user_id, query_text, word, lang, result_json, created_at, expires_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                user_id,
                _normalize_query_text(query_text),
                " ".join(word.split()),
                lang,
                json.dumps(result_data, ensure_ascii=False),
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
    return token


def get_query_result(token: str, user_id: int | None = None, include_expired: bool = False):
    with get_conn() as conn:
        params = [token]
        query = "SELECT * FROM query_results WHERE token=?"
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        row = conn.execute(query, params).fetchone()
    if row and not include_expired and _query_result_expired(row):
        return None
    return row


def find_unexpired_query(user_id: int, query_text: str, lang: str):
    """Return the most recent unexpired query_result for the same user + lang +
    normalized query_text, or None.

    R7a dedup key: the stored ``query_text`` column is normalized on insert via
    ``_normalize_query_text`` (NFC + casefold + whitespace-collapse), so this
    lookup normalizes the incoming text the same way and matches exactly. Runs
    before quota/AI, so the caller can offer retrieve-vs-new for a word the user
    already asked.
    """
    normalized = _normalize_query_text(query_text)
    now = _utc_now().isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM query_results "
            "WHERE user_id=? AND lang=? AND query_text=? AND expires_at>? "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id, lang, normalized, now),
        ).fetchone()


def mark_query_result_saved(token: str, saved_word_id: int | None = None):
    with transaction() as conn:
        conn.execute(
            "UPDATE query_results SET saved_at=COALESCE(saved_at, ?), "
            "saved_word_id=COALESCE(saved_word_id, ?) WHERE token=?",
            (_utc_now().isoformat(), saved_word_id, token),
        )


def clear_query_result_saved(token: str):
    with transaction() as conn:
        conn.execute(
            "UPDATE query_results SET saved_at=NULL, saved_word_id=NULL WHERE token=?",
            (token,),
        )


def update_query_result_fields(
    token: str,
    user_id: int,
    patch: dict,
) -> bool:
    with transaction() as conn:
        row = conn.execute(
            "SELECT result_json FROM query_results WHERE token=? AND user_id=?",
            (token, user_id),
        ).fetchone()
        if not row:
            return False
        try:
            result_data = json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(result_data, dict):
            return False
        result_data.update(patch)
        conn.execute(
            "UPDATE query_results SET result_json=? WHERE token=? AND user_id=?",
            (json.dumps(result_data, ensure_ascii=False), token, user_id),
        )
        return True


def cleanup_expired_query_results():
    with transaction() as conn:
        conn.execute(
            "DELETE FROM query_results WHERE expires_at<?",
            (_utc_now().isoformat(),),
        )


# ---------------------------------------------------------------------------
# Grammar Tips
# ---------------------------------------------------------------------------

def add_grammar_tip(
    user_id: int,
    title: str,
    lang: str,
    goal: str,
    level: str,
    tip_data: dict,
    provenance: str = "",
):
    title = " ".join(title.split())
    if not title:
        return
    with transaction() as conn:
        conn.execute(
            "INSERT INTO grammar_tips("
            "user_id, tip_date, title, lang, goal, level, tip_json, created_at, provenance"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                _today().isoformat(),
                title,
                lang,
                goal,
                level,
                json.dumps(tip_data, ensure_ascii=False),
                _utc_now().isoformat(),
                provenance,
            ),
        )


def recent_grammar_tip_titles(
    user_id: int,
    lang: str | None = None,
    limit: int = 12,
) -> list[str]:
    query = "SELECT title FROM grammar_tips WHERE user_id=?"
    params: list[object] = [user_id]
    if lang is not None:
        query += " AND lang=?"
        params.append(lang)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row["title"] for row in rows]


# ---------------------------------------------------------------------------
# LLM request tracking
# ---------------------------------------------------------------------------
from services.db.cost_tracking import (
    add_llm_request,
    breakdown_llm_requests,
    daily_costs_grouped,
    delete_llm_requests,
    recent_llm_requests,
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

# ---------- Config Tests Audit ----------

def log_config_test(test_type: str, preset_name: str, prompt: str, result: dict):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO config_tests(test_type, preset_name, prompt, result, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                test_type,
                preset_name,
                prompt,
                json.dumps(result, ensure_ascii=False),
                _utc_now().isoformat(),
            ),
        )


def prune_config_tests(max_rows: int = 1000, max_age_days: int = 30) -> int:
    """Prune unbounded config_tests audit table (O-config-tests).

    Fast-track prune: deletes rows older than max_age_days and keeps only the
    most recent max_rows rows. Returns total deleted count. No behavior change
    for callers — log_config_test continues to insert.
    """
    cutoff = (_utc_now() - datetime.timedelta(days=max_age_days)).isoformat()
    deleted = 0
    with transaction() as conn:
        cur = conn.execute("DELETE FROM config_tests WHERE created_at < ?", (cutoff,))
        deleted += cur.rowcount or 0
        count = conn.execute("SELECT COUNT(*) AS c FROM config_tests").fetchone()["c"]
        if count > max_rows:
            to_delete = count - max_rows
            conn.execute(
                "DELETE FROM config_tests WHERE id IN "
                "(SELECT id FROM config_tests ORDER BY created_at ASC, id ASC LIMIT ?)",
                (to_delete,),
            )
            deleted += to_delete
    return deleted


# ---------- Backup / Restore ----------

def export_db_bytes() -> bytes:
    snapshot_fd, snapshot_path = tempfile.mkstemp(
        suffix=".sqlite",
        dir=os.path.dirname(os.path.abspath(DB_PATH)),
    )
    os.close(snapshot_fd)
    try:
        # Exclusive hold: wait for active connections, block new ones, so the
        # snapshot reflects a stable DB (A2-1-6).
        with maintenance(), get_conn() as source, closing(sqlite3.connect(snapshot_path)) as target:
            source.backup(target)
        with open(snapshot_path, "rb") as snapshot_file:
            return snapshot_file.read()
    finally:
        try:
            if os.path.exists(snapshot_path):
                os.remove(snapshot_path)
        except OSError:
            logger.exception("Could not remove temporary database snapshot: %s", snapshot_path)


def import_db_bytes(data: bytes, backup_path: str | None = None) -> None:
    candidate_path = None
    reference_path = None
    try:
        with maintenance():
            try:
                # MUST 1: validate target safety BEFORE any FS side effect.
                try:
                    _guard_destructive_op(DB_PATH)
                except RuntimeError as exc:
                    raise ValueError(str(exc)) from exc
                candidate_fd, candidate_path = tempfile.mkstemp(
                    suffix=".sqlite",
                    dir=os.path.dirname(os.path.abspath(DB_PATH)),
                )
                original_stat = os.stat(DB_PATH)
                with os.fdopen(candidate_fd, "wb") as candidate_file:
                    candidate_file.write(data)
                with closing(sqlite3.connect(candidate_path)) as candidate_conn:
                    quick_check = candidate_conn.execute("PRAGMA quick_check").fetchone()
                    candidate_tables = {
                        row[0]
                        for row in candidate_conn.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                if not quick_check or quick_check[0] != "ok":
                    raise ValueError("فایل پشتیبان معتبر نیست.")
                if _LEGACY_DAILY_TABLES & candidate_tables:
                    raise ValueError(
                        "نسخه پشتیبان قدیمی است و قابل بازگردانی نیست."
                    )
                if not _RESTORE_CORE_TABLES.issubset(candidate_tables):
                    raise ValueError("فایل پشتیبان معتبر نیست.")
                init_db(candidate_path)
                reference_fd, reference_path = tempfile.mkstemp(
                    suffix=".sqlite",
                    dir=os.path.dirname(os.path.abspath(DB_PATH)),
                )
                os.close(reference_fd)
                init_db(reference_path)
                with closing(sqlite3.connect(candidate_path)) as candidate_conn, closing(
                    sqlite3.connect(reference_path)
                ) as reference_conn:
                    required_tables = {
                        row[0]
                        for row in reference_conn.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                    candidate_tables = {
                        row[0]
                        for row in candidate_conn.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                    def _quoted_ident(name: str) -> str:
                        # Caller filters to required_tables ∩ candidate_tables, so
                        # injection is blocked by the intersection + quote-doubling.
                        return '"' + name.replace('"', '""') + '"'

                    missing_columns = {
                        table: {
                            row[1]
                            for row in reference_conn.execute(
                                f"PRAGMA table_info({_quoted_ident(table)})"
                            )
                        }
                        - {
                            row[1]
                            for row in candidate_conn.execute(
                                f"PRAGMA table_info({_quoted_ident(table)})"
                            )
                        }
                        for table in required_tables & candidate_tables
                    }
                if any(missing_columns.values()):
                    raise RuntimeError("incomplete schema")
            except ValueError:
                raise
            except (OSError, MemoryError) as exc:
                raise ValueError(
                    "فضای ذخیره‌سازی یا دسترسی فایل برای بازگردانی کافی نیست."
                ) from exc
            except Exception as exc:
                if _is_storage_error(exc):
                    raise ValueError(
                        "فضای ذخیره‌سازی یا دسترسی فایل برای بازگردانی کافی نیست."
                    ) from exc
                raise ValueError(
                    "نسخه پشتیبان با نسخه فعلی ربات سازگار نیست."
                ) from exc
            try:
                # Candidate must not be the production path. Target already
                # validated at the top of the operation; re-checking here
                # would be after mkstemp.
                try:
                    _check_test_mode_guard(candidate_path)
                except RuntimeError as exc:
                    raise ValueError(str(exc)) from exc
                os.chmod(candidate_path, stat.S_IMODE(original_stat.st_mode))
                if hasattr(os, "chown"):
                    try:
                        os.chown(candidate_path, original_stat.st_uid, original_stat.st_gid)
                    except PermissionError:
                        pass
                if backup_path:
                    shutil.copy2(DB_PATH, backup_path)
                os.replace(candidate_path, DB_PATH)
            except OSError as exc:
                raise ValueError(
                    "جایگزینی دیتابیس در حال حاضر ممکن نیست. دوباره تلاش کنید."
                ) from exc
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = f"{DB_PATH}{suffix}"
                try:
                    if os.path.exists(sidecar):
                        os.remove(sidecar)
                except OSError:
                    logger.exception("Could not remove stale SQLite sidecar: %s", sidecar)
    finally:
        for path in (candidate_path, reference_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    logger.exception("Could not remove temporary restore file: %s", path)
