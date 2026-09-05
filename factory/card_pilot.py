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
- Enrichment v4 (locked R10-R14): pre-card IPA from the anchored sense's
  kaikki entry sounds[] (model fills gaps only, ``ipa_src`` dataset/model);
  pre-card examples from the anchored sense + tatoeba pool (FROZEN, model
  fills missing slots only, ``examples_src`` per example); full v16b topic
  vector (1-3 entries, ``topic_vector``); dataset example filter 8-20 words
  with prompt cap ~15 words and informational long_example flag (no regen);
   warm diff-style gallery (pre-card | operation | final per field).
- Pilot v5 (locked R15-R18): grammar_tip under the same fa-dominant rule
  (1 regen, then valid=False); top-3 sense_candidates on every record,
  shown ranked in the diff header; second-best also_sense as a small
  "نیز:" line (topic from the cheap vector leg only, else null + tag;
  single-sense cards unchanged); richness_counters {ipa/examples/topics %}
  in the gallery header + timings.json; opportunistic phrase_type chip +
  applied_keep flag for phrases (missing log = unjudged, never fails).

Usage (owner run, real generation — takes time, ~20 model calls):
    python factory/card_pilot.py --n-words 14 --n-phrases 6
Dry run (no network, no files written):
    python factory/card_pilot.py --dry-run
Render only (no network, no env: rebuild HTML from persisted cards.jsonl +
timings.json, never touches sample/cards):
    python factory/card_pilot.py --render-only
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
from telemetry import extract_usage as tele_extract_usage  # noqa: E402
from telemetry import record_call as tele_record_call  # noqa: E402
from telemetry import render_telemetry_table as tele_table  # noqa: E402
from telemetry import write_summary as tele_write_summary  # noqa: E402
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

# Pre-card pipeline method tag (factory/precard_pipeline.py R22-R25): items
# arriving via --from-precard carry this method in the gallery. The default
# sampling/anchor/topic/enrichment path is untouched.
PIPELINE_METHOD_TAG = "pipeline-v6"

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

# R7/R15/R-v7 — fa-dominant + headword-leak prompt rules (appended
# pilot-side, shared builder untouched). R15: grammar_tip is Persian prose
# too. V7: the rule is PER FIELD (fa_meaning lenient: at most 3 Latin
# characters for loanwords) — the combined-count loophole is closed.
FA_DOMINANT_RULE = ("Write fa_meaning, fa_explanation and grammar_tip each "
                    "in Persian: in EACH of these fields Persian-script "
                    "characters must outnumber Latin-script characters "
                    "(fa_meaning may keep at most 3 Latin characters for "
                    "loanwords; Latin terms allowed inside Persian prose).")
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

# R10 — IPA enrichment (pre-card from datasets, model fills gaps only).
# The compact "ph" key is the live bot path (_expand_card_aliases), so the
# pilot instructs the model to preserve the dataset IPA under "ph".
IPA_SRC_DATASET = "dataset"
IPA_SRC_MODEL = "model"
IPA_PRESERVE_INSTRUCTION = (
    'Pronunciation IPA (compact key "ph"): PRESERVE the given IPA exactly '
    "under phonetic; do not invent a different transcription.")

# R11/R13 — example enrichment: kaikki anchored-sense examples[] first, then
# the tatoeba pool lemma list, until 2. Dataset filter 8-20 words inclusive
# (English word count); tatoeba pool is already length-suitable, capped at
# 20 words defensively. Dataset examples are FROZEN (never rewritten); the
# model fills only missing slots and translates ALL examples to Persian.
# Prompt cap ~15 words max per example; long_example (>20w) is an
# informational machine flag only, never a regen.
EXAMPLE_MIN_WORDS = 8
EXAMPLE_MAX_WORDS = 20
EXAMPLE_PROMPT_CAP = ("Each English example ~15 words max.")
EXAMPLE_LENGTH_RULE = EXAMPLE_PROMPT_CAP
N_EXAMPLES = 2

# R12 — full v16b topic vector (1-3 {label, weight} entries) for the anchored
# sense: from the leg-2 normed output, else topic_vectors-v16b.json lookup by
# sense_id, else the single-label fallback [{label, 1.0}].
DEFAULT_TATOEBA_POOL = ("W:/hamzaban_data_factory/fixtures/"
                        "tatoeba_pool_v13a.json")
DEFAULT_TOPIC_VECTORS = ("W:/hamzaban_data_factory/fixtures/"
                         "topic_vectors-v16b.json")

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
    """Flatten index rows -> [(entry_pos, entry, sense_dict, gloss)].

    File order is preserved (sense ids are file-order indices); entries
    that fail to read are skipped. R10: the entry travels with the sense
    so the anchored sense's sounds[] (IPA) comes from the same read used
    for the gloss anchor.
    """
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
                out.append((entry_pos, entry, sense, gloss))
    return out


def score_senses(text, entries, pool_pos, read_entry):
    """Score every kaikki sense: [(score, file-idx, entry, sense, gloss)].

    Vendored v14 register_penalty * ppos, stable file order, best first.
    Shared by the anchor pick and the R17/R18 audit helpers so the anchor,
    the top-3 candidates, and the second sense never diverge.
    """
    senses = _collect_kaikki_senses(entries, read_entry)
    scored = []
    for idx, (entry_pos, entry, sense, gloss) in enumerate(senses):
        score = (_v14_register_penalty(sense.get("tags"), gloss)
                 * _v14_ppos(entry_pos, pool_pos))
        scored.append((score, idx, entry, sense, gloss))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return scored


def top_sense_candidates(text, entries, pool_pos, read_entry, k=3):
    """R17: top-k anchor candidates [{sense_id, gloss, score}] (ranked).

    sense_id is "<text.lower()>#<file-order-sense-idx>"; score rounded
    to 3 decimals. Empty entries -> [].
    """
    key = (text or "").strip().lower()
    return [{"sense_id": "%s#%d" % (key, idx), "gloss": gloss,
             "score": round(score, 3)}
            for score, idx, _, _, gloss
            in score_senses(text, entries, pool_pos, read_entry)[:k]]


# R18: second-sense topic choice — audit-only field, so NO extra LLM calls.
# The topic comes from the cheap deterministic legs only (topic-vector
# lookup by sense_id, loaded from topic_vectors-v16b.json); otherwise the
# topic stays null with this method tag. Stated, not silent.
ALSO_TOPIC_UNASSIGNED = "unassigned-cheap-only"


def build_also_sense(candidates, vector_lookup=None):
    """R18: second-best sense {sense_id, gloss, topic, topic_method}.

    Single-sense (or empty) candidate lists -> None (card unchanged).
    Topic via the cheap vector_lookup leg only; else null + tag.
    """
    if not candidates or len(candidates) < 2:
        return None
    second = candidates[1]
    vec = (vector_lookup or {}).get(second["sense_id"])
    if vec:
        return {"sense_id": second["sense_id"], "gloss": second["gloss"],
                "topic": vec[0]["label"],
                "topic_method": TOPIC_METHOD_TAG}
    return {"sense_id": second["sense_id"], "gloss": second["gloss"],
            "topic": None, "topic_method": ALSO_TOPIC_UNASSIGNED}


def pick_anchor_sense_full(text, entries, pool_pos, read_entry):
    """R6 anchor + R10/R11 carriers: (sense_id, gloss, sense, entry).

    Scoring is identical to pick_anchor_sense (vendored v14
    register_penalty * ppos, stable file order); sense_id is
    "<text.lower()>#<file-order-sense-idx>". Empty entries ->
    ("", "", None, None).
    """
    scored = score_senses(text, entries, pool_pos, read_entry)
    if not scored:
        return "", "", None, None
    _, best_idx, best_entry, best_sense, best_gloss = scored[0]
    key = (text or "").strip().lower()
    return "%s#%d" % (key, best_idx), best_gloss, best_sense, best_entry


def pick_anchor_sense(text, entries, pool_pos, read_entry):
    """R6: score every kaikki sense, anchor = top scorer (stable file order).

    Score = vendored v14 register_penalty * v14 ppos factor. Returns
    (sense_id, gloss); sense_id is "<text.lower()>#<file-order-sense-idx>".
    Empty entries -> ("", "").
    """
    sid, gloss, _, _ = pick_anchor_sense_full(
        text, entries, pool_pos, read_entry)
    return sid, gloss


def anchor_entry_pos_for_entries(text, entries, pool_pos, read_entry):
    """Entry POS of the anchored sense's entry ("" when no anchor).

    The anchor itself is always chosen by pick_anchor_sense_full (the ONE
    anchor choke point); this helper only REPORTS that entry's POS so the
    pre-card pipeline S1 can drop proper-noun anchors
    (entry POS in PROPER_NOUN_POS, deterministic, no name lists).
    anchor_item_en itself never drops.
    """
    _, _, _, entry = pick_anchor_sense_full(
        text, entries, pool_pos, read_entry)
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("pos") or "").strip().casefold()


def first_entry_ipa(entry):
    """R10: first ipa string of a kaikki entry's sounds[] ("" if none)."""
    for sound in (entry or {}).get("sounds") or []:
        if not isinstance(sound, dict):
            continue
        ipa = sound.get("ipa")
        if isinstance(ipa, str) and ipa.strip():
            return ipa.strip()
    return ""


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


def load_tatoeba_pool(path):
    """lemma.lower() -> [example, ...]; missing/unreadable file -> {}."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).lower(): [s for s in v if isinstance(s, str) and s.strip()]
            for k, v in data.items() if isinstance(v, list)}


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


def resolve_dataset_examples(item, index, read_entry, tatoeba_pool=None):
    """R11: anchored-sense kaikki examples first, then tatoeba, until 2.

    Fills item["dataset_examples"] (0-2 frozen strings). Deterministic:
    the anchor is re-derived with the same scorer as anchor_item_en.
    """
    text = (item.get("text") or "").strip()
    kind = item.get("kind") or "word"
    key = text.lower()
    sense = None
    if kind == "word":
        _, _, sense, _ = pick_anchor_sense_full(
            text, index.get(key, []), item.get("pos", ""), read_entry)
    elif key in (index or {}):
        _, _, sense, _ = pick_anchor_sense_full(
            text, index[key], "", read_entry)
    else:
        for token in sorted(set(key.split()), key=lambda t: (-len(t), t)):
            _, gloss, sense, _ = pick_anchor_sense_full(
                text, (index or {}).get(token, []), "", read_entry)
            if gloss:
                break
        else:
            sense = None
    picked = filter_examples_by_length(sense_example_texts(sense))
    if len(picked) < N_EXAMPLES:
        extra = filter_examples_by_length(
            tatoeba_candidates(tatoeba_pool, text, kind), loose_cap=True)
        seen = set(picked)
        for cand in extra:
            if cand not in seen:
                picked.append(cand)
                seen.add(cand)
            if len(picked) >= N_EXAMPLES:
                break
    item["dataset_examples"] = picked[:N_EXAMPLES]
    return item


def load_topic_vectors(path):
    """sense_id -> [{label, weight}...] from topic_vectors-v16b.json.

    File shape: [{lemma, vectors: [{sense_id, vector:
    [{topic_id, topic_label, weight}]}]}]. Missing/unreadable -> {}.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, list):
        return {}
    out = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        for scored in (row.get("vectors") or []):
            if not isinstance(scored, dict):
                continue
            sid = scored.get("sense_id")
            vec = scored.get("vector") or []
            normed = []
            for entry in vec:
                if not isinstance(entry, dict):
                    continue
                label = entry.get("topic_label")
                try:
                    weight = float(entry.get("weight"))
                except (TypeError, ValueError):
                    continue
                if isinstance(label, str) and label and weight > 0:
                    normed.append({"label": label,
                                   "weight": round(weight, 4)})
            if sid and normed:
                normed.sort(key=lambda d: -d["weight"])
                out[sid] = normed[:3]
    return out


