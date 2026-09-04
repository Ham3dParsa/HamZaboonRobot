"""Card-generation pilot: 20 learner cards through the REAL card flow.

Scope: factory research only. No bot/DB/handler changes.

- Sample: 14 words stratified over the lemmas pool CEFR mix (seed 7) +
  6 phrases spread over judged phrase levels. The sample is persisted to
  ``sample.json`` so re-runs render the same cards.
- Generate: one complete learner card per item via the REAL existing
  prompt builder (``services.ai.prompts.custom_word_system_prompt``) and
  the REAL validator (``services.ai.ai.validate_card``). The prompt is
  reused by import, never forked.
- Transport: Zen responses API with the factory key
  (``factory/env_loader`` ``OPENCODE_ZEN_API_KEY``), free model chain,
  per-call timeout 180s, 2.5s sleep between calls, bounded retry (2
  attempts per model), 401/403 aborts loudly, every failure is recorded
  with its error (no silent skip). Progress JSON supports resume.
- Cost: free chain, $0 expected; per-model call counts are recorded.
- Render: Persian RTL gallery HTML with per-card sections.
- Lexicon grounding (locked R6-R8 v3, v16b gold standard): per-item kaikki
  sense anchor (``item["sense_id"]`` + ``item["en_def"]`` = top scorer of the
  deterministic v14 per-sense scoring reused from run_v14_phase1, R4
  name-only pre-filter kept), topic via the exact v16b path (deterministic
  v16 leg + v16b LLM top-up for Others, method tag "v16b-exact", resume
  pilot_topic_progress.json), fa-dominant + headword-leak bans (1 regen,
  then valid=False), phrase ``literal_fa``, proper-noun POS filter (words) /
  null-not-judged (phrases). Gap-fill + sense-review prompt; completion
  flags + informational similarity note recorded per card (no similarity
  regen). Stage timings persisted to ``timings.json`` and rendered in the
  gallery.

Usage (owner run, real generation — takes time, ~20 model calls):
    python factory/card_pilot.py --n-words 14 --n-phrases 6
Dry run (no network, no files written):
    python factory/card_pilot.py --dry-run
"""

import argparse
import csv
import difflib
import html
import json
import pathlib
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

FACTORY_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = FACTORY_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(FACTORY_DIR))

from llm_json import AuthError, extract_json, raise_for_auth  # noqa: E402
from services.ai import prompts as card_prompts  # noqa: E402  (real prompt builder)
from services.ai.ai import CardValidationError, validate_card  # noqa: E402  (real validator)

LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
# Quota order for remainder seats: pool-size order (B-heavy pool).
QUOTA_EXTRAS_ORDER = ["B1", "B2", "A2", "C1", "A1", "C2"]
CEFR_TO_BOT_LEVEL = {
    "A1": "beginner", "A2": "beginner",
    "B1": "intermediate", "B2": "intermediate",
    "C1": "advanced", "C2": "advanced",
}
SEED = 7

ZEN_BASE = "https://opencode.ai/zen/v1"
MODELS = ["muse-spark-1.3-contributor-free", "muse-spark-1.2-contributor-free",
          "ling-3.0-flash-fin-free", "mimo-v2.5-free",
          "nemotron-3.5-lightning-free"]
CALL_TIMEOUT = 180
CALL_SLEEP = 2.5
MAX_ATTEMPTS = 2

DEFAULT_OUT_DIR = "W:/hamzaban_data_factory/pilot/"
DEFAULT_REPORT = "W:/hamzaban_data_factory/reports/card-pilot-2026-09-04.html"
DEFAULT_KAIKKI_INDEX = "W:/hamzaban_data_factory/raw/kaikki-en-index.jsonl"
DEFAULT_KAIKKI_RAW = "W:/hamzaban_data_factory/raw/kaikki-en-words.jsonl"
REPAIR_PREFIX = ("Your last reply was not valid JSON. "
                 "Re-send ONLY the JSON object.\n")

# R4 — proper-noun POS set (general rule, no hardcoded name list).
PROPER_NOUN_POS = {"name", "propn"}

# R6 — topic method tag: exact v16b path (deterministic v16 leg + v16b LLM
# top-up for Others, same free model chain). Pilot resume is separate from
# the v16b originals so the gold-standard files are never touched.
TOPIC_METHOD_TAG = "v16b-exact"
PILOT_TOPIC_PROGRESS = "pilot_topic_progress.json"

# R1 — compact key carrying the EN definition through the model reply.
# The bot validator (validate_card -> _expand_card_aliases) ignores unknown
# extra keys, so "d" passes through validation untouched; the pilot reads it
# from the raw model JSON before validation. The shared prompt builder and
# validator are reused by import, never forked.
EN_DEF_COMPACT_KEY = "d"
LITERAL_FA_KEY = "literal_fa"

# R2 — prompt ban (appended to the pilot user text, builder untouched).
META_LEAK_BAN = ("Never mention level or audience in any field "
                 "(no 'beginner', 'for A1', 'سطح', 'مبتدی' etc.).")
EN_DEF_INSTRUCTION = (
    'English definition (dictionary, compact key "%s"): PRESERVE the given '
    "definition and complete the English explanation; never invent a "
    "contradicting sense." % EN_DEF_COMPACT_KEY)
LITERAL_FA_INSTRUCTION = (
    'For this phrase also return optional key "%s": word-by-word Persian '
    "rendering of its components. Ground the usage explanation in the given "
    "English definition." % LITERAL_FA_KEY)

