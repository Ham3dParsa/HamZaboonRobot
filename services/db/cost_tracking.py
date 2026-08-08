"""LLM request cost tracking and analytics."""

import secrets

from services.db.schema import get_conn, _today, _utc_now


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
