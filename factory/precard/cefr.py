"""WordNet sense-CEFR bridge (sole owner in new home).

Whole-file copy of factory/lexicon/cefr_bridge.py (provenance: precard
line, 2026-09-14) plus normalize_lemma/normalize_pos vendored from
factory/core/registry.py. Pack/TSV data files stay shared (data, not
code).
"""

from __future__ import annotations

import collections
import json
import os
import re
import sys


FACTORY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


REPO_ROOT = os.path.dirname(FACTORY_DIR)


DEFAULT_TSV = (
    "W:/hamzaban_data_factory/fixtures/cefr-wordnet/wordnet_sensekey_cefr.tsv"
)


DEFAULT_EVP = os.path.join(FACTORY_DIR, "packs", "en", "evp_sense.json")


CEFR_ORDER = ("A1", "A2", "B1", "B2", "C1", "C2")


_CEFR_RANK = {level: i for i, level in enumerate(CEFR_ORDER)}


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


METHOD_POOL_FALLBACK = "pool-fallback"


METHOD_UNMAPPED = "unmapped"


METHOD_ZIPF_HEURISTIC = "zipf-heuristic"


# PROVISIONAL thresholds (locked 2026-09-20; revisit when phrase-CEFR
# data exists): zipf→CEFR fallback bands for card_type phrase rows ONLY
# (the word bridge above stays sensekey-official). "acronym" is RESERVED
# for the future acronym-pack producer — no live pipeline item carries
# kind="acronym" today (items are "word"/"phrase"), so the set stays
# phrase-only until that producer ships (OC review 2026-09-20). The locked
# cut points are 4.2 and 3.2; each outer band names its calibration
# pair and emits the pair's representative until calibration lands —
# B1 for the A2/B1 band, C1 for the C1/C2 band. The method tag on every
# row from this path is ALWAYS "zipf-heuristic", never wn-single,
# wn-evp-gloss, or any official-sounding label.
ZIPF_HEURISTIC_HIGH_CUT = 4.2  # >= this -> B1 (A2/B1 band)

ZIPF_HEURISTIC_LOW_CUT = 3.2  # 3.2-4.2 -> B2; below -> C1 (C1/C2 band)


ZIPF_HEURISTIC_KINDS = frozenset({"phrase"})


# Distribution of rows passing through the zipf→CEFR fallback, counts
# per band ("A2/B1", "B2", "C1/C2", "missing") — logged by the pipeline
# enrich summary for future calibration. Process-local only (reset in
# tests via reset_zipf_heuristic_dist).
ZIPF_HEURISTIC_DIST: dict = collections.Counter()


def reset_zipf_heuristic_dist():
    """Clear the zipf→CEFR fallback distribution (tests / fresh runs)."""
    ZIPF_HEURISTIC_DIST.clear()


_ALPHA_TOKEN_RX = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def phrase_zipf(text, zipf_fn):
    """Phrase zipf for the heuristic: whole-phrase lookup first.

    Lookups are casefolded before hitting wordfreq (matching
    anchor.default_zipf) — "Hot Wheels" and "hot wheels" score the
    same; library casing behavior is never relied on.
    Returns the whole-phrase zipf when positive; else the min over
    per-token zipfs (tokens with no wordfreq entry are skipped, never
    zero-filled — a zero would drag the min to the floor on missing
    data). None when nothing is known (caller stays unmapped, never
    fabricates). zipf_fn(text) -> float|None (None/<=0 = no entry).
    Never raises: hostile input fails open to None.
    """
    try:
        get = zipf_fn
        if get is None:
            try:
                from wordfreq import zipf_frequency

                def get(term):
                    try:
                        return float(zipf_frequency(term, "en"))
                    except Exception:
                        return None
            except Exception:
                return None
        try:
            whole = get(str(text or "").strip().casefold())
        except Exception:
            whole = None
        if isinstance(whole, bool):
            whole = None
        try:
            whole_f = None if whole is None else float(whole)
        except (TypeError, ValueError):
            whole_f = None
        if whole_f is not None and whole_f > 0:
            return whole_f
        tokens = _ALPHA_TOKEN_RX.findall(str(text or "").casefold())
        known = []
        for tok in tokens:
            try:
                value = get(tok.casefold())
            except Exception:
                continue
            if isinstance(value, bool):
                continue
            try:
                number = None if value is None else float(value)
            except (TypeError, ValueError):
                continue
            if number is not None and number > 0:
                known.append(number)
        if not known:
            return None
        return min(known)
    except Exception:
        return None


