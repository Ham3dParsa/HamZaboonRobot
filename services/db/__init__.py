"""Database layer — re-exports from submodules + non-SRS helpers."""

# ---------------------------------------------------------------------------
# Imports from config
# ---------------------------------------------------------------------------
from config import DB_PATH

import json
import datetime
import secrets

# ---------------------------------------------------------------------------
# Re-export from submodules
# ---------------------------------------------------------------------------
from services.db.schema import (
    get_conn,
    init_db,
    _app_timezone,
    _today,
    _utc_now,
    _normalize_word,
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
    create_user_if_needed,
    set_user_lang_goal,
    set_user_level,
    set_presentation_preference,
    set_user_lang,
    set_user_goal,
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
)

from services.db.words import (
    add_saved_word,
    update_saved_word_fields,
    due_words_for_user,
    get_saved_word,
    get_pre_first_exposure_words,
    grade_word_review,
    grade_first_exposure,
)

from services.db.reviews import (
    REVIEW_OUTCOMES,
    record_review_event,
)

from services.db.settings import (
    get_bool_setting,
    get_llm_cost_profile,
    get_phonetic_display_settings,
    get_setting,
    set_bool_setting,
    set_llm_cost_profile,
    set_setting,
)


# ---------------------------------------------------------------------------
# Query Results
# ---------------------------------------------------------------------------

def _query_result_expired(row) -> bool:
    return row is not None and row["expires_at"] <= _utc_now().isoformat()


def create_query_result(
    user_id: int,
    query_text: str,
    word: str,
    lang: str,
    result_data: dict,
    ttl_seconds: int = 24 * 60 * 60,
) -> str:
    token = secrets.token_hex(16)
    now = _utc_now()
    expires_at = now + datetime.timedelta(seconds=ttl_seconds)
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO query_results("
            "token, user_id, query_text, word, lang, result_json, created_at, expires_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                user_id,
                " ".join(query_text.split()),
                " ".join(word.split()),
                lang,
                json.dumps(result_data, ensure_ascii=False),
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()
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


def mark_query_result_saved(token: str, saved_word_id: int | None = None):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE query_results SET saved_at=COALESCE(saved_at, ?), "
            "saved_word_id=COALESCE(saved_word_id, ?) WHERE token=?",
            (_utc_now().isoformat(), saved_word_id, token),
        )
        conn.commit()


def update_query_result_fields(
    token: str,
    user_id: int,
    patch: dict,
) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
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
        conn.commit()
        return True


def cleanup_expired_query_results():
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM query_results WHERE expires_at<?",
            (_utc_now().isoformat(),),
        )
        conn.commit()


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
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
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
        conn.commit()


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
    get_preset,
    get_preset_cost,
    get_presets,
    increment_consecutive_failures,
    increment_hourly_usage,
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

# ---------- Config Tests Audit ----------

def log_config_test(test_type: str, preset_name: str, prompt: str, result: dict):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
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
        conn.commit()


# ---------- Backup / Restore ----------

def export_db_bytes() -> bytes:
    with open(DB_PATH, "rb") as f:
        return f.read()


def import_db_bytes(data: bytes) -> None:
    with open(DB_PATH, "wb") as f:
        f.write(data)
    init_db()
