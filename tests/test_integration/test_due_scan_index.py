import os
import tempfile
import sqlite3

from services.db import schema as db_schema
from services.db import DB_PATH as _orig_db_path
import services.db as db


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


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
        # EXPLAIN QUERY PLAN for actual due_words_for_user query (with lang + next_review_at pre-filter)
        # Keep WHERE in sync with services/db/words.py due_words_for_user SQL pre-filter.
        with sqlite3.connect(path) as conn:
            plan = conn.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM saved_words WHERE user_id=? AND lang=? AND COALESCE(first_exposure_done,0)=1 AND COALESCE(review_status,'idle')!='pending' AND retry_at IS NULL AND (next_review_at IS NULL OR next_review_at <= ? OR next_review_at NOT LIKE '____-__-__T%')",
                (1, "en", "2099-01-01T00:00:00+00:00"),
            ).fetchall()
            text = " ".join(r[3] for r in plan)
            assert "saved_words_due_idx" in text, f"plan should use saved_words_due_idx, got: {text}"
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
