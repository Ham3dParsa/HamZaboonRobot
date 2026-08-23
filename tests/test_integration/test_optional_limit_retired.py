import contextlib
import os
import sqlite3
import tempfile

import pytest

import services.db as db
from config import daily_card_count_for_plan, effective_daily_allowance
from services.db import DB_PATH as _orig_db_path
from services.db import schema as db_schema


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _cleanup_db(path: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


def test_effective_daily_allowance_new_signature():
    # Q-26: optional_user_limit dropped — quota is single-sourced from plans table
    for plan in ["free", "bronze", "gold"]:
        expected = daily_card_count_for_plan(plan)
        assert effective_daily_allowance(plan) == expected
        assert effective_daily_allowance(plan, bypass_limits=False) == expected


def test_effective_daily_allowance_rejects_optional_user_limit():
    # Old param must not be accepted silently — should raise TypeError
    with pytest.raises(TypeError):
        effective_daily_allowance("free", optional_user_limit=1)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        effective_daily_allowance("free", optional_user_limit=None)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        effective_daily_allowance("free", optional_user_limit=100)  # type: ignore[call-arg]


def test_users_columns_retired_after_migration():
    path = _temp_db()
    old = os.environ.get("HAMZABAN_TEST_MODE")
    try:
        db.DB_PATH = path
        db_schema.DB_PATH = path
        os.environ["HAMZABAN_TEST_MODE"] = "1"
        # init fresh should not create optional columns (they are legacy)
        # but ensure migration path drops them if they existed
        db.init_db(path)
        # if DROP succeeded, column should be absent; if SQLite too old, it stays but code ignores it
        # test that code ignores it anyway
        with contextlib.closing(sqlite3.connect(path)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
            assert "optional_daily_limit" not in cols
            assert "preferred_delivery_minute" not in cols
            assert "active_window_start_minute" not in cols
            assert "active_window_end_minute" not in cols
            assert effective_daily_allowance("free") == daily_card_count_for_plan("free")
        # simulate old DB with column
        with contextlib.closing(sqlite3.connect(path)) as conn:
            try:
                conn.execute("ALTER TABLE users ADD COLUMN optional_daily_limit INTEGER")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # already exists
        db.init_db(path)
        with contextlib.closing(sqlite3.connect(path)) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
            assert "optional_daily_limit" not in cols
            # effective_daily_allowance must use plan quota
            assert effective_daily_allowance("free") == daily_card_count_for_plan("free")
    finally:
        if old is None:
            os.environ.pop("HAMZABAN_TEST_MODE", None)
        else:
            os.environ["HAMZABAN_TEST_MODE"] = old
        db.DB_PATH = _orig_db_path
        db_schema.DB_PATH = _orig_db_path
        _cleanup_db(path)
