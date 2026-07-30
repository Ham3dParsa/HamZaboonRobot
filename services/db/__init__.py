"""Database layer — re-exports from submodules + non-SRS helpers."""

# ---------------------------------------------------------------------------
# Imports from config
# ---------------------------------------------------------------------------
from config import (
    DB_PATH,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    DEFAULT_PHONETIC_SHOW_IPA,
    FREE_DAILY_CARD_LIMIT,
    SILVER_DAILY_CARD_LIMIT,
    GOLD_DAILY_CARD_LIMIT,
    LLM_INPUT_COST_USD_PER_MILLION,
    LLM_OUTPUT_COST_USD_PER_MILLION,
    PLANS,
    APP_TIMEZONE,
    USD_TO_TOMAN_RATE,
)

import json
import datetime
import secrets

# ---------------------------------------------------------------------------
# Re-export from submodules
# ---------------------------------------------------------------------------
from services.db.schema import (
    get_conn,
    init_db,
    INTERVALS_DAYS,
    _app_timezone,
    _today,
    _utc_now,
    _normalize_word,
    _current_daily_count,
    _can_consume_daily_count,
    _init_ai_presets_table,
    _init_config_tests_table,
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
    get_daily_cards,
    get_recent_daily_words,
    get_recent_daily_card_dates,
    count_daily_cards,
    add_daily_card,
    update_daily_card_fields,
    get_daily_progress,
    set_daily_progress,
    get_daily_card_session,
    ensure_daily_card_session,
    add_saved_word,
    update_saved_word_fields,
    due_words_for_user,
    get_saved_word,
    advance_word_review,
    defer_word_review,
    get_pre_first_exposure_words,
    grade_word_review,
    grade_first_exposure,
    migrate_saved_words_to_fsrs,
)

from services.db.reviews import (
    REVIEW_OUTCOMES,
    record_review_event,
)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


def get_bool_setting(key: str, default: bool = False) -> bool:
    return get_setting(key, "true" if default else "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def set_bool_setting(key: str, value: bool):
    set_setting(key, "true" if value else "false")


def get_phonetic_display_settings() -> dict[str, bool]:
    return {
        "ipa": get_bool_setting("phonetic_show_ipa", DEFAULT_PHONETIC_SHOW_IPA),
    }


def get_llm_cost_profile() -> dict[str, float]:
    return {
        "input_cost_usd_per_million": float(
            get_setting("llm_input_cost_usd_per_million", str(LLM_INPUT_COST_USD_PER_MILLION))
        ),
        "output_cost_usd_per_million": float(
            get_setting("llm_output_cost_usd_per_million", str(LLM_OUTPUT_COST_USD_PER_MILLION))
        ),
        "usd_to_toman_rate": float(get_setting("usd_to_toman_rate", str(USD_TO_TOMAN_RATE))),
    }


def set_llm_cost_profile(
    *,
    input_cost_usd_per_million: float,
    output_cost_usd_per_million: float,
    usd_to_toman_rate: float,
):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("llm_input_cost_usd_per_million", str(input_cost_usd_per_million)),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("llm_output_cost_usd_per_million", str(output_cost_usd_per_million)),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("usd_to_toman_rate", str(usd_to_toman_rate)),
        )
        conn.commit()


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
# LLM Request Tracking
# ---------------------------------------------------------------------------

def add_llm_request(
    *,
    user_id: int,
    plan: str,
    request_kind: str,
    model: str,
    outcome: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    input_cost_usd_per_million: float,
    output_cost_usd_per_million: float,
    usd_to_toman_rate: float,
    latency_ms: int | None,
    error_class: str | None = None,
    error_message: str | None = None,
    preset_name: str | None = None,
):
    prompt_tokens = int(prompt_tokens or 0)
    completion_tokens = int(completion_tokens or 0)
    total_tokens = int(total_tokens or (prompt_tokens + completion_tokens))
    cost_usd = (
        (prompt_tokens / 1_000_000) * float(input_cost_usd_per_million)
        + (completion_tokens / 1_000_000) * float(output_cost_usd_per_million)
    )
    cost_toman = cost_usd * float(usd_to_toman_rate)
    request_id = secrets.token_hex(16)
    now = _utc_now()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO llm_requests("
            "request_id, created_at, request_date, user_id, plan, request_kind, model, "
            "outcome, prompt_tokens, completion_tokens, total_tokens, "
            "input_cost_usd_per_million, output_cost_usd_per_million, usd_to_toman_rate, "
            "cost_usd, cost_toman, latency_ms, error_class, error_message, preset_name"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request_id,
                now.isoformat(),
                _today().isoformat(),
                user_id,
                plan,
                request_kind,
                model,
                outcome,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                float(input_cost_usd_per_million),
                float(output_cost_usd_per_million),
                float(usd_to_toman_rate),
                cost_usd,
                cost_toman,
                latency_ms,
                error_class,
                (error_message or "")[:1000] or None,
                preset_name,
            ),
        )
        conn.commit()
    return request_id


