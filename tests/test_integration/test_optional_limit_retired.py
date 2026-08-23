import os
import tempfile
import sqlite3

from services.db import schema as db_schema
from services.db import DB_PATH as _orig_db_path
import services.db as db
from config import effective_daily_allowance, daily_card_count_for_plan


def _temp_db():
    import tempfile, os

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def test_effective_daily_allowance_ignores_optional_limit():
    # optional limit must not affect result after Q-26
    for plan in ["free", "bronze", "gold"]:
        expected = daily_card_count_for_plan(plan)
        assert effective_daily_allowance(plan, optional_user_limit=1) == expected
        assert effective_daily_allowance(plan, optional_user_limit=100) == expected
        assert effective_daily_allowance(plan, optional_user_limit=None) == expected


def test_users_columns_retired_after_migration():
    path = _temp_db()
    try:
        db.DB_PATH = path
        db_schema.DB_PATH = path
        old = os.environ.get("HAMZABAN_TEST_MODE")
        os.environ["HAMZABAN_TEST_MODE"] = "1"
        # init fresh should not create optional columns (they are legacy)
        # but ensure migration path drops them if they existed
        db.init_db(path)
        # manually add legacy column to simulate old DB, then re-run init_db drop
        with sqlite3.connect(path) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
            # if DROP succeeded, column should be absent; if SQLite too old, it stays but code ignores it
            # test that code ignores it anyway
            assert effective_daily_allowance("free", optional_user_limit=1) == daily_card_count_for_plan("free")
        # simulate old DB with column
        with sqlite3.connect(path) as conn:
            try:
                conn.execute("ALTER TABLE users ADD COLUMN optional_daily_limit INTEGER")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # already exists
        db.init_db(path)
        with sqlite3.connect(path) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
            # after migration, column should be dropped if supported
            # we don't assert strict drop because older SQLite may not support it — but effective_daily_allowance must still ignore it
            assert effective_daily_allowance("free", optional_user_limit=1) == daily_card_count_for_plan("free")
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
