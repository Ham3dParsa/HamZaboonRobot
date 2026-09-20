"""v0.8 gate-core for the enrich path (F3, pure, hermetic).

Single source of truth for gate verdicts in the repo. Stdlib only; no
I/O, no network, no model calls. Semantics mirror the frozen judgeops
tooling (READ-ONLY source, never imported)::

    W:\\hamzaban_data_factory\\proof-linker\\judgeops\\gates_r.py

Old -> new domain-name mapping (CONTRACT-linker.md ADOPTED 2026-09-19;
history files and shipped table/code method strings are untouched —
see the no-silent-rename test in tests/factory/test_linker_gates.py):

- Gate A -> LowRankZeroOverlapVeto
- Gate B -> EvidenceGlossMismatchVeto
- 2-1 rule -> SplitVoteVeto (ANY non-unanimous verdict)
- Idea1-Step 1 -> SignalQualityVeto (LOG-ONLY until calibration lands)
- JUDGE-REVIEW label -> ESCALATE:HUMAN_QUEUE

Enforcement (locked):

- LowRankZeroOverlapVeto / EvidenceGlossMismatchVeto / SplitVoteVeto
  are ENFORCING: any fire routes to ESCALATE:HUMAN_QUEUE, never a
  direct LINK.
- SignalQualityVeto is LOG-ONLY: apply_v08_gates records its
  would-fire verdict per row but NEVER blocks a direct LINK and NEVER
  routes. Flip to enforcing needs a new explicit lock after
  calibration numbers exist.
- Missing/invalid signals fail OPEN to LINK (missing data never
  routes a row — same preserve rule as the judgeops source).
- Table v4.x builds are untouched (table builds are not software
  versions); no IDs or words are baked in anywhere here.
"""

from __future__ import annotations

import math
import re

LINK = "LINK"

ESCALATE = "ESCALATE:HUMAN_QUEUE"

LOW_RANK_ZERO_OVERLAP_VETO = "LowRankZeroOverlapVeto"

EVIDENCE_GLOSS_MISMATCH_VETO = "EvidenceGlossMismatchVeto"

SPLIT_VOTE_VETO = "SplitVoteVeto"

SIGNAL_QUALITY_VETO = "SignalQualityVeto"

BAILOUT_J = 0.20