def delete_llm_requests(filters: dict[str, object] | None = None) -> int:
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(f"DELETE FROM llm_requests{where}", params)
        conn.commit()
    return cursor.rowcount


def _llm_request_filters_where(filters: dict[str, object]) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    def add_clause(sql: str, value: object | None):
        if value is None or value == "":
            return
        clauses.append(sql)
        params.append(value)

    add_clause("request_date>=?", filters.get("start_date"))
    add_clause("request_date<=?", filters.get("end_date"))
    add_clause("user_id=?", filters.get("user_id"))
    add_clause("plan=?", filters.get("plan"))
    add_clause("request_kind=?", filters.get("request_kind"))
    add_clause("model=?", filters.get("model"))
    add_clause("outcome=?", filters.get("outcome"))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def summarize_llm_requests(filters: dict[str, object] | None = None) -> dict[str, object]:
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        row = conn.execute(
            "SELECT "
            "COUNT(*) AS request_count, "
            "SUM(COALESCE(prompt_tokens, 0)) AS prompt_tokens, "
            "SUM(COALESCE(completion_tokens, 0)) AS completion_tokens, "
            "SUM(COALESCE(total_tokens, 0)) AS total_tokens, "
            "SUM(COALESCE(cost_usd, 0)) AS cost_usd, "
            "SUM(COALESCE(cost_toman, 0)) AS cost_toman, "
            "AVG(latency_ms) AS avg_latency_ms, "
            "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS success_count, "
            "SUM(CASE WHEN outcome='failure_billed' THEN 1 ELSE 0 END) AS billed_failure_count, "
            "SUM(CASE WHEN outcome='failure_zero_cost' THEN 1 ELSE 0 END) AS zero_cost_failure_count, "
            "SUM(CASE WHEN outcome='failure_billed' THEN COALESCE(cost_usd, 0) ELSE 0 END) "
            "AS billed_failure_cost_usd, "
            "SUM(CASE WHEN outcome='failure_billed' THEN COALESCE(cost_toman, 0) ELSE 0 END) "
            "AS billed_failure_cost_toman "
            "FROM llm_requests"
            f"{where}",
            params,
        ).fetchone()
    return dict(row or {})


def breakdown_llm_requests(
    group_by: str,
    filters: dict[str, object] | None = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    if group_by not in {"user_id", "plan", "request_kind", "model", "outcome", "preset_name"}:
        raise ValueError(f"Unsupported LLM breakdown: {group_by}")
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT "
            f"{group_by} AS bucket, "
            "COUNT(*) AS request_count, "
            "SUM(COALESCE(prompt_tokens, 0)) AS prompt_tokens, "
            "SUM(COALESCE(completion_tokens, 0)) AS completion_tokens, "
            "SUM(COALESCE(total_tokens, 0)) AS total_tokens, "
            "SUM(COALESCE(cost_usd, 0)) AS cost_usd, "
            "SUM(COALESCE(cost_toman, 0)) AS cost_toman, "
            "AVG(latency_ms) AS avg_latency_ms, "
            "SUM(CASE WHEN outcome='failure_billed' THEN 1 ELSE 0 END) "
            "AS billed_failure_count, "
            "SUM(CASE WHEN outcome='failure_zero_cost' THEN 1 ELSE 0 END) "
            "AS zero_cost_failure_count "
            "FROM llm_requests"
            f"{where} "
            f"GROUP BY {group_by} "
            "ORDER BY cost_usd DESC, request_count DESC, bucket ASC "
            "LIMIT ?",
            [*params, limit],
        ).fetchall()
    return [dict(row) for row in rows]


def recent_llm_requests(
    filters: dict[str, object] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, object]]:
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_requests"
            f"{where} "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# AI Presets
# ---------------------------------------------------------------------------

_first_enabled_name_cache: str | None = None


