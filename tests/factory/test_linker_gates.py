"""F3 v0.8 gate-core unit tests (locked contract: CONTRACT-linker.md F3 +

RANKED.md SplitVoteVeto v2 / SignalQualityVeto + judgeops/gates_r.py R
semantics + STATE_V08_CHECKPOINT §§1/4).

Pure, hermetic, zero model calls. All fixtures synthetic (no real kids,
lemmas, or rows from SET50r — anti-hardcode rule).
"""

import pytest

from factory.linker import gates


def test_low_rank_zero_overlap_fires_on_rank_ge2_and_zero_j():
    fired, reason = gates.low_rank_zero_overlap_veto(
        rank_index=2, j=0.0, lemma="apple",
        winner_fires=["Sa:j=0.00", "Sd:hyp=fruit"])
    assert fired is True
    assert reason


def test_low_rank_zero_overlap_preserves_on_positive_j():
    fired, _ = gates.low_rank_zero_overlap_veto(
        rank_index=3, j=0.25, lemma="apple",
        winner_fires=["Sa:j=0.25", "Sd:hyp=fruit"])
    assert fired is False


def test_low_rank_zero_overlap_headword_guard_preserves():
    fired, reason = gates.low_rank_zero_overlap_veto(
        rank_index=2, j=0.0, lemma="apple",
        winner_fires=["Sb:apple,pear"])
    assert fired is False
    assert "guard" in reason


def test_low_rank_zero_overlap_boundary_j_zero_no_guard_fires():
    fired, _ = gates.low_rank_zero_overlap_veto(
        rank_index=2, j=0.0, lemma="apple",
        winner_fires=["Sd:hyp=fruit"])
    assert fired is True


def test_low_rank_zero_overlap_top_ranks_never_fire():
    for rank in (0, 1):
        fired, _ = gates.low_rank_zero_overlap_veto(
            rank_index=rank, j=0.0, lemma="apple",
            winner_fires=["Sd:hyp=fruit"])
        assert fired is False


def test_low_rank_zero_overlap_missing_data_preserves():
    assert gates.low_rank_zero_overlap_veto(
        None, 0.0, "apple", ["Sd:hyp=fruit"])[0] is False
    assert gates.low_rank_zero_overlap_veto(
        2, None, "apple", ["Sd:hyp=fruit"])[0] is False


def test_evidence_gloss_mismatch_fires_on_absent_gloss():
    fired, reason = gates.evidence_gloss_mismatch_veto(
        winner_gloss="a round fruit",
        wordnet_evidence="Sa:j=0.10+Sd:hyp=company",
        j=0.10)
    assert fired is True
    assert reason


def test_evidence_gloss_mismatch_preserves_on_containment():
    fired, _ = gates.evidence_gloss_mismatch_veto(
        winner_gloss="a round fruit",
        wordnet_evidence="fires Sa:j=0.10 quoting a round fruit here",
        j=0.10)
    assert fired is False


def test_evidence_gloss_mismatch_paren_tolerant():
    fired, _ = gates.evidence_gloss_mismatch_veto(
        winner_gloss="move steadily (of a crowd)",
        wordnet_evidence="... move steadily onward ...",
        j=0.05)
    assert fired is False


def test_evidence_gloss_bailout_j_ge_020_skips():
    for j in (0.20, 0.21, 1.0):
        fired, reason = gates.evidence_gloss_mismatch_veto(
            winner_gloss="a round fruit",
            wordnet_evidence="Sa:j=0.40+Sd:hyp=company",
            j=j)
        assert fired is False
        assert "bailout" in reason


def test_evidence_gloss_missing_data_preserves():
    assert gates.evidence_gloss_mismatch_veto("", "some evidence", 0.0)[0] is False
    assert gates.evidence_gloss_mismatch_veto("a gloss", "", 0.0)[0] is False
    assert gates.evidence_gloss_mismatch_veto(None, None, 0.0)[0] is False


def test_split_vote_veto_two_one_escalates():
    fired, reason = gates.split_vote_veto(
        votes_for=2, votes_total=3, failed=0)
    assert fired is True
    assert reason


def test_split_vote_veto_one_one_one_escalates():
    assert gates.split_vote_veto(1, 3, 0)[0] is True


def test_split_vote_veto_failed_vote_escalates():
    assert gates.split_vote_veto(2, 3, failed=1)[0] is True


def test_split_vote_veto_unanimous_preserves():
    assert gates.split_vote_veto(3, 3, 0)[0] is False
    assert gates.split_vote_veto(1, 1, 0)[0] is False


def test_split_vote_veto_missing_votes_preserves():
    assert gates.split_vote_veto(None, 3, 0)[0] is False
    assert gates.split_vote_veto(2, None, 0)[0] is False


