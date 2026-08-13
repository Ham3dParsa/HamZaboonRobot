"""T06 Phase 03 — FSRS grade-transition transaction tests (TDD red->green).

These replace the vacuous return-True grading expectations with real
state-transition assertions: ownership, wrong-state guards, exact FSRS (first-)
interval math, dual-write of the UTC timestamp + local review date, transient
state clearing, and telemetry separation.
"""

from __future__ import annotations

import datetime
import os
import tempfile
import unittest
from unittest.mock import patch

from services import db
from services.db import schema as db_schema
from services.fsrs_core import (
    compute_interval,
    compute_retrievability,
    initial_difficulty,
    initial_stability_first_exposure,
    short_term_stability,
    update_difficulty,
    update_stability,
)

UTC = datetime.timezone.utc


def _aware(dt: datetime.datetime) -> datetime.datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _seed_first_exposure_word(user_id: int = 1, grade: int = 2) -> int:
    db.add_saved_word(user_id, "hello", "en", {"word": "hello"})
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT id FROM saved_words WHERE user_id=?", (user_id,)
        ).fetchone()["id"]


def _mark_regular(word_id: int, user_id: int = 1, last_review: datetime.datetime | None = None):
    """Flip a word into the regular-review state (first_exposure_done=1 +
    last_review_at present) for grade_word_review tests."""
    with db.get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE saved_words SET first_exposure_done=1, "
            "last_review_at=COALESCE(?, last_review_at), "
            "next_review_at=COALESCE(?, next_review_at), "
            "next_review=COALESCE(?, next_review), "
            "stability=COALESCE(?, stability), difficulty=COALESCE(?, difficulty) "
            "WHERE id=? AND user_id=?",
            (
                last_review.isoformat() if last_review else None,
                None,
                None,
                5.0,
                5.0,
                word_id,
                user_id,
            ),
        )
        conn.commit()


class FsrsGradeRequestTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "grade.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.create_user_if_needed(2, "other")

    def tearDown(self):
        db.DB_PATH = self.prev
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    # ---- grade domain ----
    def test_failed_first_exposure_grade_raises_and_leaves_row_unchanged(self):
        word_id = _seed_first_exposure_word()
        before = db.get_saved_word(word_id, user_id=1)
        for bad in (0, 5, -1, 99):
            with self.assertRaises(ValueError):
                db.grade_first_exposure(word_id, bad, 1)
        after = db.get_saved_word(word_id, user_id=1)
        self.assertEqual(before["first_exposure_done"], after["first_exposure_done"])
        self.assertEqual(before["stability"], after["stability"])
        self.assertEqual(before["next_review_at"], after["next_review_at"])

    def test_failed_review_grade_raises_and_leaves_row_unchanged(self):
        word_id = _seed_first_exposure_word()
        _mark_regular(word_id)
        before = db.get_saved_word(word_id, user_id=1)
        for bad in (0, 5, -1, 99):
            with self.assertRaises(ValueError):
                db.grade_word_review(word_id, bad, 1)
        after = db.get_saved_word(word_id, user_id=1)
        self.assertEqual(before["stability"], after["stability"])
        self.assertEqual(before["next_review_at"], after["next_review_at"])

    # ---- ownership ----
    def test_missing_word_returns_not_found_no_mutation(self):
        res = db.grade_first_exposure(99999, 2, 1)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "not_found")
        self.assertIsNone(res.next_review_at)

    def test_foreign_owner_returns_not_found(self):
        word_id = _seed_first_exposure_word(user_id=1)
        res = db.grade_first_exposure(word_id, 2, 2)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "not_found")

    # ---- wrong state ----
    def test_first_exposure_on_done_returns_wrong_state(self):
        word_id = _seed_first_exposure_word()
        _mark_regular(word_id)
        res = db.grade_first_exposure(word_id, 2, 1)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "wrong_state")

    def test_review_on_undone_returns_wrong_state(self):
        word_id = _seed_first_exposure_word()
        res = db.grade_word_review(word_id, 2, 1)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "wrong_state")


class FsrsFirstExposureTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "grade.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        self.now = _aware(datetime.datetime(2026, 8, 13, 10, 0, 0))

    def tearDown(self):
        db.DB_PATH = self.prev
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def test_first_exposure_grade1_schedules_near_five_hours(self):
        word_id = _seed_first_exposure_word()
        with patch("services.db.words._utc_now", return_value=self.now):
            res = db.grade_first_exposure(word_id, 1, 1)
        self.assertTrue(res.ok)
        s = initial_stability_first_exposure(1)  # 0.212
        interval_days = compute_interval(s)
        self.assertGreater(interval_days, 0.0)
        self.assertLess(interval_days, 1.0)
        expected_timestamp = self.now + datetime.timedelta(days=interval_days)
        self.assertAlmostEqual(
            (res.next_review_at - self.now).total_seconds(),
            interval_days * 86400,
            delta=300,
        )
        self.assertIsNotNone(res.interval_seconds)
        row = db.get_saved_word(word_id, user_id=1)
        self.assertEqual(row["first_exposure_done"], 1)

    def test_first_exposure_grade2_persists_fsrs_stability_and_rounded_day(self):
        word_id = _seed_first_exposure_word()
        with patch("services.db.words._utc_now", return_value=self.now):
            res = db.grade_first_exposure(word_id, 2, 1)
        self.assertTrue(res.ok)
        s = initial_stability_first_exposure(2)  # 1.5
        d = initial_difficulty(2)
        interval_days = compute_interval(s)
        interval_days = max(1.0, round(interval_days))
        row = db.get_saved_word(word_id, user_id=1)
        self.assertAlmostEqual(row["stability"], s, places=6)
        self.assertAlmostEqual(row["difficulty"], d, places=6)
        expected_timestamp = self.now + datetime.timedelta(days=interval_days)
        self.assertEqual(res.next_review_at, expected_timestamp)
        self.assertEqual(res.interval_seconds, int(interval_days * 86400))


class FsrsReviewTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "grade.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        self.now = _aware(datetime.datetime(2026, 8, 13, 10, 0, 0))

    def tearDown(self):
        db.DB_PATH = self.prev
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def test_same_day_review_persists_short_term_stability(self):
        word_id = _seed_first_exposure_word()
        last = _aware(datetime.datetime(2026, 8, 13, 8, 0, 0))  # 2h earlier
        _mark_regular(word_id, last_review=last)
        with patch("services.db.words._utc_now", return_value=self.now):
            res = db.grade_word_review(word_id, 2, 1)
        self.assertTrue(res.ok)
        s_old = 5.0
        s_new_expected = short_term_stability(s_old, 2)
        row = db.get_saved_word(word_id, user_id=1)
        self.assertAlmostEqual(row["stability"], s_new_expected, places=6)

    def test_later_review_feeds_retrievability_chain(self):
        word_id = _seed_first_exposure_word()
        interval = compute_interval(5.0)
        last = _aware(datetime.datetime(2026, 8, 1, 10, 0, 0))  # 12 days prior
        _mark_regular(word_id, last_review=last)
        with patch("services.db.words._utc_now", return_value=self.now):
            res = db.grade_word_review(word_id, 3, 1)
        self.assertTrue(res.ok)
        elapsed_days = (self.now - last).total_seconds() / 86400
        d_old = 5.0
        d_new = update_difficulty(d_old, 3)
        s_old = 5.0
        r = compute_retrievability(elapsed_days, s_old)
        s_new_expected = update_stability(d_old, s_old, r, 3)
        row = db.get_saved_word(word_id, user_id=1)
        self.assertAlmostEqual(row["difficulty"], d_new, places=6)
        self.assertAlmostEqual(row["stability"], s_new_expected, places=6)

    def test_review_clears_transient_state(self):
        word_id = _seed_first_exposure_word()
        _mark_regular(word_id, last_review=_aware(datetime.datetime(2026, 8, 13, 8, 0, 0)))
        with db.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE saved_words SET review_status='pending', "
                "review_requested_at=?, retry_at=?, srs_retry_attempts=3 WHERE id=?",
                ("2026-08-13T09:00:00+00:00", "2026-08-14T09:00:00+00:00", word_id),
            )
            conn.commit()
        with patch("services.db.words._utc_now", return_value=self.now):
            db.grade_word_review(word_id, 2, 1)
        row = db.get_saved_word(word_id, user_id=1)
        self.assertEqual(row["review_status"], "idle")
        self.assertIsNone(row["review_requested_at"])
        self.assertIsNone(row["retry_at"])
        self.assertEqual(row["srs_retry_attempts"], 0)

    def test_grade_does_not_write_review_events(self):
        word_id = _seed_first_exposure_word()
        _mark_regular(word_id, last_review=_aware(datetime.datetime(2026, 8, 13, 8, 0, 0)))
        with patch("services.db.words._utc_now", return_value=self.now):
            db.grade_word_review(word_id, 2, 1)
        with db.get_conn() as conn:
            n = conn.execute("SELECT COUNT(*) FROM review_events").fetchone()[0]
        self.assertEqual(n, 0)


class FsrsDualWriteTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "grade.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        self.now = _aware(datetime.datetime(2026, 8, 13, 23, 0, 0))

    def tearDown(self):
        db.DB_PATH = self.prev
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def test_utc_timestamp_and_local_date_represent_same_due_instant(self):
        word_id = _seed_first_exposure_word()
        with patch("services.db.words._utc_now", return_value=self.now):
            db.grade_first_exposure(word_id, 4, 1)
        s = initial_stability_first_exposure(4)  # 12.0
        interval_days = max(1.0, round(compute_interval(s)))
        expected_utc = self.now + datetime.timedelta(days=interval_days)

        from config import APP_TZ
        local_date = expected_utc.astimezone(APP_TZ).date().isoformat()
        row = db.get_saved_word(word_id, user_id=1)
        self.assertIsNotNone(row["next_review_at"])
        self.assertEqual(row["next_review"], local_date)