def get_presets() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM ai_presets ORDER BY is_custom, name").fetchall()
    return [dict(row) for row in rows]


def get_preset(name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ai_presets WHERE name=?", (name,)).fetchone()
    return dict(row) if row else None


def get_active_preset_name() -> str:
    if get_bool_setting("ai_fallback_active", False):
        return get_setting("ai_fallback_preset", "gapgpt_gemini_lite")
    return get_setting("ai_primary_preset", _first_enabled_name())


def get_active_preset() -> dict:
    name = get_active_preset_name()
    preset = get_preset(name)
    if not preset:
        preset = get_preset(_first_enabled_name())
    return preset or {}


def set_preset(
    name: str,
    base_url: str = "",
    model: str = "",
    api_key: str = "",
    daily_batch_size: int = 6,
    max_concurrency: int = 2,
    max_rpm: int = 30,
    max_tpm: int = 0,
    max_daily_req: int = 0,
    timeout_seconds: float = 30.0,
    temperature: float = 0.6,
    max_output_tokens: int = 4096,
    is_custom: int = 1,
    is_emergency: int = 0,
    input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
    in_fallback_chain: int = 1,
    group_label: str = "",
):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO ai_presets(name, base_url, model, api_key, daily_batch_size, max_concurrency, max_rpm, max_tpm, max_daily_req, timeout_seconds, temperature, max_output_tokens, is_custom, is_emergency, input_cost_per_million, output_cost_per_million, in_fallback_chain, group_label) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "base_url=excluded.base_url, model=excluded.model, api_key=excluded.api_key, "
            "daily_batch_size=excluded.daily_batch_size, "
            "max_concurrency=excluded.max_concurrency, max_rpm=excluded.max_rpm, "
            "max_tpm=excluded.max_tpm, max_daily_req=excluded.max_daily_req, "
            "timeout_seconds=excluded.timeout_seconds, temperature=excluded.temperature, "
            "max_output_tokens=excluded.max_output_tokens, is_custom=excluded.is_custom, "
            "is_emergency=excluded.is_emergency, "
            "input_cost_per_million=excluded.input_cost_per_million, "
            "output_cost_per_million=excluded.output_cost_per_million, "
            "in_fallback_chain=excluded.in_fallback_chain, "
            "group_label=excluded.group_label",
            (
                name,
                base_url,
                model,
                api_key,
                daily_batch_size,
                max_concurrency,
                max_rpm,
                max_tpm,
                max_daily_req,
                timeout_seconds,
                temperature,
                max_output_tokens,
                is_custom,
                is_emergency,
                input_cost_per_million,
                output_cost_per_million,
                in_fallback_chain,
                group_label,
            ),
        )
        conn.commit()


def set_preset_api_key_batch(names: list[str], new_key: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in names)
        conn.execute(
            f"UPDATE ai_presets SET api_key=? WHERE name IN ({placeholders})",
            (new_key, *names),
        )
        conn.commit()


def set_preset_group_label_batch(names: list[str], label: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in names)
        conn.execute(
            f"UPDATE ai_presets SET group_label=? WHERE name IN ({placeholders})",
            (label, *names),
        )
        conn.commit()


def get_group_labels() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT group_label, COUNT(*) as count FROM ai_presets "
            "WHERE group_label != '' AND group_label IS NOT NULL "
            "GROUP BY group_label ORDER BY count DESC"
        ).fetchall()
        return [{"label": r["group_label"], "count": r["count"]} for r in rows]


def rename_group_label(old_label: str, new_label: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE ai_presets SET group_label=? WHERE group_label=?",
            (new_label, old_label),
        )
        conn.commit()


def clear_group_label(label: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE ai_presets SET group_label='' WHERE group_label=?",
            (label,),
        )
        conn.commit()


def delete_preset(name: str) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "DELETE FROM ai_presets WHERE name=?", (name,)
        )
        conn.commit()
        return cursor.rowcount > 0


def activate_preset(name: str) -> bool:
    preset = get_preset(name)
    if not preset:
        return False
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_primary_preset", name),
        )
        if preset.get("base_url"):
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_base_url", preset["base_url"]),
            )
        if preset.get("model"):
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_model", preset["model"]),
            )
        if preset.get("api_key"):
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_api_key", preset["api_key"]),
            )
        conn.commit()
    return True


# ---------- Preset Cost ----------