def zipf_heuristic_cefr(text, kind, zipf_fn=None):
    """Zipf→CEFR fallback for phrase rows -> (cefr|None, method).

    kind outside {"phrase"} (or missing data) returns
    (None, METHOD_UNMAPPED) — the word path is untouched, and
    kind="acronym" stays unmapped until the acronym-pack producer
    ships (reserved, see ZIPF_HEURISTIC_KINDS). On the path,
    method is ALWAYS METHOD_ZIPF_HEURISTIC ("zipf-heuristic", never
    official). Bands (both cuts PROVISIONAL): >= 4.2 -> B1 (A2/B1
    band), 3.2-4.2 -> B2, below -> C1 (C1/C2 band). Every call bumps
    ZIPF_HEURISTIC_DIST[band] ("missing" on no data) for calibration
    logging. Pure when zipf_fn is passed; None uses wordfreq live.
    """
    try:
        norm_kind = str(kind or "").strip().casefold()
    except Exception:
        norm_kind = ""
    if norm_kind not in ZIPF_HEURISTIC_KINDS:
        return None, METHOD_UNMAPPED
    value = phrase_zipf(text, zipf_fn)
    if value is None:
        ZIPF_HEURISTIC_DIST["missing"] += 1
        return None, METHOD_UNMAPPED
    if value >= ZIPF_HEURISTIC_HIGH_CUT:
        ZIPF_HEURISTIC_DIST["A2/B1"] += 1
        return "B1", METHOD_ZIPF_HEURISTIC
    if value >= ZIPF_HEURISTIC_LOW_CUT:
        ZIPF_HEURISTIC_DIST["B2"] += 1
        return "B2", METHOD_ZIPF_HEURISTIC
    ZIPF_HEURISTIC_DIST["C1/C2"] += 1
    return "C1", METHOD_ZIPF_HEURISTIC


# R4 verdict (locked 2026-09-20): EVP direct-mapping for phrase/acronym
# rows is DROPPED — no dead path ships. Evidence measured 2026-09-20 on
# factory/packs/en/evp_sense.json (2000 entries): 32 multiword entries
# (credit card, dining room, ice cream, face to face, ...) but ZERO
# overlap with the 500-row factory/packs/en/phrases.csv pool, and the
# only all-caps entries are 10 rows over 2 ambiguous lemmas (ID —
# Idaho vs id; DNA) — not acronym-pack coverage. A mapping built on
# this would serve zero live rows. evp_phrase_acronym_coverage() below
# re-checks this mechanically; rebuild the mapping ONLY on real
# coverage hits (pack_hits > 0), never speculatively.
def evp_phrase_acronym_coverage(evp=None, pack_phrases=()):
    """Coverage check: does the EVP pack cover phrase/acronym rows?

    evp: {lemma: [(guideword, cefr)]} (same shape as
    load_evp_guidewords output; None loads the live pack). pack_phrases:
    iterable of pool phrase strings to hit-test. Returns
    {"evp_entries", "evp_multiword_entries", "evp_acronym_lemmas",
    "pack_phrases", "pack_hits", "pack_hit_sample"} — pack_hits == 0
    means no direct-mapping is justified (R4 DROP). Never raises.
    """
    try:
        mapping = get_evp() if evp is None else evp
    except Exception:
        mapping = {}
    if not isinstance(mapping, dict):
        mapping = {}
    try:
        lemmas = [str(lemma) for lemma in mapping.keys()]
    except Exception:
        lemmas = []
    multi = [lem for lem in lemmas if " " in lem.strip()]
    acros = sorted({lem.strip() for lem in lemmas
                    if re.fullmatch(r"[A-Z]{2,6}", lem.strip())})
    try:
        phrases = [str(p or "").strip().lower() for p in pack_phrases or ()]
        phrases = [p for p in phrases if p]
    except Exception:
        phrases = []
    try:
        lemma_set = {lem.strip().lower() for lem in lemmas}
    except Exception:
        lemma_set = set()
    hits = sorted({p for p in phrases if p in lemma_set})
    return {"evp_entries": len(lemmas),
            "evp_multiword_entries": len(multi),
            "evp_acronym_lemmas": acros,
            "pack_phrases": len(phrases),
            "pack_hits": len(hits),
            "pack_hit_sample": hits[:10]}