def single_topic_vector(label):
    """R12 single-label fallback: [{label, 1.0}]."""
    return [{"label": label or "Other / Abstract", "weight": 1.0}]


def long_example_flags(card):
    """R13: final examples over 20 words — informational only, no regen."""
    return [e for e in (card or {}).get("examples") or []
            if isinstance(e, str) and en_word_count(e) > EXAMPLE_MAX_WORDS]


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


def anchor_item_en(item, index, read_entry, vector_lookup=None):
    """R6 anchor + R10 IPA + R17 candidates + R18 second sense.

    Fills sense_id/en_def + ipa/ipa_src (R6/R10, unchanged) and the audit
    trail: sense_candidates (top-3 [{sense_id, gloss, score}]) from the
    SAME entries the anchor was picked from, plus also_sense (second-best
    {sense_id, gloss, topic, topic_method}, None when single-sense).
    The also-sense topic uses the cheap vector_lookup leg only (R18
    choice: no LLM for an audit-only field).
    """
    text = (item.get("text") or "").strip()
    sense, entry = None, None
    cand_entries, cand_pos = [], ""
    if item.get("kind") == "word":
        entries = index.get(text.lower(), [])
        cand_entries, cand_pos = entries, item.get("pos", "")
        sid, gloss, sense, entry = pick_anchor_sense_full(
            text, entries, item.get("pos", ""), read_entry)
    else:
        key = text.lower()
        if key in index:
            cand_entries = index[key]
            sid, gloss, sense, entry = pick_anchor_sense_full(
                text, index[key], "", read_entry)
        else:
            sid, gloss = "", ""
            for token in sorted(set(key.split()),
                                key=lambda t: (-len(t), t)):
                cand_sid, cand, sense, entry = pick_anchor_sense_full(
                    text, index.get(token, []), "", read_entry)
                if cand:
                    sid, gloss = cand_sid, cand
                    cand_entries = index.get(token, [])
                    break
            else:
                sense, entry = None, None
    item["sense_id"] = sid
    item["en_def"] = gloss
    ipa = first_entry_ipa(entry)
    item["ipa"] = ipa
    item["ipa_src"] = IPA_SRC_DATASET if ipa else IPA_SRC_MODEL
    candidates = top_sense_candidates(text, cand_entries, cand_pos,
                                      read_entry)
    item["sense_candidates"] = candidates
    item["also_sense"] = build_also_sense(candidates, vector_lookup)
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


# V7 — fa_meaning leniency: at most this many Latin characters pass
# regardless (loanwords such as "TV" inside Persian prose).
FA_MEANING_MAX_LATIN = 3


