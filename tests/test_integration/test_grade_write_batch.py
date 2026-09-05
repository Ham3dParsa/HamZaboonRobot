"""T1 (F1+F3): grade tap writes grade + review_event + streak atomically.

RED phase: grade_word_review/grade_first_exposure do not yet accept the
batched event/streak kwargs, and the review_events filter/order index does not
exist — these tests must fail before the fix and pass after.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from services import db
from services.db import schema as db_schema


def _seed_user(uid: int = 1):
    db.create_user_if_needed(uid, "learner")


def _add_word(uid: int, word: str) -> int:
    db.add_saved_word(uid, word, "en", {"word": word})
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT id FROM saved_words WHERE user_id=? AND word=?",
            (uid, word),
        ).fetchone()["id"]


def _mark_review_state(word_id: int, uid: int):
    past = (db_schema._utc_now() - datetime.timedelta(days=2)).isoformat()
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE saved_words SET first_exposure_done=1, last_review_at=?, "
            "next_review_at=?, stability=5.0, difficulty=5.0 "
            "WHERE id=? AND user_id=?",
            (past, past, word_id, uid),
        )
        conn.commit()


def _events(uid: int, word_id: int) -> int:
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM review_events WHERE user_id=? AND word_id=?",
            (uid, word_id),
        ).fetchone()[0]


def _streak(uid: int) -> int:
    return db.get_user(uid)["streak"] or 0


class GradeWriteBatchTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new
        db_schema.DB_PATH = new
        db.init_db()
        _seed_user(1)

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def test_review_batch_writes_grade_event_streak_atomically(self):
        wid = _add_word(1, "alpha")
        _mark_review_state(wid, 1)
        before_streak = _streak(1)
        res = db.grade_word_review(
            wid, 3, 1,
            grade_source="direct_button",
            raw_signal='{"button_value": 3}',
            response_time_ms=1200,
            with_streak=True,
        )
        self.assertTrue(res.ok)
        row = db.get_saved_word(wid, 1)
        self.assertEqual(row["first_exposure_done"], 1)
        self.assertIsNotNone(row["last_review_at"])
        self.assertEqual(_events(1, wid), 1)
        with db.get_conn() as conn:
            ev = conn.execute(
                "SELECT grade, activity_type, grade_source, response_time_ms "
                "FROM review_events WHERE user_id=1 AND word_id=?",
                (wid,),
            ).fetchone()
        self.assertEqual(ev["grade"], 3)
        self.assertEqual(ev["activity_type"], "srs_review")
        self.assertEqual(ev["grade_source"], "direct_button")
        self.assertEqual(ev["response_time_ms"], 1200)
        self.assertGreaterEqual(_streak(1), before_streak)
        self.assertTrue(db.is_word_graded(1, wid, "srs_review"))

    def test_first_exposure_batch_writes_all_atomically(self):
        wid = _add_word(1, "beta")
        res = db.grade_first_exposure(
            wid, 4, 1,
            grade_source="direct_button",
            raw_signal='{"button_value": 4}',
            response_time_ms=None,
            with_streak=True,
        )
        self.assertTrue(res.ok)
        row = db.get_saved_word(wid, 1)
        self.assertEqual(row["first_exposure_done"], 1)
        self.assertEqual(_events(1, wid), 1)
        with db.get_conn() as conn:
            ev = conn.execute(
                "SELECT grade, activity_type FROM review_events "
                "WHERE user_id=1 AND word_id=?",
                (wid,),
            ).fetchone()
        self.assertEqual(ev["grade"], 4)
        self.assertEqual(ev["activity_type"], "first_exposure")
        self.assertTrue(db.is_word_graded(1, wid, "first_exposure"))

    def test_batch_rolls_back_when_event_insert_fails(self):
        wid = _add_word(1, "gamma")
        _mark_review_state(wid, 1)
        before = db.get_saved_word(wid, 1)
        with mock.patch(
            "services.db.words.insert_review_event",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                db.grade_word_review(
                    wid, 3, 1,
                    grade_source="direct_button",
                    raw_signal="{}",
                    response_time_ms=5,
                    with_streak=True,
                )
        after = db.get_saved_word(wid, 1)
        self.assertEqual(after["stability"], before["stability"])
        self.assertEqual(after["last_review_at"], before["last_review_at"])
        self.assertEqual(_events(1, wid), 0)
        self.assertFalse(db.is_word_graded(1, wid, "srs_review"))

    def test_batch_rolls_back_when_streak_fails(self):
        wid = _add_word(1, "delta")
        with mock.patch(
            "services.db.words.touch_streak_in_txn",
            side_effect=RuntimeError("streak-boom"),
        ):
            with self.assertRaises(RuntimeError):
                db.grade_first_exposure(
                    wid, 3, 1,
                    grade_source="direct_button",
                    raw_signal="{}",
                    response_time_ms=None,
                    with_streak=True,
                )
        row = db.get_saved_word(wid, 1)
        self.assertEqual(row["first_exposure_done"], 0)
        self.assertEqual(_events(1, wid), 0)
        self.assertFalse(db.is_word_graded(1, wid, "first_exposure"))

    def test_backward_compat_no_event_no_streak(self):
        wid = _add_word(1, "epsilon")
        _mark_review_state(wid, 1)
        streak_before = _streak(1)
        res = db.grade_word_review(wid, 3, 1)
        self.assertTrue(res.ok)
        self.assertEqual(_events(1, wid), 0)
        self.assertEqual(_streak(1), streak_before)

    def test_touch_streak_in_txn_honors_explicit_today_iso_across_day_boundary(self):
        # A1: yesterday must derive from the resolved today value, not the
        # real clock — an explicit today_iso one day after last_active_date
        # continues the streak instead of resetting it to 1.
        explicit_today = "2026-08-10"
        yesterday = "2026-08-09"
        with db.transaction() as conn:
            conn.execute(
                "UPDATE users SET streak=5, last_active_date=? WHERE user_id=1",
                (yesterday,),
            )
            new_streak = db.touch_streak_in_txn(conn, 1, today_iso=explicit_today)
        self.assertEqual(new_streak, 6)
        row = db.get_user(1)
        self.assertEqual(row["streak"], 6)
        self.assertEqual(row["last_active_date"], explicit_today)
        # A gap day still resets even with an explicit today.
        with db.transaction() as conn:
            conn.execute(
                "UPDATE users SET streak=6, last_active_date=? WHERE user_id=1",
                ("2026-08-08",),
            )
            reset_streak = db.touch_streak_in_txn(conn, 1, today_iso=explicit_today)
        self.assertEqual(reset_streak, 1)

    def test_batched_tap_uses_single_transaction(self):
        wid = _add_word(1, "zeta")
        _mark_review_state(wid, 1)
        import services.db.words as words_mod

        real_transaction = words_mod.transaction
        calls = []

        from contextlib import contextmanager

        @contextmanager
        def counting(path=None):
            calls.append(1)
            with real_transaction(path) as conn:
                yield conn

        with mock.patch.object(words_mod, "transaction", counting):
            res = db.grade_word_review(
                wid, 3, 1,
                grade_source="direct_button",
                raw_signal="{}",
                response_time_ms=1,
                with_streak=True,
            )
        self.assertTrue(res.ok)
        self.assertEqual(len(calls), 1)

    def test_grade_paths_bump_lifetime_counters(self):
        """Regression: production grade calls must bump total_reviews/lapses.

        Calls the production grade_word_review / grade_first_exposure entry
        points (never a test helper) and asserts the per-card lifetime
        counters in saved_words actually incremented — grade 3 bumps only
        total_reviews, grade 1 bumps total_reviews + lapses. The legacy
        no-event path must leave counters untouched.
        """

        def _counters(wid: int):
            with db.get_conn() as conn:
                row = conn.execute(
                    "SELECT total_reviews, lapses FROM saved_words WHERE id=?",
                    (wid,),
                ).fetchone()
            return (row["total_reviews"] or 0, row["lapses"] or 0)

        # Regular review, recalled (grade 3): total+1, lapses unchanged.
        wid = _add_word(1, "theta")
        _mark_review_state(wid, 1)
        self.assertEqual(_counters(wid), (0, 0))
        res = db.grade_word_review(
            wid, 3, 1,
            grade_source="direct_button",
            raw_signal="{}",
            response_time_ms=10,
            with_streak=False,
        )
        self.assertTrue(res.ok)
        self.assertEqual(_counters(wid), (1, 0))
        # Same card, lapse (grade 1): total+1 AND lapses+1.
        res = db.grade_word_review(
            wid, 1, 1,
            grade_source="direct_button",
            raw_signal="{}",
            response_time_ms=10,
            with_streak=False,
        )
        self.assertTrue(res.ok)
        self.assertEqual(_counters(wid), (2, 1))
        # First exposure, lapse (grade 1): total+1 AND lapses+1.
        wid2 = _add_word(1, "iota")
        self.assertEqual(_counters(wid2), (0, 0))
        res = db.grade_first_exposure(
            wid2, 1, 1,
            grade_source="direct_button",
            raw_signal="{}",
            response_time_ms=None,
            with_streak=False,
        )
        self.assertTrue(res.ok)
        self.assertEqual(_counters(wid2), (1, 1))
        # Legacy grade-only path (no event): counters untouched.
        wid3 = _add_word(1, "kappa")
        _mark_review_state(wid3, 1)
        res = db.grade_word_review(wid3, 3, 1)
        self.assertTrue(res.ok)
        self.assertEqual(_counters(wid3), (0, 0))


class ReviewEventsFilterOrderIndexTests(unittest.TestCase):
    """F3: filter/order index on review_events(user_id, word_id, created_at)."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        self.fresh = os.path.join(self.tempdir.name, "fresh.sqlite")
        self.old = os.path.join(self.tempdir.name, "old.sqlite")

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _index_sql(self, path):
        conn = sqlite3.connect(path)
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='review_events_user_word_created_idx'"
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def test_fresh_db_has_covering_index(self):
        db.DB_PATH = self.fresh
        db_schema.DB_PATH = self.fresh
        db.init_db()
        sql = self._index_sql(self.fresh)
        self.assertIsNotNone(sql, "covering index missing on fresh DB")
        for col in ("user_id", "word_id", "created_at"):
            self.assertIn(col, sql)

    def test_old_shape_db_gains_index_on_migrate(self):
        conn = sqlite3.connect(self.old)
        try:
            conn.execute(
                "CREATE TABLE review_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "word_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
                "revealed_before_answer INTEGER NOT NULL DEFAULT 0, "
                "outcome TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                "INSERT INTO settings(key, value) "
                "VALUES ('fsrs_migration_done', '1')"
            )
            conn.execute(
                "INSERT INTO review_events(word_id, user_id, outcome, created_at) "
                "VALUES (1, 1, 'recalled', '2026-08-09T00:00:00+00:00')"
            )
            conn.commit()
        finally:
            conn.close()
        db.DB_PATH = self.old
        db_schema.DB_PATH = self.old
        db.init_db()
        sql = self._index_sql(self.old)
        self.assertIsNotNone(sql, "covering index missing after upgrade")
        for col in ("user_id", "word_id", "created_at"):
            self.assertIn(col, sql)
        conn = sqlite3.connect(self.old)
        try:
            n = conn.execute("SELECT COUNT(*) FROM review_events").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