# R7 — fa-dominant + headword-leak prompt rules (appended pilot-side,
# shared builder untouched).
FA_DOMINANT_RULE = ("Write fa_meaning and fa_explanation in Persian: "
                    "Persian-script characters must outnumber Latin-script "
                    "characters in those two fields combined.")
HEADWORD_LEAK_RULE = ("Do NOT write the Latin headword (for phrases: any "
                      "component token of 3+ letters) inside fa_meaning or "
                      "fa_explanation.")
# R7 — script counters.
_FA_RX = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF"
                    r"\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_RX = re.compile(r"[A-Za-z]")

# R8 — gap-fill + sense-review prompt (replaces echo-regen; similarity stays
# informational only, never triggers a regen).
GAPFILL_INSTRUCTION = (
    "Fill ONLY empty/missing fields; do NOT restate the given en_def; "
    "REVIEW synonyms/antonyms/examples against the anchored sense and fix "
    "any belonging to another sense.")

# R2 — machine check patterns (EN level words + CEFR codes + FA level words).
_META_LEAK_PATTERNS = (
    r"\bbeginners?\b|\bintermediates?\b|\badvanced\b|\belementary\b"
    r"|\bpre[-\s]?intermediates?\b",
    r"\b[ABC][12]\b|\bfor\s+[ABC][12]\b|\blevel\s+[ABC][12]\b",
    r"مبتدی|پیشرفته|مقدماتی|سطح|متوسط",
)
_META_LEAK_RES = [re.compile(p, re.IGNORECASE) for p in _META_LEAK_PATTERNS]

# R1 — minimal pool-POS -> kaikki-POS normalization for gloss matching.
_POS_ALIASES = {
    "adjective": "adj", "adverb": "adv", "preposition": "prep",
    "prep_phrase": "prep", "pronoun": "pron", "conjunction": "conj",
    "determiner": "det", "number": "num",
}

# TIMING — linear extrapolation target (3000 words + 500 phrases).
TARGET_EXTRAPOLATION_ITEMS = 3500


def normalize_pos(pos):
    """Casefold a POS tag through the minimal alias map (R1 gloss match)."""
    key = (pos or "").strip().casefold()
    return _POS_ALIASES.get(key, key)


def kaikki_pos_set(entries):
    """POS set of one lemma's index rows (same source R1 resolves from)."""
    return {str(e.get("pos") or "").strip().casefold()
            for e in (entries or [])
            if str(e.get("pos") or "").strip()}


def is_proper_noun_lemma(lemma, pos_set):
    """R4: single-token lemma whose kaikki POS set is subset of {name, propn}."""
    text = (lemma or "").strip()
    return bool(text) and " " not in text and bool(pos_set) \
        and set(pos_set) <= PROPER_NOUN_POS


def build_pos_sets(index):
    """lemma.lower() -> kaikki POS set, for the R4 sampling filter."""
    return {word: kaikki_pos_set(rows) for word, rows in index.items()}


def load_kaikki_index(path):
    """Load the offset index: word.lower() -> [{pos, offset, length}] (file order)."""
    index = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            word = str(row.get("word") or "").lower()
            if not word:
                continue
            try:
                offset = int(row.get("offset", 0))
                length = int(row.get("length", 0))
            except (TypeError, ValueError):
                continue
            index.setdefault(word, []).append(
                {"pos": str(row.get("pos") or ""),
                 "offset": offset, "length": length})
    return index


def read_kaikki_entry(raw_path, offset, length):
    """Seek-read one raw kaikki entry (raw file is GBs — never load fully)."""
    with open(raw_path, "rb") as handle:
        handle.seek(offset)
        blob = handle.read(length)
    return json.loads(blob.decode("utf-8"))


def _v14_register_penalty(tags, gloss):
    """R6 sense score, owner: factory/run_v14_phase1.py::main.<locals>.register_penalty.

    Vendored (minimal faithful copy) because the owner is nested inside
    main() and importing run_v14_phase1 pulls torch/sentence-transformers/
    sklearn + embedding models (side effects, non-hermetic). Logic is
    byte-faithful to the v14 ranking used for the v14c judge picks.
    """
    import re as _re
    t = set((tags or []))
    if t & {"slang", "vulgar", "derogatory", "offensive"}:
        return 0.60
    g = (gloss or "").strip()
    if _re.search(r"alternative [\w\-]+ form of|alternative spelling of|alternative name for",
                  g.lower()):
        return 0.50
    if len(g.split()) == 1 and g[:1].isupper() and g[1:2].islower():
        return 0.50
    if g in ("A surname.", "A place name.", "A surname.", "A given name."):
        return 0.50
    if t & {"obsolete", "archaic", "dated", "historical"}:
        return 0.80
    return 1.0


def _v14_ppos(entry_pos, pool_pos):
    """R6 POS factor, owner: factory/run_v14_phase1.py ranking (ppos line).

    Exact v14 rule: verb-source senses shown to non-verb lemmas are
    down-weighted 0.70; everything else 1.0. Score still decides (no hard
    POS filter here — R4 name-only drops happen at sampling).
    """
    if normalize_pos(entry_pos) == "verb" and normalize_pos(pool_pos) != "verb":
        return 0.70
    return 1.0


def _collect_kaikki_senses(entries, read_entry):
    """Flatten index rows -> [(entry_pos, sense_dict, gloss)] in file order."""
    out = []
    for row in entries or []:
        entry = _safe_read(read_entry, row)
        if not isinstance(entry, dict):
            continue
        entry_pos = str(entry.get("pos") or row.get("pos") or "")
        for sense in entry.get("senses") or []:
            if not isinstance(sense, dict):
                continue
            gloss = ""
            for cand in sense.get("glosses") or []:
                if isinstance(cand, str) and cand.strip():
                    gloss = cand.strip()
                    break
            if gloss:
                out.append((entry_pos, sense, gloss))
    return out


