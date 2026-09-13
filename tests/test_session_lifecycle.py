"""REF4-T4 lifecycle unit parity — store owns advance steps + gather.

Red-first: store.pop_next / rollback_pop / push_tier3 / rollback_tier3_push /
gather_word_records (+ date helpers) do not exist yet. Handler delegates must
be identical objects to the store owners (T3 pattern).
"""

import os
import tempfile
import unittest

from services import db as db_module
from services.db import schema as db_schema
from services.session import SessionNode


def _node(word="hello", wid=1):
    return SessionNode(
        activity_type="srs_review",
        source_tier=1,
        card_data={"word": word},
        source_id=wid,
        activity_meta={"user_id": 1},
        grade_policy_ref="srs_review",
    )


def _state(nodes, **kw):
    from services.session.store import SessionState

    base = {
        "nodes": list(nodes),
        "total_cards": len(nodes),
        "tier3_context": {},
        "study_msg_id": 999,
        "plan": "free",
        "session_date": "2026-09-12",
    }
    base.update(kw)
    return SessionState(**base)


class LifecycleHelpersTests(unittest.TestCase):
    def test_pop_next_clears_freeze_and_returns_saved(self):
        from services.session import store

        s = _state(
            [_node("a", 1), _node("b", 2)],
            revealed=True,
            active_prompt_type="meaning",
            active_prompt_word_id=1,
        )
        popped, saved = store.pop_next(s)
        self.assertEqual(popped.card_data["word"], "a")
        self.assertEqual(len(s.nodes), 1)
        self.assertFalse(s.revealed)
        self.assertIsNone(s.active_prompt_type)
        self.assertIsNone(s.active_prompt_word_id)
        self.assertEqual(saved, (True, "meaning", 1))

    def test_rollback_pop_restores_node_and_freeze(self):
        from services.session import store

        s = _state([_node("b", 2)])
        popped, saved = ( _node("a", 1), (True, "meaning", 1))
        # simulate post-pop cleared state then rollback
        s.revealed = False
        s.active_prompt_type = None
        s.active_prompt_word_id = None
        store.rollback_pop(s, popped, saved)
        self.assertEqual([n.card_data["word"] for n in s.nodes], ["a", "b"])
        self.assertTrue(s.revealed)
        self.assertEqual(s.active_prompt_type, "meaning")
        self.assertEqual(s.active_prompt_word_id, 1)

    def test_rollback_pop_with_none_popped_only_restores_freeze(self):
        from services.session import store

        s = _state([_node("b", 2)])
        s.revealed = False
        store.rollback_pop(s, None, (True, "meaning", 1))
        self.assertEqual(len(s.nodes), 1)
        self.assertTrue(s.revealed)

    def test_tier3_push_and_rollback(self):
        from services.session import store

        s = _state([], total_cards=2)
        node = _node("t3", 9)
        store.push_tier3(s, node)
        self.assertEqual(len(s.nodes), 1)
        self.assertEqual(s.total_cards, 3)
        store.rollback_tier3_push(s)
        self.assertEqual(len(s.nodes), 0)
        self.assertEqual(s.total_cards, 2)

    def test_store_has_zero_telegram_imports(self):
        import re
        from pathlib import Path

        src = Path("services/session/store.py").read_text(encoding="utf-8")
        for line in src.splitlines():
            stripped = line.strip()
            self.assertFalse(
                re.match(r"(import|from)\s+telegram\b", stripped),
                f"store must not import telegram: {line!r}",
            )


class GatherParityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db_module.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new = os.path.join(self.tempdir.name, "test.sqlite")
        db_module.DB_PATH = new
        db_schema.DB_PATH = new
        db_module.init_db()
        db_module.create_user_if_needed(1, "learner")

    def tearDown(self):
        db_module.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _add_word(self, word, stability=4.0):
        card = {
            "word": word, "fa_meaning": "م", "fa_explanation": "ت",
            "examples": [], "example_translations": [], "synonyms": [],
            "antonyms": [], "grammar_tip": "",
        }
        db_module.add_saved_word(1, word, "en", card)
        with db_module.transaction() as conn:
            conn.execute(
                "UPDATE saved_words SET stability=? WHERE user_id=1 AND word=?",
                (stability, word),
            )
            return conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)
            ).fetchone()["id"]

    def _add_event(self, wid, created_at, activity, grade):
        with db_module.transaction() as conn:
            conn.execute(
                "INSERT INTO review_events (word_id, user_id, revealed_before_answer,"
                " outcome, created_at, grade, activity_type)"
                " VALUES (?, ?, 0, ?, ?, ?, ?)",
                (wid, 1, "correct", created_at, grade, activity),
            )

    def test_gather_parity_with_handler(self):
        from services.session import store
        import handlers.study_handler as handler

        w = self._add_word("alpha")
        self._add_event(w, "2026-08-10T10:00:00Z", "srs_review", 3)
        self._add_event(w, "2026-08-19T10:00:00Z", "srs_review", 4)
        s = _state([], graded_word_ids=[w], before_stability={w: 2.0})
        expected = handler._gather_word_records(s, 1)
        got = store.gather_word_records(s, 1)
        self.assertEqual(got, expected)
        self.assertEqual(got[0].grade, 4)
        self.assertEqual(got[0].stability_before, 2.0)

    def test_gather_empty_and_fallback(self):
        from services.session import store

        s = _state([])
        self.assertEqual(store.gather_word_records(s, 1), [])
        w = self._add_word("beta", stability=1.5)
        s2 = _state([], graded_word_ids=[w])
        recs = store.gather_word_records(s2, 1)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].activity_type, "srs_review")
        self.assertIsNone(recs[0].grade)

    def test_handler_delegates_are_store_owners(self):
        import handlers.study_handler as handler
        import services.session.store as store

        self.assertIs(handler._gather_word_records, store.gather_word_records)
        # date helpers moved verbatim; handler keeps aliases
        self.assertIs(handler._parse_iso_utc, store.parse_iso_utc)
        self.assertIs(handler._to_app_tz_date, store.to_app_tz_date)
        self.assertIs(handler._interval_days, store.interval_days)


if __name__ == "__main__":
    unittest.main()
