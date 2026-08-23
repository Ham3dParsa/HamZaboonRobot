import os
import tempfile
import sqlite3
from contextlib import contextmanager

from services.db import schema as db_schema
from services.db import DB_PATH as _orig_db_path
import services.db as db


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _capture_due_sql(path, user_id=1, lang="en"):
    """Capture the actual SQL issued by due_words_for_user via trace callback.

    Patches both schema and words get_conn so the trace is set on the exact
    connection used by due_words_for_user. Returns the SELECT statement text.
    """
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
        from services.db.words import due_words_for_user

        due_words_for_user(user_id, lang)
    finally:
        db_schema.get_conn = orig_schema_get_conn
        words_mod.get_conn = orig_words_get_conn

    for sql in captured:
        # trace sees every statement; pick the due scan
        if "saved_words" in sql and "SELECT" in sql.upper() and "first_exposure_done" in sql:
            return sql
    return None


def test_due_index_exists_after_init_db():
    path = _temp_db()
    try:
        db.DB_PATH = path
        db_schema.DB_PATH = path
        old = os.environ.get("HAMZABAN_TEST_MODE")
        os.environ["HAMZABAN_TEST_MODE"] = "1"
        db.init_db(path)
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='saved_words_due_idx'"
            ).fetchone()
            assert row is not None, "saved_words_due_idx missing"
            # check columns via sql
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='saved_words_due_idx'"
            ).fetchone()
            sql = row[0] if row else ""
            assert "user_id" in sql and "next_review_at" in sql
        # EXPLAIN QUERY PLAN for the real due_words_for_user SQL captured via trace,
        # so the test cannot drift from the production query.
        real_sql = _capture_due_sql(path)
        assert real_sql is not None, "failed to capture due_words_for_user SQL via trace"
        # Build dummy params matching placeholder count
        ph_count = real_sql.count("?")
        # due query has user_id, lang, bound (and possibly more); supply plausible dummies
        dummies = []
        for i in range(ph_count):
            if i == 0:
                dummies.append(1)
            elif i == 1:
                dummies.append("en")
            else:
                dummies.append("2099-01-01T00:00:00+00:00")
        with sqlite3.connect(path) as conn:
            plan = conn.execute(f"EXPLAIN QUERY PLAN {real_sql}", tuple(dummies)).fetchall()
            text = " ".join(r[3] for r in plan)
            assert "saved_words_due_idx" in text, f"plan should use saved_words_due_idx, got: {text} sql={real_sql!r}"
    finally:
        if old is None:
            os.environ.pop("HAMZABAN_TEST_MODE", None)
        else:
            os.environ["HAMZABAN_TEST_MODE"] = old
        db.DB_PATH = _orig_db_path
        db_schema.DB_PATH = _orig_db_path
        try:
            os.remove(path)
        except OSError:
            pass


def test_due_words_for_user_still_correct():
    path = _temp_db()
    try:
        db.DB_PATH = path
        db_schema.DB_PATH = path
        old = os.environ.get("HAMZABAN_TEST_MODE")
        os.environ["HAMZABAN_TEST_MODE"] = "1"
        db.init_db(path)
        # create user and due words via direct inserts
        import datetime

        now = db_schema._utc_now()
        past = (now - datetime.timedelta(days=1)).isoformat()
        future = (now + datetime.timedelta(days=5)).isoformat()
        with db_schema.transaction(path) as conn:
            conn.execute(
                "INSERT INTO users(user_id, username, target_lang, onboarded) VALUES (1,'t','en',1)"
            )
            # due word: first_exposure_done=1, last_review_at set, next_review_at past
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, normalized_word, first_exposure_done, stability, difficulty, last_review_at, next_review_at, next_review, review_status) VALUES (1,'hello','en','hello',1, 2.0, 5.0, ?, ?, ?, 'idle')",
                (past, past, past[:10]),
            )
            # not due: future
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, normalized_word, first_exposure_done, stability, difficulty, last_review_at, next_review_at, next_review, review_status) VALUES (1,'future','en','future',1, 2.0, 5.0, ?, ?, ?, 'idle')",
                (past, future, future[:10]),
            )
        from services.db.words import due_words_for_user

        # need to ensure due_words_for_user uses the temp DB path — it uses get_conn which reads DB_PATH live
        due = due_words_for_user(1, "en")
        words = [r["word"] for r in due]
        assert "hello" in words
        assert "future" not in words
    finally:
        if old is None:
            os.environ.pop("HAMZABAN_TEST_MODE", None)
        else:
            os.environ["HAMZABAN_TEST_MODE"] = old
        db.DB_PATH = _orig_db_path
        db_schema.DB_PATH = _orig_db_path
        try:
            os.remove(path)
        except OSError:
            pass


def test_due_words_malformed_iso_fallback_is_due():
    """Regression for Kilo 254: ISO-looking but invalid next_review_at must not be dropped.

    A future-lexical malformed value like "2099-13-99T99:99:99" would be >
    bound and previously dropped by NOT LIKE; Python fallback via legacy
    next_review should make it due and it must be returned.
    """
    path = _temp_db()
    try:
        db.DB_PATH = path
        db_schema.DB_PATH = path
        old = os.environ.get("HAMZABAN_TEST_MODE")
        os.environ["HAMZABAN_TEST_MODE"] = "1"
        db.init_db(path)
        import datetime

        now = db_schema._utc_now()
        past_iso = (now - datetime.timedelta(days=1)).isoformat()
        today_str = db_schema._today().isoformat()
        # ISO-looking invalid, lexically future (> bound)
        malformed_future = "2099-13-99T99:99:99"
        # Another malformed past-lexical variant
        malformed_past = "2025-13-99T99:99:99"
        with db_schema.transaction(path) as conn:
            conn.execute(
                "INSERT INTO users(user_id, username, target_lang, onboarded) VALUES (1,'t','en',1)"
            )
            # due via fallback: malformed next_review_at + next_review == today
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, normalized_word, first_exposure_done, stability, difficulty, last_review_at, next_review_at, next_review, review_status) VALUES (1,'bad_future','en','bad_future',1, 2.0, 5.0, ?, ?, ?, 'idle')",
                (past_iso, malformed_future, today_str),
            )
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, normalized_word, first_exposure_done, stability, difficulty, last_review_at, next_review_at, next_review, review_status) VALUES (1,'bad_past','en','bad_past',1, 2.0, 5.0, ?, ?, ?, 'idle')",
                (past_iso, malformed_past, today_str),
            )
            # not due: valid future next_review_at
            future = (now + datetime.timedelta(days=5)).isoformat()
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, normalized_word, first_exposure_done, stability, difficulty, last_review_at, next_review_at, next_review, review_status) VALUES (1,'good_future','en','good_future',1, 2.0, 5.0, ?, ?, ?, 'idle')",
                (past_iso, future, future[:10]),
            )
        from services.db.words import due_words_for_user

        due = due_words_for_user(1, "en")
        words = [r["word"] for r in due]
        assert "bad_future" in words, "malformed future-lexical ISO should be due via next_review fallback"
        assert "bad_past" in words, "malformed past-lexical ISO should be due"
        assert "good_future" not in words
    finally:
        if old is None:
            os.environ.pop("HAMZABAN_TEST_MODE", None)
        else:
            os.environ["HAMZABAN_TEST_MODE"] = old
        db.DB_PATH = _orig_db_path
        db_schema.DB_PATH = _orig_db_path
        try:
            os.remove(path)
        except OSError:
            pass
