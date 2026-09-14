"""Topics (topic_vectors + topic_label stages): vectors, labels, guard.

SOLE owner of the label set inside factory/precard: the live 16 heads,
frozen copy from factory/archive/v14_v16/run_v16b_topup (provenance:
LABELS16, 2026-09-14). The v14-era 13-head names (Society & Culture,
Work & Education) are NOT valid here — the guard below rewired to live
names fixes the invalid-label bug the old home carried.
"""

from __future__ import annotations

import re

from factory.precard.judge import fanout_picks

LABELS = ["Daily Life & Home", "Food & Drink", "Health & Body",
          "Work & Careers", "Education & Exams", "Travel & Transportation",
          "Society", "Arts & Culture", "Animals & Living Beings",
          "Nature & Environment", "Science & Technology",
          "Business & Economy", "Law & Politics", "Sports & Leisure",
          "Emotions & Relationships", "Other / Abstract"]

# Method tag frozen from factory/pipeline/card_pilot TOPIC_METHOD_TAG
# (provenance: precard line, 2026-09-14).
TOPIC_METHOD = "v16b-exact"

_OTHER_ABSTRACT = "Other / Abstract"
_ANIMALS_LABEL = "Animals & Living Beings"

# (lemma -> [(gloss keyword, concrete live label)]). Fires ONLY when the
# incoming label is Other / Abstract, so a real leg-1/LLM label is never
# overridden.
_ABSTRACT_REANCHOR = {
    "call": [(("telephone", "phone"), "Science & Technology"),
             ((), "Society")],
    "working": [(("employ", "job", "work"), "Work & Careers")],
    "spectacle": [(("perform", "show", "event", "display"), "Society")],
    "accrue": [(("accumulat", "money", "interest", "financ"),
                "Business & Economy")],
    "elevate": [(("lift", "raise"), "Daily Life & Home")],
}

_GENDER_BIO_RX = None
_GENDER_BIO_SRC = (r"\b(biological sex|reproduct|anatom|hormon|"
                   r"menstruat|pregnan)\b")
_GENDER_SIGNAL_RX = None
_GENDER_SIGNAL_SRC = (r"\b(gender|sex|male|female|masculine|feminine|"
                      r"man|men|woman|women)\b")


def _gender_bio_rx():
    """Compiled biological-sex gloss signal (lazy, import-safe)."""
    global _GENDER_BIO_RX
    if _GENDER_BIO_RX is None:
        _GENDER_BIO_RX = re.compile(_GENDER_BIO_SRC, re.IGNORECASE)
    return _GENDER_BIO_RX


def _gender_signal_rx():
    """Compiled sex/gender mention signal (word-boundaried — "manage"
    and "performance" must not match "man")."""
    global _GENDER_SIGNAL_RX
    if _GENDER_SIGNAL_RX is None:
        _GENDER_SIGNAL_RX = re.compile(_GENDER_SIGNAL_SRC, re.IGNORECASE)
    return _GENDER_SIGNAL_RX


def single_topic_vector(label):
    """Single-label fallback: [{label, 1.0}]."""
    return [{"label": label or "Other / Abstract", "weight": 1.0}]


def topic_post_guard(text, gloss, label):
    """Deterministic topic post-guard (single owner).

    Narrow by design — it only ever remaps two failure modes, never a
    real label:
    - gender leak: an Animals & Living Beings label on a sex/gender
      gloss moves to Health & Body (biological cue) or Society
      (social-role default).
    - abstract dumping: an Other / Abstract label on a re-anchored
      (lemma, gloss-keyword) concept moves to its concrete domain.
    Everything else passes through unchanged (fail-closed to the
    incoming label on any hostile input).
    """
    try:
        lab = (label or "").strip()
        lemma = (text or "").strip().lower()
        gloss_l = (gloss or "").lower()
    except Exception:
        return label
    if lab == _ANIMALS_LABEL:
        blob = lemma + " " + gloss_l
        if _gender_signal_rx().search(blob):
            if _gender_bio_rx().search(gloss or ""):
                return "Health & Body"
            return "Society"
        return lab
    if lab == _OTHER_ABSTRACT:
        for keywords, concrete in _ABSTRACT_REANCHOR.get(lemma, []):
            if not keywords or any(k in gloss_l for k in keywords):
                return concrete
    return lab


def apply_topic_guard(row, text, gloss):
    """Remap a label row through topic_post_guard.

    When the guard changes the label, the vector is replaced with the
    single-label fallback (the old vector described the old label).
    Returns the same dict object (mutated); hostile rows pass through.
    """
    try:
        if not isinstance(row, dict):
            return row
        new_label = topic_post_guard(text, gloss, row.get("label"))
        if new_label and new_label != row.get("label"):
            row["label"] = new_label
            row["vector"] = single_topic_vector(new_label)
            row["topic_guarded"] = True
    except Exception:
        pass
    return row


def vectors_pseudo_records(batch, judge_map, anchor_map):
    """Group batch picks into run_v15 pseudo lemma records.

    Every fanned-out pick (primary + judged secondaries) joins the
    pseudo record, so the vectors leg returns a vector per picked sense
    (deduped by sense_id).
    """
    groups = {}
    for item in batch:
        key = (("w:" if item.get("kind") == "word" else "p:")
               + item.get("text", ""))
        pick = (judge_map.get(key) or {})
        lemma = (item.get("text") or "").strip()
        rec = groups.setdefault(
            lemma, {"lemma": lemma, "ranked_senses": []})
        for sub in fanout_picks(item, pick):
            sid = sub.get("sense_id", "")
            if not sid:
                continue
            if all(s["sense_id"] != sid for s in rec["ranked_senses"]):
                gloss = sub.get("gloss", "") or (
                    anchor_map.get(key) or {}).get("en_def", "")
                rec["ranked_senses"].append(
                    {"sense_id": sid, "gloss": gloss,
                     "topic_label": "Other / Abstract"})
    return list(groups.values())


def label_fallback_result(vector_lookup, sense_id):
    """Fail-closed label row (Other / Abstract, dataset vector known)."""
    vec = (vector_lookup or {}).get(sense_id)
    return {"label": "Other / Abstract",
            "method": TOPIC_METHOD,
            "vector": list(vec) if vec
            else single_topic_vector("Other / Abstract"),
            "topic_path": "fallback"}
