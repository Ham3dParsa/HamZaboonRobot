"""LLM request cost tracking and analytics."""

import datetime
import logging
import secrets
import sqlite3
import time

from services.db.schema import get_conn, transaction, _today, _utc_now

logger = logging.getLogger(__name__)


def _is_missing_table(exc: Exception) -> bool:
    """True for a missing-table OperationalError (pre-migration DB).

    Only this case returns a silent fallback; every other error is logged
    before falling back so dashboards never silently show wrong totals.
    """
    return isinstance(exc, sqlite3.OperationalError) and "no such table" in str(exc)


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
    with transaction() as conn:
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
    return request_id


def delete_llm_requests(filters: dict[str, object] | None = None) -> int:
    where, params = _llm_request_filters_where(filters or {})
    with transaction() as conn:
        cursor = conn.execute(f"DELETE FROM llm_requests{where}", params)
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


_ROLLUP_SUM_KEYS = (
    "request_count",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "cost_toman",
    "input_cost_usd",
    "output_cost_usd",
    "input_cost_toman",
    "output_cost_toman",
    "success_count",
    "billed_failure_count",
    "zero_cost_failure_count",
    "billed_failure_cost_usd",
    "billed_failure_cost_toman",
)


def _rollup_eligible(filters: dict[str, object]) -> bool:
    """True when the rollup can contribute exactly (date-only filter).

    The per-day rollup carries no user/plan/model/kind/outcome dimensions, so
    any dimensional filter forces a raw-only read (retained ~90d window).
    """
    return set(filters) <= {"start_date", "end_date"}


def _rollup_sums(start_date: object | None, end_date: object | None) -> dict[str, float]:
    """Per-day rollup sums for the requested date range (zeros when empty)."""
    clauses: list[str] = []
    params: list[object] = []
    if start_date not in (None, ""):
        clauses.append("request_date>=?")
        params.append(start_date)
    if end_date not in (None, ""):
        clauses.append("request_date<=?")
        params.append(end_date)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with get_conn() as conn:
        try:
            row = conn.execute(
                "SELECT "
                "SUM(request_count) AS request_count, "
                "SUM(prompt_tokens) AS prompt_tokens, "
                "SUM(completion_tokens) AS completion_tokens, "
                "SUM(total_tokens) AS total_tokens, "
                "SUM(cost_usd) AS cost_usd, "
                "SUM(cost_toman) AS cost_toman, "
                "SUM(input_cost_usd) AS input_cost_usd, "
                "SUM(output_cost_usd) AS output_cost_usd, "
                "SUM(input_cost_toman) AS input_cost_toman, "
                "SUM(output_cost_toman) AS output_cost_toman, "
                "SUM(success_count) AS success_count, "
                "SUM(billed_failure_count) AS billed_failure_count, "
                "SUM(zero_cost_failure_count) AS zero_cost_failure_count, "
                "SUM(billed_failure_cost_usd) AS billed_failure_cost_usd, "
                "SUM(billed_failure_cost_toman) AS billed_failure_cost_toman, "
                "SUM(latency_sum_ms) AS latency_sum_ms, "
                "SUM(latency_count) AS latency_count "
                f"FROM llm_daily_rollup{where}",
                params,
            ).fetchone()
        except Exception as exc:
            if not _is_missing_table(exc):
                logger.exception("llm_daily_rollup sums read failed")
            return {}
    if not row:
        return {}
    return {key: (row[key] or 0) for key in row.keys()}


