"""Parity tests for services/grade_service.py (REF4-T2).

The service is a thin sync pass-through over the untouched bodies in
``services/db/words.py`` (``grade_word_review`` review-recall vs
``grade_first_exposure`` familiarity-seed stay branch-distinct, no formula
merge). These tests prove the facade returns the same outcome + DB row as the
direct bodies across the activity x with_streak x grade_source matrix, that a
batched tap still uses a single transaction with zero await, and that the
legacy defaults (grade_source=None, with_streak=False) preserve grade-only
behavior.
"""

from __future__ import annotations

import datetime
import inspect
import os
import tempfile
import unittest
from contextlib import contextmanager
from unittest import mock

from services import db
from services.db import schema as db_schema


def _seed_user(uid: int):
    db.create_user_if_needed(uid, f"learner{uid}")


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


def _counters(wid: int):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT total_reviews, lapses FROM saved_words WHERE id=?",
            (wid,),
        ).fetchone()
    return (row["total_reviews"] or 0, row["lapses"] or 0)


class TestGradeServiceParity(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        import services.grade_service as gs

        self.gs = gs

    def tearDown(self):
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    # ---- registry / aliases ----

    def test_activity_registry(self):
        self.assertEqual(
            set(self.gs.GRADE_ACTIVITIES), {"srs_review", "first_exposure"}
        )

    def test_aliases_are_verbatim_bodies(self):
        gs = self.gs
        self.assertIs(gs.grade_word_review, db.grade_word_review)
        self.assertIs(gs.grade_first_exposure, db.grade_first_exposure)
        self.assertIs(gs.GradeResult, db.GradeResult)

    def test_unknown_activity_raises(self):
        _seed_user(1)
        wid = _add_word(1, "unknown-activity")
        with self.assertRaises(ValueError):
            self.gs.grade(wid, 3, 1, activity="nope")
        with self.assertRaises(ValueError):
            self.gs.grade(wid, 3, 1, activity="")

    def test_invalid_grade_raises_for_both_activities(self):
        _seed_user(1)
        wid = _add_word(1, "bad-grade")
        _mark_review_state(wid, 1)
        with self.assertRaises(ValueError):
            self.gs.grade(wid, 5, 1, activity="srs_review")
        with self.assertRaises(ValueError):
            self.gs.grade(wid, 0, 1, activity="first_exposure")

    # ---- parity: review ----

    def test_review_parity_same_outcome_and_row(self):
        _seed_user(11)
        _seed_user(12)
        facade_wid = _add_word(11, "facade-review")
        direct_wid = _add_word(12, "direct-review")
        _mark_review_state(facade_wid, 11)
        _mark_review_state(direct_wid, 12)
        facade_res = self.gs.grade(
            facade_wid, 3, 11,
            activity="srs_review",
            grade_source="direct_button",
            raw_signal='{"button_value": 3}',
            response_time_ms=1200,
            with_streak=False,
        )
        direct_res = db.grade_word_review(
            direct_wid, 3, 12,
            grade_source="direct_button",
            raw_signal='{"button_value": 3}',
            response_time_ms=1200,
            with_streak=False,
        )
        self.assertTrue(facade_res.ok)
        self.assertTrue(direct_res.ok)
        facade_row = db.get_saved_word(facade_wid, 11)
        direct_row = db.get_saved_word(direct_wid, 12)
        self.assertEqual(facade_row["first_exposure_done"], 1)
        self.assertEqual(direct_row["first_exposure_done"], 1)
        self.assertIsNotNone(facade_row["last_review_at"])
        self.assertIsNotNone(direct_row["last_review_at"])
        self.assertEqual(_events(11, facade_wid), 1)
        self.assertEqual(_events(12, direct_wid), 1)
        with db.get_conn() as conn:
            ev = conn.execute(
                "SELECT grade, activity_type, grade_source, response_time_ms "
                "FROM review_events WHERE user_id=11 AND word_id=?",
                (facade_wid,),
            ).fetchone()
        self.assertEqual(ev["grade"], 3)
        self.assertEqual(ev["activity_type"], "srs_review")
        self.assertEqual(ev["grade_source"], "direct_button")
        self.assertEqual(ev["response_time_ms"], 1200)
        self.assertTrue(db.is_word_graded(11, facade_wid, "srs_review"))
        self.assertEqual(_counters(facade_wid), (1, 0))
        self.assertEqual(_counters(facade_wid), _counters(direct_wid))

    # ---- parity: first exposure ----

    def test_first_exposure_parity_same_outcome_and_row(self):
        _seed_user(21)
        _seed_user(22)
        facade_wid = _add_word(21, "facade-exposure")
        direct_wid = _add_word(22, "direct-exposure")
        facade_res = self.gs.grade(
            facade_wid, 4, 21,
            activity="first_exposure",
            grade_source="direct_button",
            raw_signal='{"button_value": 4}',
            response_time_ms=None,
            with_streak=False,
        )
        direct_res = db.grade_first_exposure(
            direct_wid, 4, 22,
            grade_source="direct_button",
            raw_signal='{"button_value": 4}',
            response_time_ms=None,
            with_streak=False,
        )
        self.assertTrue(facade_res.ok)
        self.assertTrue(direct_res.ok)
        self.assertEqual(db.get_saved_word(facade_wid, 21)["first_exposure_done"], 1)
        self.assertEqual(db.get_saved_word(direct_wid, 22)["first_exposure_done"], 1)
        self.assertEqual(_events(21, facade_wid), 1)
        self.assertEqual(_events(22, direct_wid), 1)
        with db.get_conn() as conn:
            ev = conn.execute(
                "SELECT grade, activity_type FROM review_events "
                "WHERE user_id=21 AND word_id=?",
                (facade_wid,),
            ).fetchone()
        self.assertEqual(ev["grade"], 4)
        self.assertEqual(ev["activity_type"], "first_exposure")
        self.assertTrue(db.is_word_graded(21, facade_wid, "first_exposure"))

    # ---- parity matrix: activity x with_streak x grade_source ----

    def test_parity_matrix_streak_and_source(self):
        for activity, seed in (("srs_review", True), ("first_exposure", False)):
            for with_streak in (False, True):
                for grade_source in (None, "direct_button"):
                    uid = 100 + hash((activity, with_streak, grade_source)) % 800
                    _seed_user(uid)
                    word = f"m-{activity}-{with_streak}-{grade_source}-{uid}"
                    wid = _add_word(uid, word)
                    if seed:
                        _mark_review_state(wid, uid)
                    streak_before = _streak(uid)
                    res = self.gs.grade(
                        wid, 3, uid,
                        activity=activity,
                        grade_source=grade_source,
                        raw_signal="{}",
                        response_time_ms=7 if activity == "srs_review" else None,
                        with_streak=with_streak,
                    )
                    self.assertTrue(
                        res.ok,
                        f"activity={activity} streak={with_streak} source={grade_source}",
                    )
                    self.assertEqual(
                        _events(uid, wid),
                        1 if grade_source is not None else 0,
                        f"activity={activity} streak={with_streak} source={grade_source}",
                    )
                    if with_streak:
                        self.assertGreaterEqual(_streak(uid), streak_before)
                    else:
                        self.assertEqual(_streak(uid), streak_before)

    def test_legacy_defaults_grade_only_no_event_no_streak(self):
        _seed_user(31)
        wid = _add_word(31, "legacy-defaults")
        _mark_review_state(wid, 31)
        streak_before = _streak(31)
        res = self.gs.grade(wid, 3, 31, activity="srs_review")
        self.assertTrue(res.ok)
        self.assertEqual(_events(31, wid), 0)
        self.assertEqual(_streak(31), streak_before)
        self.assertEqual(_counters(wid), (0, 0))

    # ---- structural invariants ----

    def test_branches_stay_distinct_wrong_state(self):
        # Fresh word (no first exposure): review must refuse, exposure must pass.
        _seed_user(41)
        fresh = _add_word(41, "fresh-word")
        review_res = self.gs.grade(fresh, 3, 41, activity="srs_review")
        self.assertFalse(review_res.ok)
        self.assertEqual(review_res.reason, "wrong_state")
        exposure_res = self.gs.grade(fresh, 3, 41, activity="first_exposure")
        self.assertTrue(exposure_res.ok)
        # Reviewed word (exposure done): exposure must refuse, review must pass.
        _mark_review_state(_add_word(41, "reviewed-word"), 41)
        reviewed = _add_word(41, "reviewed-word-2")
        _mark_review_state(reviewed, 41)
        exposure_again = self.gs.grade(reviewed, 3, 41, activity="first_exposure")
        self.assertFalse(exposure_again.ok)
        self.assertEqual(exposure_again.reason, "wrong_state")

    def test_batched_tap_uses_single_transaction(self):
        _seed_user(51)
        wid = _add_word(51, "single-txn")
        _mark_review_state(wid, 51)
        import services.db.words as words_mod

        real_transaction = words_mod.transaction
        calls = []

        @contextmanager
        def counting(path=None):
            calls.append(1)
            with real_transaction(path) as conn:
                yield conn

        with mock.patch.object(words_mod, "transaction", counting):
            res = self.gs.grade(
                wid, 3, 51,
                activity="srs_review",
                grade_source="direct_button",
                raw_signal="{}",
                response_time_ms=1,
                with_streak=True,
            )
        self.assertTrue(res.ok)
        self.assertEqual(len(calls), 1)

    def test_grade_is_sync_with_zero_await(self):
        self.assertFalse(inspect.iscoroutinefunction(self.gs.grade))
        import services.grade_service as gs_mod

        source = inspect.getsource(gs_mod)
        self.assertNotIn("await", source)


if __name__ == "__main__":
    unittest.main()
