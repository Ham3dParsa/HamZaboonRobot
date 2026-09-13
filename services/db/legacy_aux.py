"""Auxiliary/legacy persistence leaves (verbatim split from services/db/__init__.py).

Owns the retired ``grammar_tips`` table helpers and the ``config_tests`` audit
table (insert + lazy-prune + batched purge). Imports only from
``services.db.schema`` (never the facade) per the leaf-import law.
"""

import datetime
import json
import time

from services.db.schema import get_conn, transaction, _today, _utc_now


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
    # Lazy retention, gated: the audit table is unbounded, so an insert runs
    # the prune only when it can do work (row count above max or oldest row
    # past max age) — two cheap scalar reads instead of unbounded `while True`
    # batch loops on every admin insert. Same precedent as session_reports'
    # lazy purge (R10-E); the prune itself still runs in its own short
    # transaction(s) after the insert. No scheduler wiring (per T1 contract).
    if _config_tests_prune_due():
        prune_config_tests()


def _config_tests_prune_due(
    max_rows: int = 1000, max_age_days: int = 30
) -> bool:
    """True when prune_config_tests() has work to do (cheap pre-check).

    Same thresholds as the prune defaults so the gate can never suppress a
    needed run; log_config_test is admin-triggered (low frequency), so two
    scalar reads per insert are negligible.
    """
    cutoff = (_utc_now() - datetime.timedelta(days=max_age_days)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c, MIN(created_at) AS oldest FROM config_tests"
        ).fetchone()
    if row is None:
        return False
    if (row["c"] or 0) > max_rows:
        return True
    oldest = row["oldest"]
    return oldest is not None and oldest < cutoff


def prune_config_tests(
    max_rows: int = 1000, max_age_days: int = 30, *, batch: int = 500,
    deadline: float | None = None,
) -> int:
    """Prune unbounded config_tests audit table (O-config-tests).

    Deletes rows older than max_age_days and keeps only the most recent
    max_rows rows. Returns total deleted count. DELETE-only, batched via
    rowid (each batch in its own short ``transaction()``) so a large backlog
    never holds one long transaction. Stops batching at ``deadline``
    (monotonic) when set so a backlog defers the remainder. No behavior
    change for readers of recent rows — log_config_test continues to insert.
    """
    cutoff = (_utc_now() - datetime.timedelta(days=max_age_days)).isoformat()
    deleted = 0
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            break
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM config_tests WHERE rowid IN ("
                "SELECT rowid FROM config_tests WHERE created_at < ? LIMIT ?)",
                (cutoff, batch),
            )
            n = cur.rowcount or 0
        deleted += n
        if n < batch:
            break
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            break
        with transaction() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM config_tests"
            ).fetchone()["c"]
            if count <= max_rows:
                break
            cur = conn.execute(
                "DELETE FROM config_tests WHERE id IN "
                "(SELECT id FROM config_tests ORDER BY created_at ASC, id ASC LIMIT ?)",
                (min(count - max_rows, batch),),
            )
            deleted += cur.rowcount or 0
    return deleted


def purge_grammar_tips(*, batch: int = 500, deadline: float | None = None) -> int:
    """Delete ALL grammar_tips rows in bounded batches (retired table).

    The table is retired (no prod callers of ``add_grammar_tip`` /
    ``recent_grammar_tip_titles`` — test-only). Safest path per T1 contract:
    rows only; the table shell and all code stay untouched. Each batch runs in
    its own short ``transaction()``. Stops batching at ``deadline``
    (monotonic) when set. Function only — no scheduler wiring.
    Returns the number of rows deleted.
    """
    deleted = 0
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            break
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM grammar_tips WHERE id IN ("
                "SELECT id FROM grammar_tips ORDER BY id ASC LIMIT ?)",
                (batch,),
            )
            n = cur.rowcount or 0
        deleted += n
        if n < batch:
            break
    return deleted
