"""Enrichment (enrich stage): dataset-only per-sense payloads.

Moved verbatim from factory/pipeline/precard_pipeline (provenance:
precard line R1-R6/R42/C3, 2026-09-14); example pool helpers vendored
frozen from factory/pipeline/card_pilot. No model calls here.
"""

from __future__ import annotations

import re

from factory.precard import anchor as _anchor_home
from factory.precard.cefr import CEFR_ORDER, METHOD_POOL_FALLBACK
from factory.precard.cefr import sense_cefr_for
from factory.precard.ids import compute_pre_card_id


_REGISTER_SLANG_VULGAR_TAGS = {"vulgar", "offensive"}


REGISTER_DEFAULT = "neutral"


LEXICAL_TYPE_DEFAULT = "word"


N_EXAMPLES = 2


def prefer_cloze_passing(candidates, headword, kind="word", pool_level="",
                         limit=2, zipf_fn=None):
    """R42 S5: first ``limit`` cloze-passing candidates, order kept.

    Backfills with failing candidates (original order) when fewer than
    ``limit`` pass, so the downstream release machinery (split_frozen)
    still sees and records them with their cloze-<gate> reason instead
    of silently dropping slots.
    """
    try:
        limit = max(0, int(limit))
    except (TypeError, ValueError):
        limit = 2
    pool = [c for c in (candidates or [])
            if isinstance(c, str) and c.strip()]
    passing, failing = [], []
    for cand in pool:
        ok, _ = cloze_check_example(
            cand, headword, kind, pool_level, zipf_fn)
        (passing if ok else failing).append(cand)
    return (passing + failing)[:limit]


def cloze_check_example(example, headword, kind="word", pool_level="",
                        zipf_fn=None):
    """R42: (ok, reason) for one example across all four gates.

    First failure wins (archaic -> dialogue -> zipf -> density);
    reason is "" on pass else "cloze-<gate>".
    """
    if not cloze_archaic_ok(example):
        return False, "cloze-archaic"
    if not cloze_dialogue_ok(example):
        return False, "cloze-dialogue"
    if not cloze_zipf_ok(example, headword, kind, pool_level, zipf_fn):
        return False, "cloze-zipf"
    if not cloze_density_ok(example):
        return False, "cloze-density"
    return True, ""


def cloze_density_ok(example):
    """R42d: True iff content-token ratio >= 0.40 AND count >= 3.

    Content proxy for nouns/verbs/adjectives: alpha tokens len>=4
    outside the shared _COHERENCE_STOPWORDS set (reuse, no second
    list). Total = all alpha tokens.
    """
    tokens = [t.lower() for t in _ALPHA_TOKEN_RX.findall(example or "")]
    if not tokens:
        return False
    content = [t for t in tokens
               if len(t) >= 4 and t not in _COHERENCE_STOPWORDS]
    if len(content) < CLOZE_DENSITY_MIN_COUNT:
        return False
    return len(content) / len(tokens) >= CLOZE_DENSITY_MIN_RATIO


_COHERENCE_STOPWORDS = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "for", "with", "and",
    "or", "is", "are", "was", "were", "be", "been", "by", "from",
    "as", "at", "that", "this", "it", "its",
})


_ALPHA_TOKEN_RX = re.compile(r"[A-Za-z]+")


CLOZE_DENSITY_MIN_RATIO = 0.40


CLOZE_DENSITY_MIN_COUNT = 3


def cloze_zipf_ok(example, headword, kind="word", pool_level="",
                  zipf_fn=None):
    """R42c: True iff every alpha token len>=3 clears the level floor.

    The headword itself (any inflection: 5-char stem containment either
    direction over headword_leak_tokens) is excluded. zipf_fn injects
    the lookup (hermetic tests); None uses the shared _anchor_home._freq_zipf_single
    (wordfreq, local data — reuse, no second lookup). Unknown (None)
    readings fail OPEN to pass (missing data must never drop content).
    """
    floor = cloze_zipf_floor(pool_level)
    get = zipf_fn or _anchor_home._freq_zipf_single
    heads = [h for h in headword_leak_tokens(headword, kind) if h]
    for match in _ALPHA_TOKEN_RX.finditer(example or ""):
        token = match.group(0)
        if len(token) < 3:
            continue
        lowered = token.lower()
        if any(_stem_match_5(lowered, h) for h in heads):
            continue
        try:
            value = get(lowered)
        except (KeyError, ValueError, TypeError):
            value = None
        if value is None:
            continue
        if float(value) < floor:
            return False
    return True


