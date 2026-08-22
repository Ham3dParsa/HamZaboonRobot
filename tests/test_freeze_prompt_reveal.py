"""Freeze prompt/reveal tests — kilo 132/200/547 coverage."""

import json
import unittest
from unittest.mock import MagicMock, patch

from handlers.study_handler import SessionState, _state_from_json, _state_to_json, _build_card_text_and_keyboard, _frozen_for_word
from services.session import SessionNode


def _make_node(word_id=1, activity="srs_review", word="allocate"):
    return SessionNode(
        activity_type=activity,
        source_tier=1,
        card_data={"word": word},
        source_id=word_id,
        activity_meta={"user_id": 1, "target_lang": "en"},
        grade_policy_ref=activity,
    )


class TestStateValidation(unittest.TestCase):
    def test_valid_prompt_round_trips(self):
        s = SessionState(nodes=[_make_node()], total_cards=1, tier3_context={}, study_msg_id=1, plan="free", revealed=True, active_prompt_type="meaning", active_prompt_word_id=1)
        j = _state_to_json(s)
        s2 = _state_from_json(j)
        self.assertTrue(s2.revealed)
        self.assertEqual(s2.active_prompt_type, "meaning")

    def test_invalid_prompt_cleared(self):
        raw = json.dumps({
            "nodes": [{"activity_type":"srs_review","source_tier":1,"card_data":{"word":"x"},"source_id":1,"activity_meta":{},"grade_policy_ref":"srs_review","interaction_schema":None}],
            "total_cards":1,"tier3_context":{},"study_msg_id":1,"plan":"free","graded_word_ids":[],"before_stability":{},
            "revealed": True, "active_prompt_type": "not_a_prompt", "active_prompt_word_id": 1
        })
        s = _state_from_json(raw)
        self.assertIsNone(s.active_prompt_type)
        self.assertIsNone(s.active_prompt_word_id)
        self.assertFalse(s.revealed)

    def test_old_json_backward_compat(self):
        raw = json.dumps({
            "nodes": [{"activity_type":"srs_review","source_tier":1,"card_data":{"word":"x"},"source_id":1,"activity_meta":{},"grade_policy_ref":"srs_review","interaction_schema":None}],
            "total_cards":1,"tier3_context":{},"study_msg_id":1,"plan":"free","graded_word_ids":[],"before_stability":{}
        })
        s = _state_from_json(raw)
        self.assertFalse(s.revealed)
        self.assertIsNone(s.active_prompt_type)

    def test_frozen_helper_clears_corrupt(self):
        s = SessionState(nodes=[_make_node(1)], total_cards=1, tier3_context={}, study_msg_id=1, plan="free", revealed=True, active_prompt_type="BAD", active_prompt_word_id=1)
        pt, rev = _frozen_for_word(s, 1)
        self.assertIsNone(pt)
        self.assertFalse(rev)
        self.assertIsNone(s.active_prompt_type)


class TestFreezeDeterminism(unittest.TestCase):
    def _patch_db(self):
        return patch("handlers.study_handler.db.get_saved_word", return_value={
            "word":"allocate","card_data": json.dumps({"word":"allocate","fa_meaning":"اختصاص دادن","synonyms":["assign"],"antonyms":["withhold"],"examples":["We allocate funds."],"example_translations":["ترجمه"],"phonetic":""}),
            "stability": 2.0, "last_review_at": None
        })

    def test_front_freeze_deterministic(self):
        node = _make_node(1, "srs_review", "allocate")
        state = SessionState(nodes=[node], total_cards=1, tier3_context={}, study_msg_id=1, plan="free")
        with self._patch_db(), patch("handlers.study_handler.db.resolve_card_mode", return_value="staged"), patch("handlers.study_handler.db.get_display_toggles", return_value={"synonyms":True,"antonyms":True,"examples":True,"example_translations":True,"explanation":True,"grammar_tip":True}), patch("handlers.study_handler.select_srs_prompt_type", return_value="meaning"), patch("handlers.study_handler._session_number", return_value=1):
            t1, _ = _build_card_text_and_keyboard(node, state, 1, user_data={})
            # second call should reuse frozen, not call select again (patch would still return meaning, but ensures same)
            with patch("handlers.study_handler.select_srs_prompt_type", side_effect=AssertionError("should not re-roll")), patch("handlers.study_handler._session_number", return_value=1):
                t2, _ = _build_card_text_and_keyboard(node, state, 1, user_data={})
            self.assertEqual(t1, t2)

    def test_revealed_renders_back(self):
        node = _make_node(1, "srs_review", "allocate")
        state = SessionState(nodes=[node], total_cards=1, tier3_context={}, study_msg_id=1, plan="free", revealed=True, active_prompt_type="meaning", active_prompt_word_id=1)
        with self._patch_db(), patch("handlers.study_handler.db.resolve_card_mode", return_value="staged"), patch("handlers.study_handler.db.get_display_toggles", return_value={"synonyms":True,"antonyms":True,"examples":True,"example_translations":True,"explanation":True,"grammar_tip":True}), patch("handlers.study_handler._session_number", return_value=1):
            text, kb = _build_card_text_and_keyboard(node, state, 1, user_data={})
            # back stage contains the post-reveal instruction
            self.assertIn("یادآوری", text)
            callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
            self.assertTrue(any(c.startswith("srs:1:") for c in callbacks))
