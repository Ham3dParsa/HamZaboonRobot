"""Sense-screening pruner (single owner of the sense-screening prune chain).

Pipeline position: AFTER the Kaikki index read, BEFORE the linker feed.
Input = one lemma's file-order sense dicts (raw Kaikki shapes tolerated:
``glosses``/``gloss``, ``tags``, ``topics``, ``categories`` (str or
``{"name": ...}`` dicts), ``examples`` (``{"text": ...}`` dicts or strs),
``form_of``); output = (kept, dropped, stats) with machine-readable
reason codes per drop.

Legs (locked, in order):
- R1 proper-noun leg: ``pos`` casefolded == ``"name"`` drops with
  ``DROP_PROPER_NOUN``; the organizational-acronym shape (gloss matching
  ``^initialism of`` + proper-name ``pos`` context + abbreviation-family
  tags) drops with ``DROP_OBSCURE_ACRONYM`` (shape rule, never word
  lists; checked before the plain proper drop so the acronym reason
  wins). Runs FIRST so proper names never twin-match.
- R2 hard drops: tags hitting the frozen ``OBSOLETE_TAGS`` set imported
  from :mod:`factory.precard.anchor` (never redefined here), plus
  referential stubs with no independent definition via anchor's existing
  detectors (``_is_formof_sense`` / ``detect_xref``, imported, never
  redefined). Reasons: ``obsolete``, ``form-of``, ``xref``.
- R4 niche guard: drops senses whose topics/categories are SOLELY in
  ``NICHE_TOPICS`` (casefolded, matched against both fields). A sense
  with ANY non-niche topic, or with no topics at all, survives.
  All other topics seen are counted into ``stats["topics_seen"]``
  (calibration feed, no product decision attached).
- R3 twin dedup: clusters senses with identical normalized gloss within
  the lemma; keeps the sense with the richest examples
  (most examples, then most example text, then file order); drops the
  rest with reason ``twin-of:<kept_id>``.

R2 dialectal signal is NEVER a drop: every KEPT sense of the full chain
carries an additive ``"flags"`` list including ``"dialectal"`` when its
tags hit the frozen ``DIALECTAL_TAGS`` set (casefolded). Other keys of
kept rows stay byte-identical; dropped rows carry reason only.

Standalone: no caller changes anywhere (R6). Pure functions, no I/O.
"""

from __future__ import annotations

import re

from factory.precard.anchor import OBSOLETE_TAGS, _is_formof_sense, detect_xref

# R4 niche set (locked): senses tagged ONLY with these go nowhere
# a learner needs. Casefolded at match time.
NICHE_TOPICS = frozenset({
    "nautical", "heraldry", "billiards", "cricket", "entomology",
})

REASON_OBSOLETE = "obsolete"
REASON_FORMOF = "form-of"
REASON_XREF = "xref"
REASON_NICHE = "niche"
REASON_PROPER_NOUN = "DROP_PROPER_NOUN"
REASON_OBSCURE_ACRONYM = "DROP_OBSCURE_ACRONYM"
TWIN_OF_PREFIX = "twin-of:"

# R2 dialectal signal (frozen, locked): NEVER a drop, only a kept-row flag.
# Casefolded at match time against sense_tags() output.
DIALECTAL_TAGS = frozenset({
    "dialectal", "uk", "northern-england", "midwestern-us",
    "southern-us", "scotland",
})

DIALECTAL_FLAG = "dialectal"

# R1 acronym shape (general rule by shape, not by word): anchored
# ``Initialism of ...`` gloss in a proper-name (pos == "name") context.
_INITIALISM_RX = re.compile(r"(?i)^\s*initialism\s+of\b")

# Abbreviation-family tags carrying the acronym shape (Kaikki spellings,
# casefolded at match time). Required alongside the gloss + pos legs so a
# bare "Initialism of" prose gloss without dataset abbreviation signal
# falls through to the plain proper-noun drop (still dropped).
_ACRONYM_SHAPE_TAGS = frozenset({"abbreviation", "initialism", "alt-of"})