def _stem_match_5(a, b):
    """Shared 5-char stem-prefix match (R41 owner, R42 v11 reuse).

    Morphology-tolerant overlap: exact match first (cheap), else a
    length-proportional shared PREFIX (torrent/torrential,
    torrents/torrential), with trailing-s tolerance. Substring
    containment is rejected: taste/wastebasket and apple/pineapple
    share only a suffix, not a prefix, so they must NOT match.
    Case-sensitive — callers lowercase first.
    """
    if a == b:
        return True

    def _vars(t):
        out = {t}
        if len(t) > 5 and t.endswith("s") and not t.endswith("ss"):
            out.add(t[:-1])
        return out

    def _prefix_len(x, y):
        n = 0
        for ca, cb in zip(x, y):
            if ca != cb:
                break
            n += 1
        return n
    for va in _vars(a):
        for vb in _vars(b):
            if len(va) < 5 or len(vb) < 5:
                continue
            short_len = min(len(va), len(vb))
            need = max(5, (short_len + 1) // 2)
            if _prefix_len(va, vb) >= need:
                return True
    return False


def headword_leak_tokens(text, kind):
    """R7: Latin tokens that must not leak into the FA fields."""
    lowered = (text or "").strip().lower()
    if (kind or "word") == "phrase":
        return [t for t in re.findall(r"[a-z']+", lowered) if len(t) >= 3]
    return [lowered] if lowered else []


def cloze_zipf_floor(pool_level):
    """R42c: zipf floor for a pool level (unknown -> default, stated)."""
    return CLOZE_ZIPF_FLOORS.get(
        (pool_level or "").strip().upper(), CLOZE_ZIPF_DEFAULT_FLOOR)


CLOZE_ZIPF_FLOORS = {"A1": 3.5, "A2": 3.5, "B1": 3.0, "B2": 2.5,
                     "C1": 2.5, "C2": 2.5}


CLOZE_ZIPF_DEFAULT_FLOOR = 3.0


def cloze_dialogue_ok(example):
    """R42b: True iff no comic/dialogue register signal.

    Fails on any of " " " «, on "!" more than once, on "!!" / "!?" /
    "..." substrings, or on more than one mid-sentence Capitalized
    word (sentence-first tokens and the pronoun "I" excluded).
    """
    text = example or ""
    if any(ch in text for ch in _DIALOGUE_CHARS):
        return False
    if text.count("!") > 1:
        return False
    if any(sub in text for sub in _DIALOGUE_SUBSTRINGS):
        return False
    mids = 0
    for sent in _SENT_SPLIT_RX.split(text.strip()):
        tokens = _ALPHA_TOKEN_RX.findall(sent)
        for pos, token in enumerate(tokens):
            if pos == 0 or token == "I":
                continue
            if _CAP_WORD_RX.match(token):
                mids += 1
                if mids > 1:
                    return False
    return True


_CAP_WORD_RX = re.compile(r"^[A-Z][a-z]+$")


_DIALOGUE_SUBSTRINGS = ("!!", "!?", "...")


_DIALOGUE_CHARS = frozenset({'"', "\u201c", "\u201d", "\u00ab"})


_SENT_SPLIT_RX = re.compile(r"[.!?\u2026]+\s+")


def cloze_archaic_ok(example):
    """R42a: True iff no ARCHAIC_WORDS whole-word hit (case-insensitive)."""
    return _ARCHAIC_RX.search(example or "") is None


_ARCHAIC_RX = re.compile(
    r"\b(?:thou|thee|thy|thine|ye|doth|dost|hath|hast|wilt|art|"
    r"canst|shallt|whither|thither|hither|whence|thence|nay|ere|"
    r"oft|unto|wherefore)\b", re.IGNORECASE)


def tatoeba_candidates(pool, text, kind):
    """Tatoeba lemma list: exact key, else longest tokens first (phrases)."""
    pool = pool or {}
    key = (text or "").strip().lower()
    if not key:
        return []
    if key in pool:
        return list(pool[key])
    if (kind or "word") == "phrase":
        out = []
        for token in sorted(set(key.split()), key=lambda t: (-len(t), t)):
            out.extend(pool.get(token, []))
        return out
    return []


def filter_examples_by_length(texts, loose_cap=False):
    """R13: keep 8-20 words inclusive; loose_cap drops only >20w (tatoeba)."""
    kept = []
    for text in texts or []:
        n = en_word_count(text)
        if n > EXAMPLE_MAX_WORDS:
            continue
        if not loose_cap and n < EXAMPLE_MIN_WORDS:
            continue
        kept.append(text)
    return kept


EXAMPLE_MIN_WORDS = 8


EXAMPLE_MAX_WORDS = 20


def en_word_count(text):
    """R11/R13: English word count (Latin tokens; digits/possessives count)."""
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text or ""))