def fa_field_ok(text, *, max_latin=0):
    """One Persian-prose field: nonempty, some Persian script, fa>latin.

    The max_latin leniency passes short Latin runs (loanwords) without
    dropping the fa>latin requirement otherwise. Digits-only strings
    fail (no Persian script).
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    fa_n = len(_FA_RX.findall(stripped))
    latin_n = len(_LATIN_RX.findall(stripped))
    if fa_n == 0:
        return False
    if latin_n <= max_latin:
        return True
    return fa_n > latin_n


def is_fa_dominant(fa_meaning, fa_explanation, grammar_tip=""):
    """R7/R15/v7: pass iff EACH Persian-prose field passes on its own.

    Per-field rule (v7, combined-count loophole closed): fa_meaning is
    lenient (at most FA_MEANING_MAX_LATIN Latin chars for loanwords),
    fa_explanation must be fa-dominant, and a non-empty grammar_tip must
    be fa-dominant (empty grammar_tip is skipped — gap-fill flags track
    emptiness separately, and the "" default keeps 2-arg calls working).
    """
    if not fa_field_ok(fa_meaning, max_latin=FA_MEANING_MAX_LATIN):
        return False
    if not fa_field_ok(fa_explanation):
        return False
    if (grammar_tip or "").strip() and not fa_field_ok(grammar_tip):
        return False
    return True


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


# V7 — phrase-example containment + word headword containment.
# No NLP library: plain case-insensitive substring plus a crude stem
# prefix (head minus ~2 chars) so inflected forms ("resilience" for head
# "resilient", "running" for "run") still match. Deterministic.
_HEAD_TOKEN_RX = re.compile(r"[A-Za-z']+")


def example_contains_head(example, headword, kind="word"):
    """V7: one example contains the headword (word) or phrase (phrase)."""
    ex = (example or "").lower()
    head = (headword or "").strip().lower()
    if not head or not ex:
        return False
    if (kind or "word") == "phrase":
        return head in ex
    if head in ex:
        return True
    if len(head) < 3:
        return False
    stem_len = min(len(head), max(4, len(head) - 2))
    stem = head[:stem_len]
    for token in _HEAD_TOKEN_RX.findall(ex):
        if len(token) >= stem_len and token.startswith(stem):
            return True
    return False


def example_containment_ok(text, kind, card):
    """V7: EVERY example contains the phrase text / headword (or stem)."""
    examples = (card or {}).get("examples") or []
    if not examples:
        return False
    return all(example_contains_head(e, text, kind) for e in examples)


# V7 — translation fidelity: review prompt line (appended pilot-side,
# shared builder untouched) + mechanical token-count gate (whitespace
# split): each fa translation must carry >= 50% of its en example's
# tokens, else the translation dropped named entities/numbers/sense.
FIDELITY_INSTRUCTION = ("Each fa translation must preserve all named "
                        "entities, numbers and the headword sense; "
                        "never drop them.")
FIDELITY_MIN_RATIO = 0.5

# R25 — production grammar line (verbatim-adapted from the production
# grammar_tip prompt: services.ai.ai grammar_tip_system_prompt explains
# terms "با معادل زبان مقصد یا لاتین"; for EN cards the target language
# IS English) + level-conditioned guidance from the SHARED
# services.ai.prompts.level_prompt_guidance (reused by import via
# card_prompts, never copied). Keyed ONLY by the anchored pre-card
# pool_level (CEFR_TO_BOT_LEVEL) — never a generic user level.
GRAMMAR_TIP_FA_RULE = ("نکته گرامری به فارسی بنویس؛ نام اصطلاحات را "
                       "با معادل انگلیسی هم بیاور")


def translation_fidelity_ok(card):
    """V7 mechanical gate: len(fa.split()) >= 50% of len(en.split())."""
    examples = (card or {}).get("examples") or []
    translations = (card or {}).get("example_translations") or []
    if not examples or len(examples) != len(translations):
        return False
    for en, fa in zip(examples, translations):
        if len((fa or "").split()) < FIDELITY_MIN_RATIO * len(
                (en or "").split()):
            return False
    return True


def split_frozen_by_containment(item):
    """V7 containment-release (locked A): split dataset examples.

    Returns (kept, released): dataset examples PASSING phrase/word
    containment stay FROZEN (kept); examples FAILING containment are
    released for model replacement. The caller grows the fill need as
    N_EXAMPLES - len(kept) and records ``released`` in
    completion_flags["released_containment"].
    """
    texts = [e for e in (item.get("dataset_examples") or [])
             if isinstance(e, str) and e.strip()][:N_EXAMPLES]
    kept, released = [], []
    for text in texts:
        if example_contains_head(text, item.get("text", ""),
                                 item.get("kind") or "word"):
            kept.append(text)
        else:
            released.append(text)
    return kept, released


COMPLETION_FIELDS = ("fa_meaning", "fa_explanation", "synonyms", "antonyms",
                     "examples", "example_translations", "grammar_tip",
                     "phonetic")


def build_completion_flags(card, released_containment=None):
    """R8: gap-fill record {fields_filled[], sense_review, nothing_to_complete}.

    V7 containment-release: ``released_containment`` lists the dataset
    example strings released for model replacement (containment-fail);
    always recorded (empty list when nothing was released).
    """
    filled = [k for k in COMPLETION_FIELDS if card.get(k)]
    return {"fields_filled": filled, "sense_review": True,
            "nothing_to_complete": len(filled) == len(COMPLETION_FIELDS),
            "released_containment": list(released_containment or [])}


def similarity_note(en_def, model_d):
    """R8: informational difflib ratio between dataset en_def and model "d"."""
    a, b = (en_def or "").strip().lower(), (model_d or "").strip().lower()
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)


def assign_topic(text, gloss, lookup=None, sense_id=None, llm_transport=None,
                 progress_path=None, api_key=None, model_calls=None,
                 vector_lookup=None):
    """R6 topic via the exact v16b path + R12 full vector. Method "v16b-exact".

    Leg 1 (deterministic v16): run_v16_topics.evp_fallback_label by import.
    Leg 2 (v16b LLM top-up for Others): run_v16b_topup prompt + validation +
    same free model chain, resume file pilot_topic_progress.json (separate
    from the v16b originals). Hermetic when lookup/llm_transport injected;
    without an LLM transport an Other stays Other (no network in tests).
    Returns {"label", "method", "vector"} with method tag "v16b-exact";
    "vector" is the full 1-3 entry [{label, weight}] list for the anchored
    sense — from the leg-2 normed output, else vector_lookup (sense_id ->
    vector, loaded from topic_vectors-v16b.json via load_topic_vectors),
    else the single-label fallback [{label, 1.0}].
    """
    sid = sense_id or ("%s#0" % ((text or "").strip().lower()))
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
        vec = (vector_lookup or {}).get(sid)
        return {"label": label, "method": TOPIC_METHOD_TAG,
                "vector": list(vec) if vec else single_topic_vector(label)}
    # Leg 2 — v16b top-up for Others, by import (no substitute heuristics).
    try:
        from run_v16b_topup import (MODELS as _TOPUP_MODELS,
                                    USER_TMPL as _TOPUP_TMPL,
                                    validate_senses as _topup_validate)
        from run_v16b_topup import lemma_block as _topup_block
    except Exception:
        vec = (vector_lookup or {}).get(sid)
        return {"label": "Other / Abstract", "method": TOPIC_METHOD_TAG,
                "vector": list(vec) if vec
                else single_topic_vector("Other / Abstract")}
    prog_path = pathlib.Path(progress_path) if progress_path else None
    cache = {}
    if prog_path is not None and prog_path.exists():
        try:
            cache = json.loads(prog_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    cache_key = "%s\t%s" % (text, gloss or "")
    if isinstance(cache, dict) and cache_key in cache:
        cached = cache[cache_key]
        if isinstance(cached, dict) and cached.get("label"):
            vec = cached.get("vector") or (vector_lookup or {}).get(sid)
            return {"label": cached["label"], "method": TOPIC_METHOD_TAG,
                    "vector": list(vec) if vec
                    else single_topic_vector(cached["label"])}
        return {"label": cached if isinstance(cached, str) else "Other / Abstract",
                "method": TOPIC_METHOD_TAG,
                "vector": list((vector_lookup or {}).get(sid) or [])
                or single_topic_vector(
                    cached if isinstance(cached, str) else "Other / Abstract")}
    if llm_transport is None:
        vec = (vector_lookup or {}).get(sid)
        return {"label": "Other / Abstract", "method": TOPIC_METHOD_TAG,
                "vector": list(vec) if vec
                else single_topic_vector("Other / Abstract")}
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
            vec = [{"label": e.get("topic_label"),
                    "weight": round(float(e.get("weight")), 4)}
                   for e in (normed[0].get("vector") or [])
                   if isinstance(e, dict) and e.get("topic_label")] or \
                single_topic_vector(found)
            if isinstance(cache, dict) and prog_path is not None:
                try:
                    cache[cache_key] = {"label": found, "vector": vec}
                    prog_path.write_text(json.dumps(cache, ensure_ascii=False),
                                         encoding="utf-8")
                except Exception:
                    pass
            return {"label": found, "method": TOPIC_METHOD_TAG, "vector": vec}
    vec = (vector_lookup or {}).get(sid)
    return {"label": "Other / Abstract", "method": TOPIC_METHOD_TAG,
            "vector": list(vec) if vec
            else single_topic_vector("Other / Abstract")}


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
    sense-review (R8), dataset IPA preserve with the compact "ph" key
    (R10), FROZEN dataset examples + missing-slot fill + ~15-word cap
    (R11/R13), translation-fidelity preserve line (V7), containment
    release: only containment-passing dataset examples stay FROZEN (locked
    A — failing ones are released for model replacement, need grows),
    production grammar_tip line + shared level_prompt_guidance keyed ONLY
    by the anchored pre-card pool_level (R25).
    """
    bot_level = CEFR_TO_BOT_LEVEL[item["pool_level"]]
    system = card_prompts.custom_word_system_prompt(
        "en", bot_level, compact=card_prompts.card_output_is_compact())
    user = item["text"]
    extras = [META_LEAK_BAN, FA_DOMINANT_RULE, HEADWORD_LEAK_RULE,
              GAPFILL_INSTRUCTION, EXAMPLE_LENGTH_RULE,
              FIDELITY_INSTRUCTION, GRAMMAR_TIP_FA_RULE,
              card_prompts.level_prompt_guidance(bot_level)]
    en_def = (item.get("en_def") or "").strip()
    if en_def:
        extras.append("Dictionary definition (preserve, do not contradict): "
                      + en_def)
        extras.append(EN_DEF_INSTRUCTION)
    if item.get("ipa_src") == IPA_SRC_DATASET and (item.get("ipa") or ""):
        extras.append("Dataset pronunciation IPA (preserve exactly): "
                      + item["ipa"].strip())
        extras.append(IPA_PRESERVE_INSTRUCTION)
    frozen, released = split_frozen_by_containment(item)
    if frozen:
        need = N_EXAMPLES - len(frozen)
        extras.append(
            "Dataset examples (FROZEN — do NOT rewrite, keep each exactly): "
            + " | ".join(frozen))
        if need > 0:
            extras.append(
                "Fill ONLY the %d missing example slot(s) with new "
                "sense-matching examples; still provide Persian translations "
                "for ALL examples (including the frozen ones)." % need)
        else:
            extras.append(
                "Both example slots are filled by the frozen dataset "
                "examples; provide their Persian translations, do NOT add "
                "or rewrite examples.")
    if released:
        extras.append(
            "Released examples (containment-fail — do NOT reuse verbatim, "
            "replace with sense-matching examples containing the headword): "
            + " | ".join(released))
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
                   timings=None, telemetry=None, tele_stage="card",
                   tele_batch=0, tele_key_idx=0):
    """Generate + validate one card. Failures recorded, never raised.

    Only auth failures (401/403 via AuthError) propagate to abort loudly.
    R2/R7: a validated card that leaks level wording, fails fa-dominant, or
    leaks the Latin headword into the FA fields is regenerated once (the
    next attempt); a second violation is recorded valid=False. R8: gap-fill
    completion flags + informational similarity note recorded per card (no
    similarity regen). Pilot passthroughs ("d", "literal_fa") are read from
    the raw model JSON before validation (the validator ignores them).
    R10/R11: ipa/ipa_src + dataset_examples ride from the item into the
    record; per-example examples_src (dataset vs model) is scored by exact
    match against the frozen dataset examples. R12: topic_vector rides
    along. R13: long_example (>20w) is recorded informational only —
    never a regen trigger.     R15: fa-dominant covers fa_meaning +
    fa_explanation + grammar_tip per field (V7: combined-count loophole
    closed; fa_meaning lenient to 3 Latin chars). V7: phrase/word
    example-containment + translation-fidelity join the same SINGLE
    shared regen budget (first violation of any kind regenerates once;
    any second violation is recorded valid=False). R17/R18: sense_candidates +
    also_sense ride from the item into the record (audit, no regen).
    V7 metadata merge (code-only, no prompt change): sense_id /
    topic_vector / pool_level are re-affirmed from the item AFTER
    validation as sibling keys on the RECORD — services.ai.ai.validate_card
    tolerates unknown keys but returns a fresh dict, so they can never
    ride inside the validated card.
    """
    transport = transport or call_responses
    if model_calls is None:
        model_calls = {}
    system, user, bot_level = build_prompts(item)
    # V7 containment-release (locked A): only containment-passing dataset
    # examples stay frozen; failing ones are released for model replacement
    # (the fill need in build_prompts already grows accordingly).
    frozen, released = split_frozen_by_containment(item)
    full_examples = [e for e in (item.get("dataset_examples") or [])
                     if isinstance(e, str) and e.strip()][:N_EXAMPLES]
    record = {"key": item_key(item), "kind": item["kind"], "text": item["text"],
              "pool_level": item["pool_level"], "bot_level": bot_level,
              "sense_id": item.get("sense_id", ""),
              "en_def": item.get("en_def", ""),
              "en_source": "dataset" if item.get("en_def") else "none",
              "sense_candidates": list(item.get("sense_candidates") or []),
              "also_sense": item.get("also_sense"),
              "topic": item.get("topic", ""),
              "topic_method": item.get("topic_method", ""),
              "topic_vector": list(item.get("topic_vector") or []),
              "ipa": item.get("ipa", ""),
              "ipa_src": item.get("ipa_src", IPA_SRC_MODEL),
              "dataset_examples": list(full_examples),
              "examples_src": [],
              "long_example": [],
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
                attempt_start = time.perf_counter()
                res = transport(api_key, model, system, prompt)
                latency = time.perf_counter() - attempt_start
                if isinstance(res, tuple) and len(res) == 2:
                    raw, usage = res
                else:
                    raw, usage = res, None
                if telemetry is not None:
                    prompt_tokens, completion_tokens = (
                        tele_extract_usage(usage)
                        if isinstance(usage, dict) else (None, None))
                    tele_record_call(
                        telemetry, stage=tele_stage, batch_id=tele_batch,
                        key_idx=tele_key_idx, model=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        latency_s=latency, outcome="ok")
                obj = extract_json(raw)
            except AuthError:
                if telemetry is not None:
                    tele_record_call(
                        telemetry, stage=tele_stage, batch_id=tele_batch,
                        key_idx=tele_key_idx, model=model,
                        latency_s=0.0, outcome="auth", http_status=401)
                raise
            except urllib.error.HTTPError as exc:
                if telemetry is not None:
                    tele_record_call(
                        telemetry, stage=tele_stage, batch_id=tele_batch,
                        key_idx=tele_key_idx, model=model,
                        latency_s=0.0,
                        outcome="auth" if exc.code in (401, 403)
                        else "error", http_status=exc.code)
                if exc.code in (401, 403):
                    raise_for_auth(exc)  # maps to AuthError, aborts loud
                last_error = "HTTPError %s: %s" % (exc.code, str(exc)[:200])
                continue
            except Exception as exc:
                if telemetry is not None:
                    tele_record_call(
                        telemetry, stage=tele_stage, batch_id=tele_batch,
                        key_idx=tele_key_idx, model=model,
                        latency_s=0.0, outcome="error")
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
                                        card.get("fa_explanation", ""),
                                        card.get("grammar_tip", ""))
                hw_leaks = headword_leak_scan(item["text"], item["kind"],
                                              card)
                flags = build_completion_flags(card, released)
                sim = similarity_note(item.get("en_def", ""),
                                      model_d if isinstance(model_d, str)
                                      else "")
                frozen_set = {e.strip() for e in frozen}
                src = [IPA_SRC_DATASET
                       if isinstance(e, str) and e.strip() in frozen_set
                       else IPA_SRC_MODEL
                       for e in (card.get("examples") or [])]
                longs = long_example_flags(card)
                violation = ""
                if leaks:
                    violation = "meta-leak: %s" % (
                        ", ".join(sorted(set(leaks)))[:200])
                elif not fa_ok:
                    violation = "fa-dominant"
                elif hw_leaks:
                    violation = "headword-leak: %s" % (
                        ", ".join(hw_leaks)[:200])
                elif not example_containment_ok(item["text"], item["kind"],
                                                card):
                    violation = "example-containment"
                elif not translation_fidelity_ok(card):
                    violation = "translation-fidelity"
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
                    record["examples_src"] = src
                    record["long_example"] = longs
                    return record
                record.update(model_used=model, card=card, valid=True,
                              model_d=model_d if isinstance(model_d, str)
                              else "",
                              literal_fa=literal_fa
                              if isinstance(literal_fa, str) else "",
                              completion_flags=flags, similarity_note=sim,
                              fa_dominant=True, headword_leaks=[],
                              examples_src=src, long_example=longs)
                # V7 metadata merge (code-only, no prompt change):
                # re-affirm sense_id / topic_vector / pool_level from the
                # item AFTER validation as sibling keys on the RECORD.
                # services.ai.ai.validate_card tolerates unknown keys but
                # returns a fresh dict (extras stripped), so metadata can
                # never ride inside the validated card itself.
                record.update(
                    sense_id=item.get("sense_id", ""),
                    topic_vector=list(item.get("topic_vector") or []),
                    pool_level=item.get("pool_level", ""))
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