def normalize_gloss(gloss):
    """Normalized twin key: casefolded, whitespace-collapsed, stripped."""
    if not isinstance(gloss, str):
        return ""
    return " ".join(gloss.casefold().split())


def sense_gloss(sense):
    """Raw gloss of a sense: first non-empty ``glosses[]``, else ``gloss``."""
    if not isinstance(sense, dict):
        return ""
    for cand in sense.get("glosses") or []:
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    gloss = sense.get("gloss")
    return gloss.strip() if isinstance(gloss, str) and gloss.strip() else ""


def sense_tags(sense):
    """Casefolded tag list of a sense ([] when missing/unreadable)."""
    if not isinstance(sense, dict):
        return []
    out = []
    for tag in sense.get("tags") or []:
        if isinstance(tag, str) and tag.strip():
            out.append(tag.strip().casefold())
    return out


def sense_topics(sense):
    """Normalized topic/category set of a sense (both fields, casefolded).

    Kaikki ``topics`` are plain strings; ``categories`` are ``{"name": ...}``
    dicts (bare strings tolerated). Empty/absent -> empty set (the niche
    guard cannot judge a topic-less sense, so it survives that leg).
    """
    if not isinstance(sense, dict):
        return set()
    found = set()
    for value in sense.get("topics") or []:
        if isinstance(value, str) and value.strip():
            found.add(value.strip().casefold())
    for value in sense.get("categories") or []:
        name = value.get("name") if isinstance(value, dict) else value
        if isinstance(name, str) and name.strip():
            found.add(name.strip().casefold())
    return found


def example_richness(sense):
    """(example count, example chars) of a sense; missing -> (0, 0).

    Items are ``{"text": ...}`` dicts or bare strings; non-text items
    count as zero-char examples (still counted — presence is signal).
    """
    if not isinstance(sense, dict):
        return (0, 0)
    examples = sense.get("examples")
    if not isinstance(examples, (list, tuple)):
        return (0, 0)
    chars = 0
    count = 0
    for item in examples:
        count += 1
        text = item.get("text") if isinstance(item, dict) else item
        if isinstance(text, str):
            chars += len(text)
    return (count, chars)


def sense_pos(sense):
    """Casefolded POS value(s) of a sense ([]-tolerant).

    Kaikki senses carry ``pos`` as a plain string; a list/tuple is
    tolerated (any element matching counts). Returns a list of
    casefolded non-empty values.
    """
    if not isinstance(sense, dict):
        return []
    raw = sense.get("pos")
    if isinstance(raw, (list, tuple)):
        out = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip().casefold())
            elif item is not None and str(item).strip():
                out.append(str(item).strip().casefold())
        return out
    if isinstance(raw, str):
        return [raw.strip().casefold()] if raw.strip() else []
    if raw is not None and str(raw).strip():
        return [str(raw).strip().casefold()]
    return []


def _pos_is_name(sense):
    return "name" in sense_pos(sense)


def _is_obscure_acronym(sense, gloss):
    """True on the organizational-acronym shape (R1, general, not word-list).

    Shape = anchored ``Initialism of ...`` gloss + proper-name ``pos``
    context + at least one abbreviation-family tag. Tag spellings are
    Kaikki dataset truth, casefolded at match time.
    """
    if not _INITIALISM_RX.match(gloss or ""):
        return False
    if not _pos_is_name(sense):
        return False
    return bool(set(sense_tags(sense)) & _ACRONYM_SHAPE_TAGS)


def needs_dialectal_flag(sense):
    """True when a sense's tags hit the frozen DIALECTAL_TAGS set."""
    return bool(set(sense_tags(sense)) & DIALECTAL_TAGS)


