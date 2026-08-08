"""Tests for session engine package — GradePolicy, Assembly."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import patch

import pytest

import services.session as session_pkg
from services.session import (
    GRADE_POLICIES,
    GradePolicy,
    SessionNode,
    build_session_list,
    generate_tier3_node,
    resolve_grade,
)


class TestGradePolicy:
    def test_instantiation(self):
        policy = GradePolicy(
            activity_type="test",
            grade_source="button",
            grade_mapping=MappingProxyType({1: 1, 2: 2}),
            description="test policy",
        )
        assert policy.activity_type == "test"
        assert policy.grade_source == "button"
        assert isinstance(policy.grade_mapping, MappingProxyType)

    def test_immutable_mapping(self):
        policy = GradePolicy(
            activity_type="test",
            grade_source="button",
            grade_mapping=MappingProxyType({1: 1}),
            description="test",
        )
        with pytest.raises(TypeError):
            policy.grade_mapping[1] = 99


class TestGRADEPolicies:
    def test_all_five_keys_present(self):
        assert set(GRADE_POLICIES.keys()) == {
            "srs_review",
            "first_exposure",
            "new_ai_card",
            "ai_quiz",
            "sentence_write",
        }

    def test_srs_review_maps_1_to_4(self):
        policy = GRADE_POLICIES["srs_review"]
        assert set(policy.grade_mapping.keys()) == {1, 2, 3, 4}
        assert policy.grade_mapping[1] == 1
        assert policy.grade_mapping[4] == 4

    def test_first_exposure_maps_1_to_4(self):
        policy = GRADE_POLICIES["first_exposure"]
        assert set(policy.grade_mapping.keys()) == {1, 2, 3, 4}

    def test_new_ai_card_maps_1_to_4(self):
        policy = GRADE_POLICIES["new_ai_card"]
        assert set(policy.grade_mapping.keys()) == {1, 2, 3, 4}

    def test_ai_quiz_has_string_keys(self):
        policy = GRADE_POLICIES["ai_quiz"]
        assert set(policy.grade_mapping.keys()) == {
            "incorrect", "partial", "correct", "perfect",
        }

    def test_sentence_write_has_string_keys(self):
        policy = GRADE_POLICIES["sentence_write"]
        assert set(policy.grade_mapping.keys()) == {
            "incorrect", "partial", "correct", "perfect",
        }

    def test_each_policy_has_description(self):
        for key, policy in GRADE_POLICIES.items():
            assert policy.description, f"{key} has empty description"
            assert isinstance(policy.description, str)


class TestPublicAPI:
    """The session engine exposes one assembly seam and no dormant registry."""

    def test_public_exports_match_locked_contract(self):
        expected = {
            "GRADE_POLICIES",
            "GradePolicy",
            "SessionNode",
            "build_session_list",
            "generate_tier3_node",
            "resolve_grade",
        }
        # Exact equality pins the public surface so an unintended new export
        # (or a re-added dormant symbol) fails the test.
        assert set(session_pkg.__all__) == expected

    def test_dormant_registry_and_duplicate_assembler_absent(self):
        # Removed by finding #4: ACTIVITY_REGISTRY, ActivityHandler,
        # get_interaction_ui, and build_session must not re-enter the public API.
        for removed in (
            "ACTIVITY_REGISTRY",
            "ActivityHandler",
            "get_interaction_ui",
            "build_session",
        ):
            assert removed not in session_pkg.__all__


class TestResolveGrade:
    def test_srs_review_identity(self):
        for grade in (1, 2, 3, 4):
            assert resolve_grade("srs_review", grade) == grade

    def test_first_exposure_identity(self):
        for grade in (1, 2, 3, 4):
            assert resolve_grade("first_exposure", grade) == grade

    def test_new_ai_card_identity(self):
        for grade in (1, 2, 3, 4):
            assert resolve_grade("new_ai_card", grade) == grade

    def test_ai_quiz_string_mapping(self):
        assert resolve_grade("ai_quiz", "incorrect") == 1
        assert resolve_grade("ai_quiz", "partial") == 2
        assert resolve_grade("ai_quiz", "correct") == 3
        assert resolve_grade("ai_quiz", "perfect") == 4

    def test_sentence_write_string_mapping(self):
        assert resolve_grade("sentence_write", "incorrect") == 1
        assert resolve_grade("sentence_write", "partial") == 2
        assert resolve_grade("sentence_write", "correct") == 3
        assert resolve_grade("sentence_write", "perfect") == 4

    def test_unknown_activity_raises_valueerror(self):
        with pytest.raises(ValueError, match="Unknown activity_type"):
            resolve_grade("nonexistent", 1)

    def test_unmapped_value_raises_keyerror(self):
        with pytest.raises(KeyError):
            resolve_grade("ai_quiz", "unknown_rating")


class TestSessionNode:
    def test_all_fields(self):
        node = SessionNode(
            activity_type="srs_review",
            source_tier=1,
            card_data={"word": "hello", "translation": "سلام"},
            source_id=42,
            activity_meta={"user_id": 123, "target_lang": "en"},
            grade_policy_ref="srs_review",
            interaction_schema={"type": "grade_buttons"},
        )
        assert node.activity_type == "srs_review"
        assert node.source_tier == 1
        assert node.card_data == {"word": "hello", "translation": "سلام"}
        assert node.source_id == 42
        assert node.activity_meta == {"user_id": 123, "target_lang": "en"}
        assert node.grade_policy_ref == "srs_review"
        assert node.interaction_schema == {"type": "grade_buttons"}

    def test_defaults(self):
        node = SessionNode(activity_type="test", source_tier=2, card_data={})
        assert node.source_id is None
        assert node.activity_meta == {}
        assert node.grade_policy_ref is None
        assert node.interaction_schema is None

    def test_defaults_not_shared(self):
        node1 = SessionNode(activity_type="a", source_tier=1, card_data={})
        node2 = SessionNode(activity_type="b", source_tier=2, card_data={})
        node1.activity_meta["user_id"] = 1
        assert node2.activity_meta == {}


class TestAssemblyBuildSessionList:
    @patch("services.session.assembly.due_words_for_user", return_value=[])
    @patch("services.session.assembly.get_pre_first_exposure_words", return_value=[])
    def test_returns_tuple_of_list_and_dict(self, mock_fe, mock_due):
        result = build_session_list(user_id=1, max_nodes=5)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], dict)

    @patch("services.session.assembly.due_words_for_user", return_value=[])
    @patch("services.session.assembly.get_pre_first_exposure_words", return_value=[])
    def test_tier3_context_is_never_none(self, mock_fe, mock_due):
        _, tier3 = build_session_list(user_id=1, max_nodes=5)
        assert tier3 is not None
        assert isinstance(tier3, dict)

    @patch("services.session.assembly.due_words_for_user", return_value=[])
    @patch("services.session.assembly.get_pre_first_exposure_words", return_value=[])
    def test_empty_db_returns_empty_list_with_context(self, mock_fe, mock_due):
        nodes, tier3 = build_session_list(user_id=1, max_nodes=5)
        assert nodes == []
        assert "remaining_slots" in tier3
        assert tier3["remaining_slots"] == 5

    @patch("services.session.assembly.due_words_for_user", return_value=[
        {"id": 1, "word": "hello"},
        {"id": 2, "word": "world"},
    ])
    @patch("services.session.assembly.get_pre_first_exposure_words", return_value=[])
    def test_due_words_yielded_as_srs_review(self, mock_fe, mock_due):
        nodes, _ = build_session_list(user_id=1, max_nodes=5)
        assert len(nodes) == 2
        assert nodes[0].activity_type == "srs_review"
        assert nodes[0].source_tier == 1
        assert nodes[0].source_id == 1
        assert nodes[0].card_data["word"] == "hello"

    @patch("services.session.assembly.due_words_for_user", return_value=[])
    @patch("services.session.assembly.get_pre_first_exposure_words", return_value=[
        {"id": 3, "word": "foo"},
        {"id": 4, "word": "bar"},
    ])
    def test_pre_first_exposure_yielded_as_fe(self, mock_fe, mock_due):
        nodes, _ = build_session_list(user_id=1, max_nodes=5)
        assert len(nodes) == 2
        assert nodes[0].activity_type == "first_exposure"
        assert nodes[0].source_tier == 2
        assert nodes[0].source_id == 3

    @patch("services.session.assembly.due_words_for_user", return_value=[
        {"id": 1, "word": "due1"},
        {"id": 2, "word": "due2"},
    ])
    @patch("services.session.assembly.get_pre_first_exposure_words", return_value=[
        {"id": 3, "word": "fe1"},
    ])
    def test_tier_order_preserved(self, mock_fe, mock_due):
        nodes, _ = build_session_list(user_id=1, max_nodes=5)
        assert len(nodes) == 3
        assert nodes[0].activity_type == "srs_review"
        assert nodes[0].source_tier == 1
        assert nodes[1].activity_type == "srs_review"
        assert nodes[1].source_tier == 1
        assert nodes[2].activity_type == "first_exposure"
        assert nodes[2].source_tier == 2

    @patch("services.session.assembly.due_words_for_user", return_value=[
        {"id": 1, "word": "a"},
        {"id": 2, "word": "b"},
        {"id": 3, "word": "c"},
    ])
    @patch("services.session.assembly.get_pre_first_exposure_words", return_value=[
        {"id": 4, "word": "d"},
    ])
    def test_respects_max_nodes(self, mock_fe, mock_due):
        nodes, tier3 = build_session_list(user_id=1, max_nodes=2)
        assert len(nodes) == 2
        # Only Tier 1 words fit within limit — no tier3 context needed
        assert all(n.source_tier == 1 for n in nodes)
        assert tier3 == {}

    @patch("services.session.assembly.due_words_for_user", return_value=[])
    @patch("services.session.assembly.get_pre_first_exposure_words", return_value=[])
    def test_tier3_context_has_expected_keys(self, mock_fe, mock_due):
        _, tier3 = build_session_list(user_id=1, target_lang="en", goal="vocab",
                                       level="beginner", plan="free", max_nodes=5)
        assert tier3["user_id"] == 1
        assert tier3["target_lang"] == "en"
        assert tier3["goal"] == "vocab"
        assert tier3["level"] == "beginner"
        assert tier3["plan"] == "free"
        assert tier3["remaining_slots"] == 5


class TestGenerateTier3Node:
    def test_returns_none(self):
        result = generate_tier3_node(user_id=1)
        assert result is None

    def test_returns_none_with_all_params(self):
        result = generate_tier3_node(
            user_id=1, target_lang="en", goal="vocab",
            level="beginner", plan="free",
        )
        assert result is None