# V7 — compact progress logging (factory-only, shared by card_pilot and
# precard_pipeline via import). Every batch prints ONE stdout line
# "S<stage> batch i/N ok=X fail=Y model=calls" (tqdm stays where it
# already is — sibling scripts — this line log is in addition, never a
# replacement). Each run also writes a compact run.log in its out dir
# (stage start/end with counts + timings). ok/fail semantics are counted
# per stage and stated at the call site (kept vs dropped / model vs
# fail-closed fallback / valid vs invalid).


def batch_log_line(stage, batch_no, n_batches, ok, fail, calls):
    """V7 one-line batch progress: "S<stage> batch i/N ok=X fail=Y model=C".

    calls is a {model: count} mapping (summed) or a plain int.
    """
    if isinstance(calls, dict):
        total = sum((calls or {}).values())
    else:
        total = int(calls or 0)
    return ("S%s batch %d/%d ok=%d fail=%d model=%d"
            % (stage, batch_no, n_batches, ok, fail, total))


class RunLogger:
    """V7 compact run.log writer (stage start/end + counts + timings)."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "w", encoding="utf-8")
        self._starts = {}

    def log(self, line):
        if self._handle.closed:
            # Reopen in append mode: close() may already have run in a
            # finally block while the caller still has summary lines.
            self._handle = open(self.path, "a", encoding="utf-8")
        self._handle.write(line + "\n")
        self._handle.flush()

    def stage_start(self, stage):
        self._starts[stage] = time.perf_counter()
        self.log("stage %s start" % stage)

    def stage_end(self, stage, ok=0, fail=0):
        start = self._starts.get(stage, time.perf_counter())
        secs = time.perf_counter() - start
        self.log("stage %s end ok=%d fail=%d secs=%.2f"
                 % (stage, ok, fail, secs))

    def close(self):
        try:
            self._handle.close()
        except Exception:
            pass


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
        rows.append("<tr><td class=\"en\">%s</td><td class=\"nums\">%.2f</td>"
                    "<td class=\"nums\">%.3f</td>"
                    "<td class=\"nums\">%.1f</td></tr>" % (esc(stage), secs, avg, extra))
    return (
        "<h2>زمان‌بندی مراحل (ثانیه)</h2>\n"
        "<div class=\"tbl-scroll\">\n"
        "<table border=\"1\" cellpadding=\"4\">\n"
        "<tr><th>مرحله</th><th>ثانیه</th><th>میانگین هر مورد</th>"
        "<th>برون‌یابی خطی ۳۰۰۰ واژه + ۵۰۰ عبارت</th></tr>\n"
        + "\n".join(rows) + "\n</table>\n</div>")


def render_only(out_dir, report_path):
    """Regenerate the gallery HTML from persisted pilot files only.

    Loads ``cards.jsonl`` + ``timings.json`` (+ ``progress.json`` model
    calls when present) from *out_dir* and writes the gallery to
    *report_path*. No network, no env, never touches sample/cards.
    Returns the number of cards rendered.
    """
    out = pathlib.Path(out_dir)
    cards = load_cards_jsonl(str(out / "cards.jsonl"))
    timings_path = out / "timings.json"
    timings = (json.loads(timings_path.read_text(encoding="utf-8"))
               if timings_path.exists() else None)
    tele_path = out / "telemetry_summary.json"
    telemetry_summary = None
    if tele_path.exists():
        try:
            telemetry_summary = json.loads(
                tele_path.read_text(encoding="utf-8"))
        except Exception:
            telemetry_summary = None
    model_calls = {}
    prog_path = out / "progress.json"
    if prog_path.exists():
        try:
            model_calls = json.loads(
                prog_path.read_text(encoding="utf-8")).get("model_calls",
                                                           {}) or {}
        except Exception:
            model_calls = {}
    if not model_calls:
        for rec in cards:
            model = rec.get("model_used") or ""
            if model:
                model_calls[model] = model_calls.get(model, 0) + 1
    meta = {"date_tehran": tehran_now_str(), "commit": git_commit(),
            "model_calls": model_calls, "timings": timings,
            "telemetry": telemetry_summary}
    # Opportunistic phrase-type display (missing log = unjudged, no fail).
    phrase_types = load_phrase_types(DEFAULT_PHRASE_TYPE_LOG)
    gallery_html = render_gallery(cards, meta, phrase_types=phrase_types)
    report = pathlib.Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(gallery_html, encoding="utf-8")
    print("render-only: %d cards -> %s" % (len(cards), report))
    return len(cards)


def _badge_html(rec):
    """Validation badge for one record (audit strip + card header).

    R14 bidi: the Persian word and the Latin detail live in separate
    spans — no mixed text node.
    """
    if rec.get("valid"):
        return '<span class="badge ok">تأیید شد</span>'
    if rec.get("card") is not None:
        return ('<span class="badge bad"><span>نامعتبر</span> '
                '<span class="en">%s</span></span>'
                % esc(rec.get("reason")))
    return ('<span class="badge bad"><span>خطا</span> '
            '<span class="en">%s</span></span>'
            % esc(rec.get("error") or rec.get("reason")))


def _check_chip(label, passed, detail=""):
    """Pass/fail chip for one pipeline control (R14 bidi-safe spans)."""
    cls = "pass" if passed else "open"
    word = "گذشت" if passed else "نیفتاد"
    extra = (' <span class="en">%s</span>' % esc(detail)) if detail else ""
    return ('<span class="chip %s"><span class="en">%s</span> '
            '<span>%s</span>%s</span>'
            % (cls, esc(label), word, extra))


def _blk_fa(text):
    """R14: one Persian value block (own line run, dir=rtl)."""
    return '<div class="blk" dir="rtl" lang="fa">%s</div>' % esc(text)


def _blk_en(text, nums=False):
    """R14: one English value block (own line run, dir=ltr)."""
    cls = "blk en nums" if nums else "blk en"
    return '<div class="%s" dir="ltr" lang="en">%s</div>' % (cls, esc(text))


def _strip_row(label, blocks):
    """R14: one stage-strip row — fa label line, then value blocks."""
    return ('<div class="srow"><div class="slabel" dir="rtl" lang="fa">%s</div>'
            '<div class="sblocks">%s</div></div>'
            % (esc(label), "".join(blocks)))


def render_stage_strip(rec):
    """STAGE STRIP: audit rows, pipeline order, R14 bidi-safe blocks.

    Six rows, newest-last: (1) استخر (2) لنگر حس (3) موضوع
    (4) پیش‌کارت (5) تکمیل مدل (6) کنترل‌ها. Presentation only —
    every value is read from the record, nothing recomputed. Persian
    labels and English values never share a line run: each value sits
    in its own dir=rtl / dir=ltr block.
    """
    kind_fa = "واژه" if rec.get("kind") == "word" else "عبارت"

    # (1) استخر: lemma + kind + pool CEFR.
    row_pool = _strip_row("استخر", [
        _blk_fa(kind_fa),
        _blk_en(rec.get("text") or "—"),
        _blk_fa("سطح استخر"),
        _blk_en(rec.get("pool_level") or "—"),
    ])

    # (2) لنگر حس: sense_id + en gloss (dataset tag).
    sense_id = (rec.get("sense_id") or "").strip()
    en_def = (rec.get("en_def") or "").strip()
    en_source = (rec.get("en_source") or "").strip()
    sense_blocks = [_blk_en(sense_id if sense_id else "—"),
                    _blk_en(en_def if en_def else "—")]
    if en_source:
        sense_blocks.append(_blk_en("[%s]" % en_source))
    row_sense = _strip_row("لنگر حس", sense_blocks)

    # (3) موضوع: label chip + full vector chips + method tag.
    row_topic = _strip_row("موضوع", [_topic_chips_html(rec),
                                    _blk_en("(%s)" % (
                                        (rec.get("topic_method")
                                         or TOPIC_METHOD_TAG).strip()))])

    # (4) پیش‌کارت: en_def given to the model + fields EMPTY before
    # completion (= COMPLETION_FIELDS minus final fields_filled).
    flags = rec.get("completion_flags") or {}
    filled = list(flags.get("fields_filled", []) or [])
    empty_before = [k for k in COMPLETION_FIELDS if k not in filled]
    pre_blocks = [_blk_fa("تعریف دیتاستی"),
                  _blk_en(en_def if en_def else "—"),
                  _blk_fa("خالی پیش از تکمیل")]
    if flags.get("nothing_to_complete"):
        pre_blocks.append(_blk_fa("— (بدون‌کار)"))
    elif empty_before:
        pre_blocks.append(_blk_en(", ".join(empty_before)))
    else:
        pre_blocks.append(_blk_fa("—"))
    literal_fa = (rec.get("literal_fa") or "").strip()
    if rec.get("kind") == "phrase" and literal_fa:
        pre_blocks.append(_blk_fa("معنی تحت‌اللفظی"))
        pre_blocks.append(_blk_fa(literal_fa))
    if rec.get("kind") == "phrase" and rec.get("proper_noun") is None:
        pre_blocks.append(_blk_fa(
            "نام خاص: قضاوت نشده ـ سؤال باز برای داوری مجدد"))
        pre_blocks.append(_blk_en("F4"))
    if rec.get("regen"):
        pre_blocks.append(_blk_fa("بازتولید کنترلی: یک بار"))
    row_pre = _strip_row("پیش‌کارت", pre_blocks)

    # (5) تکمیل مدل: model name, fields_filled, sense_review,
    # nothing_to_complete, similarity note.
    model_used = (rec.get("model_used") or "").strip() or "—"
    sim = rec.get("similarity_note")
    fill_blocks = [_blk_fa("مدل"), _blk_en(model_used),
                   _blk_fa("تکمیل شکاف + بازبینی معنایی"),
                   _blk_en("fields_filled"),
                   _blk_en(", ".join(filled) if filled else "—"),
                   _blk_fa("بازبینی"),
                   _blk_en(str(flags.get("sense_review"))),
                   _blk_fa("بدون‌کار"),
                   _blk_en(str(flags.get("nothing_to_complete"))),
                   _blk_fa("شباهت تعریف"),
                   _blk_en(("%.3f" % sim) if isinstance(sim, float)
                           else "—", nums=True)]
    model_d = (rec.get("model_d") or "").strip()
    if model_d:
        fill_blocks.append(_blk_fa("تکمیل مدل"))
        fill_blocks.append(_blk_en("model-completed"))
        fill_blocks.append(_blk_en(model_d))
    row_fill = _strip_row("تکمیل مدل", fill_blocks)

    # (6) کنترل‌ها: validation badge + meta-leak/fa-dominant/headword chips
    # + R13 informational long-example flag (never a regen).
    leaks = rec.get("leaks") or []
    fa_ok = rec.get("fa_dominant")
    hw_leaks = rec.get("headword_leaks") or []
    longs = rec.get("long_example") or []
    checks = [_badge_html(rec),
              _check_chip("meta-leak", not leaks,
                          ", ".join(sorted(set(leaks)))[:200]
                          if leaks else "")]
    if fa_ok is not None:
        checks.append(_check_chip("fa-dominant", bool(fa_ok)))
    else:
        checks.append('<span class="chip"><span class="en">fa-dominant</span> '
                      '<span>—</span></span>')
    checks.append(_check_chip("headword", not hw_leaks,
                              ", ".join(hw_leaks)[:200] if hw_leaks else ""))
    if longs:
        checks.append(
            '<span class="chip open"><span>مثال طولانی</span> '
            '<span class="en nums">%d</span></span>' % len(longs))
    row_checks = _strip_row(
        "کنترل‌ها",
        ['<div class="blk chips" dir="rtl" lang="fa">%s</div>'
         % " ".join(checks)])
    return ('<div class="strip">\n%s\n%s\n%s\n%s\n%s\n%s\n</div>'
            % (row_pool, row_sense, row_topic, row_pre, row_fill,
               row_checks))


def _card_ipa(card):
    """Final IPA string from a validated card (dict or plain phonetic)."""
    phon = (card or {}).get("phonetic", {})
    if isinstance(phon, dict):
        return str(phon.get("ipa", "") or "")
    return str(phon or "")


def _topic_vector_entries(rec):
    """R12: [{label, weight}] — record vector, else single-label fallback."""
    vec = [e for e in (rec.get("topic_vector") or [])
           if isinstance(e, dict) and e.get("label")]
    if vec:
        return [{"label": str(e["label"]),
                 "weight": float(e.get("weight", 1.0) or 1.0)}
                for e in vec[:3]]
    topic = (rec.get("topic") or "").strip()
    if topic:
        return single_topic_vector(topic)
    return []


def richness_counters(cards):
    """R17: {ipa_dataset_pct, examples_dataset_pct, topics_non_other_pct}.

    ipa: % records with ipa_src == dataset. examples: % example slots
    with src == dataset (over records carrying examples_src). topics: %
    records with a non-empty, non-Other label. Empty input -> 0.0s.
    """
    cards = list(cards or [])
    n = len(cards)
    if not n:
        return {"ipa_dataset_pct": 0.0, "examples_dataset_pct": 0.0,
                "topics_non_other_pct": 0.0}
    ipa_hits = sum(1 for rec in cards
                   if rec.get("ipa_src") == IPA_SRC_DATASET)
    slots = sum(len(rec.get("examples_src") or []) for rec in cards)
    slot_hits = sum(1 for rec in cards
                    for src in (rec.get("examples_src") or [])
                    if src == IPA_SRC_DATASET)
    topic_hits = sum(1 for rec in cards
                     if (rec.get("topic") or "").strip()
                     and (rec.get("topic") or "").strip()
                     != "Other / Abstract")
    return {"ipa_dataset_pct": round(100.0 * ipa_hits / n, 1),
            "examples_dataset_pct": round(
                100.0 * slot_hits / slots, 1) if slots else 0.0,
            "topics_non_other_pct": round(100.0 * topic_hits / n, 1)}


# Pilot phrase display: opportunistic read of the type-pass audit log.
# Missing/unreadable file -> {} -> every phrase shows "نوع: قضاوت‌نشده",
# never a failure (the pilot must render without the re-judge).
DEFAULT_PHRASE_TYPE_LOG = ("W:/hamzaban_data_factory/fixtures/"
                           "phrase_type_log.jsonl")


def load_phrase_types(path):
    """phrase -> {phrase_type, applied_keep}; any error -> {} (never fail)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle) if str(path).endswith(".json") \
                else [json.loads(line) for line in handle if line.strip()]
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict):
        data = data.get("phrases", [])
    out = {}
    try:
        for row in data or []:
            if not isinstance(row, dict):
                continue
            phrase = (row.get("phrase") or "").strip()
            phrase_type = (row.get("phrase_type") or "").strip()
            if phrase and phrase_type:
                out[phrase] = {"phrase_type": phrase_type,
                               "applied_keep": bool(
                                   row.get("applied_keep"))}
    except Exception:
        return {}
    return out