def rollup_request_count_since(date: str) -> int:
    """Lifetime request count held in the rollup for request_date >= date."""
    with get_conn() as conn:
        try:
            row = conn.execute(
                "SELECT SUM(request_count) AS cnt FROM llm_daily_rollup "
                "WHERE request_date >= ?",
                (date,),
            ).fetchone()
        except Exception as exc:
            if not _is_missing_table(exc):
                logger.exception("llm_daily_rollup count read failed")
            return 0
    return int(row["cnt"] or 0) if row else 0


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
            "SUM(COALESCE(prompt_tokens, 0) * COALESCE(input_cost_usd_per_million, 0) / 1000000.0) AS input_cost_usd, "
            "SUM(COALESCE(completion_tokens, 0) * COALESCE(output_cost_usd_per_million, 0) / 1000000.0) AS output_cost_usd, "
            "SUM(COALESCE(prompt_tokens, 0) * COALESCE(input_cost_usd_per_million, 0) * COALESCE(usd_to_toman_rate, 0) / 1000000.0) AS input_cost_toman, "
            "SUM(COALESCE(completion_tokens, 0) * COALESCE(output_cost_usd_per_million, 0) * COALESCE(usd_to_toman_rate, 0) / 1000000.0) AS output_cost_toman, "
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
    result = dict(row or {})
    active = filters or {}
    if _rollup_eligible(active):
        roll = _rollup_sums(active.get("start_date"), active.get("end_date"))
        if roll:
            for key in _ROLLUP_SUM_KEYS:
                result[key] = (result.get(key) or 0) + (roll.get(key) or 0)
            # NOTE: avg_latency_ms is the ONLY derived average in the base
            # query above (every other merged key is an additive SUM), and it
            # is recomputed here from merged (raw + rollup) totals — never by
            # averaging averages. Pinned by
            # test_purge_aggregates_exactly_then_deletes (pre/post-purge
            # summary equality over every key including avg_latency_ms).
            raw_lat_sum = 0.0
            raw_lat_cnt = 0
            with get_conn() as conn:
                lat = conn.execute(
                    "SELECT SUM(latency_ms) AS s, COUNT(latency_ms) AS c "
                    f"FROM llm_requests{where}",
                    params,
                ).fetchone()
            if lat:
                raw_lat_sum = float(lat["s"] or 0)
                raw_lat_cnt = int(lat["c"] or 0)
            total_cnt = raw_lat_cnt + int(roll.get("latency_count") or 0)
            if total_cnt:
                result["avg_latency_ms"] = (
                    raw_lat_sum + float(roll.get("latency_sum_ms") or 0)
                ) / total_cnt
    return result


def breakdown_llm_requests(
    group_by: str,
    filters: dict[str, object] | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, object]]:
    """Dimensional breakdown over retained raw rows only (~90d window).

    The per-day rollup carries no user/plan/model/kind dimensions, so purged
    history is not representable here by design (see purge_old_llm_requests).
    """
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
            "SUM(COALESCE(prompt_tokens, 0) * COALESCE(input_cost_usd_per_million, 0) / 1000000.0) AS input_cost_usd, "
            "SUM(COALESCE(completion_tokens, 0) * COALESCE(output_cost_usd_per_million, 0) / 1000000.0) AS output_cost_usd, "
            "SUM(COALESCE(prompt_tokens, 0) * COALESCE(input_cost_usd_per_million, 0) * COALESCE(usd_to_toman_rate, 0) / 1000000.0) AS input_cost_toman, "
            "SUM(COALESCE(completion_tokens, 0) * COALESCE(output_cost_usd_per_million, 0) * COALESCE(usd_to_toman_rate, 0) / 1000000.0) AS output_cost_toman, "
            "AVG(latency_ms) AS avg_latency_ms, "
            "SUM(CASE WHEN outcome='failure_billed' THEN 1 ELSE 0 END) "
            "AS billed_failure_count, "
            "SUM(CASE WHEN outcome='failure_zero_cost' THEN 1 ELSE 0 END) "
            "AS zero_cost_failure_count "
            "FROM llm_requests"
            f"{where} "
            f"GROUP BY {group_by} "
            "ORDER BY cost_usd DESC, request_count DESC, bucket ASC "
            "LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows]