def with_dialectal_flags(sense):
    """Additive ``flags`` copy of a sense (input never mutated).

    Existing ``flags`` entries are preserved order-first; ``"dialectal"``
    is appended when needs_dialectal_flag() holds and not already
    present. All other keys keep their identical values.
    """
    flagged = dict(sense) if isinstance(sense, dict) else {}
    existing = flagged.get("flags")
    if isinstance(existing, (list, tuple)):
        merged = list(existing)
    elif existing is None:
        merged = []
    else:
        merged = [existing]
    if needs_dialectal_flag(sense) and DIALECTAL_FLAG not in merged:
        merged.append(DIALECTAL_FLAG)
    flagged["flags"] = merged
    return flagged


def _sense_id(sense, index, lemma=""):
    """Stable id: the sense's own, else ``<lemma>#<index>`` (``#<index>``)."""
    if isinstance(sense, dict):
        sid = sense.get("sense_id")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    prefix = ("%s#" % lemma) if lemma else "#"
    return "%s%d" % (prefix, index)


def _drop(sid, reason, gloss):
    return {"sense_id": sid, "reason": reason, "gloss": gloss}


def _obsolete_set():
    return {str(t or "").strip().casefold() for t in OBSOLETE_TAGS}


def _proper_pairs(pairs):
    """R1 on (sid, sense) pairs. Returns (kept_pairs, dropped).

    Acronym shape is checked before the plain proper drop so the
    ``DROP_OBSCURE_ACRONYM`` reason wins on overlap (both require
    pos == "name"; acronyms additionally match the initialism shape).
    """
    kept_p, dropped = [], []
    for sid, sense in pairs:
        gloss = sense_gloss(sense)
        if _is_obscure_acronym(sense, gloss):
            dropped.append(_drop(sid, REASON_OBSCURE_ACRONYM, gloss))
            continue
        if _pos_is_name(sense):
            dropped.append(_drop(sid, REASON_PROPER_NOUN, gloss))
            continue
        kept_p.append((sid, sense))
    return kept_p, dropped


def _hard_pairs(pairs):
    """R2 on (sid, sense) pairs. Returns (kept_pairs, dropped)."""
    obsolete = _obsolete_set()
    kept_p, dropped = [], []
    for sid, sense in pairs:
        gloss = sense_gloss(sense)
        if any(t in obsolete for t in sense_tags(sense)):
            dropped.append(_drop(sid, REASON_OBSOLETE, gloss))
            continue
        if _is_formof_sense(sense):
            dropped.append(_drop(sid, REASON_FORMOF, gloss))
            continue
        if detect_xref(gloss) is not None:
            dropped.append(_drop(sid, REASON_XREF, gloss))
            continue
        kept_p.append((sid, sense))
    return kept_p, dropped


def _niche_pairs(pairs):
    """R4 on (sid, sense) pairs. Returns (kept_pairs, dropped)."""
    kept_p, dropped = [], []
    for sid, sense in pairs:
        topics = sense_topics(sense)
        if topics and topics <= NICHE_TOPICS:
            dropped.append(_drop(sid, REASON_NICHE, sense_gloss(sense)))
            continue
        kept_p.append((sid, sense))
    return kept_p, dropped


def _twins_pairs(pairs):
    """R3 on (sid, sense) pairs. Returns (kept_pairs, dropped)."""
    clusters = {}
    for at, (sid, sense) in enumerate(pairs):
        key = normalize_gloss(sense_gloss(sense))
        if not key:
            continue
        clusters.setdefault(key, []).append(at)
    drop_at = {}
    for positions in clusters.values():
        if len(positions) < 2:
            continue
        ranked = sorted(
            positions,
            key=lambda a: (example_richness(pairs[a][1]), -a),
            reverse=True)
        winner = ranked[0]
        for at in ranked[1:]:
            drop_at[at] = TWIN_OF_PREFIX + pairs[winner][0]
    kept_p = [p for at, p in enumerate(pairs) if at not in drop_at]
    dropped = [_drop(pairs[at][0], drop_at[at], sense_gloss(pairs[at][1]))
               for at in sorted(drop_at)]
    return kept_p, dropped