def _topic_chips_html(rec):
    """R12: primary chip + secondary chips with weights (tabular-nums)."""
    vec = _topic_vector_entries(rec)
    if not vec:
        return _blk_fa("—")
    chips = ['<span class="tchip primary">%s</span>' % esc(vec[0]["label"])]
    for entry in vec[1:]:
        chips.append(
            '<span class="tchip">%s <span class="nums">%.2f</span></span>'
            % (esc(entry["label"]), entry["weight"]))
    return ('<div class="blk" dir="rtl" lang="fa">%s</div>'
            % " ".join(chips))


# R14 — diff operation labels (gallery-only presentation).
OP_KEEP = "نگه‌داشت dataset"
OP_MODEL = "پرشده model"
OP_REVIEW = "بازبینی‌شده"
OP_NONE = "بدون‌کار"
# V7 containment-release op label (locked A): dataset examples failing
# containment are released for model replacement (need grows).
OP_RELEASED = "آزادشده (containment)"
DIFF_TRUNCATE_AT = 140


def _op_chip(pre, final, match=False):
    """R14: three-state operation chip (bidi-safe: Latin part isolated)."""
    if pre and final:
        op, cls = (OP_KEEP, "keep") if match else (OP_REVIEW, "review")
    elif final:
        op, cls = OP_MODEL, "model"
    elif pre:
        op, cls = OP_REVIEW, "review"
    else:
        op, cls = OP_NONE, "none"
    if " " in op:
        fa, en = op.split(" ", 1)
        inner = '%s <span class="en">%s</span>' % (esc(fa), esc(en))
    else:
        inner = esc(op)
    return '<span class="op %s">%s</span>' % (cls, inner)


def _op_chip_released():
    """V7 containment-release op chip (bidi-safe: Latin part isolated).

    The full "آزادشده (containment)" string rides in the title attribute
    so gallery scans find it verbatim; the visible label keeps the
    R14 split-run convention.
    """
    return ('<span class="op review" title="%s">%s '
            '<span class="en">%s</span></span>'
            % (esc(OP_RELEASED), esc("آزادشده"), esc("(containment)")))


def _diff_val(text, direction):
    """R14: diff value cell — long values truncated + <details> expander."""
    text = "" if text is None else str(text)
    if not text.strip():
        return ('<div class="blk empty" dir="rtl" lang="fa">خالی</div>')
    lang = "fa" if direction == "rtl" else "en"
    if len(text) > DIFF_TRUNCATE_AT:
        short = text[:DIFF_TRUNCATE_AT] + "…"
        return (
            '<div class="blk" dir="%s" lang="%s">%s'
            "<details><summary>نمایش کامل</summary>"
            '<div dir="%s" lang="%s">%s</div></details></div>'
            % (direction, lang, esc(short),
               direction, lang, esc(text)))
    return ('<div class="blk" dir="%s" lang="%s">%s</div>'
            % (direction, lang, esc(text)))


def _src_tag(source):
    """R10/R11: per-value origin tag (dataset/model)."""
    if not source:
        return ""
    return ('<div class="srctag"><span class="en">[%s]</span></div>'
            % esc(source))


def _diff_row(label, pre_text, pre_dir, final_text, final_dir,
              match=False, pre_src="", final_src="", op_html=None):
    """R14: one field row — label line, pre-card, operation, final.

    ``op_html`` overrides the computed chip (V7 containment-release rows
    pass the آزادشده chip for released pre-card examples).
    """
    op = op_html if op_html is not None else _op_chip(
        (pre_text or "").strip(), (final_text or "").strip(), match)
    return (
        '<div class="diff-row">'
        '<div class="diff-label" dir="rtl" lang="fa">%s</div>'
        '<div class="diff-pre">%s%s</div>'
        '<div class="diff-op">%s</div>'
        '<div class="diff-fin">%s%s</div>'
        "</div>"
        % (esc(label), _diff_val(pre_text, pre_dir), _src_tag(pre_src),
           op, _diff_val(final_text, final_dir), _src_tag(final_src)))


def render_diff_table(rec, card):
    """R14: per-field diff (pre-card | operation | final) for 9 fields."""
    card = card or {}
    frozen = [(e.strip() if isinstance(e, str) else "")
              for e in (rec.get("dataset_examples") or [])]
    # V7 containment-release: released pre-card examples render the
    # آزادشده (containment) op chip instead of the keep/review chip.
    released_set = {
        (e.strip() if isinstance(e, str) else "")
        for e in ((rec.get("completion_flags") or {})
                  .get("released_containment") or [])}
    src = list(rec.get("examples_src") or [])
    examples = list(card.get("examples") or [])
    trans = list(card.get("example_translations") or [])
    ipa_src = rec.get("ipa_src", "") or ""
    rec_ipa = (rec.get("ipa") or "").strip()
    pre_ipa = rec_ipa if ipa_src == IPA_SRC_DATASET else ""
    fin_ipa = _card_ipa(card).strip()
    en_def = (rec.get("en_def") or "").strip()
    model_d = (rec.get("model_d") or "").strip()
    fin_en = model_d or (en_def
                         if rec.get("en_source") == "dataset" else "")
    rows = [
        _diff_row("معنی فارسی", "", "rtl",
                  card.get("fa_meaning") or "", "rtl"),
        _diff_row("توضیح فارسی", "", "rtl",
                  card.get("fa_explanation") or "", "rtl"),
        _diff_row("تعریف انگلیسی", en_def, "ltr", fin_en, "ltr",
                  match=bool(en_def) and fin_en.strip() == en_def,
                  pre_src=rec.get("en_source") or "",
                  final_src="model" if model_d else (
                      rec.get("en_source") or "")),
        _diff_row("تلفظ", pre_ipa, "ltr", fin_ipa, "ltr",
                  match=bool(pre_ipa) and fin_ipa == pre_ipa,
                  pre_src=ipa_src if pre_ipa else "",
                  final_src=(ipa_src
                             if fin_ipa and fin_ipa == pre_ipa else "model")
                  if fin_ipa else ""),
    ]
    for pos in range(N_EXAMPLES):
        pre = frozen[pos] if pos < len(frozen) else ""
        fin = examples[pos] if pos < len(examples) else ""
        fin_src = ""
        if fin:
            fin_src = (src[pos] if pos < len(src)
                       else (IPA_SRC_DATASET
                             if pre and fin.strip() == pre else IPA_SRC_MODEL))
        match = (fin_src == IPA_SRC_DATASET)
        translation = trans[pos] if pos < len(trans) else ""
        fin_cell = fin
        released_chip = (_op_chip_released()
                         if pre.strip() and pre.strip() in released_set
                         else None)
        rows.append(_diff_row("مثال %d" % (pos + 1), pre, "ltr",
                              fin_cell, "ltr", match=match,
                              pre_src=IPA_SRC_DATASET if pre else "",
                              final_src=fin_src, op_html=released_chip))
        if fin and translation:
            rows.append(_diff_row("ترجمه مثال %d" % (pos + 1), "", "rtl",
                                  translation, "rtl"))
    rows.append(_diff_row("مترادف‌ها", "", "ltr",
                          ", ".join(card.get("synonyms") or []), "ltr"))
    rows.append(_diff_row("متضادها", "", "ltr",
                          ", ".join(card.get("antonyms") or []), "ltr"))
    rows.append(_diff_row("نکته گرامری", "", "rtl",
                          card.get("grammar_tip") or "", "rtl"))
    return (
        '<div class="diff">'
        '<div class="diff-row diff-head">'
        '<div class="diff-label" dir="rtl" lang="fa">میدان</div>'
        '<div class="diff-pre" dir="rtl" lang="fa">پیش‌کارت</div>'
        '<div class="diff-op" dir="rtl" lang="fa">عملیات</div>'
        '<div class="diff-fin" dir="rtl" lang="fa">نهایی</div>'
        "</div>\n%s\n</div>" % "\n".join(rows))


