"""REF3-T1: pre-exposure covering index + due-scan non-regression guard.

Additive DDL only: ``saved_words(user_id, first_exposure_done, added_at)``
(LEAD-LOCKED column order). This top-level file is distinct from
``tests/test_integration/test_due_scan_index.py`` (due-index EXPLAIN +
correctness); here we assert the pre-exposure path is index-backed and the
due path stays LIMIT-free.
"""

import os
import sqlite3
import tempfile
from contextlib import contextmanager

from services.db import schema as db_schema
from services.db import DB_PATH as _orig_db_path
import services.db as db

PRE_EXPOSURE_INDEX = "saved_words_pre_exposure_idx"


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


@contextmanager
def _temp_db_path():
    path = _temp_db()
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
    """Capture the real SELECT issued by a production read via trace callback."""
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


def _explain_uses_index(path, sql, params, index_name):
    with sqlite3.connect(path) as conn:
        plan = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    text = " ".join(r[3] for r in plan)
    assert index_name in text, (
        f"plan should use {index_name}, got: {text} sql={sql!r}"
    )
    return text


def _seed_words(conn, now_iso, past_iso):
    conn.execute(
        "INSERT INTO users(user_id, username, target_lang, onboarded) "
        "VALUES (1,'t','en',1)"
    )
    conn.execute(
        "INSERT INTO saved_words(user_id, word, lang, normalized_word, "
        "first_exposure_done, entry_source, added_at) "
        "VALUES (1,'apple','en','apple',0,'manual',?)",
        (past_iso,),
    )
    conn.execute(
        "INSERT INTO saved_words(user_id, word, lang, normalized_word, "
        "first_exposure_done, entry_source, added_at) "
        "VALUES (1,'banana','en','banana',0,'auto',?)",
        (now_iso,),
    )
    conn.execute(
        "INSERT INTO saved_words(user_id, word, lang, normalized_word, "
        "first_exposure_done, stability, difficulty, last_review_at, "
        "next_review_at, next_review, review_status) "
        "VALUES (1,'cherry','en','cherry',1,2.0,5.0,?,?,?,'idle')",
        (past_iso, past_iso, past_iso[:10]),
    )


def test_pre_exposure_index_exists_after_init_db():
    with _temp_db_path() as path:
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                (PRE_EXPOSURE_INDEX,),
            ).fetchone()
        assert row is not None, f"{PRE_EXPOSURE_INDEX} missing after init_db"
        sql = row[0].upper()
        # LEAD-LOCKED column order: (user_id, first_exposure_done, added_at)
        uid_pos = sql.find("USER_ID")
        fed_pos = sql.find("FIRST_EXPOSURE_DONE")
        added_pos = sql.find("ADDED_AT")
        assert uid_pos != -1 and fed_pos != -1 and added_pos != -1, sql
        assert uid_pos < fed_pos < added_pos, f"wrong column order: {sql}"


def test_pre_exposure_query_uses_index():
    from services.db.words import get_pre_first_exposure_words

    with _temp_db_path() as path:
        real_sql = _capture_select(
            path,
            lambda: get_pre_first_exposure_words(1, "en"),
            "FIRST_EXPOSURE_DONE",
        )
        assert real_sql is not None, "failed to capture pre-exposure SQL via trace"
        ph_count = real_sql.count("?")
        dummies = [1, "en"][:ph_count] + ["x"] * max(0, ph_count - 2)
        _explain_uses_index(path, real_sql, tuple(dummies), PRE_EXPOSURE_INDEX)


def test_due_scan_has_no_limit():
    from services.db.words import due_words_for_user

    with _temp_db_path() as path:
        real_sql = _capture_select(
            path, lambda: due_words_for_user(1, "en"), "FIRST_EXPOSURE_DONE"
        )
        assert real_sql is not None, "failed to capture due SQL via trace"
        assert "LIMIT" not in real_sql.upper(), (
            f"due path must stay unbounded, got: {real_sql!r}"
        )


def test_init_db_idempotent_and_rowsets_identical():
    import datetime

    from services.db.words import due_words_for_user, get_pre_first_exposure_words

    with _temp_db_path() as path:
        now = db_schema._utc_now()
        past_iso = (now - datetime.timedelta(days=1)).isoformat()
        now_iso = now.isoformat()
        with db_schema.transaction(path) as conn:
            _seed_words(conn, now_iso, past_iso)

        def snapshot():
            pre = [
                (r["word"], r["first_exposure_done"]) for r in get_pre_first_exposure_words(1, "en")
            ]
            due = [r["word"] for r in due_words_for_user(1, "en")]
            return pre, due

        before = snapshot()
        db.init_db(path)  # second init_db must be a no-op
        after = snapshot()
        assert before == after, f"row sets changed across re-init: {before} vs {after}"

        with sqlite3.connect(path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?",
                (PRE_EXPOSURE_INDEX,),
            ).fetchone()[0]
        assert count == 1, f"expected exactly one {PRE_EXPOSURE_INDEX}, got {count}"
        assert [w for w, _ in after[0]] == ["apple", "banana"]
        assert "cherry" in after[1]


def test_upgraded_db_gains_index_with_rows_intact():
    import datetime

    from services.db.words import get_pre_first_exposure_words

    with _temp_db_path() as path:
        now = db_schema._utc_now()
        past_iso = (now - datetime.timedelta(days=1)).isoformat()
        with db_schema.transaction(path) as conn:
            _seed_words(conn, now.isoformat(), past_iso)
        # Simulate a pre-T1 database: drop the new index, keep the rows.
        with sqlite3.connect(path) as conn:
            conn.execute(f"DROP INDEX IF EXISTS {PRE_EXPOSURE_INDEX}")
            missing = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?",
                (PRE_EXPOSURE_INDEX,),
            ).fetchone()[0]
            assert missing == 0
        db.init_db(path)  # upgrade re-run must restore the index
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (PRE_EXPOSURE_INDEX,),
            ).fetchone()
            assert row is not None, "upgrade did not restore pre-exposure index"
        words = [r["word"] for r in get_pre_first_exposure_words(1, "en")]
        assert words == ["apple", "banana"]