def sense_example_texts(sense):
    """Raw example strings of one kaikki sense (dicts with "text" or strs)."""
    out = []
    for raw in (sense or {}).get("examples") or []:
        if isinstance(raw, dict):
            cand = raw.get("text")
        else:
            cand = raw
        if isinstance(cand, str) and cand.strip():
            out.append(cand.strip())
    return out


def register_for(sense_tags):
    """Register for one precard row (pure, dataset-only).

    slang_vulgar (vulgar/offensive tags) wins over informal; slang or
    colloquial tags imply at least informal (F3 floor); default is
    neutral. The vulgar/offensive set is the locked ticket scope — the
    broader S1 VULGAR_TAGS drop is a separate gate, untouched here.
    """
    tags = _anchor_home._normalize_tags(sense_tags)
    if tags & _REGISTER_SLANG_VULGAR_TAGS:
        return REGISTER_SLANG_VULGAR
    if tags & (_REGISTER_INFORMAL_TAGS | _LEXICAL_SLANG_TAGS
               | _LEXICAL_COLLOQUIAL_TAGS):
        return REGISTER_INFORMAL
    return REGISTER_DEFAULT


_LEXICAL_SLANG_TAGS = {"slang"}


_REGISTER_INFORMAL_TAGS = {"informal"}


_LEXICAL_COLLOQUIAL_TAGS = {"colloquial"}


REGISTER_INFORMAL = "informal"


REGISTER_SLANG_VULGAR = "slang_vulgar"


def lexical_type_for(kind, sense_tags, phrase_entry=None):
    """Lexical type for one precard row (pure, dataset-only).

    Phrases with a phrase-type log entry use its phrase_type, casefolded
    (log values are the lowercase PHRASE_TYPES vocabulary; the fold only
    guards a stray capital from forking downstream pack filters).
    Everything else maps the picked-sense kaikki tags (slang >
    colloquial > idiomatic) with a "word" default.
    """
    if (kind or "word") == "phrase" and isinstance(phrase_entry, dict):
        phrase_type = str(phrase_entry.get("phrase_type") or "").strip()
        if phrase_type:
            return phrase_type.casefold()
    tags = _anchor_home._normalize_tags(sense_tags)
    if tags & _LEXICAL_SLANG_TAGS:
        return "slang"
    if tags & _LEXICAL_COLLOQUIAL_TAGS:
        return "colloquial"
    if tags & _LEXICAL_IDIOMATIC_TAGS:
        return "idiomatic"
    return LEXICAL_TYPE_DEFAULT


_LEXICAL_IDIOMATIC_TAGS = {"idiomatic"}


def _sense_cefr_or_pool_fallback(item, lemma, pos, gloss):
    """Bridge sense-CEFR with the never-null pool fallback.

    Returns (sense_cefr, method): the bridge value when non-empty, else
    the item pool_level (stripped + uppercased) with method
    "pool-fallback" — but only when the normalized pool value is a known
    CEFR level (``CEFR_ORDER``). Unknown/empty/non-string
    pool values keep the bridge verdict as-is (unmapped): uncertainty
    keeps, never a fabricated level, never a raise on hostile items.
    """
    sense_cefr, method = sense_cefr_for(lemma, pos, gloss)
    if sense_cefr:
        return sense_cefr, method
    pool_raw = item.get("pool_level")
    pool = pool_raw.strip().upper() if isinstance(pool_raw, str) else ""
    if pool and pool in CEFR_ORDER:
        return pool, METHOD_POOL_FALLBACK
    return sense_cefr, method


def _lemma_fallback_examples(entries, read_entry, seen):
    """Lemma-level example fallback (R3, deterministic, zero LLM).

    All kaikki senses of the lemma's entries (not just the judged
    sense), length-filtered, excluding already-seen strings. Lookup
    errors fail open to [] (the caller keeps whatever it has).
    """
    out = []
    try:
        rows = list(entries or [])
    except Exception:
        return out
    for row in rows:
        try:
            entry = read_entry(row) or {}
        except Exception:
            continue
        if not isinstance(entry, dict):
            continue
        try:
            senses = entry.get("senses") or []
        except Exception:
            continue
        for sense in senses:
            if not isinstance(sense, dict):
                continue
            try:
                texts = sense_example_texts(sense)
            except Exception:
                continue
            for text in filter_examples_by_length(texts or []):
                if text not in seen and text not in out:
                    out.append(text)
    return out