def _pair_up(senses, lemma=""):
    senses = list(senses or [])
    return [(_sense_id(s, pos, lemma), s) for pos, s in enumerate(senses)]


def prune_proper_nouns(senses, lemma=""):
    """R1: proper-noun + obscure-acronym drops. Returns (kept, dropped)."""
    pairs = _pair_up(senses, lemma)
    kept_p, dropped = _proper_pairs(pairs)
    return [s for _, s in kept_p], dropped


def prune_hard_drops(senses, lemma=""):
    """R2: obsolete-tag + referential-stub drops. Returns (kept, dropped)."""
    pairs = _pair_up(senses, lemma)
    kept_p, dropped = _hard_pairs(pairs)
    return [s for _, s in kept_p], dropped


def collect_topic_stats(senses):
    """Normalized topic/category -> sense count over the given senses."""
    counts = {}
    for sense in senses or []:
        for topic in sense_topics(sense):
            counts[topic] = counts.get(topic, 0) + 1
    return counts


def prune_niche(senses, lemma=""):
    """R4: drop senses whose topics/categories are SOLELY niche.

    Returns (kept, dropped, topics_seen): ``topics_seen`` counts every
    normalized topic/category value observed on the input senses
    (calibration feed — niche values included, so the "solely" leg
    stays auditable).
    """
    pairs = _pair_up(senses, lemma)
    topics_seen = collect_topic_stats([s for _, s in pairs])
    kept_p, dropped = _niche_pairs(pairs)
    return [s for _, s in kept_p], dropped, topics_seen


def dedup_twins(senses, lemma=""):
    """R3: twin dedup on identical normalized gloss. Returns (kept, dropped).

    Winner per cluster = richest examples (count, then chars), file order
    breaks ties. Senses with an empty normalized gloss never cluster.
    Input list is never mutated. Drops carry ``twin-of:<kept_id>``.
    """
    pairs = _pair_up(senses, lemma)
    kept_p, dropped = _twins_pairs(pairs)
    return [s for _, s in kept_p], dropped


def prune_senses(senses, lemma=""):
    """Full sense-screening chain R1 -> R2 -> R4 -> R3. Returns (kept, dropped, stats).

    ``stats`` = {"total", "kept", "dropped", "topics_seen",
    "reason_counts", "example_counts"} (twin drops count under the
    ``twin-of`` base key; ``example_counts`` = {"with_example", n,
    "zero_example", m} counted over the INPUT senses, no drops involved).
    Fallback sense ids (``<lemma>#<file-order>``) stay stable across legs.
    Kept rows carry the additive ``"flags"`` list (``"dialectal"`` when
    the sense's tags hit ``DIALECTAL_TAGS`` — never a drop); all other
    kept keys stay identical, dropped rows carry reason only.
    Pure: no I/O, inputs never mutated.
    """
    pairs = _pair_up(senses, lemma)

    topics_seen = collect_topic_stats([s for _, s in pairs])
    with_example = sum(1 for _, s in pairs if example_richness(s)[0] > 0)
    kept_p, all_dropped = _proper_pairs(pairs)
    kept_p, hard_dropped = _hard_pairs(kept_p)
    all_dropped += hard_dropped
    kept_p, niche_dropped = _niche_pairs(kept_p)
    all_dropped += niche_dropped
    kept_p, twin_dropped = _twins_pairs(kept_p)
    all_dropped += twin_dropped

    kept = [with_dialectal_flags(s) for _, s in kept_p]
    reason_counts = {}
    for drop in all_dropped:
        reason = drop["reason"]
        base = "twin-of" if reason.startswith(TWIN_OF_PREFIX) else reason
        reason_counts[base] = reason_counts.get(base, 0) + 1
    stats = {"total": len(pairs), "kept": len(kept),
             "dropped": len(all_dropped), "topics_seen": topics_seen,
             "reason_counts": reason_counts,
             "example_counts": {"with_example": with_example,
                                "zero_example": len(pairs) - with_example}}
    return kept, all_dropped, stats