def test_signal_quality_rank2_quality_beats_rank1():
    would, reason = gates.shadow_signal_quality_veto(
        rank1_fires=["Sd:hyp=move"],
        rank2_fires=["Sb:source", "Sd:hyp=light"])
    assert would is True
    assert reason


def test_signal_quality_rank1_generic_only():
    would, _ = gates.shadow_signal_quality_veto(
        rank1_fires=["Sd:hyp=move"],
        rank2_fires=["Sd:hyp=period"])
    assert would is True


def test_signal_quality_clean_pair_quiet():
    would, _ = gates.shadow_signal_quality_veto(
        rank1_fires=["Sa:j=0.27", "Sb:source"],
        rank2_fires=["Sd:hyp=move"])
    assert would is False


def test_signal_quality_empty_inputs_quiet():
    assert gates.shadow_signal_quality_veto([], [])[0] is False
    assert gates.shadow_signal_quality_veto(None, None)[0] is False


def test_apply_enforcing_split_routes_escalate_never_direct_link():
    out = gates.apply_v08_gates({
        "rank_index": 0, "winner_jaccard": 0.27,
        "winner_gloss": "a round fruit",
        "wordnet_evidence": "x a round fruit y",
        "winner_fires": ["Sa:j=0.27", "Sb:source"],
        "votes_for": 2, "votes_total": 3, "failed": 0,
        "rank1_fires": ["Sa:j=0.27", "Sb:source"],
        "rank2_fires": ["Sd:hyp=move"],
    })
    assert out["verdict"] == gates.ESCALATE
    assert "SplitVoteVeto" in out["fires"]
    assert out["verdict"] != gates.LINK


def test_apply_clean_unanimous_links():
    out = gates.apply_v08_gates({
        "rank_index": 0, "winner_jaccard": 0.27,
        "winner_gloss": "a round fruit",
        "wordnet_evidence": "x a round fruit y",
        "winner_fires": ["Sa:j=0.27", "Sb:source"],
        "votes_for": 3, "votes_total": 3, "failed": 0,
        "rank1_fires": ["Sa:j=0.27", "Sb:source"],
        "rank2_fires": ["Sd:hyp=move"],
    })
    assert out["verdict"] == gates.LINK
    assert out["fires"] == []
    assert out["signal_quality_would_fire"] is False


def test_apply_signal_quality_log_only_never_blocks():
    out = gates.apply_v08_gates({
        "rank_index": 0, "winner_jaccard": 0.27,
        "winner_gloss": "a round fruit",
        "wordnet_evidence": "x a round fruit y",
        "winner_fires": ["Sa:j=0.27", "Sb:source"],
        "votes_for": 3, "votes_total": 3, "failed": 0,
        "rank1_fires": ["Sd:hyp=move"],
        "rank2_fires": ["Sb:source", "Sd:topic=light"],
    })
    assert out["signal_quality_would_fire"] is True
    assert out["verdict"] == gates.LINK
    assert out["fires"] == []


def test_apply_empty_ctx_preserves_link():
    out = gates.apply_v08_gates(None)
    assert out["verdict"] == gates.LINK
    assert out["fires"] == []
    assert out["signal_quality_would_fire"] is False


def test_shipped_method_vocab_untouched_no_silent_rename():
    from factory.linker.linker import LINK_METHOD_VOCAB
    assert "JUDGE-REVIEW" in LINK_METHOD_VOCAB
    assert "JUDGE-PENDING" in LINK_METHOD_VOCAB
    assert gates.ESCALATE not in LINK_METHOD_VOCAB


def test_as_float_rejects_nonfinite_and_out_of_range():
    for bad in (float("nan"), "nan", float("inf"), "-inf", -1.0, 1.5):
        assert gates._as_float(bad) is None
    assert gates._as_float(0.0) == 0.0
    assert gates._as_float(1.0) == 1.0
    assert gates._as_float("0.27") == 0.27


def test_invalid_jaccard_fails_open_to_link():
    assert gates.low_rank_zero_overlap_veto(2, float("nan"), "apple", [])[0] is False
    assert gates.low_rank_zero_overlap_veto(2, -1.0, "apple", [])[0] is False
    assert gates.evidence_gloss_mismatch_veto(
        "a round fruit", "totally unrelated text", float("nan"))[0] is False
    out = gates.apply_v08_gates({
        "rank_index": 2, "winner_jaccard": float("nan"),
        "winner_gloss": "a round fruit",
        "wordnet_evidence": "totally unrelated text",
        "winner_fires": [],
        "votes_for": 3, "votes_total": 3, "failed": 0,
        "rank1_fires": [], "rank2_fires": [],
    })
    assert out["verdict"] == gates.LINK
