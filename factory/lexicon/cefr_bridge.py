"""kaikki -> WordNet sense-CEFR bridge (input leg, stdlib only).

Joins kaikki lemma+POS lookups onto the WordNet sensekey->CEFR table
(``wordnet_sensekey_cefr.tsv``: no header, ``sensekey<TAB>CEFR`` rows)
without needing WordNet glosses: disambiguation reuses the EVP subset
guidewords (guideword-in-gloss, same pattern as the v16
``evp_fallback_label``), intersected with the TSV candidate CEFRs.

Locked cascade (contract R3, owner "locked"):
  candidates ∩ EVP-guideword-gloss-match -> that CEFR ("wn-evp-gloss");
  elif single TSV row -> it ("wn-single");
  else min CEFR over candidates ("wn-lemma-min");
  no rows -> (None, "unmapped").

WordNet POS numbers: 1 noun, 2 verb, 3 adj, 4 adv, 5 satellite-adj
(satellites join the adj bucket). Unknown kaikki POS spellings fall back
to all-POS candidates for the lemma (coverage over precision).

Only dependency: stdlib + ``factory.core.registry`` normalizers (lemma
normalization is single-sourced there; the kaikki-spelling -> WN-number
table below is owned HERE — it is WordNet-side vocabulary, not a copy
of the kaikki alias map). No network, no embeddings, no LLM. Missing
TSV / malformed lines fail closed (empty map / skip + count, never
raise), so hermetic tests and CI stay green without W:.
"""

from __future__ import annotations

import json
import os
import re
import sys

FACTORY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(FACTORY_DIR)
if REPO_ROOT not in sys.path:  # noqa: E402 (script-mode + `python -m` both work)
    sys.path.insert(0, REPO_ROOT)  # noqa: E402
from factory.core.registry import normalize_lemma, normalize_pos  # noqa: E402

DEFAULT_TSV = (
    "W:/hamzaban_data_factory/fixtures/cefr-wordnet/wordnet_sensekey_cefr.tsv"
)
DEFAULT_EVP = os.path.join(FACTORY_DIR, "packs", "en", "evp_sense.json")

CEFR_ORDER = ("A1", "A2", "B1", "B2", "C1", "C2")
_CEFR_RANK = {level: i for i, level in enumerate(CEFR_ORDER)}

# kaikki POS spelling (already registry-normalized: stripped + lowercased)
# -> WordNet POS numbers. Satellite adjectives (%5) join the adj bucket.
WN_POS = {
    "noun": {1},
    "verb": {2},
    "adj": {3, 5},
    "adjective": {3, 5},
    "adv": {4},
    "adverb": {4},
}
_ALL_POSNUMS = {1, 2, 3, 4, 5}

METHOD_SINGLE = "wn-single"
METHOD_EVP_GLOSS = "wn-evp-gloss"
METHOD_LEMMA_MIN = "wn-lemma-min"
METHOD_UNMAPPED = "unmapped"

_CACHE: dict = {}


def clear_cache():
    """Drop cached bridge/EVP maps (tests re-point DEFAULT_* per case)."""
    _CACHE.clear()


def parse_sensekey(sensekey):
    """Parse a WordNet sensekey into (lemma, posnum) or None when malformed.

    Sensekey shape: ``lemma%posnum:...`` (multiword lemmas use
    underscores, e.g. ``credit_card%1:06:00::``). Unknown POS numbers and
    empty lemmas are malformed (fail-closed: caller skips + counts).
    """
    if not isinstance(sensekey, str) or "%" not in sensekey:
        return None
    head, _, tail = sensekey.partition("%")
    try:
        posnum = int((tail.split(":") or [""])[0])
    except (TypeError, ValueError):
        return None
    if posnum not in _ALL_POSNUMS:
        return None
    try:
        lemma = normalize_lemma(head.replace("_", " "))
    except ValueError:
        return None
    return lemma, posnum


