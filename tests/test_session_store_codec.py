"""Session store codec + persistence (REF4-T3).

Proves the verbatim move of the SessionState shape + JSON codec +
save/load/clear from handlers/study_handler.py:78-244 into
services/session/store.py (public canonical names; the handler keeps thin
``_state_*``/``_persist*``/``_restore*`` delegates so srs_handler, tools and
tests keep their import paths; caller migration is REF4-T4):

- byte-equivalent JSON schema (round-trip incl. before_stability coercion,
  SessionNode kwargs, revealed/prompt validation, legacy "" date);
- corrupt payloads invalidate (load -> None + row cleared);
- restart-safe (save/load across connections), stale-day discard, freeze
  fields survive;
- store takes caller-side ``today`` explicitly and never computes the
  app-day itself (no midnight-straddle inside the store);
- store has zero Telegram imports.
"""

import inspect
import json
import os
import tempfile
import unittest

from services import db as db_module
from services.db import schema as db_schema
from services.session import SessionNode


def _make_node(word_id=1, **kw):
    base = {
        "activity_type": "first_exposure",
        "source_tier": 1,
        "card_data": {"word": "hello", "fa_meaning": "سلام"},
        "source_id": word_id,
        "activity_meta": {"user_id": 7},
        "grade_policy_ref": "first_exposure",
        "interaction_schema": None,
    }
    base.update(kw)
    return SessionNode(**base)


def _make_state(**kw):
    from services.session.store import SessionState

    base = {
        "nodes": [_make_node()],
        "total_cards": 1,
        "tier3_context": {"user_id": 7, "remaining_slots": 0},
        "study_msg_id": 999,
        "plan": "free",
    }
    base.update(kw)
    return SessionState(**base)


class StoreNoTelegramTests(unittest.TestCase):
    def test_store_source_has_zero_telegram_imports(self):
        import re
        from pathlib import Path

        src = Path("services/session/store.py").read_text(encoding="utf-8")
        for line in src.splitlines():
            stripped = line.strip()
            self.assertFalse(
                re.match(r"(import|from)\s+telegram\b", stripped),
                f"store must not import telegram: {line!r}",
            )
            self.assertFalse(
                re.match(r"(import|from)\s+handlers\b", stripped)
                or re.match(r"from\s+handlers\.", stripped),
                f"store must not import handlers: {line!r}",
            )

    def test_store_never_computes_app_day(self):
        """R4: today is caller-side; the store must not resolve the day."""
        import re
        from pathlib import Path

        src = Path("services/session/store.py").read_text(encoding="utf-8")
        for banned in ("_today_str", "_app_day_str", "scheduling"):
            self.assertIsNone(
                re.search(rf"\b{re.escape(banned)}\b", src),
                f"store must not reference {banned} (R4 explicit-today)",
            )

    def test_save_and_load_require_explicit_today(self):
        from services.session import store

        for name in ("save_session", "load_session"):
            sig = inspect.signature(getattr(store, name))
            today = sig.parameters["today"]
            self.assertIs(
                today.default,
                inspect.Parameter.empty,
                f"store.{name} must require explicit today (R4)",
            )


class StoreCodecTests(unittest.TestCase):
    def test_round_trip_full_state(self):
        from services.session.store import (
            SessionState,
            state_from_json,
            state_to_json,
        )

        s = _make_state(
            graded_word_ids=[1],
            before_stability={1: 2.5},
            revealed=True,
            active_prompt_type="meaning",
            active_prompt_word_id=1,
            session_date="2026-09-12",
        )
        s2 = state_from_json(state_to_json(s))
        self.assertEqual(s2, s)
        self.assertIsInstance(s2, SessionState)

    def test_before_stability_coercion_string_keys(self):
        from services.session.store import state_from_json, state_to_json

        s = _make_state(before_stability={3: 1.25})
        raw = json.loads(state_to_json(s))
        self.assertIn("3", raw["before_stability"])  # JSON keys are strings
        s2 = state_from_json(json.dumps(raw))
        self.assertEqual(s2.before_stability, {3: 1.25})
        for k, v in s2.before_stability.items():
            self.assertIsInstance(k, int)
            self.assertIsInstance(v, float)

    def test_session_node_kwargs_survive(self):
        from services.session.store import state_from_json, state_to_json

        node = _make_node(
            activity_type="srs_review",
            source_tier=2,
            activity_meta={"user_id": 7, "extra": [1, 2]},
            grade_policy_ref="review",
            interaction_schema={"kind": "grade4"},
        )
        s = _make_state(nodes=[node], total_cards=1)
        s2 = state_from_json(state_to_json(s))
        self.assertEqual(s2.nodes[0], node)

    def test_invalid_prompt_type_clears_prompt_and_reveal(self):
        from services.session.store import state_from_json, state_to_json

        s = _make_state(
            revealed=True,
            active_prompt_type="BAD",
            active_prompt_word_id=1,
        )
        s2 = state_from_json(state_to_json(s))
        self.assertIsNone(s2.active_prompt_type)
        self.assertIsNone(s2.active_prompt_word_id)
        self.assertFalse(s2.revealed)

    def test_stray_revealed_without_prompt_clears_both(self):
        from services.session.store import state_from_json

        raw = json.dumps(
            {
                "nodes": [
                    {
                        "activity_type": "first_exposure",
                        "source_tier": 1,
                        "card_data": {},
                        "source_id": 1,
                        "activity_meta": {},
                        "grade_policy_ref": None,
                        "interaction_schema": None,
                    }
                ],
                "total_cards": 1,
                "tier3_context": {},
                "study_msg_id": None,
                "plan": "free",
                "revealed": True,
            }
        )
        s = state_from_json(raw)
        self.assertFalse(s.revealed)
        self.assertIsNone(s.active_prompt_word_id)

    def test_prompt_word_id_string_coerced_to_int(self):
        from services.session.store import state_from_json, state_to_json

        s = _make_state(
            revealed=True,
            active_prompt_type="meaning",
            active_prompt_word_id=1,
        )
        raw = json.loads(state_to_json(s))
        raw["active_prompt_word_id"] = "5"
        s2 = state_from_json(json.dumps(raw))
        self.assertEqual(s2.active_prompt_word_id, 5)

    def test_corrupt_prompt_word_id_becomes_none(self):
        from services.session.store import state_from_json, state_to_json

        raw = json.loads(state_to_json(_make_state()))
        raw["active_prompt_word_id"] = "abc"
        raw["active_prompt_type"] = "meaning"
        raw["revealed"] = True
        s2 = state_from_json(json.dumps(raw))
        self.assertIsNone(s2.active_prompt_word_id)
        self.assertFalse(s2.revealed)

    def test_legacy_missing_date_means_empty_string(self):
        from services.session.store import state_from_json, state_to_json

        raw = json.loads(state_to_json(_make_state(session_date="2026-09-12")))
        del raw["session_date"]
        s2 = state_from_json(json.dumps(raw))
        self.assertEqual(s2.session_date, "")

    def test_is_valid_prompt_type_seam(self):
        from services.session.store import is_valid_prompt_type
        from services.utils.formatting import SRS_PROMPT_TYPES

        for pt in SRS_PROMPT_TYPES:
            self.assertTrue(is_valid_prompt_type(pt))
        self.assertFalse(is_valid_prompt_type("BAD"))
        self.assertFalse(is_valid_prompt_type(None))
        self.assertFalse(is_valid_prompt_type(123))


class StorePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "store.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_persist_restore_roundtrip_same_day(self):
        from services.scheduling import _today_str
        from services.session.store import load_session, save_session

        today = _today_str()
        s = _make_state(session_date=today)
        save_session(7, s, today)
        got = load_session(7, today)
        self.assertIsNotNone(got)
        self.assertEqual(got, s)

    def test_restore_missing_user_returns_none(self):
        from services.scheduling import _today_str
        from services.session.store import load_session

        self.assertIsNone(load_session(4242, _today_str()))

    def test_clear_removes_row(self):
        from services.scheduling import _today_str
        from services.db import sessions as sessions_module
        from services.session.store import (
            clear_session,
            load_session,
            save_session,
        )

        today = _today_str()
        save_session(7, _make_state(session_date=today), today)
        clear_session(7)
        self.assertIsNone(load_session(7, today))
        self.assertIsNone(sessions_module.load_study_session(7))

    def test_stale_day_discards_and_clears(self):
        from services.db import sessions as sessions_module
        from services.session.store import load_session, save_session

        save_session(7, _make_state(session_date="2000-01-01"), "2000-01-01")
        self.assertIsNone(load_session(7, "2000-01-02"))
        self.assertIsNone(sessions_module.load_study_session(7))

    def test_corrupt_json_invalidates(self):
        from services.scheduling import _today_str
        from services.db import sessions as sessions_module
        from services.session.store import load_session

        today = _today_str()
        sessions_module.save_study_session(7, today, "{not-json")
        self.assertIsNone(load_session(7, today))
        self.assertIsNone(sessions_module.load_study_session(7))

    def test_empty_nodes_invalidates(self):
        from services.scheduling import _today_str
        from services.db import sessions as sessions_module
        from services.session.store import load_session, save_session

        today = _today_str()
        save_session(7, _make_state(nodes=[], total_cards=0, session_date=today), today)
        self.assertIsNone(load_session(7, today))
        self.assertIsNone(sessions_module.load_study_session(7))

    def test_freeze_fields_survive_persist_restore(self):
        from services.scheduling import _today_str
        from services.session.store import load_session, save_session

        today = _today_str()
        s = _make_state(
            revealed=True,
            active_prompt_type="meaning",
            active_prompt_word_id=1,
            session_date=today,
        )
        save_session(7, s, today)
        got = load_session(7, today)
        self.assertIsNotNone(got)
        self.assertTrue(got.revealed)
        self.assertEqual(got.active_prompt_type, "meaning")
        self.assertEqual(got.active_prompt_word_id, 1)


class StoreHandlerParityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "store-parity.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_handler_codec_names_are_store_objects(self):
        import handlers.study_handler as handler
        import services.session.store as store

        for private, public in (
            ("_state_to_json", "state_to_json"),
            ("_state_from_json", "state_from_json"),
            ("_is_valid_prompt_type", "is_valid_prompt_type"),
            ("_clear_persisted_session", "clear_session"),
        ):
            self.assertIs(
                getattr(handler, private),
                getattr(store, public),
                f"handlers.study_handler.{private} must re-export store.{public}",
            )
        self.assertIs(handler.SessionState, store.SessionState)

    def test_handler_persist_restore_delegate_with_explicit_today(self):
        import handlers.study_handler as handler
        import services.session.store as store

        today = "2026-09-12"
        s = _make_state(session_date=today)
        sig = inspect.signature(handler._persist_session)
        self.assertIn("today", sig.parameters)
        handler._persist_session(7, s, today)
        self.assertEqual(store.load_session(7, today), s)
        self.assertEqual(handler._restore_persisted_session.__code__.co_argcount, 1)

    def test_frozen_for_word_stays_with_render(self):
        import handlers.study_handler as handler

        self.assertTrue(hasattr(handler, "_frozen_for_word"))
        import services.session.store as store

        self.assertFalse(
            hasattr(store, "_frozen_for_word"),
            "_frozen_for_word must stay in the handler render seam",
        )


if __name__ == "__main__":
    unittest.main()
