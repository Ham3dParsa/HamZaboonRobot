"""Sense judge (sense_judge stage): multi-pick validation + veto.

Moved verbatim from factory/pipeline/precard_pipeline (provenance:
precard line R1-R6/F4, 2026-09-14); only the imports changed (intra-
package) and two names went public (judge_prompt, apply_inflection_veto).
Vendored with it: LEVEL_N + validate_picks + JUDGE_MODELS (frozen copy
from factory/archive/v14_v16/run_v14_phase3_judge) and the inflection /
superlative stub predicates (frozen copy from factory/pipeline/card_pilot).
"""

from __future__ import annotations

import re

from factory.precard.accounting import item_key
from factory.precard.ids import normalize_id_part

MAX_FANOUT = 4

LEVEL_N = (("beginner", 2), ("intermediate", 3), ("advanced", 4))

JUDGE_MODELS = ["muse-spark-1.3-contributor-free",
                "muse-spark-1.2-contributor-free",
                "ling-3.0-flash-fin-free", "mimo-v2.5-free",
                "nemotron-3.5-lightning-free"]


def validate_picks(picks, input_ids):
    """Frozen copy of factory/archive/v14_v16/run_v14_phase3_judge."""
    if not isinstance(picks, dict):
        return False
    for lvl, n in LEVEL_N:
        want = min(n, len(input_ids))
        lst = picks.get(lvl)
        if not isinstance(lst, list) or len(lst) != want:
            return False
        if any(i not in input_ids for i in lst) or len(set(lst)) != len(lst):
            return False
    return True


_INFLECTION_RX = re.compile(
    r"(?i)\b(?:plural|past(?:\s+participle)?|present\s+participle"
    r"(?:\s+and\s+gerund)?|gerund|comparative(?:\s+degree)?|"
    r"superlative(?:\s+degree)?|third(?:-|\s+)person\s+singular)"
    r"\s+of\b")


def is_inflection_gloss(gloss):
    """Frozen copy from factory/pipeline/card_pilot (R36)."""
    return bool(_INFLECTION_RX.search(gloss or ""))


_SUPERLATIVE_RX = re.compile(
    r"(?i)^\s*(?:superlative|comparative)(?:\s+form)?\s+of\s+(.+?)\s*\.?\s*$")


def is_superlative_gloss(gloss):
    """Frozen copy from factory/pipeline/card_pilot (R44)."""
    return bool(_SUPERLATIVE_RX.search(gloss or ""))


def judge_fallback(item, anchor_res):
    """Fail-closed pick: anchor-top first candidate.

    The old home routed scoreless pseudo-entries through the archive
    deterministic_picks, which provably returns input order there
    (no scores, no EVP entries), so [0] is the anchor top either way
    (pinned by test_fallback_matches_archive_first_candidate).
    """
    cands = (anchor_res or {}).get("candidates", [])
    if not cands:
        return {"sense_id": "", "gloss": "", "model": "s1-fallback-empty",
                "picks": []}
    first = cands[0]["sense_id"]
    gloss = cands[0].get("gloss", "")
    return {"sense_id": first, "gloss": gloss, "model": "s1-fallback",
            "picks": [{"sense_id": first, "gloss": gloss}]}


def judge_prompt(batch, anchor_map):
    lines = ["PICK the 1-4 most useful senses per item for Persian "
             "learners of English, ordered most-useful-first (one card "
             "= one atomic sense downstream, so rank every sense worth "
             "its own card).",
             "Prioritization hierarchy:",
             "1. High-frequency tangible and conversational meaning over "
             "technical, academic, or domain-specific jargon (e.g., "
             "cooking/water boil > thermodynamic boil), UNLESS the item's "
             "pool_level is C1/C2 or all candidates are strictly "
             "abstract/technical.",
             "2. Modern living usage over archaic, obsolete, or highly "
             "regional dialectal senses.",
             "3. If candidates contain both an independent lexical meaning "
             "and a purely grammatical/inflectional reference, ALWAYS pick "
             "the independent lexical meaning.",
             "4. For modal/auxiliary verbs (would, could, should), the "
             "grammatical main sense takes absolute precedence over any "
             "nominal or philosophical sense.",
              "",
              'Output: {"results": [{"key": "<item key>", '
              '"picks": ["<sense_id>", ... up to 4]}]}.',
              "A single \"pick\": \"<sense_id>\" row is also accepted "
              "(one sense).",
              "Every pick MUST be one of that item's candidate ids "
              "(empty picks only when the item has no candidates).",
              "Input follows:"]
    for item in batch:
        key = item_key(item)
        cands = (anchor_map.get(key) or {}).get("candidates", [])
        lines.append("KEY %s (%s, pool %s):" % (
            key, item.get("kind", "?"), item.get("pool_level", "?")))
        for cand in cands:
            tags = sorted((cand.get("tags") or []))
            tag_bit = " [%s]" % ", ".join(tags) if tags else ""
            lines.append("- %s%s %s" % (cand.get("sense_id", "?"), tag_bit,
                                        (cand.get("gloss") or "")[:200]))
        if not cands:
            lines.append("- (no candidates)")
    return "\n".join(lines)