def load_tsv(path):
    """Load the sensekey->CEFR TSV into {(lemma, posnum): [(sensekey, cefr)]}.

    Returns (bridge, stats) with stats {path, rows, skipped}. Missing /
    unreadable files fail closed to ({}, stats) — never raise — so
    callers (and CI without W:) degrade to "unmapped" instead of
    crashing. Malformed lines (no tab, bad sensekey, unknown CEFR) are
    skipped and counted, never silent (the count is in stats).
    """
    bridge: dict = {}
    stats = {"path": str(path), "rows": 0, "skipped": 0}
    try:
        handle = open(str(path), encoding="utf-8")
    except OSError:
        return bridge, stats
    with handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                stats["skipped"] += 1
                continue
            parsed = parse_sensekey(parts[0].strip())
            cefr = parts[1].strip()
            if parsed is None or cefr not in _CEFR_RANK:
                stats["skipped"] += 1
                continue
            lemma, posnum = parsed
            bridge.setdefault((lemma, posnum), []).append(
                (parts[0].strip(), cefr))
            stats["rows"] += 1
    return bridge, stats


def load_evp_guidewords(path):
    """Load {lemma: [(guideword, cefr)]} from the EVP subset pack.

    Pack shape: {"entries": {"lemma|pos|key": {"guideword", "cefr",
    "domain", ...}}}. Missing/unreadable files fail closed to {}.
    Entries without a guideword or with an unknown CEFR are skipped
    (they can never disambiguate).
    """
    try:
        with open(str(path), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    out: dict = {}
    for key, value in entries.items():
        if not isinstance(value, dict):
            continue
        guideword = (value.get("guideword") or "").replace("_", " ").strip()
        cefr = (value.get("cefr") or "").strip()
        if not guideword or cefr not in _CEFR_RANK:
            continue
        try:
            lemma = normalize_lemma(str(key).split("|")[0])
        except (ValueError, IndexError):
            continue
        out.setdefault(lemma, []).append((guideword.lower(), cefr))
    return out


def get_bridge(path=None):
    """Cached TSV map for path (default DEFAULT_TSV). Loads once."""
    key = ("bridge", str(path or DEFAULT_TSV))
    if key not in _CACHE:
        _CACHE[key] = load_tsv(key[1])[0]
    return _CACHE[key]


def get_evp(path=None):
    """Cached EVP guideword map for path (default DEFAULT_EVP). Loads once."""
    key = ("evp", str(path or DEFAULT_EVP))
    if key not in _CACHE:
        _CACHE[key] = load_evp_guidewords(key[1])
    return _CACHE[key]


def _min_cefr(levels):
    """Min CEFR over levels (None when no known level)."""
    ranked = sorted({_CEFR_RANK[lvl] for lvl in levels
                     if lvl in _CEFR_RANK})
    if not ranked:
        return None
    return CEFR_ORDER[ranked[0]]


def sense_cefr_for(lemma, pos, gloss, bridge=None, evp=None):
    """CEFR for one (lemma, pos, gloss) triple -> (cefr|None, method).

    bridge defaults to the cached DEFAULT_TSV map, evp to the cached
    DEFAULT_EVP map (both fail-closed: missing data degrades down the
    cascade to "unmapped", never raises). Pure + hermetic when both
    maps are passed explicitly.
    """
    if bridge is None:
        bridge = get_bridge()
    if evp is None:
        evp = get_evp()
    try:
        lemma_norm = normalize_lemma(str(lemma or "").replace("_", " "))
    except ValueError:
        return None, METHOD_UNMAPPED
    try:
        pos_norm = normalize_pos(pos)
    except ValueError:
        pos_norm = ""
    posnums = WN_POS.get(pos_norm, _ALL_POSNUMS)
    cands = []
    for posnum in posnums:
        cands.extend(bridge.get((lemma_norm, posnum), []))
    if not cands:
        return None, METHOD_UNMAPPED
    cand_levels = {cefr for _, cefr in cands}
    glossary = (gloss or "").lower()
    if glossary:
        matched = set()
        for guideword, cefr in evp.get(lemma_norm, []):
            if cefr not in cand_levels:
                continue
            # Word-boundary match: raw substring lets "art" hit "heart".
            if guideword and re.search(r"\b" + re.escape(guideword) + r"\b",
                                       glossary):
                matched.add(cefr)
        if matched:
            return _min_cefr(matched), METHOD_EVP_GLOSS
    if len(cands) == 1:
        return cands[0][1], METHOD_SINGLE
    return _min_cefr(cand_levels), METHOD_LEMMA_MIN
