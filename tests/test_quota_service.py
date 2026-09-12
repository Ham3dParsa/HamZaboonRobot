"""Facade-parity tests for services/quota_service.py (REF4-T1).

The facade is additive only: kind-dispatched can/reserve/consume/release plus
import-aliases of the verbatim bodies in services/db/users.py:297-377 and
services/scheduling.py:115-178. These tests prove same return value + same DB
row for facade vs direct body, reserve/release idempotence, cross-kind
isolation, and that the can_* hint never consumes.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from services import db
from services.db import schema as db_schema
import services.scheduling as scheduling


class TestQuotaServiceParity(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        import services.quota_service as qs

        self.qs = qs

    def tearDown(self):
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def _row(self, user_id: int):
        return dict(db.get_user(user_id))

    # ---- registry / aliases ----

    def test_kind_registry_maps_storage(self):
        self.assertEqual(
            set(self.qs.QUOTA_KINDS), {"word", "grammar_tip", "session_slot"}
        )
        word = self.qs.KIND_STORAGE["word"]
        self.assertEqual(word["store"], "users")
        self.assertIn("words_asked_today", word["count_column"])
        grammar = self.qs.KIND_STORAGE["grammar_tip"]
        self.assertEqual(grammar["store"], "users")
        self.assertIn("grammar_tips_asked_today", grammar["count_column"])
        slot = self.qs.KIND_STORAGE["session_slot"]
        self.assertEqual(slot["store"], "settings")
        self.assertIn("sessions_used_", slot["key_pattern"])

    def test_aliases_are_verbatim_bodies(self):
        qs = self.qs
        self.assertIs(qs.can_ask_word, db.can_ask_word)
        self.assertIs(qs.reserve_word_query, db.reserve_word_query)
        self.assertIs(qs.release_word_query, db.release_word_query)
        self.assertIs(qs.can_ask_grammar_tip, db.can_ask_grammar_tip)
        self.assertIs(qs.reserve_grammar_tip, db.reserve_grammar_tip)
        self.assertIs(qs.release_grammar_tip, db.release_grammar_tip)
        self.assertIs(qs.consume_session_slot, scheduling.consume_session_slot)
        self.assertIs(qs.release_session_slot, scheduling.release_session_slot)

    def test_unknown_kind_raises(self):
        for fn in (
            lambda: self.qs.can("nope", 1, daily_limit=1),
            lambda: self.qs.reserve("nope", 1, daily_limit=1),
            lambda: self.qs.consume("nope", 1),
            lambda: self.qs.release("nope", 1),
        ):
            with self.assertRaises(ValueError):
                fn()

    # ---- word parity ----

    def test_word_parity_same_return_and_row(self):
        db.create_user_if_needed(11, "facade")
        db.create_user_if_needed(12, "direct")
        self.assertEqual(
            self.qs.can("word", 11, daily_limit=1),
            db.can_ask_word(12, 1),
        )
        self.assertEqual(
            self.qs.reserve("word", 11, daily_limit=1),
            db.reserve_word_query(12, 1),
        )
        self.assertEqual(self._row(11)["words_asked_today"], 1)
        self.assertEqual(
            self._row(11)["words_asked_today"],
            self._row(12)["words_asked_today"],
        )
        # Exhausted: second reserve fails on both paths.
        self.assertFalse(self.qs.reserve("word", 11, daily_limit=1))
        self.assertFalse(db.reserve_word_query(12, 1))
        self.assertFalse(self.qs.can("word", 11, daily_limit=1))
        # Release restores on both paths.
        self.qs.release("word", 11)
        db.release_word_query(12)
        self.assertTrue(self.qs.can("word", 11, daily_limit=1))
        self.assertTrue(db.can_ask_word(12, 1))

    def test_can_hint_never_consumes(self):
        db.create_user_if_needed(21, "hint")
        before = self._row(21)["words_asked_today"]
        self.assertTrue(self.qs.can("word", 21, daily_limit=1))
        self.assertTrue(self.qs.can("word", 21, daily_limit=1))
        self.assertEqual(self._row(21)["words_asked_today"], before)
        self.assertTrue(self.qs.reserve("word", 21, daily_limit=1))
        self.assertFalse(self.qs.can("word", 21, daily_limit=1))

    def test_word_release_idempotent_and_clamped(self):
        db.create_user_if_needed(31, "rel")
        # Release without reserve: no negative, stays usable.
        self.qs.release("word", 31)
        self.assertEqual(self._row(31)["words_asked_today"] or 0, 0)
        self.assertTrue(self.qs.can("word", 31, daily_limit=1))
        self.assertTrue(self.qs.reserve("word", 31, daily_limit=1))
        self.qs.release("word", 31)
        self.qs.release("word", 31)
        self.assertEqual(self._row(31)["words_asked_today"] or 0, 0)

    # ---- grammar parity ----

    def test_grammar_parity_same_return_and_row(self):
        db.create_user_if_needed(41, "facade")
        db.create_user_if_needed(42, "direct")
        self.assertEqual(
            self.qs.can("grammar_tip", 41, daily_limit=1),
            db.can_ask_grammar_tip(42, 1),
        )
        self.assertEqual(
            self.qs.reserve("grammar_tip", 41, daily_limit=1),
            db.reserve_grammar_tip(42, 1),
        )
        self.assertEqual(
            self._row(41)["grammar_tips_asked_today"],
            self._row(42)["grammar_tips_asked_today"],
        )
        self.assertFalse(self.qs.reserve("grammar_tip", 41, daily_limit=1))
        self.assertFalse(db.reserve_grammar_tip(42, 1))
        self.qs.release("grammar_tip", 41)
        db.release_grammar_tip(42)
        self.assertTrue(self.qs.can("grammar_tip", 41, daily_limit=1))
        self.assertTrue(db.can_ask_grammar_tip(42, 1))

    # ---- session_slot parity ----

    def test_session_slot_parity_consume_release(self):
        plan = "free"
        limit = db.get_plan(plan)["max_sessions"]
        self.assertTrue(self.qs.consume("session_slot", 51, plan=plan))
        self.assertTrue(scheduling.consume_session_slot(52, plan))
        self.assertEqual(
            scheduling.daily_session_budget(51, plan)["used"],
            scheduling.daily_session_budget(52, plan)["used"],
        )
        # Fill to the limit on both paths, then both refuse.
        for _ in range(limit - 1):
            self.assertTrue(self.qs.consume("session_slot", 51, plan=plan))
            self.assertTrue(scheduling.consume_session_slot(52, plan))
        self.assertFalse(self.qs.consume("session_slot", 51, plan=plan))
        self.assertFalse(scheduling.consume_session_slot(52, plan))
        # reserve() routes to the same gate for session_slot.
        self.assertFalse(self.qs.reserve("session_slot", 51, plan=plan))
        # Hint reflects exhaustion without consuming.
        self.assertFalse(self.qs.can("session_slot", 51, plan=plan))
        # Release restores on both paths; double release never negative.
        self.qs.release("session_slot", 51)
        scheduling.release_session_slot(52)
        self.assertEqual(
            scheduling.daily_session_budget(51, plan)["used"], limit - 1
        )
        self.assertEqual(
            scheduling.daily_session_budget(52, plan)["used"], limit - 1
        )
        self.qs.release("session_slot", 99)
        self.assertEqual(
            scheduling.daily_session_budget(99, plan)["used"], 0
        )

    # ---- cross-kind isolation ----

    def test_cross_kind_isolation(self):
        db.create_user_if_needed(61, "iso")
        self.assertTrue(self.qs.reserve("word", 61, daily_limit=1))
        # Word spend touches neither the grammar counter nor the session usage.
        self.assertTrue(self.qs.can("grammar_tip", 61, daily_limit=1))
        self.assertEqual(
            scheduling.daily_session_budget(61, "free")["used"], 0
        )
        self.assertTrue(
            self.qs.consume("session_slot", 61, plan="free")
        )
        self.assertEqual(self._row(61)["words_asked_today"], 1)
        self.assertEqual(
            self._row(61)["grammar_tips_asked_today"] or 0, 0
        )


if __name__ == "__main__":
    unittest.main()