_CACHE: dict = {}


_CAND_CACHE: dict = {}


_CAND_CACHE_MAX = 20000


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
        try:
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
        except (OSError, ValueError):
            # Decode/read error mid-file (UnicodeDecodeError is a
            # ValueError): keep the rows decoded so far, degrade the rest
            # to "unmapped" instead of crashing the caller.
            pass
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
        raw_guideword = value.get("guideword")
        raw_cefr = value.get("cefr")
        if not isinstance(raw_guideword, str) \
                or not isinstance(raw_cefr, str):
            continue
        guideword = raw_guideword.replace("_", " ").strip()
        cefr = raw_cefr.strip()
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
    if not isinstance(bridge, dict):
        bridge = {}
    if not isinstance(evp, dict):
        evp = {}
    try:
        lemma_norm = normalize_lemma(str(lemma or "").replace("_", " "))
    except ValueError:
        return None, METHOD_UNMAPPED
    try:
        pos_norm = normalize_pos(pos)
    except ValueError:
        pos_norm = ""
    posnums = WN_POS.get(pos_norm, _ALL_POSNUMS)
    # Lazy per-lemma cache: same lemma+pos hits share one cands list
    # (avoids per-sense duplication — expected ~5% RAM drop on 500-sample).
    # Identity-checked: a cached entry is only reused when its stored
    # bridge id matches; mismatch rebuilds (validated on hit; bridge
    # reload via clear_cache covers staleness).
    bridge_id = id(bridge)
    cache_key = (lemma_norm, pos_norm)
    cached = _CAND_CACHE.get(cache_key)
    if cached is not None and cached[0] == bridge_id:
        cands = cached[1]
    else:
        cands = []
        for posnum in posnums:
            try:
                rows = bridge.get((lemma_norm, posnum), [])
            except (TypeError, AttributeError):
                continue
            if not isinstance(rows, list):
                continue
            for row in rows:
                try:
                    sensekey, cefr = row
                except (TypeError, ValueError):
                    continue
                if not isinstance(sensekey, str) \
                        or not isinstance(cefr, str) \
                        or cefr not in _CEFR_RANK:
                    continue
                cands.append((sensekey, cefr))
        if len(_CAND_CACHE) >= _CAND_CACHE_MAX and cache_key not in _CAND_CACHE:
            _CAND_CACHE.pop(next(iter(_CAND_CACHE)))
        _CAND_CACHE[cache_key] = (bridge_id, cands)
    if not cands:
        return None, METHOD_UNMAPPED
    if len(cands) == 1:
        return cands[0][1], METHOD_SINGLE
    cand_levels = {cefr for _, cefr in cands}
    glossary = gloss.lower() if isinstance(gloss, str) else ""
    if glossary:
        try:
            pairs = list(evp.get(lemma_norm, []) or [])
        except (TypeError, AttributeError):
            pairs = []
        matched = set()
        for pair in pairs:
            try:
                guideword, cefr = pair
            except (TypeError, ValueError):
                continue
            if not isinstance(guideword, str) \
                    or not isinstance(cefr, str):
                continue
            if cefr not in cand_levels:
                continue
            # Word-boundary match: raw substring lets "art" hit "heart".
            if guideword and re.search(r"\b" + re.escape(guideword) + r"\b",
                                       glossary):
                matched.add(cefr)
        if matched:
            return _min_cefr(matched), METHOD_EVP_GLOSS
    return None, METHOD_UNMAPPED


def normalize_lemma(s):
    """Lowercased lemma with stripped/collapsed whitespace. Fail-closed."""
    if s is None or (isinstance(s, str) and not s.strip()):
        raise ValueError("normalize_lemma: empty lemma")
    return " ".join(str(s).strip().split()).lower()


def normalize_pos(s):
    # NOTE: anchor.py has a same-named cousin with a tolerant contract
    # (alias map, never raises). Keep them separate.
    if s is None or (isinstance(s, str) and not s.strip()):
        raise ValueError("normalize_pos: empty pos")
    return str(s).strip().lower()