def judge_validate_multi(data, batch, anchor_map):
    """Validate ordered multi-pick {"key","picks":[...]} rows (R1).

    Each pick must be one of the item's candidate ids; unknown ids are
    dropped, duplicates collapse (first wins), the list caps at
    MAX_FANOUT. A legacy single {"key","pick"} row is accepted as a
    one-pick list (same shape _judge_validate accepts, including its
    lemma-style "picks"-dict collapse to the first pick and the empty
    pick for candidatelss items). Returns {key: {"sense_id", "gloss",
    "picks": [{sense_id, gloss}, ...]}} with sense_id/gloss = the
    primary (first) pick — downstream stages keep reading those keys
    unchanged. Invalid rows are left out (caller fails closed); None
    unless every batch item validates.
    """
    if not isinstance(data, dict) or not isinstance(
            data.get("results"), list):
        return None
    by_key = {}
    for row in data["results"]:
        if isinstance(row, dict) and "key" in row:
            by_key[row["key"]] = row
    out = {}
    for item in batch:
        key = item_key(item)
        row = by_key.get(key)
        cands = (anchor_map.get(key) or {}).get("candidates", [])
        ids = [c["sense_id"] for c in cands]
        gloss_of = {c["sense_id"]: c.get("gloss", "") for c in cands}
        if not isinstance(row, dict):
            continue
        raw_picks = row.get("picks")
        if raw_picks is None and row.get("pick") is not None:
            raw_picks = [row.get("pick")]
        if isinstance(raw_picks, dict):
            if validate_picks(raw_picks, ids):
                flat = (row["picks"].get("beginner")
                        or row["picks"].get("intermediate")
                        or row["picks"].get("advanced") or [])
                raw_picks = flat[:1] if flat else None
            else:
                continue
        if not isinstance(raw_picks, list):
            continue
        seen, seen_gloss, picks = set(), set(), []
        for sid in raw_picks:
            if not isinstance(sid, str) or sid in seen:
                continue
            if sid == "" and not ids:
                continue
            if sid in ids and len(picks) < MAX_FANOUT:
                norm_gloss = normalize_id_part(gloss_of.get(sid, ""))
                if norm_gloss in seen_gloss:
                    continue
                seen.add(sid)
                seen_gloss.add(norm_gloss)
                picks.append({"sense_id": sid,
                              "gloss": gloss_of.get(sid, "")})
        if not picks:
            if not ids and not any(
                    isinstance(s, str) and s != "" for s in raw_picks):
                out[key] = {"sense_id": "", "gloss": "", "picks": []}
            continue
        out[key] = {"sense_id": picks[0]["sense_id"],
                    "gloss": picks[0]["gloss"], "picks": picks}
    want = {item_key(i) for i in batch}
    if set(out) != want:
        return None
    return out


def _judge_validate(data, batch, anchor_map):
    """Accept single {"key","pick"} rows (plus lemma-style "picks" rows).

    Thin single-pick view over judge_validate_multi: multi-pick rows
    collapse to their primary pick. Returns {key: {"sense_id","gloss"}}
    for valid rows only; invalid rows are left out (caller fails closed).
    """
    multi = judge_validate_multi(data, batch, anchor_map)
    if multi is None:
        return None
    return {k: {"sense_id": v["sense_id"], "gloss": v["gloss"]}
            for k, v in multi.items()}