def pick_anchor_sense(text, entries, pool_pos, read_entry):
    """R6: score every kaikki sense, anchor = top scorer (stable file order).

    Score = vendored v14 register_penalty * v14 ppos factor. Returns
    (sense_id, gloss); sense_id is "<text.lower()>#<file-order-sense-idx>".
    Empty entries -> ("", "").
    """
    senses = _collect_kaikki_senses(entries, read_entry)
    if not senses:
        return "", ""
    scored = []
    for idx, (entry_pos, sense, gloss) in enumerate(senses):
        score = (_v14_register_penalty(sense.get("tags"), gloss)
                 * _v14_ppos(entry_pos, pool_pos))
        scored.append((score, idx, sense, gloss))
    scored.sort(key=lambda t: (-t[0], t[1]))
    _, best_idx, _, best_gloss = scored[0]
    key = (text or "").strip().lower()
    return "%s#%d" % (key, best_idx), best_gloss


def _safe_read(read_entry, row):
    try:
        return read_entry(row)
    except Exception:
        return None


def resolve_word_en_def(entries, pool_pos, read_entry):
    """R6: anchor gloss = top v14-scored sense of the POS-preferred entries.

    R4 POS pre-filter (name-only drops) stays at sampling; here every sense
    is scored and the top scorer wins even when it is not the first gloss.
    Returns the gloss string ("" if none) for backward compatibility; the
    sense id comes from pick_anchor_sense().
    """
    if not entries:
        return ""
    want = normalize_pos(pool_pos)
    ordered = ([e for e in entries if normalize_pos(e.get("pos")) == want]
               + [e for e in entries if normalize_pos(e.get("pos")) != want])
    # Score senses entry-group by group so a POS-matching top scorer beats a
    # non-matching first gloss, but a higher-scored non-matching sense can
    # still win inside its own group only if no matching gloss exists.
    # To let score decide globally, collect across the ordered rows and pick
    # the global top scorer instead of the first non-empty gloss.
    _, gloss = pick_anchor_sense("", ordered, pool_pos, read_entry)
    return gloss


def resolve_phrase_en_def(index, phrase, read_entry):
    """R6: phrase anchor = top v14-scored sense (exact phrase, else tokens)."""
    key = (phrase or "").strip().lower()
    if not key:
        return ""
    if key in index:
        _, gloss = pick_anchor_sense(key, index[key], "", read_entry)
        if gloss:
            return gloss
    for token in sorted(set(key.split()), key=lambda t: (-len(t), t)):
        _, gloss = pick_anchor_sense(
            key, index.get(token, []), "", read_entry)
        if gloss:
            return gloss
    return ""


def anchor_item_en(item, index, read_entry):
    """R6: fill item["sense_id"] + item["en_def"] from the scored anchor."""
    text = (item.get("text") or "").strip()
    if item.get("kind") == "word":
        entries = index.get(text.lower(), [])
        sid, gloss = pick_anchor_sense(
            text, entries, item.get("pos", ""), read_entry)
    else:
        key = text.lower()
        if key in index:
            sid, gloss = pick_anchor_sense(text, index[key], "", read_entry)
        else:
            sid, gloss = "", ""
            for token in sorted(set(key.split()),
                                key=lambda t: (-len(t), t)):
                cand_sid, cand = pick_anchor_sense(
                    text, index.get(token, []), "", read_entry)
                if cand:
                    sid, gloss = cand_sid, cand
                    break
    item["sense_id"] = sid
    item["en_def"] = gloss
    return item