def get_preset_cost(preset_name: str) -> dict:
    preset = get_preset(preset_name)
    if not preset:
        return {"input_cost_per_million": None, "output_cost_per_million": None}
    return {
        "input_cost_per_million": preset.get("input_cost_per_million"),
        "output_cost_per_million": preset.get("output_cost_per_million"),
    }


# ---------- Fallback State Management ----------

def set_fallback_active(active: bool, fallback_preset: str | None = None):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_fallback_active", "true" if active else "false"),
        )
        if active:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_fallback_since", _utc_now().isoformat()),
            )
            if fallback_preset:
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("ai_fallback_preset", fallback_preset),
                )
        else:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_fallback_since", ""),
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_consecutive_failures", "0"),
            )
        conn.commit()


def increment_consecutive_failures() -> int:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = int(get_setting("ai_consecutive_failures", "0")) + 1
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_consecutive_failures", str(current)),
        )
        conn.commit()
        return current


def reset_consecutive_failures():
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_consecutive_failures", "0"),
        )
        conn.commit()


def _first_enabled_name() -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM ai_presets WHERE enabled=1 AND is_emergency=0 ORDER BY priority ASC, name ASC LIMIT 1"
        ).fetchone()
    return row["name"] if row else "google_35_flash_hpof"


def get_fallback_status() -> dict:
    return {
        "fallback_active": get_bool_setting("ai_fallback_active", False),
        "primary_preset": get_setting("ai_primary_preset", _first_enabled_name()),
        "fallback_preset": get_setting("ai_fallback_preset", "gapgpt_gemini_lite"),
        "fallback_since": get_setting("ai_fallback_since", ""),
        "consecutive_failures": int(get_setting("ai_consecutive_failures", "0")),
    }


# ---------- Preset Hourly Usage ----------

def get_hourly_usage(preset_name: str, hours_back: int = 24) -> tuple[int, int]:
    import datetime as dt
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_back)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(request_count), 0) req, COALESCE(SUM(token_count), 0) tok "
            "FROM preset_hourly_usage WHERE preset_name=? AND hour_bucket >= ?",
            (preset_name, cutoff[:13]),
        ).fetchone()
    return (row["req"], row["tok"])


def increment_hourly_usage(preset_name: str, hour_bucket: str, req_count: int = 1, token_count: int = 0):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO preset_hourly_usage(preset_name, hour_bucket, request_count, token_count) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(preset_name, hour_bucket) DO UPDATE SET "
            "request_count=request_count+excluded.request_count, "
            "token_count=token_count+excluded.token_count",
            (preset_name, hour_bucket, req_count, token_count),
        )
        conn.commit()


# ---------- Preset Management ----------

def get_enabled_presets_ordered() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_presets WHERE enabled=1 ORDER BY is_emergency ASC, priority ASC, name ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_fallback_chain_presets() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_presets WHERE enabled=1 AND in_fallback_chain=1 "
            "ORDER BY is_emergency ASC, priority ASC, name ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def reindex_preset_priority(name: str, target_rank: int, group_is_emergency: bool):
    target_idx = target_rank - 1
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT name, priority FROM ai_presets "
            "WHERE enabled=1 AND is_emergency=? AND in_fallback_chain=1 "
            "ORDER BY priority ASC, name ASC",
            (1 if group_is_emergency else 0,),
        ).fetchall()

        count = len(rows)
        if not (1 <= target_rank <= count):
            raise ValueError(f"target_rank {target_rank} out of range [1, {count}]")

        names = [r["name"] for r in rows]
        current_idx = names.index(name) if name in names else -1
        if current_idx == -1:
            raise ValueError(f"preset {name} not found in group")
        if current_idx == target_idx:
            conn.commit()
            return

        item = rows.pop(current_idx)
        rows.insert(target_idx, item)

        for i, row in enumerate(rows):
            conn.execute(
                "UPDATE ai_presets SET priority=? WHERE name=?",
                (i, row["name"]),
            )
        conn.commit()


def set_preset_priority(name: str, priority: int):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE ai_presets SET priority=? WHERE name=?", (priority, name))
        conn.commit()


def set_preset_enabled(name: str, enabled: bool):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE ai_presets SET enabled=? WHERE name=?", (1 if enabled else 0, name))
        conn.commit()


def set_preset_emergency(name: str, is_emergency: bool):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE ai_presets SET is_emergency=? WHERE name=?", (1 if is_emergency else 0, name))
        conn.commit()


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