def is_circular_def(lemma, en_def):
    """R4: True iff the definition defines the lemma with itself.

    Revegetation case: ``revegetation = "The act or process of
    revegetating"`` teaches nothing — the head nominalizes the lemma
    stem instead of giving a genus-differentia ("a round fruit").
    FLAG only, never drop (card line decides drop/rewrite later).

    Narrow: the definition head must match ``The act/state/process
    [or ...] of <word>`` or ``The state of being <word>`` (case-
    insensitive), AND that head word must share a morphological stem
    with the lemma (``_stem_match_5`` reuse). Bare-infinitive
    definitions (``to accumulate``) never fire even when the verb
    equals the lemma. Fail-open: empty lemma/definition, short
    stems, or any uncertainty returns False. Deterministic,
    stdlib-only.
    """
    text = en_def.strip() if isinstance(en_def, str) else ""
    lem = lemma.strip().lower() if isinstance(lemma, str) else ""
    if not text or not lem:
        return False
    hit = _CIRCULAR_BEING_RX.match(text)
    head = hit.group(1).lower() if hit else None
    if head is None:
        hit = _CIRCULAR_HEAD_RX.match(text)
        if hit is None:
            return False
        head = hit.group(1).lower()
    if not head:
        return False
    lem_tokens = _ALPHA_TOKEN_RX.findall(lem)
    if not lem_tokens:
        return False
    return any(_stem_match_5(head, tok) for tok in lem_tokens)


_CIRCULAR_BEING_RX = re.compile(
    r"the\s+state\s+of\s+being\s+([A-Za-z]+)", re.IGNORECASE)


_CIRCULAR_HEAD_RX = re.compile(
    r"the\s+(?:act|state|process)"
    r"(?:\s+or\s+(?:act|state|process))*\s+of\s+([A-Za-z]+)",
    re.IGNORECASE)