def meta_leak_scan(card):
    """R2: regex EN+FA level words across all string fields -> hit list."""
    hits = []

    def walk(value):
        if isinstance(value, str):
            for rx in _META_LEAK_RES:
                hits.extend(m.group(0) for m in rx.finditer(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(card)
    return list(dict.fromkeys(hits))


def is_fa_dominant(fa_meaning, fa_explanation):
    """R7: pass iff Persian-script chars outnumber Latin-script chars."""
    combined = "%s\n%s" % (fa_meaning or "", fa_explanation or "")
    return len(_FA_RX.findall(combined)) > len(_LATIN_RX.findall(combined))


def headword_leak_tokens(text, kind):
    """R7: Latin tokens that must not leak into the FA fields."""
    lowered = (text or "").strip().lower()
    if (kind or "word") == "phrase":
        return [t for t in re.findall(r"[a-z']+", lowered) if len(t) >= 3]
    return [lowered] if lowered else []


def headword_leak_scan(text, kind, card):
    """R7: case-insensitive headword leak check over fa_meaning+fa_explanation.

    Rationale: front-of-card study prompting must not leak the answer —
    the Persian side must cue recall, not restate the Latin headword.
    """
    fa = "%s\n%s" % (card.get("fa_meaning") or "",
                     card.get("fa_explanation") or "")
    fa_low = fa.lower()
    return [t for t in headword_leak_tokens(text, kind) if t and t in fa_low]


COMPLETION_FIELDS = ("fa_meaning", "fa_explanation", "synonyms", "antonyms",
                     "examples", "example_translations", "grammar_tip",
                     "phonetic")


def build_completion_flags(card):
    """R8: gap-fill record {fields_filled[], sense_review, nothing_to_complete}."""
    filled = [k for k in COMPLETION_FIELDS if card.get(k)]
    return {"fields_filled": filled, "sense_review": True,
            "nothing_to_complete": len(filled) == len(COMPLETION_FIELDS)}


def similarity_note(en_def, model_d):
    """R8: informational difflib ratio between dataset en_def and model "d"."""
    a, b = (en_def or "").strip().lower(), (model_d or "").strip().lower()
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)


def assign_topic(text, gloss, lookup=None, sense_id=None, llm_transport=None,
                 progress_path=None, api_key=None, model_calls=None):
    """R6: topic via the exact v16b path, reused by import. Method "v16b-exact".

    Leg 1 (deterministic v16): run_v16_topics.evp_fallback_label by import.
    Leg 2 (v16b LLM top-up for Others): run_v16b_topup prompt + validation +
    same free model chain, resume file pilot_topic_progress.json (separate
    from the v16b originals). Hermetic when lookup/llm_transport injected;
    without an LLM transport an Other stays Other (no network in tests).
    Returns {"label", "method"} with method tag "v16b-exact".
    """
    if lookup is None:
        try:
            from run_v16_topics import evp_fallback_label as lookup
        except Exception:
            lookup = None
    label = None
    if lookup is not None:
        try:
            label = lookup(text, gloss or "")
        except Exception:
            label = None
    if label:
        return {"label": label, "method": TOPIC_METHOD_TAG}
    # Leg 2 — v16b top-up for Others, by import (no substitute heuristics).
    try:
        from run_v16b_topup import (MODELS as _TOPUP_MODELS,
                                    USER_TMPL as _TOPUP_TMPL,
                                    validate_senses as _topup_validate)
        from run_v16b_topup import lemma_block as _topup_block
    except Exception:
        return {"label": "Other / Abstract", "method": TOPIC_METHOD_TAG}
    sid = sense_id or ("%s#0" % ((text or "").strip().lower()))
    prog_path = pathlib.Path(progress_path) if progress_path else None
    cache = {}
    if prog_path is not None and prog_path.exists():
        try:
            cache = json.loads(prog_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    cache_key = "%s\t%s" % (text, gloss or "")
    if isinstance(cache, dict) and cache_key in cache:
        return {"label": cache[cache_key], "method": TOPIC_METHOD_TAG}
    if llm_transport is None:
        return {"label": "Other / Abstract", "method": TOPIC_METHOD_TAG}
    user_text = _TOPUP_TMPL + _topup_block(
        text, [{"sense_id": sid, "gloss": gloss or ""}])
    from llm_json import extract_json as _extract
    for model in _TOPUP_MODELS:
        if model_calls is not None:
            model_calls[model] = model_calls.get(model, 0) + 1
        try:
            raw = llm_transport(api_key, model, user_text)
            data = _extract(raw)
        except Exception:
            continue
        by_lemma = {x.get("lemma"): x for x in (data.get("results") or [])
                    if isinstance(x, dict)}
        items = (by_lemma.get(text) or {}).get("senses")
        ok, normed = _topup_validate(items, [sid])
        if ok and normed:
            found = normed[0].get("topic_label") or "Other / Abstract"
            if isinstance(cache, dict) and prog_path is not None:
                try:
                    cache[cache_key] = found
                    prog_path.write_text(json.dumps(cache, ensure_ascii=False),
                                         encoding="utf-8")
                except Exception:
                    pass
            return {"label": found, "method": TOPIC_METHOD_TAG}
    return {"label": "Other / Abstract", "method": TOPIC_METHOD_TAG}


def compute_quotas(n, levels=LEVEL_ORDER, extras=QUOTA_EXTRAS_ORDER):
    """Split n seats over CEFR levels: even base + remainder to extras order."""
    base, rem = divmod(n, len(levels))
    quotas = {lv: base for lv in levels}
    for lv in extras[:rem]:
        quotas[lv] += 1
    return quotas


def load_word_pool(path):
    with open(path, encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_phrase_judgements(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sample_words(pool, n_words=14, seed=SEED, pos_sets=None):
    """Stratified sample of unique lemmas across the pool CEFR mix.

    R4: when pos_sets (lemma.lower() -> kaikki POS set) is given,
    single-token lemmas whose POS set is subset of {name, propn} drop.
    """
    by_level = {lv: [] for lv in LEVEL_ORDER}
    seen = set()
    for row in pool:
        lemma = (row.get("lemma") or "").strip()
        cefr = (row.get("cefr") or "").strip()
        if not lemma or lemma in seen or cefr not in by_level:
            continue
        if pos_sets is not None and is_proper_noun_lemma(
                lemma, pos_sets.get(lemma.lower(), set())):
            continue
        seen.add(lemma)
        by_level[cefr].append(row)
    for lv in by_level:
        by_level[lv].sort(key=lambda r: r["lemma"])
    quotas = compute_quotas(n_words)
    rng = random.Random(seed)
    sample = []
    for lv in LEVEL_ORDER:
        group = by_level[lv]
        want = min(quotas[lv], len(group))
        sample.extend(rng.sample(group, want) if want else [])
    return [{"kind": "word", "text": r["lemma"], "pos": r.get("pos", ""),
             "pool_level": r["cefr"]} for r in sample]


def sample_phrases(judged, n_phrases=6, seed=SEED):
    """Spread sample across judged phrase levels."""
    by_level = {lv: [] for lv in LEVEL_ORDER}
    seen = set()
    for row in judged:
        phrase = (row.get("phrase") or "").strip()
        level = (row.get("verdict_level") or "").strip()
        if not phrase or phrase in seen or level not in by_level:
            continue
        if row.get("failed_flag"):
            continue
        seen.add(phrase)
        by_level[level].append(row)
    for lv in by_level:
        by_level[lv].sort(key=lambda r: r["phrase"])
    quotas = compute_quotas(n_phrases)
    rng = random.Random(seed)
    sample = []
    for lv in LEVEL_ORDER:
        group = by_level[lv]
        want = min(quotas[lv], len(group))
        sample.extend(rng.sample(group, want) if want else [])
    return [{"kind": "phrase", "text": r["phrase"],
             "freq": r.get("freq"), "pool_level": r["verdict_level"],
             "proper_noun": None}  # R4: not judged; open question for F4 re-judge
            for r in sample]


def item_key(item):
    return ("w:" if item["kind"] == "word" else "p:") + item["text"]


def build_prompts(item):
    """System/user prompts via the REAL learner-card prompt builder.

    The shared builder output is used verbatim (never forked); the pilot only
    appends user-side context: meta-leak ban (R2), dataset en_def + preserve
    instruction with the compact "d" key (R1/R6 anchor), phrase literal_fa
    grounding (R3), fa-dominant + headword-leak bans (R7), gap-fill +
    sense-review (R8).
    """
    bot_level = CEFR_TO_BOT_LEVEL[item["pool_level"]]
    system = card_prompts.custom_word_system_prompt(
        "en", bot_level, compact=card_prompts.card_output_is_compact())
    user = item["text"]
    extras = [META_LEAK_BAN, FA_DOMINANT_RULE, HEADWORD_LEAK_RULE,
              GAPFILL_INSTRUCTION]
    en_def = (item.get("en_def") or "").strip()
    if en_def:
        extras.append("Dictionary definition (preserve, do not contradict): "
                      + en_def)
        extras.append(EN_DEF_INSTRUCTION)
    if item.get("kind") == "phrase":
        extras.append(LITERAL_FA_INSTRUCTION)
    if extras:
        user = user + "\n" + "\n".join(extras)
    return system, user, bot_level


def validate_card_obj(obj, timings=None):
    """Validate with the REAL card validator. Returns (ok, card, reason).

    The compact->full expansion (_expand_card_aliases) inside validate_card
    is the live path — verified, not forked. timings optionally accumulates
    {"validate": seconds} for the TIMING stage split.
    """
    start = time.perf_counter()
    try:
        try:
            return True, validate_card(obj), ""
        except CardValidationError as exc:
            return False, None, str(exc)
        except Exception as exc:  # defensive: never crash the pilot on a card
            return False, None, "%s: %s" % (type(exc).__name__, str(exc)[:200])
    finally:
        if timings is not None:
            timings["validate"] = timings.get("validate", 0.0) \
                + (time.perf_counter() - start)


def call_responses(api_key, model, system, user, timeout=CALL_TIMEOUT):
    body = json.dumps({"model": model, "input": [
        {"role": "system", "content": system}, {"role": "user", "content": user}],
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": 2000}).encode()
    req = urllib.request.Request(
        ZEN_BASE + "/responses", data=body,
        headers={"Authorization": "Bearer %s" % api_key,
                 "Content-Type": "application/json",
                 "User-Agent": "HamZaban-factory/1.0 (card pilot)",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    parts = []
    for out_item in data.get("output", []):
        for chunk in out_item.get("content", []):
            if chunk.get("type") == "output_text":
                parts.append(chunk.get("text", ""))
    return "".join(parts)


def generate_card(item, api_key, transport=None, model_calls=None,
                   timings=None):
    """Generate + validate one card. Failures recorded, never raised.

    Only auth failures (401/403 via AuthError) propagate to abort loudly.
    R2/R7: a validated card that leaks level wording, fails fa-dominant, or
    leaks the Latin headword into the FA fields is regenerated once (the
    next attempt); a second violation is recorded valid=False. R8: gap-fill
    completion flags + informational similarity note recorded per card (no
    similarity regen). Pilot passthroughs ("d", "literal_fa") are read from
    the raw model JSON before validation (the validator ignores them).
    """
    transport = transport or call_responses
    if model_calls is None:
        model_calls = {}
    system, user, bot_level = build_prompts(item)
    record = {"key": item_key(item), "kind": item["kind"], "text": item["text"],
              "pool_level": item["pool_level"], "bot_level": bot_level,
              "sense_id": item.get("sense_id", ""),
              "en_def": item.get("en_def", ""),
              "en_source": "dataset" if item.get("en_def") else "none",
              "topic": item.get("topic", ""),
              "topic_method": item.get("topic_method", ""),
              "proper_noun": item.get("proper_noun"),
              "model_used": "", "card": None, "valid": False,
              "reason": "", "error": "", "model_d": "", "literal_fa": "",
              "leaks": [], "regen": False, "completion_flags": {},
              "similarity_note": 0.0, "fa_dominant": None,
              "headword_leaks": []}
    last_error = ""
    regen_used = False
    for model in MODELS:
        for attempt in range(MAX_ATTEMPTS):
            prompt = user if attempt == 0 else REPAIR_PREFIX + user
            try:
                model_calls[model] = model_calls.get(model, 0) + 1
                raw = transport(api_key, model, system, prompt)
                obj = extract_json(raw)
            except AuthError:
                raise
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise_for_auth(exc)  # maps to AuthError, aborts loud
                last_error = "HTTPError %s: %s" % (exc.code, str(exc)[:200])
                continue
            except Exception as exc:
                last_error = "%s: %s" % (type(exc).__name__, str(exc)[:200])
                continue
            ok, card, reason = validate_card_obj(obj, timings)
            if ok:
                leaks = meta_leak_scan(card)
                model_d = obj.get(EN_DEF_COMPACT_KEY) \
                    if isinstance(obj, dict) else ""
                literal_fa = obj.get(LITERAL_FA_KEY) \
                    if isinstance(obj, dict) else ""
                fa_ok = is_fa_dominant(card.get("fa_meaning", ""),
                                       card.get("fa_explanation", ""))
                hw_leaks = headword_leak_scan(item["text"], item["kind"],
                                              card)
                flags = build_completion_flags(card)
                sim = similarity_note(item.get("en_def", ""),
                                      model_d if isinstance(model_d, str)
                                      else "")
                violation = ""
                if leaks:
                    violation = "meta-leak: %s" % (
                        ", ".join(sorted(set(leaks)))[:200])
                elif not fa_ok:
                    violation = "fa-dominant"
                elif hw_leaks:
                    violation = "headword-leak: %s" % (
                        ", ".join(hw_leaks)[:200])
                if violation and not regen_used:
                    regen_used = True
                    record["regen"] = True
                    last_error = violation
                    continue  # the single R2/R7 regeneration
                if violation:
                    record["error"] = last_error = violation
                    record["reason"] = last_error
                    record["leaks"] = sorted(set(leaks))
                    record["fa_dominant"] = bool(fa_ok)
                    record["headword_leaks"] = hw_leaks
                    record["completion_flags"] = flags
                    record["similarity_note"] = sim
                    return record
                record.update(model_used=model, card=card, valid=True,
                              model_d=model_d if isinstance(model_d, str)
                              else "",
                              literal_fa=literal_fa
                              if isinstance(literal_fa, str) else "",
                              completion_flags=flags, similarity_note=sim,
                              fa_dominant=True, headword_leaks=[])
                return record
            last_error = "validation: %s" % reason
        # next model after exhausting attempts
    record["error"] = last_error
    record["reason"] = last_error
    return record


def build_timings(sample_s, gloss_s, gen_total, per_card, validate_s,
                  render_s, n_items):
    """TIMING payload: stage seconds + per-item avg + linear extrapolation
    to 3000 words + 500 phrases (3500 items). Persisted to timings.json."""
    stages = {"sample": sample_s, "gloss_resolve": gloss_s,
              "generate": gen_total, "validate": validate_s,
              "render": render_s}
    denom = max(1, n_items)
    return {
        "sample": sample_s, "gloss_resolve": gloss_s,
        "generate": {"total": gen_total, "per_card": per_card},
        "validate": validate_s, "render": render_s,
        "n_items": n_items, "target_items": TARGET_EXTRAPOLATION_ITEMS,
        "extrapolated_3500": {
            stage: (secs / denom) * TARGET_EXTRAPOLATION_ITEMS
            for stage, secs in stages.items()},
    }


def git_commit():
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()[:12] or "unknown"
    except Exception:
        return "unknown"


def tehran_now_str():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Tehran")
    except Exception:
        tz = timezone(timedelta(hours=3, minutes=30))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z")


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def render_timings_table(timings):
    """TIMING stage table: stage, seconds, per-item avg, 3500-item extrapolation."""
    if not timings:
        return ""
    stages = [("sample", timings.get("sample", 0.0)),
              ("gloss_resolve", timings.get("gloss_resolve", 0.0)),
              ("generate", (timings.get("generate") or {}).get("total", 0.0)
               if isinstance(timings.get("generate"), dict)
               else timings.get("generate", 0.0)),
              ("validate", timings.get("validate", 0.0)),
              ("render", timings.get("render", 0.0))]
    denom = max(1, timings.get("n_items", 0))
    rows = []
    for stage, secs in stages:
        secs = float(secs or 0.0)
        avg = secs / denom
        extra = avg * TARGET_EXTRAPOLATION_ITEMS
        rows.append("<tr><td class=\"en\">%s</td><td>%.2f</td><td>%.3f</td>"
                    "<td>%.1f</td></tr>" % (esc(stage), secs, avg, extra))
    return (
        "<h2>زمان‌بندی مراحل (ثانیه)</h2>\n"
        "<table border=\"1\" cellpadding=\"4\">\n"
        "<tr><th>مرحله</th><th>ثانیه</th><th>میانگین هر مورد</th>"
        "<th>برون‌یابی خطی ۳۰۰۰ واژه + ۵۰۰ عبارت</th></tr>\n"
        + "\n".join(rows) + "\n</table>")


def render_gallery(cards, meta):
    """Render the Persian RTL gallery HTML for card records."""
    total = len(cards)
    passed = sum(1 for c in cards if c.get("valid"))
    rate = (100.0 * passed / total) if total else 0.0
    calls = meta.get("model_calls", {})
    calls_str = ", ".join("<span class=\"en\">%s: %d</span>" % (esc(m), n)
                          for m, n in calls.items()) or "—"
    timings_table = render_timings_table(meta.get("timings"))
    sections = []
    for idx, rec in enumerate(cards, 1):
        card = rec.get("card") or {}
        if rec.get("valid"):
            badge = "<span class=\"badge ok\">تأیید شد</span>"
        elif rec.get("card") is not None:
            badge = "<span class=\"badge bad\">نامعتبر: %s</span>" % esc(rec.get("reason"))
        else:
            badge = "<span class=\"badge bad\">خطا: %s</span>" % esc(rec.get("error") or rec.get("reason"))
        kind_fa = "واژه" if rec.get("kind") == "word" else "عبارت"
        examples = "".join(
            "<li><span class=\"en\">%s</span><br>%s</li>"
            % (esc(e), esc(t))
            for e, t in zip(card.get("examples", []),
                            card.get("example_translations", [])))
        syns = ", ".join("<span class=\"en\">%s</span>" % esc(s)
                         for s in card.get("synonyms", [])) or "—"
        ants = ", ".join("<span class=\"en\">%s</span>" % esc(a)
                         for a in card.get("antonyms", [])) or "—"
        phon = card.get("phonetic", {})
        ipa = esc(phon.get("ipa", "") if isinstance(phon, dict) else phon)
        raw_json = esc(json.dumps(card, ensure_ascii=False) if card else "")
        topic = rec.get("topic") or ""
        method = rec.get("topic_method") or TOPIC_METHOD_TAG
        topic_html = ("<p>موضوع: <span class=\"chip\">%s</span> "
                      "<span class=\"en\">(%s)</span></p>"
                      % (esc(topic), esc(method))) if topic else ""
        sense_id = (rec.get("sense_id") or "").strip()
        en_def = (rec.get("en_def") or "").strip()
        model_d = (rec.get("model_d") or "").strip()
        if sense_id or en_def or model_d:
            en_html = "<p><b>لنگر معنایی (sense anchor):</b> " \
                "<span class=\"en\">%s</span> ـ %s</p>" \
                % (esc(sense_id) if sense_id else "—",
                   esc(en_def) if en_def else "—")
            if model_d:
                en_html += "<p><b>تکمیل مدل (model-completed):</b> " \
                    "<span class=\"en\">%s</span></p>" % esc(model_d)
            sim = rec.get("similarity_note")
            if isinstance(sim, float):
                en_html += "<p>شباهت تعریف (informational): " \
                    "<span class=\"en\">%.3f</span></p>" % sim
        else:
            en_html = ""
        flags = rec.get("completion_flags") or {}
        if flags:
            filled = ", ".join("<span class=\"en\">%s</span>" % esc(f)
                               for f in flags.get("fields_filled", [])) or "—"
            en_html += "<p><b>تکمیل شکاف + بازبینی معنایی:</b> پرشده: %s ـ " \
                "بازبینی: %s ـ بدون‌کار: %s</p>" \
                % (filled, esc(flags.get("sense_review")),
                   esc(flags.get("nothing_to_complete")))
        literal_fa = (rec.get("literal_fa") or "").strip()
        literal_html = ("<p><b>معنی تحت‌اللفظی:</b> %s</p>" % esc(literal_fa)) \
            if rec.get("kind") == "phrase" and literal_fa else ""
        proper_html = ""
        if rec.get("kind") == "phrase" and rec.get("proper_noun") is None:
            proper_html = ("<p>نام خاص: قضاوت نشده ـ سؤال باز برای "
                           "داوری مجدد F4</p>")
        sections.append(
            "<section class=\"card\" id=\"card-%d\">\n"
            "<h2><span class=\"en\">%s</span> <span class=\"kind\">(%s)</span> %s</h2>\n"
            "<p>سطح برچسب: <b>%s</b> ـ سطح کارت: <b>%s</b> ـ مدل: "
            "<span class=\"en\">%s</span></p>\n"
            "%s\n"
            "%s\n"
            "%s\n"
            "%s\n"
            "<p><b>معنی:</b> %s</p>\n"
            "<p><b>توضیح:</b> %s</p>\n"
            "<p><b>تلفظ:</b> <span class=\"en\">%s</span></p>\n"
            "<p><b>مثال‌ها:</b></p>\n<ol>%s</ol>\n"
            "<p><b>مترادف:</b> %s</p>\n<p><b>متضاد:</b> %s</p>\n"
            "<p><b>نکته گرامری:</b> %s</p>\n"
            "<details><summary>JSON خام</summary>"
            "<pre class=\"en\">%s</pre></details>\n"
            "</section>"
            % (idx, esc(rec.get("text")), kind_fa, badge,
               esc(rec.get("pool_level")), esc(rec.get("bot_level")),
               esc(rec.get("model_used") or "—"),
               topic_html, en_html, literal_html, proper_html,
               esc(card.get("fa_meaning", "—")), esc(card.get("fa_explanation", "—")),
               ipa, examples or "<li>—</li>", syns, ants,
               esc(card.get("grammar_tip", "—") or "—"), raw_json))
    return (
        "<!DOCTYPE html>\n<html lang=\"fa\" dir=\"rtl\">\n<head>\n"
        "<meta charset=\"utf-8\">\n<title>گذرنامه کارت‌ها</title>\n"
        "<link rel=\"stylesheet\" "
        "href=\"https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css\">\n"
        "<style>\n"
        "body{font-family:Vazirmatn,Tahoma,sans-serif;max-width:900px;margin:auto;padding:1em;}\n"
        ".en{font-family:Georgia,serif;direction:ltr;unicode-bidi:embed;}\n"
        ".card{border:1px solid #ccc;border-radius:8px;padding:1em;margin:1em 0;}\n"
        ".badge{border-radius:4px;padding:0.1em 0.5em;font-size:0.85em;}\n"
        ".ok{background:#d9f2d9;} .bad{background:#f7d9d9;}\n"
        ".chip{background:#e3ecf7;border-radius:10px;padding:0.1em 0.6em;}\n"
        "pre{white-space:pre-wrap;}\n"
        "</style>\n</head>\n<body>\n"
        "<h1>گذرنامه کارت‌ها (آزمایشی)</h1>\n"
        "<p>تاریخ تهران: %s ـ commit: <span class=\"en\">%s</span></p>\n"
        "<p>کارت‌ها: %d ـ تأییدشده: %d ـ نرخ قبولی: %.1f%%</p>\n"
        "<p>فراخوانی مدل‌ها: %s ـ هزینه مورد انتظار: $0 (زنجیره رایگان)</p>\n"
        "<p>روش موضوع: v16b-exact ـ مسیر دقیق v16b (قطعی v16 از "
        "run_v16_topics + تکمیل Others از run_v16b_topup).</p>\n"
        "%s\n"
        "%s\n</body>\n</html>"
        % (esc(meta.get("date_tehran", "")), esc(meta.get("commit", "")),
           total, passed, rate, calls_str, timings_table,
           "\n".join(sections)))


def load_cards_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Card-gen pilot (factory research)")
    ap.add_argument("--n-words", type=int, default=14)
    ap.add_argument("--n-phrases", type=int, default=6)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--report", default=DEFAULT_REPORT)
    ap.add_argument("--word-pool", default=str(
        REPO_ROOT / "factory" / "packs" / "en" / "lemmas_10k.csv"))
    ap.add_argument("--phrase-log", default=(
        "W:/hamzaban_data_factory/fixtures/phrase_judge_log.jsonl"))
    ap.add_argument("--kaikki-index", default=DEFAULT_KAIKKI_INDEX)
    ap.add_argument("--kaikki-raw", default=DEFAULT_KAIKKI_RAW)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    pool = load_word_pool(args.word_pool)
    judged = load_phrase_judgements(args.phrase_log)
    if args.dry_run:
        # Hermetic: no kaikki/W: touch, no files, no network.
        sample = sample_words(pool, args.n_words, args.seed)
        sample += sample_phrases(judged, args.n_phrases, args.seed)
        print("dry-run: %d words + %d phrases sampled, no files written, "
              "no network calls" % (args.n_words, args.n_phrases))
        return 0

    sample_start = time.perf_counter()
    try:
        index = load_kaikki_index(args.kaikki_index)
    except OSError as exc:
        sys.exit("cannot load kaikki index %s: %s" % (args.kaikki_index, exc))
    pos_sets = build_pos_sets(index)
    sample = sample_words(pool, args.n_words, args.seed, pos_sets=pos_sets)
    sample += sample_phrases(judged, args.n_phrases, args.seed)
    if len(sample) != args.n_words + args.n_phrases:
        print("warning: short sample %d (pool gaps)" % len(sample))
    sample_s = time.perf_counter() - sample_start

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sample_path = out_dir / "sample.json"
    if sample_path.exists():
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        print("reusing persisted sample (%d items)" % len(sample))

    def read_entry(row):
        return read_kaikki_entry(args.kaikki_raw, row["offset"],
                                 row["length"])

    gloss_start = time.perf_counter()
    sys.path.insert(0, str(FACTORY_DIR))
    from env_loader import load_factory_env
    _env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
    _topic_key = _env.get("OPENCODE_ZEN_API_KEY", "")
    from run_v16b_topup import call_responses as _topup_transport
    topic_calls = {}
    topic_prog = out_dir / PILOT_TOPIC_PROGRESS
    for item in sample:  # R6 anchor + v16b-exact topic enrichment
        if not item.get("en_def") or not item.get("sense_id"):
            anchor_item_en(item, index, read_entry)
        if not item.get("topic"):
            assigned = assign_topic(
                item["text"], item.get("en_def", ""),
                sense_id=item.get("sense_id") or None,
                llm_transport=_topup_transport, progress_path=topic_prog,
                api_key=_topic_key, model_calls=topic_calls)
            item["topic"] = assigned["label"]
            item["topic_method"] = assigned["method"]
    sample_path.write_text(json.dumps(sample, ensure_ascii=False),
                           encoding="utf-8")
    gloss_s = time.perf_counter() - gloss_start

    env = _env
    api_key = env["OPENCODE_ZEN_API_KEY"]
    if not api_key:
        sys.exit("no OPENCODE_ZEN_API_KEY in factory/.env")

    prog_path = out_dir / "progress.json"
    prog = json.loads(prog_path.read_text(encoding="utf-8")) if prog_path.exists() else {}
    done = prog.get("done", {})
    model_calls = prog.get("model_calls", {})
    gen_timings = {"validate": 0.0}
    per_card = []
    gen_start = time.perf_counter()
    for item in sample:
        key = item_key(item)
        if key in done:
            continue
        card_start = time.perf_counter()
        rec = generate_card(item, api_key, model_calls=model_calls,
                            timings=gen_timings)
        per_card.append({"key": key,
                         "seconds": time.perf_counter() - card_start})
        done[key] = rec
        prog_path.write_text(json.dumps(
            {"done": done, "failed": [k for k, v in done.items() if not v.get("valid")],
             "model_calls": model_calls}, ensure_ascii=False), encoding="utf-8")
        print("%s %s valid=%s model=%s" % (
            rec["kind"], rec["text"], rec["valid"], rec["model_used"] or "none"))
        time.sleep(CALL_SLEEP)
    gen_total = time.perf_counter() - gen_start

    records = [done[item_key(item)] for item in sample]
    (out_dir / "cards.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8")
    render_start = time.perf_counter()
    timings = build_timings(sample_s, gloss_s, gen_total, per_card,
                            gen_timings["validate"],
                            0.0, len(sample))
    meta = {"date_tehran": tehran_now_str(), "commit": git_commit(),
            "model_calls": model_calls, "timings": timings}
    gallery_html = render_gallery(records, meta)
    timings["render"] = time.perf_counter() - render_start
    meta["timings"] = timings  # refresh with measured render seconds
    gallery_html = render_gallery(records, meta)
    report_path = pathlib.Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(gallery_html, encoding="utf-8")
    (out_dir / "timings.json").write_text(
        json.dumps(timings, ensure_ascii=False), encoding="utf-8")
    passed = sum(1 for r in records if r.get("valid"))
    print("pilot done: %d/%d valid, calls=%s, report=%s"
          % (passed, len(records), model_calls, report_path))
    return 0


if __name__ == "__main__":
    main()