def breakdown_llm_requests_preset_kind(
    filters: dict[str, object] | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[dict[str, object]]:
    """Group by preset_name × request_kind composite (R5 B).

    Returns bucket as ``preset:kind`` string (COALESCE preset to '—' when NULL).
    Same metrics as breakdown_llm_requests plus input/output splits computed on
    the fly (no migration, R2).
    """
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT "
            "COALESCE(preset_name, '—') || ':' || request_kind AS bucket, "
            "COUNT(*) AS request_count, "
            "SUM(COALESCE(prompt_tokens, 0)) AS prompt_tokens, "
            "SUM(COALESCE(completion_tokens, 0)) AS completion_tokens, "
            "SUM(COALESCE(total_tokens, 0)) AS total_tokens, "
            "SUM(COALESCE(cost_usd, 0)) AS cost_usd, "
            "SUM(COALESCE(cost_toman, 0)) AS cost_toman, "
            "SUM(COALESCE(prompt_tokens, 0) * COALESCE(input_cost_usd_per_million, 0) / 1000000.0) AS input_cost_usd, "
            "SUM(COALESCE(completion_tokens, 0) * COALESCE(output_cost_usd_per_million, 0) / 1000000.0) AS output_cost_usd, "
            "SUM(COALESCE(prompt_tokens, 0) * COALESCE(input_cost_usd_per_million, 0) * COALESCE(usd_to_toman_rate, 0) / 1000000.0) AS input_cost_toman, "
            "SUM(COALESCE(completion_tokens, 0) * COALESCE(output_cost_usd_per_million, 0) * COALESCE(usd_to_toman_rate, 0) / 1000000.0) AS output_cost_toman, "
            "AVG(latency_ms) AS avg_latency_ms, "
            "SUM(CASE WHEN outcome='failure_billed' THEN 1 ELSE 0 END) "
            "AS billed_failure_count, "
            "SUM(CASE WHEN outcome='failure_zero_cost' THEN 1 ELSE 0 END) "
            "AS zero_cost_failure_count "
            "FROM llm_requests"
            f"{where} "
            "GROUP BY preset_name, request_kind "
            "ORDER BY cost_usd DESC, request_count DESC, bucket ASC "
            "LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows]


def count_breakdown_groups(
    group_by: str,
    filters: dict[str, object] | None = None,
) -> int:
    if group_by not in {"user_id", "plan", "request_kind", "model", "outcome", "preset_name"}:
        raise ValueError(f"Unsupported LLM breakdown: {group_by}")
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM (SELECT 1 FROM llm_requests{where} GROUP BY {group_by})",
            params,
        ).fetchone()
    return int(row["cnt"] or 0) if row else 0


def count_breakdown_preset_kind_groups(
    filters: dict[str, object] | None = None,
) -> int:
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM (SELECT 1 FROM llm_requests{where} GROUP BY preset_name, request_kind)",
            params,
        ).fetchone()
    return int(row["cnt"] or 0) if row else 0


def recent_llm_requests(
    filters: dict[str, object] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, object]]:
    """Recent raw rows only (retained ~90d window); trends read the rollup."""
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


def daily_costs_grouped(
    filters: dict[str, object] | None = None,
) -> dict[str, float]:
    """Return daily total USD costs grouped by request_date (GROUP BY).

    Ticket #9 fix: replaces fetching 5000 rows and aggregating in Python with
    a single SQL GROUP BY. Reduces per-dashboard DB volume from O(5000) rows
    to O(days) rows.
    """
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT request_date AS d, SUM(COALESCE(cost_usd, 0)) AS total "
            "FROM llm_requests"
            f"{where} GROUP BY request_date ORDER BY d",
            params,
        ).fetchall()
    merged: dict[str, float] = {str(r["d"]): float(r["total"] or 0) for r in rows}
    active = filters or {}
    if _rollup_eligible(active):
        clauses: list[str] = []
        rparams: list[object] = []
        if active.get("start_date") not in (None, ""):
            clauses.append("request_date>=?")
            rparams.append(active.get("start_date"))
        if active.get("end_date") not in (None, ""):
            clauses.append("request_date<=?")
            rparams.append(active.get("end_date"))
        rwhere = " WHERE " + " AND ".join(clauses) if clauses else ""
        with get_conn() as conn:
            try:
                rrows = conn.execute(
                    "SELECT request_date AS d, SUM(cost_usd) AS total "
                    f"FROM llm_daily_rollup{rwhere} GROUP BY request_date",
                    rparams,
                ).fetchall()
            except Exception as exc:
                if not _is_missing_table(exc):
                    logger.exception("llm_daily_rollup read failed")
                rrows = []
        for r in rrows:
            day = str(r["d"])
            merged[day] = merged.get(day, 0.0) + float(r["total"] or 0)
    return dict(sorted(merged.items()))