def enrich_item(item, judge_pick, index, read_entry, tatoeba_pool,
                   zipf_fn=None, phrase_entry=None):
    """Enrichment (s5) from the judge-chosen sense (card_pilot helpers).

    R29/R32 v8: also returns abbrev_expansion (dataset-first parse of the
    chosen gloss) and pos/pos_src (anchored entry POS first, 1-3 tags).
    R42 v11: the example pool (anchored-sense kaikki examples, then the
    tatoeba pool — both through the existing length filter, reused)
    additionally passes the four cloze gates via
    prefer_cloze_passing (reused by import): cloze-passing
    examples fill the N_EXAMPLES slots first; cloze failures backfill
    only when no passing alternative exists, so the downstream release
    machinery (split_frozen_by_containment) still records them with
    their cloze-<gate> reason instead of silently keeping weak slots.
    "enrich_path" is "full" when the dataset carriers cover IPA + all
    N_EXAMPLES slots, else "partial" (the model fills gaps downstream)
    so the fallback is counted in stage_calls, not silent.
    v14.1 (R3) example-preservation fallback: when the picked sense
    lacks examples (sense switching for `for`/`call` emptied A1 fields),
    the pool backfills from lemma-level kaikki examples (all senses),
    then the tatoeba pool; "example_fallback" names the first tier that
    yielded an example ("sense"/"lemma"/"pool"/"synthetic-needed") and
    "example_synthetic_needed" flags rows still empty so the downstream
    model synthesizes instead of emitting a blank field.
    C3: also returns lexical_type + register (picked-sense kaikki tags /
    phrase-type log entry) and pre_card_id (stable EN-content id) —
    dataset sources only, zero LLM calls.
    Sense-CEFR never-null rule (owner lock 2026-09-12): when the bridge
    returns an empty/None sense_cefr, the item pool_level is copied
    (stripped + uppercased, known CEFR levels only) with method
    "pool-fallback" — every precard row leaves with non-empty sense_cefr
    whenever pool_level carries a valid level.
    R4: also returns circular_def (per-sense FLAG only, never drop) —
    True when en_def defines the lemma with itself ("The act or
    process of revegetating" for revegetation); see is_circular_def.
    """
    sid = (judge_pick or {}).get("sense_id", "")
    gloss = (judge_pick or {}).get("gloss", "")
    kind = item.get("kind") or "word"
    lemma = (item.get("text") or "").strip()
    if not sid:
        sense_cefr, sense_cefr_method = _sense_cefr_or_pool_fallback(
            item, lemma, item.get("pos") or "", gloss or "")
        return {"sense_id": "", "en_def": gloss or "",
                "circular_def": is_circular_def(lemma, gloss or ""),
                "ipa": "", "ipa_src": _anchor_home.IPA_SRC_MODEL,
                "dataset_examples": [], "example_fallback": "synthetic-needed",
                "example_synthetic_needed": True,
                "abbrev_expansion": "",
                "pos": [], "pos_src": "none", "enrich_path": "partial",
                "sense_cefr": sense_cefr,
                "sense_cefr_method": sense_cefr_method,
                "lexical_type": lexical_type_for(kind, set(),
                                                 phrase_entry),
                "register": REGISTER_DEFAULT,
                "pre_card_id": compute_pre_card_id(
                    lemma, item.get("pos", ""), gloss or "")}
    try:
        want_idx = int(sid.split("#")[-1])
    except (TypeError, ValueError):
        want_idx = None
    entries, pos = _anchor_home._entries_for(item, index)
    # R34 v9: an xref-resolved pick carries the TARGET lemma in its
    # sense_id ("colour#2" for item "color") — enrich from the target
    # rows, not the item rows.
    sid_lemma = sid.rpartition("#")[0].strip().lower() if "#" in sid \
        else ""
    if sid_lemma and sid_lemma != (item.get("text") or "").strip().lower():
        target_rows = (index or {}).get(sid_lemma)
        if target_rows:
            entries, pos = list(target_rows), ""
    entry = sense = None
    if want_idx is not None:
        try:
            scored = _anchor_home.score_senses(
                sid_lemma or item.get("text", ""), entries, pos,
                read_entry)
        except Exception:
            scored = []
        for _score, idx, cand_entry, cand_sense, _gloss in scored:
            if idx == want_idx:
                entry, sense = cand_entry, cand_sense
                break
    ipa = _anchor_home.first_entry_ipa(entry) if entry else ""
    sense_texts = filter_examples_by_length(
        sense_example_texts(sense)) if sense else []
    pool = list(sense_texts)
    seen = set(pool)
    # v14.1 (R3): lemma-level fallback BEFORE the tatoeba pool — a
    # sense switch that empties the picked sense (for/call A1) inherits
    # sibling-sense kaikki examples first (dataset-dataset, zero LLM).
    lemma_texts = _lemma_fallback_examples(entries, read_entry, seen)
    for cand in lemma_texts:
        if cand not in seen:
            pool.append(cand)
            seen.add(cand)
    extra = filter_examples_by_length(
        tatoeba_candidates(
            tatoeba_pool, item.get("text", ""),
            item.get("kind") or "word"),
        loose_cap=True)
    for cand in extra:
        if cand not in seen:
            pool.append(cand)
            seen.add(cand)
    picked = prefer_cloze_passing(
        pool, item.get("text", ""), item.get("kind") or "word",
        item.get("pool_level", ""), N_EXAMPLES, zipf_fn)
    if sense_texts:
        example_fallback = "sense"
    elif lemma_texts:
        example_fallback = "lemma"
    elif [c for c in extra if c in pool]:
        example_fallback = "pool"
    else:
        example_fallback = "synthetic-needed"
    pos_tags = _anchor_home.anchor_pos_tags(
        item.get("text", ""), entries, pos, read_entry)
    picked_examples = picked[:N_EXAMPLES]
    enrich_path = ("full" if ipa and len(picked_examples) >=
                   N_EXAMPLES else "partial")
    sense_tags = _anchor_home._sense_tag_set(sense)
    id_pos = (pos_tags[0] if pos_tags else (item.get("pos") or ""))
    sense_cefr, sense_cefr_method = _sense_cefr_or_pool_fallback(
        item, lemma, id_pos, gloss or "")
    return {"sense_id": sid, "en_def": gloss or "",
            "circular_def": is_circular_def(lemma, gloss or ""),
            "ipa": ipa,
            "ipa_src": _anchor_home.IPA_SRC_DATASET if ipa
            else _anchor_home.IPA_SRC_MODEL,
            "dataset_examples": picked_examples,
            "example_fallback": example_fallback,
            "example_synthetic_needed": not picked_examples,
            "abbrev_expansion": _anchor_home.parse_abbrev_expansion(
                gloss or ""),
            "pos": pos_tags,
            "pos_src": "dataset" if pos_tags else "none",
            "enrich_path": enrich_path,
            "sense_cefr": sense_cefr,
            "sense_cefr_method": sense_cefr_method,
            "lexical_type": lexical_type_for(kind, sense_tags,
                                              phrase_entry),
            "register": register_for(sense_tags),
            "pre_card_id": compute_pre_card_id(lemma, id_pos,
                                               gloss or "")}