def _as_int(value):
    """int(value) or None (bools and hostile shapes never count)."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value):
    """float(value) or None (bools, non-finite and out-of-range never count).

    Jaccard lives in 0.0..1.0 — nan/inf/negative/>1.0 inputs are invalid
    signals, so they map to None and every gate fails OPEN to LINK.
    """
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        return None
    return result


def _fire_list(value):
    """winner/rank fires as a cleaned list (None/hostile -> [])."""
    if not isinstance(value, (list, tuple)):
        return []
    return [str(f or "").strip() for f in value if str(f or "").strip()]


def gloss_in_evidence(winner_gloss, wordnet_evidence):
    """Paren-tolerant substring (parity with the judgeops source).

    The winner gloss with parentheticals stripped (then collapsed,
    lowercased) must sit whole inside the evidence; the raw gloss is
    the fallback. No token fallback — a single shared word must NOT
    pass.
    """
    if not winner_gloss or not wordnet_evidence:
        return False
    try:
        gloss = re.sub(r"\([^)]*\)", " ", str(winner_gloss))
        gloss = re.sub(r"\s+", " ", gloss).strip().lower()
        if gloss and gloss in str(wordnet_evidence).lower():
            return True
        raw = re.sub(r"\s+", " ", str(winner_gloss)).strip().lower()
        return bool(raw) and raw in str(wordnet_evidence).lower()
    except Exception:
        return False


def short_gloss_head_equals_lemma(lemma, winner_fires):
    """Per-row mechanical guard: an Sb: headword exactly equals the lemma.

    Case-insensitive exact string equality — no stemming, no fixed word
    list, no per-row exemption table.
    """
    try:
        lowered = (lemma or "").strip().lower()
    except Exception:
        return False
    if not lowered:
        return False
    for fire in _fire_list(winner_fires):
        if fire.startswith("Sb:"):
            heads = [h.strip().lower() for h in fire[3:].split(",")]
            if lowered in heads:
                return True
    return False


def low_rank_zero_overlap_veto(rank_index, j, lemma, winner_fires):
    """Gate A: rank>=2 AND j<=0 -> ESCALATE, with preserve guards.

    Guards (preserve LINK): j>0, or a short-gloss headword exactly
    equals the lemma. The j==0.0 boundary with no guard match stays
    ESCALATE. Missing rank/j preserve (never route on missing data).
    Returns (fired, reason).
    """
    rank = _as_int(rank_index)
    overlap = _as_float(j)
    if rank is None or overlap is None:
        return (False, "no-rank-or-j:preserve")
    if overlap > 0.0:
        return (False, "guard:j>0:preserve")
    if short_gloss_head_equals_lemma(lemma, winner_fires):
        return (False, "guard:short-gloss-head-equals-lemma:preserve")
    if rank >= 2 and overlap <= 0.0:
        return (True, "rank>=2&j<=0")
    return (False, "keep")


def evidence_gloss_mismatch_veto(winner_gloss, wordnet_evidence, j):
    """Gate B: winner gloss must sit in wordnet_evidence (paren-tolerant).

    MANDATORY BAILOUT: j>=0.20 (j==1.0 subsumed) -> skip B entirely.
    Missing gloss/evidence preserves LINK (never route on missing
    data). Invalid j (missing/non-finite/out-of-range) also preserves
    LINK per the locked fail-open rule. Returns (fired, reason).
    """
    overlap = _as_float(j)
    if overlap is None:
        return (False, "invalid-j:preserve")
    if overlap >= BAILOUT_J:
        return (False, "bailout:j>=0.20:skip")
    if not winner_gloss or not wordnet_evidence:
        return (False, "missing-gloss-or-evidence:preserve")
    if gloss_in_evidence(winner_gloss, wordnet_evidence):
        return (False, "gloss-quoted")
    return (True, "evidence-lacks-gloss")


def split_vote_veto(votes_for, votes_total, failed=0):
    """SplitVoteVeto: ANY non-unanimous verdict -> ESCALATE, never LINK.

    Fires on 2-1, 1-1-1, or any failed/parse-fail vote riding along
    (a 2-agree + 1-failed row is still a split). Unanimous N-of-N is
    the only quiet shape. Missing/invalid tallies preserve (never
    route on missing data). Returns (fired, reason).
    """
    agreed = _as_int(votes_for)
    total = _as_int(votes_total)
    bad = _as_int(failed)
    if bad is None:
        bad = 0
    if agreed is None or total is None or total <= 0:
        return (False, "no-vote-tally:preserve")
    if agreed < 0 or agreed > total or bad < 0:
        return (False, "invalid-tally:preserve")
    if bad > 0:
        return (True, "failed-vote-present:split")
    if agreed != total:
        return (True, "non-unanimous:split")
    return (False, "unanimous:keep")


def _has_quality_signal(fires):
    """True iff the fire list carries an Sb: or Sd:topic= signal."""
    for fire in _fire_list(fires):
        if fire.startswith("Sb:") or fire.startswith("Sd:topic="):
            return True
    return False


def _is_generic_only(fires):
    """True iff the fires are non-empty and every one is Sd:hyp=."""
    cleaned = _fire_list(fires)
    return bool(cleaned) and all(f.startswith("Sd:hyp=") for f in cleaned)


def signal_quality_would_fire(rank1_fires, rank2_fires):
    """SignalQualityVeto (LOG-ONLY): would-block iff rank-2 beats rank-1.

    Fires when rank-2 carries a higher-quality signal (Sb: or
    Sd:topic=) that rank-1 lacks, or when rank-1 signals are
    generic-only (Sd:hyp=). Structural rule, no token list. The caller
    (apply_v08_gates) records this verdict but NEVER routes on it —
    calibration is pending. Returns (would_fire, reason).
    """
    rank1 = _fire_list(rank1_fires)
    rank2 = _fire_list(rank2_fires)
    if not rank1 and not rank2:
        return (False, "no-fires:quiet")
    if _is_generic_only(rank1):
        return (True, "rank1-generic-only")
    if _has_quality_signal(rank2) and not _has_quality_signal(rank1):
        return (True, "rank2-higher-quality-beats-rank1")
    return (False, "keep")


def apply_v08_gates(ctx):
    """Full v0.8 pipeline for one enrich row. Returns a verdict dict.

    ctx keys (all optional; missing signals fail open to LINK):

    - rank_index, winner_jaccard, lemma, winner_fires
    - winner_gloss, wordnet_evidence
    - votes_for, votes_total, failed
    - rank1_fires, rank2_fires (SignalQuality inputs)

    Enforcing vetoes route to ESCALATE:HUMAN_QUEUE; SignalQuality is
    annotation-only and never appears in "fires".
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    fires = []
    reasons = {}

    veto_fired, veto_reason = low_rank_zero_overlap_veto(
        ctx.get("rank_index"), ctx.get("winner_jaccard"),
        ctx.get("lemma"), ctx.get("winner_fires"))
    reasons[LOW_RANK_ZERO_OVERLAP_VETO] = veto_reason
    if veto_fired:
        fires.append(LOW_RANK_ZERO_OVERLAP_VETO)

    mismatch_fired, mismatch_reason = evidence_gloss_mismatch_veto(
        ctx.get("winner_gloss"), ctx.get("wordnet_evidence"),
        ctx.get("winner_jaccard"))
    reasons[EVIDENCE_GLOSS_MISMATCH_VETO] = mismatch_reason
    if mismatch_fired:
        fires.append(EVIDENCE_GLOSS_MISMATCH_VETO)

    split_fired, split_reason = split_vote_veto(
        ctx.get("votes_for"), ctx.get("votes_total"),
        ctx.get("failed", 0))
    reasons[SPLIT_VOTE_VETO] = split_reason
    if split_fired:
        fires.append(SPLIT_VOTE_VETO)

    would_fire, quality_reason = signal_quality_would_fire(
        ctx.get("rank1_fires"), ctx.get("rank2_fires"))

    return {
        "verdict": ESCALATE if fires else LINK,
        "fires": fires,
        "reasons": reasons,
        "signal_quality_would_fire": would_fire,
        "signal_quality_reason": quality_reason,
    }