def render_diff_header(rec, phrase_types=None):
    """R14: stage-strip essentials folded into the diff header.

    Sense anchor + topic vector + model + checks chips stay visible at
    the top of each card; every mixed line is split into dir-safe blocks.
    R17: top-3 sense candidates shown ranked + compact. R18: second sense
    shown as a small "نیز:" line under the anchor (absent when
    single-sense). Phrase kinds show the opportunistic phrase_type chip +
    applied_keep flag (missing log -> "نوع: قضاوت‌نشده", never fails).
    """
    sense_id = (rec.get("sense_id") or "").strip()
    en_def = (rec.get("en_def") or "").strip()
    en_source = (rec.get("en_source") or "").strip()
    model_used = (rec.get("model_used") or "").strip() or "—"
    leaks = rec.get("leaks") or []
    fa_ok = rec.get("fa_dominant")
    hw_leaks = rec.get("headword_leaks") or []
    longs = rec.get("long_example") or []
    checks = [_badge_html(rec),
              _check_chip("meta-leak", not leaks,
                          ", ".join(sorted(set(leaks)))[:200]
                          if leaks else "")]
    if fa_ok is not None:
        checks.append(_check_chip("fa-dominant", bool(fa_ok)))
    checks.append(_check_chip("headword", not hw_leaks,
                              ", ".join(hw_leaks)[:200] if hw_leaks else ""))
    if longs:
        checks.append(
            '<span class="chip open"><span>مثال طولانی</span> '
            '<span class="en nums">%d</span></span>' % len(longs))
    # R17: ranked compact candidate list (one dir-safe block each).
    cand_row = ""
    candidates = [c for c in (rec.get("sense_candidates") or [])
                  if isinstance(c, dict) and c.get("sense_id")]
    if candidates:
        cand_blocks = []
        for rank, cand in enumerate(candidates[:3], start=1):
            try:
                score = float(cand.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            cand_blocks.append(_blk_en("%d. %s — %s (%.3f)"
                                      % (rank, cand.get("sense_id", ""),
                                         (cand.get("gloss") or "").strip(),
                                         score)))
        cand_row = ('<div class="dh-row"><div class="dh-label" dir="rtl" '
                    'lang="fa">نامزدها</div>%s</div>' % "".join(cand_blocks))
    # R18: small "نیز:" line under the anchor (single-sense -> absent).
    also_row = ""
    also = rec.get("also_sense") or {}
    if isinstance(also, dict) and (also.get("sense_id") or "").strip():
        also_blocks = [_blk_fa("نیز:"),
                       _blk_en((also.get("sense_id") or "").strip()),
                       _blk_en((also.get("gloss") or "").strip() or "—")]
        if (also.get("topic") or "").strip():
            also_blocks.append(_blk_en((also.get("topic") or "").strip()))
        else:
            also_blocks.append(_blk_en("(%s)" % (
                (also.get("topic_method")
                 or ALSO_TOPIC_UNASSIGNED).strip())))
        also_row = ('<div class="dh-row also"><div class="dh-label" '
                    'dir="rtl" lang="fa">حس دوم</div>%s</div>'
                    % "".join(also_blocks))
    # Pilot phrase display: opportunistic type chip + applied_keep flag.
    type_row = ""
    if (rec.get("kind") or "word") == "phrase":
        known = (phrase_types or {}).get(rec.get("text") or "")
        if isinstance(known, dict) and known.get("phrase_type"):
            flag = ('<span class="chip pass"><span class="en">applied_keep'
                    '</span> <span class="en">%s</span></span>'
                    % ("true" if known.get("applied_keep") else "false"))
            type_row = ('<div class="dh-row"><div class="dh-label" '
                        'dir="rtl" lang="fa">نوع عبارت</div>'
                        '<div class="blk" dir="ltr" lang="en">'
                        '<span class="tchip">%s</span></div>%s</div>'
                        % (esc(known["phrase_type"]), flag))
        else:
            type_row = ('<div class="dh-row"><div class="dh-label" '
                        'dir="rtl" lang="fa">نوع عبارت</div>%s</div>'
                        % _blk_fa("نوع: قضاوت‌نشده"))
    return (
        '<div class="dhead">'
        '<div class="dh-row"><div class="dh-label" dir="rtl" lang="fa">'
        "لنگر حس</div>"
        "%s%s%s</div>"
        "%s%s"
        '<div class="dh-row"><div class="dh-label" dir="rtl" lang="fa">'
        "موضوع</div>%s</div>"
        "%s"
        '<div class="dh-row"><div class="dh-label" dir="rtl" lang="fa">'
        "مدل</div>%s</div>"
        '<div class="dh-row chips-row">%s</div>'
        "</div>"
        % (_blk_en(sense_id if sense_id else "—"),
           _blk_en(en_def if en_def else "—"),
           _blk_en("[%s]" % en_source) if en_source else "",
           cand_row, also_row,
           _topic_chips_html(rec),
           type_row,
           _blk_en(model_used),
           " ".join(checks)))


# V7 — level-conditioned study guidance, keyed ONLY by the anchored
# pool_level carried on the record. Unknown/empty pool levels show NO
# line (never a generic user-level fallback; bot_level is never shown
# in the learner block).
LEVEL_GUIDANCE = {
    "A1": "راهنما: هر مثال را بلند بخوان و معنی فارسی را حدس بزن.",
    "A2": "راهنما: مثال‌ها را با صدای بلند تکرار کن و مترادف‌ها را به خاطر بسپار.",
    "B1": "راهنما: نکته گرامری را در مثال‌ها پیدا کن و یک جمله تازه بساز.",
    "B2": "راهنما: با مترادف‌ها و متضادها جمله‌های خودت را بساز.",
    "C1": "راهنما: تفاوت‌های ظریف معنایی مترادف‌ها را با هم مقایسه کن.",
    "C2": "راهنما: کاربرد رسمی و غیررسمی این واژه را در مثال‌ها بررسی کن.",
}


def render_final_card(rec, card):
    """FINAL CARD: learner view, card-styled box, separated from audit.

    V7 header: the block STARTS with headword + IPA together (bot-style
    header), then a study-guidance line conditioned ONLY on the anchored
    pool_level (absent when the pool level is unknown — no generic
    user-level text), then a small metadata line (sense_id / pool_level
    / topic, V7 record siblings). R14 bidi: Persian labels sit on their
    own line; every value has its own dir=rtl / dir=ltr block.
    """
    items = []
    for pos, (e, t) in enumerate(zip(card.get("examples", []),
                                     card.get("example_translations", []))):
        items.append(
            '<li><div class="blk en" dir="ltr" lang="en">%s</div>'
            '<div class="blk" dir="rtl" lang="fa">%s</div></li>'
            % (esc(e), esc(t)))
    syns = card.get("synonyms") or []
    ants = card.get("antonyms") or []
    ipa = _card_ipa(card)
    raw_json = esc(json.dumps(card, ensure_ascii=False) if card else "")
    en_def = (rec.get("en_def") or "").strip()
    en_detail = ("<details><summary>تعریف انگلیسی (English definition)"
                 "</summary>"
                 '<div class="blk en" dir="ltr" lang="en">%s</div></details>'
                 % (esc(en_def) if en_def else "—"))
    # V7 header: headword + IPA together first (bot-style header).
    headword = ((rec.get("text") or card.get("word") or "").strip()
                or "—")
    ipa_disp = ipa.strip() or "—"
    if ipa_disp != "—" and "/" not in ipa_disp:
        ipa_disp = "/%s/" % ipa_disp
    head_html = (
        '<div class="final-head" dir="ltr" lang="en">'
        '<span class="en">%s</span> '
        '<span class="en">%s</span></div>'
        % (esc(headword), esc(ipa_disp)))
    # V7 guidance: ONLY from the anchored pool_level; unknown -> no line.
    guidance = LEVEL_GUIDANCE.get((rec.get("pool_level") or "").strip())
    guidance_html = (_blk_fa(guidance) if guidance else "")
    # V7 metadata line: record siblings sense_id / pool_level / topic.
    sense_id = (rec.get("sense_id") or "").strip() or "—"
    pool_level = (rec.get("pool_level") or "").strip() or "—"
    topic = (rec.get("topic") or "").strip() or "—"
    meta_html = (
        '<div class="final-meta" dir="ltr" lang="en">'
        '<span class="en">%s</span> '
        '<span class="en">%s</span> '
        '<span class="en">%s</span></div>'
        % (esc(sense_id), esc(pool_level), esc(topic)))
    return (
        "<div class=\"final\">\n"
        "%s\n"
        "%s\n"
        "%s\n"
        '<div class="fld-label" dir="rtl" lang="fa">معنی</div>\n'
        '<div class="blk lead" dir="rtl" lang="fa">%s</div>\n'
        '<div class="fld-label" dir="rtl" lang="fa">توضیح</div>\n'
        '<div class="blk" dir="rtl" lang="fa">%s</div>\n'
        "%s\n"
        '<div class="fld-label" dir="rtl" lang="fa">تلفظ</div>\n'
        '<div class="blk en" dir="ltr" lang="en">%s</div>\n'
        '<div class="fld-label" dir="rtl" lang="fa">مثال‌ها</div>\n'
        "<ol>%s</ol>\n"
        '<div class="fld-label" dir="rtl" lang="fa">مترادف</div>\n'
        '<div class="blk en" dir="ltr" lang="en">%s</div>\n'
        '<div class="fld-label" dir="rtl" lang="fa">متضاد</div>\n'
        '<div class="blk en" dir="ltr" lang="en">%s</div>\n'
        '<div class="fld-label" dir="rtl" lang="fa">نکته گرامری</div>\n'
        '<div class="blk" dir="rtl" lang="fa">%s</div>\n'
        "<details><summary>JSON خام</summary>"
        "<pre class=\"en\">%s</pre></details>\n"
        "</div>"
            % (head_html, guidance_html, meta_html,
               esc(card.get("fa_meaning", "—") or "—"),
               esc(card.get("fa_explanation", "—") or "—"),
               en_detail, esc(ipa) if ipa else "—",
               "".join(items) or "<li>—</li>",
               esc(", ".join(syns)) if syns else "—",
               esc(", ".join(ants)) if ants else "—",
               esc(card.get("grammar_tip", "—") or "—"), raw_json))


def render_nav(cards):
    """Sticky mini-nav: one anchor per card (#card-0..N)."""
    links = []
    for idx, rec in enumerate(cards):
        chip = ("<span class=\"chip done\">تأیید شد</span>"
                if rec.get("valid") else
                "<span class=\"chip open\">نامعتبر</span>")
        links.append(
            "<a href=\"#card-%d\"><span class=\"en\">%s</span> "
            "<span class=\"nums\">%s</span> %s</a>"
            % (idx, esc(rec.get("text")), esc(rec.get("pool_level")),
               chip))
    return ("<nav class=\"top\" aria-label=\"فهرست کارت‌ها\">\n%s\n</nav>"
            % "\n".join(links))


def render_gallery(cards, meta, phrase_types=None):
    """Render the Persian RTL gallery HTML for card records."""
    total = len(cards)
    passed = sum(1 for c in cards if c.get("valid"))
    rate = (100.0 * passed / total) if total else 0.0
    calls = meta.get("model_calls", {})
    timings_table = render_timings_table(meta.get("timings"))
    try:
        tele_table = tele_table(meta.get("telemetry"))
    except Exception:
        tele_table = ""
    rich = ((meta.get("timings") or {}).get("richness")
            or meta.get("richness"))
    nav = render_nav(cards)
    sections = []
    for idx, rec in enumerate(cards):
        card = rec.get("card") or {}
        kind_fa = "واژه" if rec.get("kind") == "word" else "عبارت"
        if card:
            diff_html = render_diff_table(rec, card)
            final_html = render_final_card(rec, card)
        else:
            diff_html = render_diff_table(rec, {})
            final_html = ("<div class=\"final final-empty\">"
                          '<div class="blk" dir="rtl" lang="fa">'
                          "کارتی برای نمایش نیست</div>"
                          '<div class="blk en" dir="ltr" lang="en">%s</div>'
                          "</div>"
                          % esc(rec.get("error") or rec.get("reason")
                                or "—"))
        sections.append(
            "<section class=\"card\" id=\"card-%d\">\n"
            "<h2><span class=\"en\">%s</span> "
            "<span class=\"kind\">(%s)</span> %s</h2>\n"
            '<div class="blk" dir="rtl" lang="fa">سطح برچسب</div>\n'
            '<div class="blk en" dir="ltr" lang="en">%s</div>\n'
            '<div class="blk" dir="rtl" lang="fa">سطح کارت</div>\n'
            '<div class="blk en" dir="ltr" lang="en">%s</div>\n'
            "<h3>سربرگ + مقایسه پیش‌کارت و نهایی (diff)</h3>\n"
            "%s\n"
            "%s\n"
            "<details><summary>نوار مراحل (pipeline)</summary>\n"
            "%s\n</details>\n"
            "<h3>کارت نهایی (نمای زبان‌آموز)</h3>\n"
            "%s\n"
            "</section>"
            % (idx, esc(rec.get("text")), kind_fa, _badge_html(rec),
               esc(rec.get("pool_level")), esc(rec.get("bot_level")),
               render_diff_header(rec, phrase_types), diff_html,
               render_stage_strip(rec), final_html))
    head = (
        "<!DOCTYPE html>\n<html lang=\"fa\" dir=\"rtl\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>گذرنامه کارت‌ها</title>\n"
        "<style>\n"
        ":root{--ink:#2a241d;--muted:#7a6f60;--line:#e3d9c8;"
        "--paper:#faf7f0;--soft:#f3ecdd;--accent:#b3552e;"
        "--green:#3f7a2e;--green-soft:#e9f1e2;"
        "--amber:#9a6a1c;--amber-soft:#faf0da;--radius:10px;}\n"
        "*{box-sizing:border-box;}\n"
        "body{font-family:Vazirmatn,\"Segoe UI\",Tahoma,sans-serif;margin:0;"
        "color:var(--ink);line-height:2;background:var(--paper);}\n"
        ".wrap{max-width:920px;margin:0 auto;padding:0 1.2em 3em;}\n"
        "nav.top{position:sticky;top:0;background:var(--paper);"
        "border-bottom:1px solid var(--line);padding:.6em 1.2em;z-index:10;"
        "display:flex;gap:1em;flex-wrap:wrap;}\n"
        "nav.top a{color:var(--accent);text-decoration:none;font-size:.85em;}\n"
        "nav.top a:hover{text-decoration:underline;}\n"
        "nav.top a:focus-visible{outline:2px solid var(--accent);"
        "outline-offset:2px;}\n"
        "h1{font-size:1.5em;margin:1.2em 0 .2em;}\n"
        "h2{font-size:1.15em;margin-top:1.5em;}\n"
        "h3{font-size:1em;margin-top:1.5em;border-bottom:2px solid "
        "var(--accent);padding-bottom:.3em;}\n"
        ".en{direction:ltr;unicode-bidi:isolate;"
        "font-family:Consolas,monospace;font-size:.88em;}\n"
        ".nums{font-variant-numeric:tabular-nums;direction:ltr;"
        "unicode-bidi:isolate;}\n"
        ".card{border:1px solid var(--line);border-radius:var(--radius);"
        "padding:1em 1.2em;margin:1.2em 0;background:var(--paper);}\n"
        ".badge{border-radius:4px;padding:0.1em 0.5em;font-size:0.85em;}\n"
        ".ok{background:var(--green-soft);color:var(--green);} "
        ".bad{background:var(--amber-soft);color:var(--amber);}\n"
        ".chip{display:inline-block;font-size:.8em;border-radius:20px;"
        "padding:.1em .8em;white-space:nowrap;}\n"
        ".chip.done{background:var(--green-soft);color:var(--green);"
        "border:1px solid var(--green);}\n"
        ".chip.pass{background:var(--paper);color:var(--accent);"
        "border:1px solid var(--accent);}\n"
        ".chip.open{background:var(--amber-soft);color:var(--amber);"
        "border:1px solid var(--amber);}\n"
        ".tchip{display:inline-block;font-size:.82em;border-radius:20px;"
        "padding:.1em .8em;border:1px solid var(--line);"
        "background:var(--soft);}\n"
        ".tchip.primary{border-color:var(--accent);color:var(--accent);"
        "font-weight:700;}\n"
        ".blk{margin:.15em 0;}\n"
        ".blk.empty{color:var(--muted);}\n"
        ".blk.lead{font-size:1.2em;}\n"
        ".fld-label{font-weight:700;margin-top:.7em;}\n"
        ".srctag{font-size:.78em;color:var(--muted);}\n"
        ".strip{border:1px solid var(--line);border-radius:var(--radius);"
        "padding:.6em .9em;margin:.8em 0;background:var(--paper);}\n"
        ".srow{margin:.4em 0;}\n"
        ".slabel{font-weight:700;}\n"
        ".sblocks{display:flex;flex-wrap:wrap;gap:.2em 1em;}\n"
        ".dhead{border:1px solid var(--line);border-radius:var(--radius);"
        "padding:.6em .9em;margin:.8em 0;background:var(--soft);}\n"
        ".dh-row{display:flex;flex-wrap:wrap;gap:.2em 1em;align-items:baseline;"
        "margin:.25em 0;}\n"
        ".dh-label{font-weight:700;min-width:5em;}\n"
        ".chips-row{display:flex;flex-wrap:wrap;gap:.4em;}\n"
        ".dh-row.also{font-size:.9em;color:var(--muted);}\n"
        ".diff{display:grid;gap:.35em;margin:.8em 0;}\n"
        ".diff-row{display:grid;grid-template-columns:7em 1fr auto 1fr;"
        "gap:.6em;align-items:start;border-bottom:1px dashed var(--line);"
        "padding:.35em 0;}\n"
        ".diff-head{font-weight:700;border-bottom:2px solid var(--line);}\n"
        ".diff-label{font-weight:700;}\n"
        ".op{display:inline-block;font-size:.78em;border-radius:20px;"
        "padding:.1em .7em;white-space:nowrap;border:1px solid var(--line);}\n"
        ".op.keep{border-color:var(--accent);color:var(--accent);}\n"
        ".op.model{color:var(--ink);background:var(--soft);}\n"
        ".op.review{background:var(--amber-soft);color:var(--amber);"
        "border-color:var(--amber);}\n"
        ".op.none{color:var(--muted);}\n"
        "@media (max-width: 600px){"
        ".diff-row{grid-template-columns:1fr;gap:.2em;}"
        ".diff-head{display:none;}}\n"
        ".tbl-scroll{overflow-x:auto;}\n"
        "table{border-collapse:collapse;width:100%;margin:1em 0;"
        "font-size:.9em;}\n"
        "th,td{border:1px solid var(--line);padding:.5em .7em;"
        "text-align:right;vertical-align:top;}\n"
        "th{background:var(--soft);font-weight:500;}\n"
        ".final{background:var(--soft);border:1px solid var(--line);"
        "border-radius:var(--radius);padding:.8em 1.1em;margin:1em 0;}\n"
        ".final .lead{font-size:1.2em;}\n"
        ".final-empty{color:var(--muted);}\n"
        "pre{white-space:pre-wrap;}\n"
        "details{margin:.6em 0;}\n"
        "summary{cursor:pointer;color:var(--accent);}\n"
        "@media (prefers-reduced-motion: reduce)"
        "{*{transition:none !important;}}\n"
        "</style>\n</head>\n<body>\n")
    header = (
        "<div class=\"wrap\">\n"
        "<h1>گذرنامه کارت‌ها (آزمایشی)</h1>\n"
        '<div class="blk" dir="rtl" lang="fa">تاریخ تهران: '
        + esc(meta.get("date_tehran", "")) + "</div>\n"
        + '<div class="blk en" dir="ltr" lang="en">commit: '
        + esc(meta.get("commit", "")) + "</div>\n"
        + '<div class="blk nums" dir="rtl" lang="fa">کارت‌ها: ' + esc(total)
        + " ـ تأییدشده: " + esc(passed)
        + " ـ نرخ قبولی: " + ("%.1f" % rate) + "٪</div>\n"
        + '<div class="blk" dir="rtl" lang="fa">فراخوانی مدل‌ها</div>\n'
        + '<div class="blk en" dir="ltr" lang="en">'
        + ", ".join("%s: %d" % (m, n) for m, n in calls.items())
        + "</div>\n"
        + '<div class="blk" dir="rtl" lang="fa">هزینه مورد انتظار: $0 '
        "(زنجیره رایگان)</div>\n"
        + '<div class="blk" dir="rtl" lang="fa">روش موضوع</div>\n'
        + '<div class="blk en" dir="ltr" lang="en">v16b-exact</div>\n'
        + '<div class="blk" dir="rtl" lang="fa">مسیر دقیق v16b (قطعی v16 از '
        "run_v16_topics + تکمیل Others از run_v16b_topup).</div>\n")
    if isinstance(rich, dict) and rich:
        header += (
            '<div class="blk" dir="rtl" lang="fa">غنای دیتاست</div>\n'
            '<div class="blk en nums" dir="ltr" lang="en">'
            "ipa_dataset: %.1f%% | examples_dataset: %.1f%% | "
            "topics_non_other: %.1f%%</div>\n"
            % (float(rich.get("ipa_dataset_pct", 0.0)),
               float(rich.get("examples_dataset_pct", 0.0)),
               float(rich.get("topics_non_other_pct", 0.0))))
    return (head + nav + "\n" + header + timings_table + "\n" + tele_table
            + "\n"
            + "\n".join(sections) + "\n</div>\n</body>\n</html>")


def load_cards_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_precard_items(path):
    """Load a precard.jsonl file into pilot sample items (R22-R25).

    Each pre-card line already carries sense_id/en_def/ipa/dataset_examples
    /topic_vector/topic_method/stage_calls, so the caller SKIPS sampling,
    anchor scoring, topic assignment, and dataset enrichment. The gallery
    method is forced to PIPELINE_METHOD_TAG ("pipeline-v6").
    """
    with open(path, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    items = []
    for rec in records:
        if not isinstance(rec, dict) or not (rec.get("text") or "").strip():
            raise SystemExit("corrupt pre-card %s: bad record" % path)
        vec = [e for e in (rec.get("topic_vector") or [])
               if isinstance(e, dict) and e.get("label")]
        vec.sort(key=lambda d: -float(d.get("weight", 0.0) or 0.0))
        text = rec["text"].strip()
        items.append({
            "kind": rec.get("kind") or "word",
            "text": text,
            "pos": rec.get("pos", ""),
            "pool_level": rec.get("pool_level", ""),
            "freq": rec.get("freq"),
            "proper_noun": None,
            "sense_id": rec.get("sense_id", ""),
            "en_def": rec.get("en_def", ""),
            "en_source": "dataset" if rec.get("en_def") else "none",
            "sense_candidates": list(rec.get("sense_candidates") or []),
            "also_sense": rec.get("also_sense"),
            "topic": vec[0]["label"] if vec else "",
            "topic_method": PIPELINE_METHOD_TAG,
            "topic_vector": vec,
            "ipa": rec.get("ipa", ""),
            "ipa_src": rec.get("ipa_src", IPA_SRC_MODEL),
            "dataset_examples": list(rec.get("dataset_examples") or []),
        })
    return items


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
    ap.add_argument("--tatoeba-pool", default=DEFAULT_TATOEBA_POOL)
    ap.add_argument("--topic-vectors", default=DEFAULT_TOPIC_VECTORS)
    ap.add_argument("--phrase-type-log", default=DEFAULT_PHRASE_TYPE_LOG,
                    help="opportunistic phrase-type audit log for the "
                    "gallery display (missing file = unjudged, never fails)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from-precard", default="",
                    help="pre-card pipeline file (precard.jsonl): when given, "
                    "sampling/anchor/topic/enrichment are SKIPPED and items "
                    "come from this file (gallery method pipeline-v6). "
                    "Default path (sampling) is unchanged when empty.")
    ap.add_argument("--render-only", action="store_true",
                    help="regenerate the gallery HTML from out-dir/"
                    "cards.jsonl + timings.json only (no network, no env, "
                    "never touches sample/cards)")
    args = ap.parse_args(argv)

    if args.render_only:
        # Hermetic gallery rebuild: no kaikki/env/network, files read-only
        # except the HTML report write.
        render_only(args.out_dir, args.report)
        return 0

    precard_sample = None
    if args.from_precard:
        try:
            precard_sample = load_precard_items(args.from_precard)
        except OSError as exc:
            sys.exit("cannot load pre-card %s: %s"
                     % (args.from_precard, exc))
        if args.dry_run:
            print("dry-run: %d pre-card items from %s, no files written, "
                  "no network calls"
                  % (len(precard_sample), args.from_precard))
            return 0

    pool = load_word_pool(args.word_pool)
    judged = load_phrase_judgements(args.phrase_log)
    if args.dry_run:
        # Hermetic: no kaikki/W: touch, no files, no network.
        sample = sample_words(pool, args.n_words, args.seed)
        sample += sample_phrases(judged, args.n_phrases, args.seed)
        print("dry-run: %d words + %d phrases sampled, no files written, "
              "no network calls" % (args.n_words, args.n_phrases))
        return 0

    if precard_sample is not None:
        index = {}
        sample = []
        sample_s = 0.0
    else:
        sample_start = time.perf_counter()
        try:
            index = load_kaikki_index(args.kaikki_index)
        except OSError as exc:
            sys.exit("cannot load kaikki index %s: %s"
                     % (args.kaikki_index, exc))
        pos_sets = build_pos_sets(index)
        sample = sample_words(pool, args.n_words, args.seed,
                              pos_sets=pos_sets)
        sample += sample_phrases(judged, args.n_phrases, args.seed)
        if len(sample) != args.n_words + args.n_phrases:
            print("warning: short sample %d (pool gaps)" % len(sample))
        sample_s = time.perf_counter() - sample_start

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # V7: compact run.log in the out dir (stage start/end + counts).
    run_logger = RunLogger(out_dir / "run.log")
    run_logger.stage_start("sample")
    if precard_sample is not None:
        # R22-R25: sampling/anchor/topic/enrichment SKIPPED — items come
        # from the pre-card file (gallery method pipeline-v6).
        sample = precard_sample
        sample_s = 0.0
        gloss_s = 0.0
        print("using pre-card items (%d from %s): anchor/topic/ "
              "enrichment skipped" % (len(sample), args.from_precard))
        sys.path.insert(0, str(FACTORY_DIR))
        from env_loader import load_factory_env
        _env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
    else:
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
        tatoeba_pool = load_tatoeba_pool(args.tatoeba_pool)
        topic_vectors = load_topic_vectors(args.topic_vectors)
        for item in sample:  # R6 anchor + v16b-exact topic + R10-R12 enrichment
            if not item.get("en_def") or not item.get("sense_id") \
                    or not item.get("ipa_src") \
                    or "sense_candidates" not in item \
                    or "also_sense" not in item:
                anchor_item_en(item, index, read_entry,  # R6 + R10 + R17/R18
                               vector_lookup=topic_vectors)
            if "dataset_examples" not in item:
                resolve_dataset_examples(  # R11 frozen pre-card examples
                    item, index, read_entry, tatoeba_pool)
            if not item.get("topic") or not item.get("topic_vector"):
                assigned = assign_topic(
                    item["text"], item.get("en_def", ""),
                    sense_id=item.get("sense_id") or None,
                    llm_transport=_topup_transport, progress_path=topic_prog,
                    api_key=_topic_key, model_calls=topic_calls,
                    vector_lookup=topic_vectors)  # R12 full vector
                item["topic"] = assigned["label"]
                item["topic_method"] = assigned["method"]
                item["topic_vector"] = assigned["vector"]
        sample_path.write_text(json.dumps(sample, ensure_ascii=False),
                               encoding="utf-8")
        gloss_s = time.perf_counter() - gloss_start
    run_logger.stage_end("sample", ok=len(sample), fail=0)
    run_logger.stage_start("anchor")

    env = _env
    api_key = env["OPENCODE_ZEN_API_KEY"]
    if not api_key:
        sys.exit("no OPENCODE_ZEN_API_KEY in factory/.env")
    run_logger.stage_end("anchor", ok=len(sample), fail=0)

    # Reviewer F3: precard mode uses its own progress file so stale
    # sampling-mode done[] records can never leak into precard runs.
    prog_path = out_dir / ("precard_progress.json" if args.from_precard
                           else "progress.json")
    prog = json.loads(prog_path.read_text(encoding="utf-8")) if prog_path.exists() else {}
    done = prog.get("done", {})
    model_calls = prog.get("model_calls", {})
    gen_timings = {"validate": 0.0}
    tele_store = []  # R27: per-attempt records (key_idx only, never values)
    per_card = []
    gen_start = time.perf_counter()
    run_logger.stage_start("generate")
    # V7: ONE stdout line per batch of 8 (no per-item spam); ok = valid
    # cards in the batch, fail = invalid cards, model = total calls.
    GEN_BATCH = 8
    n_gen_batches = (len(sample) + GEN_BATCH - 1) // GEN_BATCH or 1
    for batch_no, base in enumerate(range(0, len(sample), GEN_BATCH),
                                    start=1):
        batch_ok = batch_fail = 0
        for item in sample[base:base + GEN_BATCH]:
            key = item_key(item)
            if key in done:
                if done[key].get("valid"):
                    batch_ok += 1
                else:
                    batch_fail += 1
                continue
            card_start = time.perf_counter()
            rec = generate_card(item, api_key, model_calls=model_calls,
                                timings=gen_timings, telemetry=tele_store,
                                tele_batch=batch_no)
            per_card.append({"key": key,
                             "seconds": time.perf_counter() - card_start})
            done[key] = rec
            prog_path.write_text(json.dumps(
                {"done": done, "failed": [k for k, v in done.items() if not v.get("valid")],
                 "model_calls": model_calls}, ensure_ascii=False), encoding="utf-8")
            if rec.get("valid"):
                batch_ok += 1
            else:
                batch_fail += 1
            time.sleep(CALL_SLEEP)
        print(batch_log_line("gen", batch_no, n_gen_batches,
                             batch_ok, batch_fail, model_calls))
    gen_total = time.perf_counter() - gen_start
    run_logger.stage_end(
        "generate",
        ok=sum(1 for v in done.values() if v.get("valid")),
        fail=sum(1 for v in done.values() if not v.get("valid")))

    records = [done[item_key(item)] for item in sample]
    (out_dir / "cards.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8")
    run_logger.stage_start("render")
    render_start = time.perf_counter()
    timings = build_timings(sample_s, gloss_s, gen_total, per_card,
                            gen_timings["validate"],
                            0.0, len(sample))
    timings["richness"] = richness_counters(records)  # R17 -> timings.json
    phrase_types = load_phrase_types(args.phrase_type_log)  # opportunistic
    tele_summary = tele_write_summary(
        out_dir / "telemetry_summary.json", tele_store)
    meta = {"date_tehran": tehran_now_str(), "commit": git_commit(),
            "model_calls": model_calls, "timings": timings,
            "telemetry": tele_summary}
    gallery_html = render_gallery(records, meta, phrase_types=phrase_types)
    timings["render"] = time.perf_counter() - render_start
    meta["timings"] = timings  # refresh with measured render seconds
    gallery_html = render_gallery(records, meta, phrase_types=phrase_types)
    report_path = pathlib.Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(gallery_html, encoding="utf-8")
    (out_dir / "timings.json").write_text(
        json.dumps(timings, ensure_ascii=False), encoding="utf-8")
    passed = sum(1 for r in records if r.get("valid"))
    run_logger.stage_end("render", ok=passed,
                         fail=len(records) - passed)
    run_logger.log("pilot done: %d/%d valid" % (passed, len(records)))
    run_logger.close()
    print("pilot done: %d/%d valid, calls=%s, report=%s"
          % (passed, len(records), model_calls, report_path))
    return 0


if __name__ == "__main__":
    main()
