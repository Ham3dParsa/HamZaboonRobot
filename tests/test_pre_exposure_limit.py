"""REF3-T3: pre-exposure LIMIT only; due-LIMIT forbidden.

- get_pre_first_exposure_words gains limit=None; LIMIT ? appended after
  byte-identical ORDER BY.
- assembly passes remaining = max_nodes - len(nodes); remaining<=0 issues
  zero Tier-2 queries.
- due_words_for_user stays unbounded (HIGH risk: _row_priority_key not
  SQL-reproducible + Kilo-254 net).
"""

import os
import sqlite3
import tempfile
from contextlib import contextmanager
from unittest.mock import patch

from services.db import schema as db_schema
import services.db as db


@contextmanager
def _temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old_db, old_schema_db = db.DB_PATH, db_schema.DB_PATH
    old_test_mode = os.environ.get("HAMZABAN_TEST_MODE")
    db.DB_PATH = path
    db_schema.DB_PATH = path
    os.environ["HAMZABAN_TEST_MODE"] = "1"
    try:
        db.init_db(path)
        yield path
    finally:
        if old_test_mode is None:
            os.environ.pop("HAMZABAN_TEST_MODE", None)
        else:
            os.environ["HAMZABAN_TEST_MODE"] = old_test_mode
        db.DB_PATH = old_db
        db_schema.DB_PATH = old_schema_db
        try:
            os.remove(path)
        except OSError:
            pass


def _capture_select(path, call_fn, marker):
    import services.db.words as words_mod

    captured = []
    orig_schema_get_conn = db_schema.get_conn
    orig_words_get_conn = words_mod.get_conn

    @contextmanager
    def tracing_get_conn(p=None):
        target = p if p is not None else path
        with orig_schema_get_conn(target) as conn:
            try:
                conn.set_trace_callback(lambda sql: captured.append(sql))
            except Exception:
                pass
            yield conn

    db_schema.get_conn = tracing_get_conn
    words_mod.get_conn = tracing_get_conn
    try:
        call_fn()
    finally:
        db_schema.get_conn = orig_schema_get_conn
        words_mod.get_conn = orig_words_get_conn

    for sql in captured:
        upper = sql.upper()
        if "SAVED_WORDS" in upper and "SELECT" in upper and marker in upper:
            return sql
    return None


def _seed_pre_exposure(n=10):
    import datetime

    now = db_schema._utc_now()
    with db_schema.transaction() as conn:
        conn.execute(
            "INSERT INTO users(user_id, username, target_lang, onboarded) "
            "VALUES (1,'t','en',1)"
        )
        for i in range(n):
            added = (now - datetime.timedelta(minutes=n - i)).isoformat()
            source = "manual" if i % 2 == 0 else "auto"
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, normalized_word, "
                "first_exposure_done, entry_source, added_at) "
                "VALUES (1,?,'en',?,0,?,?)",
                (f"w{i:02d}", f"w{i:02d}", source, added),
            )


def test_limit_returns_same_head_rows_as_unbounded():
    from services.db.words import get_pre_first_exposure_words

    with _temp_db_path():
        _seed_pre_exposure(10)
        full = [r["word"] for r in get_pre_first_exposure_words(1, "en")]
        assert len(full) == 10
        limited = [r["word"] for r in get_pre_first_exposure_words(1, "en", limit=2)]
        assert limited == full[:2]


def test_limit_sql_appends_limit_after_identical_order_by():
    from services.db.words import get_pre_first_exposure_words

    with _temp_db_path() as path:
        _seed_pre_exposure(10)
        base_sql = _capture_select(
            path, lambda: get_pre_first_exposure_words(1, "en"),
            "FIRST_EXPOSURE_DONE",
        )
        limited_sql = _capture_select(
            path, lambda: get_pre_first_exposure_words(1, "en", limit=2),
            "FIRST_EXPOSURE_DONE",
        )
        assert base_sql is not None and limited_sql is not None
        assert "LIMIT" not in base_sql.upper()
        # Trace callback inlines bound params, so LIMIT ? appears as LIMIT 2.
        import re

        assert re.search(r"LIMIT\s+2\s*$", limited_sql.upper()), limited_sql
        order_marker = "ORDER BY CASE WHEN ENTRY_SOURCE"
        assert order_marker in base_sql.upper()
        assert order_marker in limited_sql.upper()
        # Byte-identical prefix before LIMIT (modulo trailing whitespace).
        prefix = limited_sql.upper().split("LIMIT")[0].rstrip()
        assert prefix == base_sql.upper().rstrip(), (
            f"ORDER BY prefix changed: {base_sql!r} vs {limited_sql!r}"
        )


def test_session_passes_remaining_not_max_nodes():
    from services.session.assembly import build_session_list

    with _temp_db_path():
        _seed_pre_exposure(10)
        from services.db.words import get_pre_first_exposure_words

        expected = [r["word"] for r in get_pre_first_exposure_words(1, "en")][:2]
        nodes, tier3 = build_session_list(user_id=1, target_lang="en", max_nodes=2)
        assert [n.card_data["word"] for n in nodes] == expected
        assert all(n.source_tier == 2 for n in nodes)
        assert tier3 == {}


def test_session_remaining_zero_issues_no_tier2_query():
    from services.session import assembly as assembly_mod
    from services.session.assembly import build_session_list

    due_rows = [{"id": i, "word": f"due{i}"} for i in (1, 2)]
    with patch.object(
        assembly_mod, "due_words_for_user", return_value=due_rows
    ), patch.object(
        assembly_mod, "get_pre_first_exposure_words",
        side_effect=AssertionError("Tier-2 must not be queried when remaining=0"),
    ):
        nodes, tier3 = build_session_list(user_id=1, max_nodes=2)
        assert len(nodes) == 2
        assert all(n.source_tier == 1 for n in nodes)
        assert tier3 == {}


def test_due_path_has_no_limit_regression_lock():
    from services.db.words import due_words_for_user

    with _temp_db_path() as path:
        _seed_pre_exposure(3)
        real_sql = _capture_select(
            path, lambda: due_words_for_user(1, "en"), "FIRST_EXPOSURE_DONE"
        )
        assert real_sql is not None, "failed to capture due SQL via trace"
        assert "LIMIT" not in real_sql.upper(), (
            f"due path must stay unbounded, got: {real_sql!r}"
        )
