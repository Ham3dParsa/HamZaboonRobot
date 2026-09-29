"""P1 arbiter-runner tests (behavior-first, stub transports only).

Locked contracts: prompt via SenseLinkingArbitrationPromptBuilder (BASE);
model answers JSON {verdict LINK|NONE, winner_index N|null, evidences};
winner NUMBER resolves via index_map; anything unparseable/timeout →
abstain (verdict None + needs_review), never an invented verdict.
"""

from __future__ import annotations

import pytest

from factory.linking import arbiter_runner


def _sense():
    return {
        "sense_id": "run#0",
        "lemma": "run",
        "definition": "move fast",
        "example": "I run daily",
        "tags": ["verb"],
        "candidates": [
            {"synset_id": "run%2:38:00::", "definition": "move fast",
             "example": "run fast"},
            {"synset_id": "run%2:38:01::", "definition": "operate",
             "example": ""},
        ],
    }


def _preset():
    return {"provider": "stub", "model": "stub-model"}


def test_clean_link_resolves_number_to_synset():
    def _transport(prompt):
        assert "LEARNER-DICTIONARY ENTRY" in prompt
        return ('{"verdict": "LINK", "winner_index": 2, '
                '"kaikki_evidence": "move fast", '
                '"wordnet_evidence": "operate"}')

    out = arbiter_runner.run_arbiter([_sense()], _preset(), _transport)
    assert len(out) == 1
    rec = out[0]
    assert rec["sense_id"] == "run#0"
    assert rec["verdict"] == "link"
    assert rec["target_synset"] == "run%2:38:01::"
    assert rec["model"] == "stub-model"
    assert rec["needs_review"] is False


def test_clean_none_has_null_target():
    def _transport(prompt):
        return ('{"verdict": "NONE", "winner_index": null, '
                '"kaikki_evidence": "move fast", "wordnet_evidence": ""}')

    (rec,) = arbiter_runner.run_arbiter([_sense()], _preset(), _transport)
    assert rec["verdict"] == "none"
    assert rec["target_synset"] is None
    assert rec["needs_review"] is False


def test_malformed_answer_abstains_never_invents():
    def _transport(prompt):
        return "I think maybe the second one, not sure"

    (rec,) = arbiter_runner.run_arbiter([_sense()], _preset(), _transport)
    assert rec["verdict"] is None
    assert rec["needs_review"] is True


def test_out_of_range_winner_abstains():
    def _transport(prompt):
        return ('{"verdict": "LINK", "winner_index": 9, '
                '"kaikki_evidence": "x", "wordnet_evidence": "y"}')

    (rec,) = arbiter_runner.run_arbiter([_sense()], _preset(), _transport)
    assert rec["verdict"] is None
    assert rec["needs_review"] is True


def test_transport_failure_abstains_without_verdict():
    def _transport(prompt):
        raise TimeoutError("model too slow")

    (rec,) = arbiter_runner.run_arbiter([_sense()], _preset(), _transport)
    assert rec["verdict"] is None
    assert rec["needs_review"] is True
    assert "TimeoutError" in (rec.get("error") or "")


def test_prose_wrapped_json_still_parses():
    def _transport(prompt):
        return ('Here is my answer:\n{"verdict": "NONE", '
                '"winner_index": null, "kaikki_evidence": "move fast", '
                '"wordnet_evidence": ""}\nDone.')

    (rec,) = arbiter_runner.run_arbiter([_sense()], _preset(), _transport)
    assert rec["verdict"] == "none"
    assert rec["needs_review"] is False


def test_empty_senses_returns_empty():
    assert arbiter_runner.run_arbiter([], _preset(),
                                      lambda prompt: "{}") == []