def purge_old_llm_requests(retention_days: int = 90, batch: int = 500,
                         *, deadline: float | None = None) -> int:
    """Aggregate-then-drop purge of llm_requests older than retention_days.

    Rows with ``request_date`` older than (app-day today - retention_days) are
    first folded into per-day totals in ``llm_daily_rollup`` and then deleted.
    Each batch runs id-select + per-batch sums + rollup UPSERT + delete inside
    a single short ``transaction()`` via the canonical seam (no await across
    it), so a crash between batches never double-counts and two concurrent
    purgers cannot double-add: the second blocks on the write lock, then
    re-selects only rows the first has not deleted yet. A batch either fully
    merged+deleted or not at all. Idempotent — a re-run finds no old raw rows
    and changes nothing.

    Readers: ``summarize_llm_requests`` and ``daily_costs_grouped`` merge the
    rollup for date-only filters, so totals/trends are identical before and
    after. Dimensional readers (``breakdown_*``, ``count_breakdown_*``,
    ``recent_llm_requests``) intentionally read the retained raw window only
    (~90d); the per-day rollup carries no user/plan/model/kind dimensions.
    Stops batching at ``deadline`` (monotonic) when set so a backlog defers
    the remainder instead of starving the 05:30 backup.
    Function only — no scheduler wiring.
    """
    cutoff = (_today() - datetime.timedelta(days=retention_days)).isoformat()
    deleted = 0
    batch = max(1, int(batch))
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            with transaction() as conn:
                id_rows = conn.execute(
                    "SELECT id FROM llm_requests WHERE request_date < ? "
                    "ORDER BY id ASC LIMIT ?",
                    (cutoff, batch),
                ).fetchall()
                ids = [int(r["id"]) for r in id_rows]
                if not ids:
                    break
                placeholders = ",".join("?" * len(ids))
                sums = conn.execute(
                    "SELECT "
                    "request_date AS d, "
                    "COUNT(*) AS request_count, "
                    "SUM(COALESCE(prompt_tokens, 0)) AS prompt_tokens, "
                    "SUM(COALESCE(completion_tokens, 0)) AS completion_tokens, "
                    "SUM(COALESCE(total_tokens, 0)) AS total_tokens, "
                    "SUM(COALESCE(cost_usd, 0)) AS cost_usd, "
                    "SUM(COALESCE(cost_toman, 0)) AS cost_toman, "
                    "SUM(COALESCE(prompt_tokens, 0) * COALESCE(input_cost_usd_per_million, 0) / 1000000.0) AS input_cost_usd, "
                    "SUM(COALESCE(completion_tokens, 0) * COALESCE(output_cost_usd_per_million, 0) / 1000000.0) AS output_cost_usd, "
                    "SUM(COALESCE(prompt_tokens, 0) * COALESCE(input_cost_usd_per_million, 0) * COALESCE(usd_to_toman_rate, 0) / 1000000.0) AS input_cost_toman, "
                    "SUM(COALESCE(completion_tokens, 0) * COALESCE(output_cost_usd_per_million, 0) * COALESCE(usd_to_toman_rate, 0) / 1000000.0) AS output_cost_toman, "
                    "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS success_count, "
                    "SUM(CASE WHEN outcome='failure_billed' THEN 1 ELSE 0 END) AS billed_failure_count, "
                    "SUM(CASE WHEN outcome='failure_zero_cost' THEN 1 ELSE 0 END) AS zero_cost_failure_count, "
                    "SUM(CASE WHEN outcome='failure_billed' THEN COALESCE(cost_usd, 0) ELSE 0 END) AS billed_failure_cost_usd, "
                    "SUM(CASE WHEN outcome='failure_billed' THEN COALESCE(cost_toman, 0) ELSE 0 END) AS billed_failure_cost_toman, "
                    "SUM(latency_ms) AS latency_sum_ms, "
                    "COUNT(latency_ms) AS latency_count "
                    f"FROM llm_requests WHERE id IN ({placeholders}) GROUP BY request_date",
                    ids,
                ).fetchall()
                for s in sums:
                    conn.execute(
                        "INSERT INTO llm_daily_rollup("
                        "request_date, request_count, prompt_tokens, completion_tokens, "
                        "total_tokens, cost_usd, cost_toman, input_cost_usd, output_cost_usd, "
                        "input_cost_toman, output_cost_toman, success_count, "
                        "billed_failure_count, zero_cost_failure_count, "
                        "billed_failure_cost_usd, billed_failure_cost_toman, "
                        "latency_sum_ms, latency_count"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(request_date) DO UPDATE SET "
                        "request_count=request_count+excluded.request_count, "
                        "prompt_tokens=prompt_tokens+excluded.prompt_tokens, "
                        "completion_tokens=completion_tokens+excluded.completion_tokens, "
                        "total_tokens=total_tokens+excluded.total_tokens, "
                        "cost_usd=cost_usd+excluded.cost_usd, "
                        "cost_toman=cost_toman+excluded.cost_toman, "
                        "input_cost_usd=input_cost_usd+excluded.input_cost_usd, "
                        "output_cost_usd=output_cost_usd+excluded.output_cost_usd, "
                        "input_cost_toman=input_cost_toman+excluded.input_cost_toman, "
                        "output_cost_toman=output_cost_toman+excluded.output_cost_toman, "
                        "success_count=success_count+excluded.success_count, "
                        "billed_failure_count=billed_failure_count+excluded.billed_failure_count, "
                        "zero_cost_failure_count=zero_cost_failure_count+excluded.zero_cost_failure_count, "
                        "billed_failure_cost_usd=billed_failure_cost_usd+excluded.billed_failure_cost_usd, "
                        "billed_failure_cost_toman=billed_failure_cost_toman+excluded.billed_failure_cost_toman, "
                        "latency_sum_ms=latency_sum_ms+excluded.latency_sum_ms, "
                        "latency_count=latency_count+excluded.latency_count",
                        (
                            str(s["d"]),
                            int(s["request_count"] or 0),
                            int(s["prompt_tokens"] or 0),
                            int(s["completion_tokens"] or 0),
                            int(s["total_tokens"] or 0),
                            float(s["cost_usd"] or 0),
                            float(s["cost_toman"] or 0),
                            float(s["input_cost_usd"] or 0),
                            float(s["output_cost_usd"] or 0),
                            float(s["input_cost_toman"] or 0),
                            float(s["output_cost_toman"] or 0),
                            int(s["success_count"] or 0),
                            int(s["billed_failure_count"] or 0),
                            int(s["zero_cost_failure_count"] or 0),
                            float(s["billed_failure_cost_usd"] or 0),
                            float(s["billed_failure_cost_toman"] or 0),
                            int(s["latency_sum_ms"] or 0),
                            int(s["latency_count"] or 0),
                        ),
                    )
                conn.execute(
                    f"DELETE FROM llm_requests WHERE id IN ({placeholders})",
                    ids,
                )
        except Exception as exc:
            # Best-effort maintenance: a failed batch rolls back (no partial
            # rollup), committed batches keep their progress, and a re-run
            # resumes idempotently. Pre-migration DBs without the llm tables
            # return 0 silently (as before); any other failure is logged so a
            # stalled purge never goes unnoticed.
            if not _is_missing_table(exc):
                logger.exception("purge_old_llm_requests batch failed")
            return deleted
        deleted += len(ids)
        if len(ids) < batch:
            break
    return deleted