def fanout_picks(item, pick_entry):
    """Ordered [{sense_id, gloss}] for one item's precard rows (R1).

    Primary first, then judged secondaries (capped at MAX_FANOUT);
    entries without a stored picks list fan out to their single pick.
    Dedupes by sense_id AND normalized gloss: kaksi duplicate glosses
    across senses (call#2/call#0 "To reach out with one's voice") are
    the same atomic sense — emitting both would fork two identical
    cards under one pre_card_id. Covers legacy stored picks too (all
    stages read through this choke point).
    """
    try:
        picks = (pick_entry or {}).get("picks")
        if isinstance(picks, list) and picks:
            out, seen_sid, seen_gloss = [], set(), set()
            for pick in picks[:MAX_FANOUT]:
                if not isinstance(pick, dict) or not pick.get("sense_id"):
                    continue
                norm_gloss = normalize_id_part(pick.get("gloss", ""))
                if pick["sense_id"] in seen_sid or norm_gloss in seen_gloss:
                    continue
                seen_sid.add(pick["sense_id"])
                seen_gloss.add(norm_gloss)
                out.append({"sense_id": pick["sense_id"],
                            "gloss": pick.get("gloss", "")})
            if out:
                return out
        sid = (pick_entry or {}).get("sense_id", "")
        return [{"sense_id": sid,
                 "gloss": (pick_entry or {}).get("gloss", "")}]
    except Exception:
        return [{"sense_id": "", "gloss": ""}]


def _veto_inflection_pick(pick, anchor_res):
    """F4 post-judge veto: (sense_id, gloss) with stub picks corrected.

    When the picked gloss is a mechanical-inflection reference (S0b
    verdict-path predicates: is_inflection_gloss / is_superlative_gloss
    — both "of"-requiring, so a real gloss like "a comparative study"
    never vetoes), the judge crowned a stub
    (removed/forcing/wondering/better): fall back to the anchor-top
    non-stub — the first window candidate in anchor order whose gloss
    is NOT such a reference. Anything else (real pick, empty pick,
    all-stub window) returns the pick unchanged — a veto reroutes, it
    never drops, so uncertainty keeps the item. The judge model tag is
    untouched (the sense_id change is visible in s2 progress); the
    predicates live in card_pilot (single source, reused by import —
    the veto inherits their exact boundary, including whole-gloss
    superlative anchoring).
    """
    sid = (pick or {}).get("sense_id", "")
    gloss = (pick or {}).get("gloss", "")
    if not sid or not gloss or not _is_veto_stub_gloss(gloss):
        return sid, gloss
    for cand in (anchor_res or {}).get("candidates", []) or []:
        if cand.get("sense_id") \
                and not _is_veto_stub_gloss(cand.get("gloss", "")):
            return cand.get("sense_id", ""), cand.get("gloss", "")
    return sid, gloss


def _is_veto_stub_gloss(gloss):
    """F4 stub predicate: vendored S0b verdict-path predicates below."""
    return bool(is_inflection_gloss(gloss)
                or is_superlative_gloss(gloss))


def apply_inflection_veto(out, batch, anchor_map):
    """F4: veto every stub pick in a judge_batch result dict, in place."""
    for item in batch:
        key = item_key(item)
        if key in out:
            sid, gloss = _veto_inflection_pick(
                out[key], (anchor_map or {}).get(key))
            out[key]["sense_id"], out[key]["gloss"] = sid, gloss
            # v14.1: the veto reroutes every fanned-out pick, not just
            # the primary — a stub crowned second still falls back to
            # the anchor-top non-stub (veto reroutes, never drops).
            # Stub picks vetoed onto the same anchor sense collapse
            # (first wins) — one card per atomic sense, never twins.
            vetoed, veto_seen = [], set()
            for pick in (out[key].get("picks") or []):
                vsid, vgloss = _veto_inflection_pick(
                    pick, (anchor_map or {}).get(key))
                if vsid in veto_seen:
                    continue
                veto_seen.add(vsid)
                vetoed.append({"sense_id": vsid, "gloss": vgloss})
            if vetoed:
                out[key]["picks"] = vetoed
                out[key]["sense_id"] = vetoed[0]["sense_id"]
                out[key]["gloss"] = vetoed[0]["gloss"]
    return out
