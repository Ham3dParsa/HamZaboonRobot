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

# Dataset vulgarity signal: anchored senses carrying any of these kaikki
# tags never become learner cards (S1 vulgar-anchor drop, no word lists).
VULGAR_TAGS = {"vulgar", "offensive", "derogatory", "obscene", "profane",
               "ethnic-slur", "slur"}

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
    """Casefold a POS tag through the minimal alias map (R1 gloss match).

    R32 v8: tolerates the dataset tag list in item["pos"] (uses the
    first tag) so re-ranking an already-anchored item never crashes.
    """
    if isinstance(pos, (list, tuple)):
        pos = pos[0] if pos else ""
    if not isinstance(pos, str):
        pos = str(pos or "")
    key = pos.strip().casefold()
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
    R34 v9: v14-pattern gap fixed — the owner regex requires a qualifier
    word ("alternative <X> form of") so the bare "alternative form of X"
    stub scored 1.0 here; it now scores 0.50 like its siblings. The
    owner function (run_v14_phase1.py) is untouched.
    """
    import re as _re
    t = set((tags or []))
    if t & {"slang", "vulgar", "derogatory", "offensive"}:
        return 0.60
    g = (gloss or "").strip()
    if _re.search(r"alternative (?:[\w\-]+ )?form of|alternative spelling of|alternative name for",
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


# R37 v9 — frequency leg, owners: factory/run_v14_phase1.py::main.<locals>.
# sense_words / freq_per_sense (owner lines ~90-95). Vendored (minimal
# faithful copy) because importing run_v14_phase1 pulls numpy/torch/
# sentence-transformers/sklearn + embedding models (side effects,
# non-hermetic).
# R38 v10: freq is NO LONGER an additive pre-score leg. The pre-score is
# the file-index decay Score_pre = (1/sqrt(file_index+1)) * preg * ppos;
# freq_per_sense survives ONLY as the final tie-breaker when two
# pre-scores differ by less than FREQ_TIE_EPS (0.05).
# R38 v10 — tie-breaker epsilon: pre-score diffs below this defer to freq.
FREQ_TIE_EPS = 0.05


def _v14_sense_words(gloss, synonyms, lemma):
    """R37 owner: run_v14_phase1 sense_words (words len>=3, minus lemma)."""
    words = [w for w in re.findall(
        r"[a-zA-Z']+", (gloss or "").lower())
        if len(w) >= 3 and w != (lemma or "").lower()]
    for s in synonyms or []:
        w = (s.get("word") if isinstance(s, dict) else str(s)) or ""
        words += [p for p in re.findall(
            r"[a-zA-Z']+", w.lower().replace("_", " ")) if len(p) >= 3]
    return words


def _freq_zipf_single(word):
    """Single-word zipf via wordfreq; None when unknown/uninstalled."""
    try:
        from wordfreq import zipf_frequency
        return float(zipf_frequency(word, "en"))
    except Exception:
        return None


def _v14_freq_per_sense(gloss, synonyms, lemma, zipf_fn=None):
    """R37 owner: run_v14_phase1 freq_per_sense (mean zipf, None if <3w)."""
    words = _v14_sense_words(gloss, synonyms, lemma)
    if len(words) < 3:
        return None  # shrink to median later (owner R1 note)
    get = zipf_fn or _freq_zipf_single
    try:
        sc = [get(w) for w in words]
    except Exception:
        return None
    sc = [s for s in sc if isinstance(s, (int, float)) and s > 0]
    return float(sum(sc) / len(sc)) if sc else None


def _freq_norm(values):
    """R37 owner: run_v14_phase1 ranking norm() (min-max, 0.5 on tie)."""
    import numpy as _np
    a = _np.array(list(values), dtype=float)
    if len(a) == 0:
        return []
    if a.max() - a.min() < 1e-9:
        return [0.5] * len(a)
    return [float((v - a.min()) / (a.max() - a.min())) for v in a]


# R34 v9 — cross-reference detection. General case-insensitive gloss
# patterns (no word lists): "Alternative form/spelling of X",
# "Synonym/Variant of X", bare "See X". Inflection stubs ("plural of",
# "past of", ...) are R36, NOT xref — deliberately unmatched here.
_XREF_RES = (
    re.compile(r"(?i)^\s*alternative\s+(?:[\w\-]+\s+)?"
               r"(?:form|spelling)\s+of\s+(.+?)\s*\.?\s*$"),
    re.compile(r"(?i)^\s*(?:synonym|variant)\s+of\s+(.+?)\s*\.?\s*$"),
    re.compile(r"(?i)^\s*see\s+(?:also\s+)?(.+?)\s*\.?\s*$"),
)


def detect_xref(gloss):
    """R34: cross-reference target of a bare-xref gloss, else None.

    Returns the stripped target string ("colour" for 'Alternative
    spelling of "colour".'). Non-bare glosses (prose merely mentioning
    "see" mid-sentence) never match: patterns are whole-gloss anchored.
    """
    g = (gloss or "").strip()
    if not g:
        return None
    for rx in _XREF_RES:
        hit = rx.match(g)
        if hit:
            target = (hit.group(1) or "").strip().strip(
                "'\"“”‘’").strip().rstrip(".").strip()
            return target or None
    return None


# R36 v9 — inflection-stub detection. General pattern over the
# inflectional categories (no word lists): plural / past / participles /
# comparative / superlative / 3rd-person-singular "of X".
_INFLECTION_RX = re.compile(
    r"(?i)\b(?:plural|past(?:\s+participle)?|present\s+participle|"
    r"comparative|superlative|third(?:-|\s+)person\s+singular)\s+of\b")


def is_inflection_gloss(gloss):
    """R36: True when the gloss is an inflection stub ("plural of X")."""
    return bool(_INFLECTION_RX.search(gloss or ""))


# R34 v9 — xref method tag (anchor resolved through the target entry).
XREF_METHOD_TAG = "xref-resolved"


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


def _decay_prescore(file_index, preg, ppos):
    """R38 v10 pre-score: (1/sqrt(file_index+1)) * preg * ppos."""
    import math as _math
    return (1.0 / _math.sqrt(float(file_index) + 1.0)) * preg * ppos


def score_senses(text, entries, pool_pos, read_entry, zipf_fn=None):
    """Score every kaikki sense: [(score, file-idx, entry, sense, gloss)].

    R38 v10: Score_pre = (1/sqrt(file_index+1)) * preg * ppos where
    file_index is the stable file-order sense idx, preg is the vendored
    v14 register_penalty (incl. the R34 bare-alt-form extension) and
    ppos the vendored v14 POS factor (both kept as-is). The vendored
    v14 freq_per_sense leg survives ONLY as the final tie-breaker: when
    two pre-scores differ by less than FREQ_TIE_EPS (0.05) the higher
    freq_norm wins; otherwise file-decay order wins. zipf_fn injects
    the per-word zipf lookup (hermetic tests); None uses wordfreq live.
    Shared by the anchor pick and the R17/R18 audit helpers so the anchor,
    the top-3 candidates, and the second sense never diverge.
    """
    import functools as _ft
    senses = _collect_kaikki_senses(entries, read_entry)
    lemma = (text or "").strip()
    fraw = [_v14_freq_per_sense(
        gloss, (sense or {}).get("synonyms", []), lemma, zipf_fn)
        for _, _, sense, gloss in senses]
    present = [x for x in fraw if x is not None]
    if present:
        import numpy as _np
        med = float(_np.median(present))
    else:
        med = 3.0  # owner fallback when every sense is short/unknown
    fnorm = _freq_norm([x if x is not None else med for x in fraw])
    scored = []
    for idx, ((entry_pos, entry, sense, gloss), fn) in enumerate(
            zip(senses, fnorm)):
        preg = _v14_register_penalty(
            (sense or {}).get("tags"), gloss)
        ppos = _v14_ppos(entry_pos, pool_pos)
        score = _decay_prescore(idx, preg, ppos)
        scored.append([score, idx, entry, sense, gloss, float(fn)])

    def _cmp(a, b):
        if abs(a[0] - b[0]) >= FREQ_TIE_EPS:
            return -1 if a[0] > b[0] else 1
        if abs(a[5] - b[5]) >= 1e-12:
            return -1 if a[5] > b[5] else 1
        if a[1] != b[1]:
            return -1 if a[1] < b[1] else 1
        return 0

    scored.sort(key=_ft.cmp_to_key(_cmp))
    return [(s, i, e, se, g) for s, i, e, se, g, _fn in scored]


# R39 v10 — tiered bucketing for the candidate window feeding S2 (and the
# pilot anchor shortlist display). Replaces any hard index cap: A1-A2 look
# at file-index 0-5 first and go higher ONLY when no POS-matching sense
# is found there; upper levels (B1-C2) look at 0-9 first. Per level, at
# least one candidate per POS present in the window is enforced by
# pulling the top-scored missing-POS sense from above the bucket.
CANDIDATE_BUCKET_A1A2 = 6
CANDIDATE_BUCKET_UPPER = 10
JUDGE_WINDOW_CAP = 10


def candidate_bucket_cap(pool_level):
    """R39: file-index bucket size by pool level (6 for A1/A2, else 10)."""
    return CANDIDATE_BUCKET_A1A2 \
        if (pool_level or "").strip().upper() in ("A1", "A2") else \
        CANDIDATE_BUCKET_UPPER


def select_candidate_window(scored, pool_pos="", pool_level="A1", cap=10):
    """R39: tiered candidate window over score_senses output (score order).

    scored is the score_senses list [(score, file-idx, entry, sense,
    gloss)] already in rank order. The window starts as the senses whose
    file-idx falls inside the level bucket (0-5 for A1/A2, 0-9 above);
    when pool_pos is given and NO window sense has an entry POS matching
    it, the window expands to the full list (fallback-to-higher). Then
    POS coverage is enforced: for every distinct entry POS in scored
    missing from the window, the top-scored sense of that POS is pulled
    in. The result preserves score order and is capped at cap entries.
    """
    scored = list(scored or [])
    if not scored:
        return []
    try:
        cap = max(1, int(cap))
    except (TypeError, ValueError):
        cap = 10
    bucket = candidate_bucket_cap(pool_level)
    by_idx = sorted(scored, key=lambda t: t[1])
    window_ids = {t[1] for t in by_idx[:bucket]}
    window = [t for t in scored if t[1] in window_ids]
    if not window:
        window = list(scored)
    want = normalize_pos(pool_pos) if (pool_pos or "") else ""
    if want:
        def _pos_of(t):
            try:
                return normalize_pos((t[2] or {}).get("pos") or "")
            except Exception:
                return ""
        if not any(_pos_of(t) == want for t in window):
            window = list(scored)
    # POS coverage: at least one candidate per POS present.
    def _pos_of(t):
        try:
            return normalize_pos((t[2] or {}).get("pos") or "")
        except Exception:
            return ""
    have = {_pos_of(t) for t in window if _pos_of(t)}
    all_pos = [_pos_of(t) for t in scored if _pos_of(t)]
    for pos in dict.fromkeys(all_pos):
        if pos and pos not in have:
            for cand in scored:
                if _pos_of(cand) == pos:
                    window.append(cand)
                    have.add(pos)
                    break
    seen = set()
    ordered = []
    for t in window:
        if t[1] not in seen:
            seen.add(t[1])
            ordered.append(t)
    ordered.sort(key=lambda t: ([i for i, s in enumerate(scored)
                                 if s[1] == t[1]] or [0])[0])
    return ordered[:cap]


def top_sense_candidates(text, entries, pool_pos, read_entry, k=3,
                         zipf_fn=None, pool_level="A1", window_cap=None):
    """R17 top-k anchor candidates [{sense_id, gloss, score}] (ranked).

    R39 v10: candidates are drawn from the tiered bucket window
    (select_candidate_window) before slicing the top-k, so the anchor,
    the shortlist display, and the S2 judge window never diverge.
    sense_id is "<text.lower()>#<file-order-sense-idx>"; score rounded
    to 3 decimals. Empty entries -> [].
    """
    key = (text or "").strip().lower()
    scored = score_senses(text, entries, pool_pos, read_entry,
                          zipf_fn=zipf_fn)
    cap = window_cap if window_cap is not None else max(
        k, candidate_bucket_cap(pool_level))
    try:
        cap = max(int(k), int(cap))
    except (TypeError, ValueError):
        cap = max(3, int(k))
    window = select_candidate_window(scored, pool_pos, pool_level, cap=cap)
    return [{"sense_id": "%s#%d" % (key, idx), "gloss": gloss,
             "score": round(score, 3)}
            for score, idx, _, _, gloss in window[:k]]


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


def _target_rows(index, target):
    """R34: index rows for an xref target (full-phrase key, else 1st token).

    Returns [] when the target has no entry (unresolvable).
    """
    if not target or not isinstance(index, dict):
        return []
    key = target.strip().lower()
    if key in index:
        return list(index[key])
    first = (key.split() or [""])[0]
    return list(index.get(first, []))


def resolve_xref_anchor(target, pool_pos, read_entry, index, zipf_fn=None):
    """R34: top sense of the xref target entry (max 1 hop, no chains).

    Returns (sense_id, gloss, sense, entry) of the target's top scorer,
    or (None, None, None, None) when unresolvable: no target entry, or
    the target top is itself a bare xref (chains stop after 1 hop).
    sense_id is "<target.lower()>#<file-order-sense-idx>".
    """
    rows = _target_rows(index, target)
    if not rows:
        return None, None, None, None
    tkey = (target or "").strip().lower()
    if tkey not in (index or {}):
        tkey = (tkey.split() or [""])[0]
    scored = score_senses(tkey, rows, pool_pos, read_entry,
                          zipf_fn=zipf_fn)
    if not scored:
        return None, None, None, None
    _, best_idx, best_entry, best_sense, best_gloss = scored[0]
    if detect_xref(best_gloss) is not None:
        return None, None, None, None  # 1-hop max: target also bare-xref
    return "%s#%d" % (tkey, best_idx), best_gloss, best_sense, best_entry


def pick_anchor_sense_full(text, entries, pool_pos, read_entry,
                           index=None, zipf_fn=None):
    """R6 anchor + R10/R11 carriers: (sense_id, gloss, sense, entry).

    Scoring is Score_pre = file-index decay * register_penalty * ppos
    (R38 v10; freq_per_sense survives only as <0.05 tie-breaker); sense_id
    is "<text.lower()>#<file-order-sense-idx>". Empty entries ->
    ("", "", None, None). R34 v9: when the top scorer is a bare xref
    and the same kaikki index is passed, the anchor resolves to the
    target entry's top sense (4-tuple of the TARGET: its sense_id/gloss/
    sense/entry); unresolvable xref (no target entry, target also
    bare-xref) returns the ORIGINAL top tuple unchanged — the caller
    (anchor_item_en / S1) flags it via detect_xref for the no-real-def
    drop. index=None preserves the legacy unresolved behavior.
    """
    scored = score_senses(text, entries, pool_pos, read_entry,
                          zipf_fn=zipf_fn)
    if not scored:
        return "", "", None, None
    _, best_idx, best_entry, best_sense, best_gloss = scored[0]
    key = (text or "").strip().lower()
    if index is not None and detect_xref(best_gloss) is not None:
        target = detect_xref(best_gloss)
        resolved = resolve_xref_anchor(
            target, pool_pos, read_entry, index, zipf_fn=zipf_fn)
        if resolved[0]:
            return resolved
    return "%s#%d" % (key, best_idx), best_gloss, best_sense, best_entry


def pick_anchor_sense(text, entries, pool_pos, read_entry):
    """R6: score every kaikki sense, anchor = top scorer (stable file order).

    Score = vendored v14 register_penalty * v14 ppos factor. Returns
    (sense_id, gloss); sense_id is "<text.lower()>#<file-order-sense-idx>".
    Empty entries -> ("", ""). Legacy unresolved path (no xref index).
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


# R29 v8 — abbreviation expansion, dataset-first. General case-insensitive
# regex over gloss patterns (no word lists): "Initialism of X",
# "Abbreviation of X", "Short for X", "Contraction of X".
_ABBREV_RX = re.compile(
    r"(?i)^\s*(?:initialism\s+of|abbreviation\s+of|short\s+for|"
    r"contraction\s+of)\s+(.+?)\s*\.?\s*$")


def parse_abbrev_expansion(gloss):
    """R29: expansion of an abbreviation gloss ("" when not matching).

    Matches the whole gloss only (anchored ^...$) so prose glosses that
    merely mention "short for" mid-sentence never parse.
    """
    hit = _ABBREV_RX.match(gloss or "")
    if not hit:
        return ""
    return (hit.group(1) or "").strip().rstrip(".")


ABBREV_FILL_INSTRUCTION = (
    'If this word is an abbreviation, initialism or short form, also '
    'return key "abbrev_expansion": the full expanded form in English, '
    "grounded in the given English definition; omit when the word is not "
    "an abbreviation.")
ABBREV_PRESERVE_INSTRUCTION = (
    'Dataset abbreviation expansion (preserve exactly under '
    '"abbrev_expansion"): ')


def anchor_pos_tags(text, entries, pool_pos, read_entry, limit=3):
    """R32 v8: dataset POS tags from the anchored entry (1-3 tags).

    The anchored sense's entry POS comes first, then the remaining
    distinct entry POS values in file order (casefolded, deduped,
    capped at ``limit``). [] when nothing anchors.
    """
    sid, _, _, _ = pick_anchor_sense_full(
        text, entries, pool_pos, read_entry)
    if not sid:
        return []
    try:
        want = int(sid.split("#")[-1])
    except (TypeError, ValueError):
        return []
    try:
        flat = _collect_kaikki_senses(entries, read_entry)
    except Exception:
        return []
    if want < 0 or want >= len(flat):
        return []
    first = ((flat[want][0] or "").strip().casefold())
    tags = []
    for entry_pos, _, _, _ in flat:
        tag = (entry_pos or "").strip().casefold()
        if tag and tag not in tags:
            tags.append(tag)
    if first and first in tags:
        tags.remove(first)
        tags.insert(0, first)
    return tags[:max(1, limit)]


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


def anchor_item_en(item, index, read_entry, vector_lookup=None,
                   zipf_fn=None, candidate_k=3):
    """R6 anchor + R10 IPA + R17 candidates + R18 second sense.

    Fills sense_id/en_def + ipa/ipa_src (R6/R10, unchanged) and the audit
    trail: sense_candidates (top-candidate_k [{sense_id, gloss, score}],
    3 by default for the pilot shortlist display, JUDGE_WINDOW_CAP for
    the S2 judge window via candidate_k) from the SAME entries the
    anchor was picked from, plus also_sense (second-best
    {sense_id, gloss, topic, topic_method}, None when single-sense).
    The also-sense topic uses the cheap vector_lookup leg only (R18
    choice: no LLM for an audit-only field).
    R29 v8: abbrev_expansion parsed dataset-first from the anchored gloss
    ("" when the gloss is not an abbreviation pattern). R32 v8:
    item["pos"] becomes the dataset tag list (anchored entry POS first,
    1-3 tags) with pos_src "dataset" ("none" when nothing anchors); the
    pool POS string it replaces was already consumed by the scorer above.
    R34 v9: bare-xref top senses resolve through the same kaikki index
    (pick_anchor_sense_full with index=): a hit re-bases sense_id/en_def/
    ipa/candidates/POS onto the TARGET entry (sense_id is the target's,
    xref_method "xref-resolved", xref_resolved_from the original sense
    id); unresolvable xref (no target entry / target also bare-xref,
    1 hop max) keeps the original gloss and sets xref_unresolvable=True
    (S1 drops it as no-real-def — this helper itself never drops).
    anchor_pos carries the anchored entry POS ("" when no anchor).
    """
    text = (item.get("text") or "").strip()
    sense, entry = None, None
    cand_entries, cand_pos = [], ""
    if item.get("kind") == "word":
        entries = index.get(text.lower(), [])
        cand_entries, cand_pos = entries, item.get("pos", "")
        sid, gloss, sense, entry = pick_anchor_sense_full(
            text, entries, item.get("pos", ""), read_entry,
            index=index, zipf_fn=zipf_fn)
    else:
        key = text.lower()
        if key in index:
            cand_entries = index[key]
            sid, gloss, sense, entry = pick_anchor_sense_full(
                text, index[key], "", read_entry,
                index=index, zipf_fn=zipf_fn)
        else:
            sid, gloss = "", ""
            for token in sorted(set(key.split()),
                                key=lambda t: (-len(t), t)):
                cand_sid, cand, sense, entry = pick_anchor_sense_full(
                    text, index.get(token, []), "", read_entry,
                    index=index, zipf_fn=zipf_fn)
                if cand:
                    sid, gloss = cand_sid, cand
                    cand_entries = index.get(token, [])
                    break
            else:
                sense, entry = None, None
    key = text.lower()
    sid_lemma = sid.rpartition("#")[0] if "#" in (sid or "") else ""
    item["xref_method"] = ""
    item["xref_resolved_from"] = ""
    item["xref_unresolvable"] = False
    cand_text = text
    if sid and sid_lemma and sid_lemma != key:
        # R34 resolved: re-base candidates/POS onto the target rows.
        try:
            raw = score_senses(text, cand_entries, cand_pos, read_entry,
                               zipf_fn=zipf_fn)
            orig_sid = "%s#%d" % (key, raw[0][1]) if raw else ""
        except Exception:
            orig_sid = ""
        item["xref_method"] = XREF_METHOD_TAG
        item["xref_resolved_from"] = orig_sid
        cand_entries = _target_rows(index, sid_lemma)
        cand_text = sid_lemma
    elif gloss and detect_xref(gloss) is not None:
        item["xref_unresolvable"] = True
    item["sense_id"] = sid
    item["en_def"] = gloss
    ipa = first_entry_ipa(entry)
    item["ipa"] = ipa
    item["ipa_src"] = IPA_SRC_DATASET if ipa else IPA_SRC_MODEL
    item["anchor_pos"] = (str((entry or {}).get("pos") or "").strip()
                          .casefold() if isinstance(entry, dict) else "")
    # Anchor sense tags ride along for the S1 vulgar-anchor drop (dataset
    # signal: vulgar/offensive/derogatory senses never become learner cards).
    try:
        _tags = ((sense or {}).get("tags") or [])
        item["anchor_tags"] = sorted(
            {str(t).strip().casefold() for t in _tags if str(t or "").strip()})
    except Exception:
        item["anchor_tags"] = []
    item["abbrev_expansion"] = parse_abbrev_expansion(gloss)
    pos_tags = anchor_pos_tags(cand_text, cand_entries, cand_pos,
                               read_entry)
    item["pos"] = pos_tags
    item["pos_src"] = "dataset" if pos_tags else "none"
    # R39 v10: the shortlist display rides the same tiered bucket window
    # as the S2 judge window (pool_level carried for the bucket size;
    # candidate_k selects display width 3 vs judge width JUDGE_WINDOW_CAP
    # in a SINGLE scorer pass — no extra read_entry sweep).
    _lvl = item.get("pool_level") or "A1"
    if isinstance(_lvl, list):
        _lvl = _lvl[0] if _lvl else "A1"
    try:
        _k = max(1, int(candidate_k or 3))
    except (TypeError, ValueError):
        _k = 3
    candidates = top_sense_candidates(
        cand_text, cand_entries, cand_pos, read_entry, k=_k,
        zipf_fn=zipf_fn, pool_level=str(_lvl or "A1"),
        window_cap=max(_k, JUDGE_WINDOW_CAP if _k > 3 else
                       candidate_bucket_cap(str(_lvl or "A1"))))
    item["sense_candidates"] = candidates
    item["also_sense"] = build_also_sense(candidates, vector_lookup)
    return item


def sense_report(items, index, read_entry, k=3, zipf_fn=None):
    """R38-R39 v10 human-run report helper (no network, no files).

    items: [{text, pos, pool_level}...]. Returns [{text, top:
    [{sense_id, gloss, score}]...}] using the live scorer + tiered
    window. The owner runs this against the real kaikki index to write
    W:/hamzaban_data_factory/reports/v10-sense-check.md; unit tests
    assert the synthetic kiss/bank/note orderings through this helper.
    """
    out = []
    for item in items or []:
        text = (item.get("text") or "").strip()
        entries = (index or {}).get(text.lower(), [])
        cands = top_sense_candidates(
            text, entries, item.get("pos", ""), read_entry, k=k,
            zipf_fn=zipf_fn,
            pool_level=str(item.get("pool_level") or "A1"),
            window_cap=max(k, JUDGE_WINDOW_CAP))
        out.append({"text": text, "top": cands})
    return out


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


# R41 v10 — hard validation gate: fa-alpha. fa_meaning /
# fa_explanation / example_translations may contain ONLY Persian/Arabic
# script letters, digits, punctuation, and explicitly-allowed inline
# Latin TERMS (empty by default). Any other Latin run fails — including
# Latin words with diacritics (fuerte/nino with n~/e'/u" always fail
# because the base letters are Latin). Grammar_tip is NOT covered
# (R7 fa-dominant owns it). REJECT (not regen) after existing gates.
_LATIN_RUN_RX = re.compile(
    r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]+")


def fa_alpha_check(card, allowed_terms=None):
    """R41: True iff the FA fields carry no unlisted Latin runs.

    Checks fa_meaning, fa_explanation, and every example_translation.
    allowed_terms is an optional iterable of explicitly-allowed inline
    Latin terms (matched case-insensitively, whole-run); empty/None
    means any Latin run fails.
    """
    allowed = {str(t or "").strip().lower()
               for t in (allowed_terms or []) if str(t or "").strip()}
    fields = [(card or {}).get("fa_meaning") or "",
              (card or {}).get("fa_explanation") or ""]
    fields += list((card or {}).get("example_translations") or [])
    for field in fields:
        if not isinstance(field, str):
            continue
        for run in _LATIN_RUN_RX.findall(field):
            if run.lower() not in allowed:
                return False
    return True


# R41 v10 — hard validation gate: sense coherence. Content-word overlap
# (len>=4 alpha tokens, stopword-free with the minimal inline EN list
# below) between the anchor gloss keywords and the card's (examples +
# FA-field latin tokens + synonyms); zero overlap REJECTs the card
# (valid=False, reason sense-incoherence, not a flag). REJECT (not
# regen) after existing gates.
_COHERENCE_STOPWORDS = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "for", "with", "and",
    "or", "is", "are", "was", "were", "be", "been", "by", "from",
    "as", "at", "that", "this", "it", "its",
})
_COHERENCE_TOKEN_RX = re.compile(r"[A-Za-z]+")


def _coherence_tokens(text):
    return {t for t in (
        m.lower() for m in _COHERENCE_TOKEN_RX.findall(text or ""))
        if len(t) >= 4 and t not in _COHERENCE_STOPWORDS}


def sense_coherence_check(anchor_gloss, card):
    """R41: True iff anchor keywords overlap the card's EN-bearing fields.

    Anchor side: content tokens of anchor_gloss. Card side: content
    tokens of examples + FA-field latin runs + synonyms. Empty anchor
    keyword sets pass (nothing to be incoherent with — fail-open).
    """
    anchor_keys = _coherence_tokens(anchor_gloss or "")
    if not anchor_keys:
        return True
    parts = []
    for ex in (card or {}).get("examples") or []:
        if isinstance(ex, str):
            parts.append(ex)
    for key in ("fa_meaning", "fa_explanation"):
        val = (card or {}).get(key) or ""
        if isinstance(val, str):
            parts.append(" ".join(_LATIN_RUN_RX.findall(val)))
    for tr in (card or {}).get("example_translations") or []:
        if isinstance(tr, str):
            parts.append(" ".join(_LATIN_RUN_RX.findall(tr)))
    syns = (card or {}).get("synonyms") or []
    for syn in syns:
        parts.append(syn if isinstance(syn, str) else str(syn or ""))
    card_keys = set()
    for part in parts:
        card_keys |= _coherence_tokens(part)

    def _stem_hit(a, b):
        # R42 v11: delegates to the shared _stem_match_5 helper (same
        # 5-char stem-containment semantics, factored out for reuse).
        return _stem_match_5(a, b)
    return any(_stem_hit(a, b) for a in anchor_keys for b in card_keys)


def _stem_match_5(a, b):
    """Shared 5-char stem-containment match (R41 owner, R42 v11 reuse).

    Morphology-tolerant overlap: exact match first (cheap), else a
    shared substring of 5+ chars in either direction
    (torrent/torrential, thing/nothing), with trailing-s tolerance
    (torrents/torrential). Case-sensitive — callers lowercase first.
    """
    if a == b:
        return True

    def _vars(t):
        out = {t}
        if len(t) > 5 and t.endswith("s") and not t.endswith("ss"):
            out.add(t[:-1])
        return out
    for va in _vars(a):
        for vb in _vars(b):
            if len(va) < 5 or len(vb) < 5:
                continue
            short, long = (va, vb) if len(va) <= len(vb) else (vb, va)
            if short in long:
                return True
    return False


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


# R42 v11 — cloze-suitability gates for examples (dataset + model).
# Factory-only, deterministic, stdlib + wordfreq only. Four gates, first
# failure wins with reason "cloze-<gate>":
#   archaic  — Early-Modern English words (Gemini list) fail whole-word,
#              case-insensitive. "smack" is deliberately NOT in the set:
#              it is a modern word (to hit / a loud kiss sound), not an
#              archaism, so dataset examples containing it must stay.
#   dialogue — comic/dialogue register: any of " “ ” «, or "!" more than
#              once, or "!!" / "!?" / "..." present, or more than one
#              mid-sentence Capitalized word (sentence-first tokens and
#              the pronoun "I" excluded).
#   zipf     — every alpha token len>=3 must clear a level-relative
#              wordfreq floor (A1/A2 3.5, B1 3.0, B2+ 2.5, unknown 3.0),
#              except the headword itself in any inflection (5-char stem
#              containment either direction via _stem_match_5 over
#              headword_leak_tokens — reuse, no second tokenizer).
#   density  — clue density: content tokens (alpha len>=4 outside the
#              shared _COHERENCE_STOPWORDS set — reuse, no second list)
#              over total alpha tokens >= 0.40 AND content count >= 3.
# Length 8-20 stays owned by filter_examples_by_length (reused, never
# duplicated here).
ARCHAIC_WORDS = frozenset({
    "thou", "thee", "thy", "thine", "ye", "doth", "dost", "hath",
    "hast", "wilt", "art", "canst", "shallt", "whither", "thither",
    "hither", "whence", "thence", "nay", "ere", "oft", "unto",
    "wherefore",
})
_ARCHAIC_RX = re.compile(
    r"\b(?:thou|thee|thy|thine|ye|doth|dost|hath|hast|wilt|art|"
    r"canst|shallt|whither|thither|hither|whence|thence|nay|ere|"
    r"oft|unto|wherefore)\b", re.IGNORECASE)

# R42 v11 — dialogue/comic signals (exact set, no extensions).
_DIALOGUE_CHARS = frozenset({'"', "\u201c", "\u201d", "\u00ab"})
_DIALOGUE_SUBSTRINGS = ("!!", "!?", "...")
_CAP_WORD_RX = re.compile(r"^[A-Z][a-z]+$")
_SENT_SPLIT_RX = re.compile(r"[.!?\u2026]+\s+")
_ALPHA_TOKEN_RX = re.compile(r"[A-Za-z]+")

# R42 v11 — level-relative zipf floors (unknown level fails to 3.0,
# the middle floor, stated not silent).
CLOZE_ZIPF_FLOORS = {"A1": 3.5, "A2": 3.5, "B1": 3.0, "B2": 2.5,
                     "C1": 2.5, "C2": 2.5}
CLOZE_ZIPF_DEFAULT_FLOOR = 3.0
CLOZE_DENSITY_MIN_RATIO = 0.40
CLOZE_DENSITY_MIN_COUNT = 3
CLOZE_GATES = ("archaic", "dialogue", "zipf", "density")


def cloze_archaic_ok(example):
    """R42a: True iff no ARCHAIC_WORDS whole-word hit (case-insensitive)."""
    return _ARCHAIC_RX.search(example or "") is None


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


def cloze_zipf_floor(pool_level):
    """R42c: zipf floor for a pool level (unknown -> default, stated)."""
    return CLOZE_ZIPF_FLOORS.get(
        (pool_level or "").strip().upper(), CLOZE_ZIPF_DEFAULT_FLOOR)


def cloze_zipf_ok(example, headword, kind="word", pool_level="",
                  zipf_fn=None):
    """R42c: True iff every alpha token len>=3 clears the level floor.

    The headword itself (any inflection: 5-char stem containment either
    direction over headword_leak_tokens) is excluded. zipf_fn injects
    the lookup (hermetic tests); None uses the shared _freq_zipf_single
    (wordfreq, local data — reuse, no second lookup). Unknown (None)
    readings fail OPEN to pass (missing data must never drop content).
    """
    floor = cloze_zipf_floor(pool_level)
    get = zipf_fn or _freq_zipf_single
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
        except Exception:
            value = None
        if value is None:
            continue
        if float(value) < floor:
            return False
    return True


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


def split_frozen_by_containment(item, zipf_fn=None):
    """V7 containment-release (locked A) + R31 v8 content-flag release.

    Splits dataset examples: PASSING phrase/word containment stay FROZEN
    (kept); FAILING containment are released for model replacement. R31:
    examples flagged by the appropriateness review (item["content_flags"]
    {example: reason}) join ``released`` with the content-flag reason —
    same release machinery, same growing fill need. R42 v11: containment
    survivors additionally pass the four cloze gates
    (cloze_check_example, pool_level from the item, zipf_fn injected or
    live wordfreq); cloze failures join ``released`` and record their
    "cloze-<gate>" reason on item["content_flags"] (an existing R31 flag
    always wins — never overwritten). Returns (kept, released). The
    caller grows the fill need as N_EXAMPLES - len(kept) and records
    ``released`` in completion_flags["released_containment"]; reasons
    ride on item["content_flags"] into the record.
    """
    texts = [e for e in (item.get("dataset_examples") or [])
             if isinstance(e, str) and e.strip()][:N_EXAMPLES]
    flags = item.get("content_flags")
    if not isinstance(flags, dict):
        flags = {}
        item["content_flags"] = flags
    flagged = set(flags)
    kept, released = [], []
    for text in texts:
        if text in flagged or text.strip() in flagged:
            released.append(text)
        elif example_contains_head(text, item.get("text", ""),
                                   item.get("kind") or "word"):
            ok, reason = cloze_check_example(
                text, item.get("text", ""), item.get("kind") or "word",
                item.get("pool_level", ""), zipf_fn)
            if ok:
                kept.append(text)
            else:
                released.append(text)
                if text not in flags and text.strip() not in flags:
                    flags[text] = reason
        else:
            released.append(text)
    return kept, released


COMPLETION_FIELDS = ("fa_meaning", "fa_explanation", "synonyms", "antonyms",
                     "examples", "example_translations", "grammar_tip",
                     "phonetic")


def build_completion_flags(card, released_containment=None, delta=None):
    """R8: gap-fill record {fields_filled[], sense_review, nothing_to_complete}.

    V7 containment-release: ``released_containment`` lists the dataset
    example strings released for model replacement (containment-fail);
    always recorded (empty list when nothing was released).
    R28 v8: ``delta`` (the merge report from merge_precard_delta, or None
    for legacy full-card replies) contributes the response-shape lists
    delta_filled/delta_improved/delta_kept + the kept_tamper flag. The
    pre-vs-final diff itself is still computed by us in render_diff_table.
    """
    filled = [k for k in COMPLETION_FIELDS if card.get(k)]
    flags = {"fields_filled": filled, "sense_review": True,
             "nothing_to_complete": len(filled) == len(COMPLETION_FIELDS),
             "released_containment": list(released_containment or [])}
    delta = delta or {}
    flags["delta_filled"] = list(delta.get("filled_keys") or [])
    flags["delta_improved"] = list(delta.get("improved_keys") or [])
    flags["delta_kept"] = list(delta.get("kept") or [])
    flags["kept_tamper"] = bool(delta.get("kept_tamper", False))
    return flags


def similarity_note(en_def, model_d):
    """R8: informational difflib ratio between dataset en_def and model "d"."""
    a, b = (en_def or "").strip().lower(), (model_d or "").strip().lower()
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)


# R28 v8 — token-optimized delta I/O. The model no longer echoes preserved
# pre-card values: it returns ONLY
#   {"kept": [...], "filled": {...}, "improved": {...}, "improved_flag": bool}
# and the pilot merges that delta onto the stored pre-card values in code.
# Delta field namespace (canonical card names; compact aliases accepted and
# normalized — the mirror of services.ai.ai._COMPACT_CARD_FIELDS, reused by
# import nowhere so vendored here as a pure rename table, no logic copy):
#   "phonetic" (dataset IPA string) and "examples" (dataset example strings)
# are the only pre-knowable fields. "filled" carries every other card field
# at full value, plus ONLY the missing example slots when pre-card examples
# are partial (never the frozen ones). "improved" carries corrected values
# for pre-card fields the model judges wrong (with improved_flag true).
DELTA_ALIASES = {"w": "word", "ph": "phonetic", "m": "fa_meaning",
                 "x": "fa_explanation", "s": "synonyms", "a": "antonyms",
                 "e": "examples", "t": "example_translations",
                 "g": "grammar_tip"}
# Passthrough extras the validator tolerates (read pre-validation like "d").
DELTA_EXTRAS = ("d", LITERAL_FA_KEY, "abbrev_expansion")
DELTA_CARD_FIELDS = ("word", "phonetic", "fa_meaning", "fa_explanation",
                     "synonyms", "antonyms", "examples",
                     "example_translations", "grammar_tip")

DELTA_IO_INSTRUCTION = (
    "TOKEN-SAVING DELTA OUTPUT (mandatory): the pre-card values quoted "
    "above are already stored — NEVER echo them back. Return ONLY this "
    'JSON object: {"kept": [...], "filled": {...}, "improved": {...}, '
    '"improved_flag": bool}. "kept" lists the pre-card field names you '
    'preserve exactly as given ("phonetic" and/or "examples"). "filled" '
    "carries ONLY new values for empty/missing fields (fa_meaning, "
    "fa_explanation, synonyms, antonyms, example_translations for ALL "
    "examples, grammar_tip — and, only when a pre-card example slot is "
    'still empty, the missing example strings). "improved" carries '
    "corrected values ONLY when a pre-card value is wrong (then set "
    '"improved_flag" true); otherwise {} and false. A kept field repeated '
    "inside filled/improved is discarded. Echoing a preserved pre-card "
    "value is forbidden.")

# R28 fix: the shared bot system prompt shows the FULL-card schema, so the
# model obeys it and ignores the user-side delta line (0% delta adoption in
# v8 trial). The override below is appended to the END of the system message
# (factory pilot only — the bot path is untouched): it restates that the
# full-card schema above describes CONTENT rules, but the OUTPUT envelope
# must be the delta object. System text is cacheable; output tokens are not.
DELTA_SYSTEM_OVERRIDE = (
    "OUTPUT CONTRACT OVERRIDE (factory pipeline — higher priority than the "
    "card schema above): the schema above defines CONTENT and LANGUAGE "
    "rules only. Your reply envelope MUST be exactly this JSON object and "
    'nothing else: {"kept": [...], "filled": {...}, "improved": {...}, '
    '"improved_flag": bool}. NEVER output a full card object. NEVER repeat '
    "a pre-card value you preserve — list its field name under kept. "
    "Fill ONLY empty/missing fields under filled. Correct a wrong pre-card "
    "value ONLY under improved with improved_flag true.")


def build_precard_values(item, frozen=None):
    """R28: stored pre-card values the model must NOT echo.

    {"phonetic": dataset IPA} only when ipa_src is dataset, {"examples":
    frozen kept list} only when non-empty. Missing slots stay absent —
    the model fills exactly those.
    """
    if frozen is None:
        frozen = [e for e in (item.get("dataset_examples") or [])
                  if isinstance(e, str) and e.strip()][:N_EXAMPLES]
    precard = {}
    ipa = (item.get("ipa") or "").strip()
    if item.get("ipa_src") == IPA_SRC_DATASET and ipa:
        precard["phonetic"] = ipa
    if frozen:
        precard["examples"] = list(frozen)
    return precard


def _normalize_delta_keys(mapping):
    """Canonicalize delta filled/improved keys via DELTA_ALIASES."""
    out = {}
    if not isinstance(mapping, dict):
        return out
    for key, value in mapping.items():
        if not isinstance(key, str):
            continue
        canon = DELTA_ALIASES.get(key.strip(), key.strip())
        if canon in DELTA_CARD_FIELDS or canon in DELTA_EXTRAS:
            out[canon] = value
    return out


def validate_delta_response(obj):
    """R28: validate the delta envelope.

    Returns (ok, kept, filled, improved, improved_flag, reason). kept is a
    list of pre-card field names, filled/improved are canonicalized dicts.
    Non-dict values inside filled/improved fail the envelope (fail-closed
    at the caller: next attempt/model).
    """
    if not isinstance(obj, dict):
        return False, [], {}, {}, False, "delta must be a JSON object"
    kept = obj.get("kept")
    filled = obj.get("filled")
    improved = obj.get("improved", {})
    improved_flag = obj.get("improved_flag", False)
    if not isinstance(kept, list) \
            or not all(isinstance(k, str) for k in kept):
        return False, [], {}, {}, False, "delta.kept must be a string list"
    if not isinstance(filled, dict):
        return False, [], {}, {}, False, "delta.filled must be an object"
    if not isinstance(improved, dict):
        return False, [], {}, {}, False, "delta.improved must be an object"
    if not isinstance(improved_flag, bool):
        return False, [], {}, {}, False, "delta.improved_flag must be bool"
    filled = _normalize_delta_keys(filled)
    improved = _normalize_delta_keys(improved)
    # C1: canonicalize kept too, else kept:["ph"] + filled:{"phonetic":…}
    # evades the tamper discard (alias asymmetry).
    kept = [DELTA_ALIASES.get(k.strip(), k.strip())
            for k in kept if k.strip()]
    return True, kept, filled, improved, \
        improved_flag, ""


def is_delta_response(obj):
    """R28: detect the delta shape (vs a legacy full-card reply)."""
    return isinstance(obj, dict) and "kept" in obj and "filled" in obj \
        and "word" not in obj and "w" not in obj \
        and "fa_meaning" not in obj and "m" not in obj


def merge_precard_delta(item, precard, kept, filled, improved,
                        improved_flag):
    """R28: merge a validated delta onto the stored pre-card values.

    Starts from pre-card values, applies filled then improved. A kept
    field repeated inside filled/improved is DISCARDED and reported in
    tampered (kept_tamper). Echoed frozen examples inside filled examples
    are deduped out (echoing is forbidden); the missing slots are filled
    in order. Returns (full_obj, report) where full_obj uses canonical
    card keys ready for validate_card_obj, and report carries
    kept/filled_keys/improved_keys/kept_tamper/tampered for
    build_completion_flags.
    """
    filled = dict(filled or {})
    improved = dict(improved or {})
    tampered = []
    for key in list(kept or []):
        if key in filled or key in improved:
            filled.pop(key, None)
            improved.pop(key, None)
            tampered.append(key)
    filled_keys = sorted(filled)
    improved_keys = sorted(improved)
    frozen = list((precard or {}).get("examples") or [])
    if "examples" in improved and isinstance(improved["examples"], list):
        base_examples = [e for e in improved["examples"]
                         if isinstance(e, str) and e.strip()]
    else:
        base_examples = list(frozen)
    new_examples = filled.get("examples")
    if not isinstance(new_examples, list):
        new_examples = []
    frozen_set = {e.strip() for e in base_examples}
    for cand in new_examples:
        if not isinstance(cand, str) or not cand.strip():
            continue
        if cand.strip() in frozen_set:
            continue  # echoed frozen value: forbidden, dropped
        if len(base_examples) < N_EXAMPLES:
            base_examples.append(cand.strip())
            frozen_set.add(cand.strip())
    obj = {"word": (item.get("text") or "").strip()}
    phonetic = improved.get("phonetic", filled.get(
        "phonetic", (precard or {}).get("phonetic", "")))
    obj["phonetic"] = phonetic if isinstance(phonetic, str) else ""
    obj["examples"] = base_examples
    for key in ("fa_meaning", "fa_explanation", "synonyms", "antonyms",
                "example_translations", "grammar_tip"):
        if key in improved:
            obj[key] = improved[key]
        elif key in filled:
            obj[key] = filled[key]
    for extra in DELTA_EXTRAS:
        if extra in improved:
            obj[extra] = improved[extra]
        elif extra in filled:
            obj[extra] = filled[extra]
    report = {"kept": list(kept or []), "filled_keys": filled_keys,
              "improved_keys": improved_keys,
              "kept_tamper": bool(tampered), "tampered": tampered,
              "improved_flag": bool(improved_flag)}
    return obj, report


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


def build_prompts(item, zipf_fn=None):
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
    by the anchored pre-card pool_level (R25). R28 v8: the token-saving
    delta contract (model returns ONLY kept/filled/improved/improved_flag
    — echoing preserved pre-card values is forbidden) + abbrev fill line
    when the dataset expansion is missing (R29) + a never-reuse line for
    content-flagged examples (R31).
    """
    bot_level = CEFR_TO_BOT_LEVEL[item["pool_level"]]
    system = card_prompts.custom_word_system_prompt(
        "en", bot_level, compact=card_prompts.card_output_is_compact())
    system = system + "\n\n" + DELTA_SYSTEM_OVERRIDE
    user = item["text"]
    extras = [META_LEAK_BAN, FA_DOMINANT_RULE, HEADWORD_LEAK_RULE,
              GAPFILL_INSTRUCTION, EXAMPLE_LENGTH_RULE,
              FIDELITY_INSTRUCTION, GRAMMAR_TIP_FA_RULE,
              DELTA_IO_INSTRUCTION,
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
    abbrev = (item.get("abbrev_expansion") or "").strip()
    if abbrev:
        extras.append(ABBREV_PRESERVE_INSTRUCTION + abbrev)
    elif (item.get("kind") or "word") == "word":
        extras.append(ABBREV_FILL_INSTRUCTION)
    frozen, released = split_frozen_by_containment(item, zipf_fn)
    if frozen:
        need = N_EXAMPLES - len(frozen)
        extras.append(
            "Dataset examples (FROZEN — do NOT rewrite or echo, list the "
            "field under kept): " + " | ".join(frozen))
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
            "Released examples (quality-gate fail: containment or "
            "cloze-<gate> — do NOT reuse verbatim, "
            "replace with sense-matching examples containing the headword): "
            + " | ".join(released))
    content_flags = item.get("content_flags") or {}
    # R42 v11: cloze-<gate> reasons are quality gates, not content
    # flags — the never-reuse line is for R31 appropriateness flags
    # only (a cloze release may be replaced by a similar safe example).
    flagged_here = [e for e in released
                    if e in content_flags
                    and not str(content_flags[e] or "").startswith(
                        "cloze-")]
    if flagged_here:
        extras.append(
            "Flagged examples (inappropriate for learners — never reuse "
            "or echo, replace with safe sense-matching examples): "
            + " | ".join(flagged_here))
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
                   tele_batch=0, tele_key_idx=0, cloze_zipf_fn=None):
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
    example-containment + translation-fidelity + R42 cloze-<gate> join
    the same SINGLE shared regen budget (first violation of any kind
    regenerates once; any second violation is recorded valid=False). R17/R18: sense_candidates +
    also_sense ride from the item into the record (audit, no regen).
    V7 metadata merge (code-only, no prompt change): sense_id /
    topic_vector / pool_level are re-affirmed from the item AFTER
    validation as sibling keys on the RECORD — services.ai.ai.validate_card
    tolerates unknown keys but returns a fresh dict, so they can never
    ride inside the validated card. R32 v8 extends the merge with
    pos/pos_src; R29 with abbrev_expansion; R31 with content_flags.
    R28 v8: the model returns ONLY the delta envelope
    {kept, filled, improved, improved_flag} (echoing preserved pre-card
    values is forbidden by instruction); the pilot merges it onto the
    stored pre-card values in code, discards kept-tamper alterations +
    flags them. Legacy full-card replies are still accepted (robustness:
    older transports / retry echoes fall through the unchanged path).
    """
    transport = transport or call_responses
    if model_calls is None:
        model_calls = {}
    system, user, bot_level = build_prompts(item, cloze_zipf_fn)
    # V7 containment-release (locked A): only containment-passing dataset
    # examples stay frozen; failing ones are released for model replacement
    # (the fill need in build_prompts already grows accordingly). R31 v8:
    # content-flagged examples join the same released list. R42 v11:
    # containment survivors additionally pass the cloze gates (see
    # split_frozen_by_containment) — cloze failures join released with
    # their "cloze-<gate>" reason on item["content_flags"].
    frozen, released = split_frozen_by_containment(item, cloze_zipf_fn)
    precard = build_precard_values(item, frozen)  # R28: never echoed back
    full_examples = [e for e in (item.get("dataset_examples") or [])
                     if isinstance(e, str) and e.strip()][:N_EXAMPLES]
    pos_tags = item.get("pos")
    pos_list = [t for t in (pos_tags if isinstance(pos_tags, list)
                            else ([pos_tags] if pos_tags else []))
                if isinstance(t, str) and t.strip()]
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
              "pos": pos_list, "pos_src": item.get("pos_src", "none"),
              "abbrev_expansion": (item.get("abbrev_expansion") or ""),
              "content_flags": dict(item.get("content_flags") or {}),
              "grammar_review": None,
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
            delta_report = None
            if not ok and is_delta_response(obj):
                # R28 delta path: validate the envelope, merge onto the
                # stored pre-card values in code, then validate the merged
                # full object through the REAL validator.
                dok, kept, filled, improved, improved_flag, dreason = \
                    validate_delta_response(obj)
                if not dok:
                    last_error = "validation: bad delta: %s" % dreason
                    continue
                merged_obj, delta_report = merge_precard_delta(
                    item, precard, kept, filled, improved, improved_flag)
                ok, card, reason = validate_card_obj(merged_obj, timings)
                obj = merged_obj  # passthroughs below read the merged view
            if ok:
                leaks = meta_leak_scan(card)
                model_d = obj.get(EN_DEF_COMPACT_KEY) \
                    if isinstance(obj, dict) else ""
                literal_fa = obj.get(LITERAL_FA_KEY) \
                    if isinstance(obj, dict) else ""
                abbrev = (obj.get("abbrev_expansion")
                          if isinstance(obj, dict) else "")
                if not (isinstance(abbrev, str) and abbrev.strip()):
                    abbrev = item.get("abbrev_expansion") or ""
                fa_ok = is_fa_dominant(card.get("fa_meaning", ""),
                                        card.get("fa_explanation", ""),
                                        card.get("grammar_tip", ""))
                hw_leaks = headword_leak_scan(item["text"], item["kind"],
                                              card)
                flags = build_completion_flags(card, released, delta_report)
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
                else:
                    # R42 v11: model-filled examples pass the same four
                    # cloze gates (first failing example's gate wins);
                    # joins the SAME single shared regen budget above.
                    for model_ex in (card.get("examples") or []):
                        if not isinstance(model_ex, str):
                            violation = "cloze-density"
                            break
                        ok, reason = cloze_check_example(
                            model_ex, item["text"], item["kind"],
                            item.get("pool_level", ""), cloze_zipf_fn)
                        if not ok:
                            violation = reason
                            break
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
                    record["abbrev_expansion"] = abbrev \
                        if isinstance(abbrev, str) else ""
                    return record
                # R41 v10 hard gates: REJECT (never regen), after all
                # existing gates. fa-alpha first, then sense coherence.
                allowed_terms = item.get("allowed_terms") or []
                hard_violation = ""
                if not fa_alpha_check(card,
                                      allowed_terms=allowed_terms):
                    hard_violation = "fa-alpha"
                elif not sense_coherence_check(
                        item.get("en_def", ""), card):
                    hard_violation = "sense-incoherence"
                if hard_violation:
                    record["error"] = last_error = hard_violation
                    record["reason"] = last_error
                    record["leaks"] = sorted(set(leaks))
                    record["fa_dominant"] = bool(fa_ok)
                    record["headword_leaks"] = hw_leaks
                    record["completion_flags"] = flags
                    record["similarity_note"] = sim
                    record["examples_src"] = src
                    record["long_example"] = longs
                    record["abbrev_expansion"] = abbrev \
                        if isinstance(abbrev, str) else ""
                    return record
                record.update(model_used=model, card=card, valid=True,
                              model_d=model_d if isinstance(model_d, str)
                              else "",
                              literal_fa=literal_fa
                              if isinstance(literal_fa, str) else "",
                              abbrev_expansion=abbrev
                              if isinstance(abbrev, str) else "",
                              completion_flags=flags, similarity_note=sim,
                              fa_dominant=True, headword_leaks=[],
                              examples_src=src, long_example=longs)
                # V7 metadata merge (code-only, no prompt change):
                # re-affirm sense_id / topic_vector / pool_level from the
                # item AFTER validation as sibling keys on the RECORD.
                # services.ai.ai.validate_card tolerates unknown keys but
                # returns a fresh dict (extras stripped), so metadata can
                # never ride inside the validated card itself. R32 v8 adds
                # pos/pos_src to the same merge.
                record.update(
                    sense_id=item.get("sense_id", ""),
                    topic_vector=list(item.get("topic_vector") or []),
                    pool_level=item.get("pool_level", ""),
                    pos=pos_list, pos_src=item.get("pos_src", "none"))
                return record
            last_error = "validation: %s" % reason
        # next model after exhausting attempts
    record["error"] = last_error
    record["reason"] = last_error
    return record


# R30 v8 — grammar fact-review (Muse chain, batch 16, tips are short).
# Wired as a card_pilot POST-STEP (tips exist only after generation, so a
# precard S5b stage could never see them — stated choice). Batched pass
# review_grammar_tips + resume in review_records_grammar + fail-closed
# (review infra failure keeps the original tip; a rejected tip gets 1
# focused regen of the tip field only, then the outcome is recorded).
GRAMMAR_REVIEW_BATCH = 16
GRAMMAR_REVIEW_MODELS = MODELS[:2]
GRAMMAR_REVIEW_SYS = (
    "You are an English grammar fact-checker for Persian learners. "
    "Given word/sense-gloss/tip, reply {ok:bool, problem:string}. Reject "
    "factually wrong tips (wrong affix names, wrong rules). Persian may "
    "be used in problem. Return ONLY raw JSON, no markdown fences, no "
    "commentary.")
GRAMMAR_REGEN_SYS = (
    "You rewrite a single English-grammar tip for Persian learners in "
    "Persian. Return ONLY raw JSON, no markdown fences, no commentary.")


def _grammar_review_prompt(batch):
    """Batch prompt: one KEY/word/gloss/tip block per item."""
    lines = ["Check EACH grammar tip against the word and its sense gloss.",
             'Output: {"results": [{"key": "<item key>", "ok": true/false, '
             '"problem": "<why it is wrong, or empty>"}]}.',
             "Input follows:"]
    for entry in batch:
        lines.append("KEY %s" % entry["key"])
        lines.append("word: %s" % (entry.get("text") or ""))
        lines.append("sense: %s" % ((entry.get("en_def") or "")[:200]))
        lines.append("tip: %s" % ((entry.get("grammar_tip") or "")[:500]))
    return "\n".join(lines)


def _validate_review_results(data, want_keys, key_field="key"):
    """Shared envelope check for the R30/R31 review passes.

    Returns the {key: row} mapping when every wanted key is present,
    else None (caller fails closed / retries).
    """
    if not isinstance(data, dict) or not isinstance(
            data.get("results"), list):
        return None
    by_key = {}
    for row in data["results"]:
        if isinstance(row, dict) and isinstance(row.get(key_field), str):
            by_key[row[key_field]] = row
    if set(by_key) != set(want_keys):
        return None
    return by_key


def review_grammar_tips(items, transport, api_key="", model_calls=None):
    """R30: batched grammar fact-check. Returns {key: {ok, problem, model}}.

    Muse-only chain (MODELS[:2]), batch 16, 2 attempts per model. Auth
    (401/403) aborts loudly; any other failure fails closed per item to
    {ok: True, problem: "", model: "review-fallback"} (a broken reviewer
    must never sink cards). Hermetic with an injected transport.
    """
    if model_calls is None:
        model_calls = {}
    out = {}
    for base in range(0, len(items), GRAMMAR_REVIEW_BATCH):
        batch = items[base:base + GRAMMAR_REVIEW_BATCH]
        want = [e["key"] for e in batch]
        prompt = _grammar_review_prompt(batch)
        settled = False
        for model in GRAMMAR_REVIEW_MODELS:
            for attempt in range(MAX_ATTEMPTS):
                text = prompt if attempt == 0 else REPAIR_PREFIX + prompt
                try:
                    model_calls[model] = model_calls.get(model, 0) + 1
                    raw = transport(api_key, model, GRAMMAR_REVIEW_SYS,
                                    text)
                    data = extract_json(raw)
                except AuthError:
                    raise
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        raise_for_auth(exc)
                    data = None
                except Exception:
                    data = None
                if data is None:
                    continue
                by_key = _validate_review_results(data, want)
                if by_key is None:
                    continue
                for key in want:
                    row = by_key[key]
                    ok = row.get("ok")
                    problem = row.get("problem", "")
                    out[key] = {
                        "ok": bool(ok) if isinstance(ok, bool) else True,
                        "problem": problem if isinstance(problem, str)
                        else "",
                        "model": model}
                settled = True
                break
            if settled:
                break
        if not settled:
            for key in want:
                out[key] = {"ok": True, "problem": "",
                            "model": "review-fallback"}
    return out


def regen_grammar_tip(item_text, en_def, bad_tip, problem, api_key,
                      transport, model_calls=None):
    """R30: 1 focused regen of the tip field only. Returns the new tip.

    Returns "" when the regen fails (caller keeps the original tip and
    records the outcome — fail-closed).
    """
    if model_calls is None:
        model_calls = {}
    user_text = (
        "Word: %s\nSense gloss: %s\nRejected tip: %s\nProblem: %s\n"
        "Write ONE correct short grammar tip in Persian about this word "
        "(bring English term equivalents like the production rule). "
        'Output: {"grammar_tip": "..."}.'
        % (item_text or "", (en_def or "")[:200], (bad_tip or "")[:500],
           (problem or "")[:500]))
    for model in GRAMMAR_REVIEW_MODELS:
        try:
            model_calls[model] = model_calls.get(model, 0) + 1
            raw = transport(api_key, model, GRAMMAR_REGEN_SYS, user_text)
            data = extract_json(raw)
        except AuthError:
            raise
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(
                data.get("grammar_tip"), str) \
                and data["grammar_tip"].strip():
            return data["grammar_tip"].strip()
    return ""


def _load_review_progress(path):
    """Review resume state {done:{}, failed:[]}; missing/corrupt -> empty."""
    try:
        saved = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"done": {}, "failed": []}
    if not isinstance(saved, dict):
        return {"done": {}, "failed": []}
    done = saved.get("done")
    failed = saved.get("failed")
    return {"done": done if isinstance(done, dict) else {},
            "failed": failed if isinstance(failed, list) else []}


def _save_review_progress(path, state):
    try:
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        pass


def review_records_grammar(records, api_key, transport=None, model_calls=None,
                           progress_path=None):
    """R30 post-step: fact-check valid records' tips, 1 focused regen each.

    Mutates records in place: rec["grammar_review"] = {verdict
    ok/rejected/review-error, problem, regen, model}. Resume via
    progress_path (done keys are re-applied, never re-called). Returns
    (checked, regens). Fail-closed: review errors keep the original tip.
    transport=None skips the pass entirely (hermetic tests): records are
    untouched, (0, 0) returned.
    """
    if transport is None:
        return 0, 0
    if model_calls is None:
        model_calls = {}
    state = _load_review_progress(progress_path) \
        if progress_path else {"done": {}, "failed": []}
    done = state["done"]
    todo = []
    for rec in records or []:
        card = rec.get("card") or {}
        if not rec.get("valid") or not (card.get("grammar_tip") or ""):
            continue
        key = rec.get("key") or ""
        saved = done.get(key)
        if isinstance(saved, dict) and "verdict" in saved:
            if saved.get("final_tip"):
                card["grammar_tip"] = saved["final_tip"]
            rec["grammar_review"] = saved
        else:
            todo.append(rec)
    checked = regens = 0
    for base in range(0, len(todo), GRAMMAR_REVIEW_BATCH):
        batch = todo[base:base + GRAMMAR_REVIEW_BATCH]
        try:
            verdicts = review_grammar_tips(
                [{"key": r.get("key") or "", "text": r.get("text") or "",
                  "en_def": r.get("en_def") or "",
                  "grammar_tip": (r.get("card") or {}).get(
                      "grammar_tip") or ""}
                 for r in batch],
                transport, api_key, model_calls)
        except AuthError:
            raise
        except Exception:
            verdicts = {}
        for rec in batch:
            key = rec.get("key") or ""
            card = rec.get("card") or {}
            verdict = verdicts.get(key)
            if verdict is None:
                review = {"verdict": "review-error", "problem": "",
                          "regen": False,
                          "model": "review-fallback", "final_tip": ""}
            elif verdict.get("ok"):
                review = {"verdict": "ok", "problem": "",
                          "regen": False, "model": verdict.get("model", ""),
                          "final_tip": ""}
            else:
                new_tip = ""
                try:
                    new_tip = regen_grammar_tip(
                        rec.get("text") or "", rec.get("en_def") or "",
                        card.get("grammar_tip") or "",
                        verdict.get("problem") or "", api_key, transport,
                        model_calls)
                except AuthError:
                    raise
                except Exception:
                    new_tip = ""
                if new_tip:
                    card["grammar_tip"] = new_tip
                    regens += 1
                review = {"verdict": "rejected",
                          "problem": verdict.get("problem") or "",
                          "regen": bool(new_tip),
                          "model": verdict.get("model", ""),
                          "final_tip": new_tip}
            rec["grammar_review"] = review
            done[key] = review
            checked += 1
        if progress_path:
            _save_review_progress(progress_path, state)
    return checked, regens


# R31 v8 — dataset-example content gate (same batched style as R30).
# Flagged dataset examples join released_containment with the content-flag
# reason (same release machinery: split_frozen_by_containment reads
# item["content_flags"]). Wired as a card_pilot PRE-STEP (examples are
# known before generation in both sampling and precard modes).
CONTENT_REVIEW_BATCH = 16
CONTENT_REVIEW_MODELS = MODELS[:2]
CONTENT_REVIEW_SYS = (
    "You are a content appropriateness reviewer for English learners. "
    "Given dataset example sentences, reply {flagged:bool, reason:string}. "
    "Flag sexual/creepy/offensive/age-inappropriate examples for "
    "learners. Persian may be used in reason. Return ONLY raw JSON, no "
    "markdown fences, no commentary.")


def _content_review_prompt(batch):
    """Batch prompt: one KEY block with numbered examples per item."""
    lines = ["Flag EACH dataset example that is sexual, creepy, "
             "offensive, or otherwise age-inappropriate for learners.",
             'Output: {"results": [{"key": "<item key>", '
             '"flagged": ["<exact example text>", ...], '
             '"reason": "<why, or empty>"}]}. '
             "flagged MUST quote examples exactly as given (empty when "
             "all are appropriate).",
             "Input follows:"]
    for entry in batch:
        lines.append("KEY %s" % entry["key"])
        for pos, example in enumerate(entry.get("examples") or []):
            lines.append("%d. %s" % (pos + 1, example))
    return "\n".join(lines)


def review_dataset_examples(items, transport, api_key="", model_calls=None):
    """R31: batched appropriateness review.

    items: [{key, examples[]}]. Returns {key: {flagged:[exact examples],
    reason, model}}. Flagged entries not quoting a given example exactly
    are dropped. Auth aborts loudly; anything else fails closed to
    {flagged: [], ...} (fail-open keep — a broken reviewer never drops
    dataset content).
    """
    if model_calls is None:
        model_calls = {}
    out = {}
    for base in range(0, len(items), CONTENT_REVIEW_BATCH):
        batch = items[base:base + CONTENT_REVIEW_BATCH]
        want = [e["key"] for e in batch]
        members = {e["key"]: set(e.get("examples") or []) for e in batch}
        prompt = _content_review_prompt(batch)
        settled = False
        for model in CONTENT_REVIEW_MODELS:
            for attempt in range(MAX_ATTEMPTS):
                text = prompt if attempt == 0 else REPAIR_PREFIX + prompt
                try:
                    model_calls[model] = model_calls.get(model, 0) + 1
                    raw = transport(api_key, model, CONTENT_REVIEW_SYS,
                                    text)
                    data = extract_json(raw)
                except AuthError:
                    raise
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        raise_for_auth(exc)
                    data = None
                except Exception:
                    data = None
                if data is None:
                    continue
                by_key = _validate_review_results(data, want)
                if by_key is None:
                    continue
                for key in want:
                    row = by_key[key]
                    flagged = row.get("flagged", [])
                    reason = row.get("reason", "")
                    if not isinstance(flagged, list):
                        flagged = []
                    flagged = [e for e in flagged
                               if isinstance(e, str) and e in members[key]]
                    out[key] = {
                        "flagged": flagged,
                        "reason": reason if isinstance(reason, str)
                        else "",
                        "model": model}
                settled = True
                break
            if settled:
                break
        if not settled:
            for key in want:
                out[key] = {"flagged": [], "reason": "",
                            "model": "review-fallback"}
    return out


def run_content_gate(items, api_key, transport=None, model_calls=None,
                     progress_path=None, sleep_fn=None):
    """R31 pre-step: review dataset examples, set item["content_flags"].

    {example: reason} per item; flagged examples are released by
    split_frozen_by_containment when generate_card runs. Resume via
    progress_path. Returns (flagged_total,). Fail-open: review errors
    keep every example (never silent — failed keys recorded).
    transport=None skips the gate entirely (hermetic tests / dry runs):
    items only get the default empty content_flags.
    """
    if transport is None:
        for item in items or []:
            item.setdefault("content_flags", {})
        return (0,)
    if model_calls is None:
        model_calls = {}
    sleep_fn = sleep_fn or time.sleep
    state = _load_review_progress(progress_path) \
        if progress_path else {"done": {}, "failed": []}
    done = state["done"]
    todo = [i for i in items or []
            if [e for e in (i.get("dataset_examples") or [])
                if isinstance(e, str) and e.strip()]
            and item_key(i) not in done]
    flagged_total = 0
    for base in range(0, len(todo), CONTENT_REVIEW_BATCH):
        batch = todo[base:base + CONTENT_REVIEW_BATCH]
        try:
            verdicts = review_dataset_examples(
                [{"key": item_key(i),
                  "examples": [e for e in (i.get("dataset_examples") or [])
                               if isinstance(e, str) and e.strip()]}
                 for i in batch],
                transport, api_key, model_calls)
        except AuthError:
            raise
        except Exception:
            verdicts = {}
        for item in batch:
            key = item_key(item)
            verdict = verdicts.get(key) or {}
            flags = {e: (verdict.get("reason") or "content-flag")
                     for e in (verdict.get("flagged") or [])}
            item["content_flags"] = flags
            done[key] = {"flagged": sorted(flags),
                         "reason": verdict.get("reason") or "",
                         "model": verdict.get("model") or "review-fallback"}
            if not verdict:
                state["failed"].append(key)
            flagged_total += len(flags)
        if progress_path:
            _save_review_progress(progress_path, state)
        if base + CONTENT_REVIEW_BATCH < len(todo):
            sleep_fn(CALL_SLEEP)
    for item in items or []:
        item.setdefault("content_flags", {})
    return (flagged_total,)


# R36 v9 — inflection judge (batched LLM micro-pass, Muse chain).
# Items whose anchor gloss is an inflection stub ("plural of X", "past
# of X", ...) are reviewed: keep IFF the inflected form has its own
# learner value (irregulars, common usage as a headword), else drop in
# favor of the base lemma. Same conventions as the R30/R31 review
# passes (MODELS[:2], 2 attempts, repair prefix, hermetic with an
# injected transport). Fail-closed: any error keeps the item (never
# drop on uncertainty) with the review-uncertain flag.
INFLECTION_REVIEW_BATCH = 16
INFLECTION_REVIEW_MODELS = MODELS[:2]
INFLECTION_REVIEW_SYS = (
    "You are an English learner-dictionary editor for Persian learners. "
    "Given an inflected word form and its dictionary gloss, reply "
    "{keep:bool, reason:string}. Keep IFF the inflected form has its own "
    "learner value as a headword: irregular forms, or forms commonly "
    "looked up/used as headwords. Otherwise drop it in favor of the base "
    "lemma (regular plurals, regular past tenses, plain comparatives). "
    "Persian may be used in reason. Return ONLY raw JSON, no markdown "
    "fences, no commentary.")
INFLECTION_UNCERTAIN_TAG = "review-uncertain"


def _inflection_review_prompt(batch):
    """Batch prompt: one KEY/word/gloss block per item."""
    lines = ["Judge EACH inflected form against its dictionary gloss.",
             'Output: {"results": [{"key": "<item key>", '
             '"keep": true/false, "reason": "<why>"}]}.',
             "Input follows:"]
    for entry in batch:
        lines.append("KEY %s" % entry["key"])
        lines.append("word: %s" % (entry.get("text") or ""))
        lines.append("gloss: %s" % ((entry.get("gloss") or "")[:200]))
    return "\n".join(lines)


def inflection_review(items, transport, api_key="", model_calls=None):
    """R36: batched inflection-form review.

    items: [{key, text, gloss}]. Returns {key: {keep:bool, reason:str,
    model:str, uncertain:bool}}. keep=False only on an explicit LLM
    drop verdict; every failure (transport error, bad JSON, envelope
    mismatch) fails closed to {keep: True, uncertain: True} flagged
    review-uncertain (never drop on uncertainty). Auth aborts loudly.
    Hermetic with an injected transport.
    """
    if model_calls is None:
        model_calls = {}
    out = {}
    for base in range(0, len(items or []), INFLECTION_REVIEW_BATCH):
        batch = items[base:base + INFLECTION_REVIEW_BATCH]
        want = [e["key"] for e in batch]
        prompt = _inflection_review_prompt(batch)
        settled = False
        for model in INFLECTION_REVIEW_MODELS:
            for attempt in range(MAX_ATTEMPTS):
                text = prompt if attempt == 0 else REPAIR_PREFIX + prompt
                try:
                    model_calls[model] = model_calls.get(model, 0) + 1
                    raw = transport(api_key, model,
                                    INFLECTION_REVIEW_SYS, text)
                    data = extract_json(raw)
                except AuthError:
                    raise
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        raise_for_auth(exc)
                    data = None
                except Exception:
                    data = None
                if data is None:
                    continue
                by_key = _validate_review_results(data, want)
                if by_key is None:
                    continue
                rows_ok = True
                for key in want:
                    row = by_key[key]
                    keep = row.get("keep")
                    reason = row.get("reason", "")
                    if not isinstance(keep, bool):
                        rows_ok = False
                        break
                    out[key] = {
                        "keep": keep,
                        "reason": reason if isinstance(reason, str)
                        else "",
                        "model": model, "uncertain": False}
                if not rows_ok:
                    out = {k: v for k, v in out.items() if k not in want}
                    continue
                settled = True
                break
            if settled:
                break
        if not settled:
            for key in want:
                if key not in out:
                    out[key] = {"keep": True, "reason": "review-error",
                                "model": "review-fallback",
                                "uncertain": True}
    return out


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
# R28 v8: delta-state chip (kept/filled/improved) keyed by the
# completion_flags delta lists; colors come from the R33 op color system
# (.op.kept green / .op.filled blue / .op.improved amber).
_OP_STATE_CHIP = {"kept": (OP_KEEP, "kept"), "filled": (OP_MODEL, "filled"),
                  "improved": (OP_REVIEW, "improved")}
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


def _op_chip_named(op, cls):
    """Bidi-safe op chip for an explicit (label, class) pair."""
    if " " in op:
        fa, en = op.split(" ", 1)
        inner = '%s <span class="en">%s</span>' % (esc(fa), esc(en))
    else:
        inner = esc(op)
    return '<span class="op %s">%s</span>' % (cls, inner)


def _delta_op_state(rec, field_key):
    """R28: delta op state for one card field (kept/filled/improved/"")."""
    if not field_key:
        return ""
    flags = rec.get("completion_flags") or {}
    if field_key in (flags.get("delta_improved") or []):
        return "improved"
    if field_key in (flags.get("delta_filled") or []):
        return "filled"
    if field_key in (flags.get("delta_kept") or []):
        return "kept"
    return ""


def _op_chip_released():
    """V7 containment-release op chip (bidi-safe: Latin part isolated).

    The full "آزادشده (containment)" string rides in the title attribute
    so gallery scans find it verbatim; the visible label keeps the
    R14 split-run convention.
    """
    return ('<span class="op review" title="%s">%s '
            '<span class="en">%s</span></span>'
            % (esc(OP_RELEASED), esc("آزادشده"), esc("(containment)")))


def _op_chip_cloze(reason):
    """R42 v11 cloze-release op chip (bidi-safe: Latin part isolated).

    ``reason`` is the "cloze-<gate>" string: it rides verbatim in the
    title attribute (gallery scans) and as the visible Latin run, next
    to the Persian "آزادشده" label.
    """
    label = "(%s)" % (reason or "cloze-?")
    return ('<span class="op review" title="%s">%s '
            '<span class="en">%s</span></span>'
            % (esc(reason or "cloze-?"), esc("آزادشده"), esc(label)))


def _cloze_release_reason(content_flags, pre_text):
    """R42 v11: "cloze-<gate>" reason for a released pre-card example.

    Reads item["content_flags"] (the shared release-machinery reason
    map); "" when the example was released for another reason.
    """
    flags = content_flags if isinstance(content_flags, dict) else {}
    reason = flags.get(pre_text, "")
    if not reason and isinstance(pre_text, str):
        reason = flags.get(pre_text.strip(), "")
    if isinstance(reason, str) and reason.startswith("cloze-"):
        return reason
    return ""


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
              match=False, pre_src="", final_src="", op_html=None,
              op_state=""):
    """R14: one field row — label line, pre-card, operation, final.

    ``op_html`` overrides the computed chip (V7 containment-release rows
    pass the آزادشده chip for released pre-card examples). R28 v8:
    ``op_state`` (kept/filled/improved from the delta lists) overrides
    the heuristic chip with the v8 delta chip.
    """
    if op_html is None and op_state in _OP_STATE_CHIP:
        op_label, op_cls = _OP_STATE_CHIP[op_state]
        op_html = _op_chip_named(op_label, op_cls)
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
    # release op chip instead of the keep/review chip. R42 v11:
    # cloze-gate releases render the cloze-<gate> chip (reason from
    # rec["content_flags"], same release machinery).
    released_set = {
        (e.strip() if isinstance(e, str) else "")
        for e in ((rec.get("completion_flags") or {})
                  .get("released_containment") or [])}
    cloze_flags = rec.get("content_flags") or {}
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
                  card.get("fa_meaning") or "", "rtl",
                  op_state=_delta_op_state(rec, "fa_meaning")),
        _diff_row("توضیح فارسی", "", "rtl",
                  card.get("fa_explanation") or "", "rtl",
                  op_state=_delta_op_state(rec, "fa_explanation")),
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
                  if fin_ipa else "",
                  op_state=_delta_op_state(rec, "phonetic")),
    ]
    examples_state = _delta_op_state(rec, "examples")
    trans_state = _delta_op_state(rec, "example_translations")
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
        if pre.strip() and pre.strip() in released_set:
            cloze_reason = _cloze_release_reason(cloze_flags, pre.strip())
            released_chip = (_op_chip_cloze(cloze_reason)
                             if cloze_reason else _op_chip_released())
        else:
            released_chip = None
        rows.append(_diff_row("مثال %d" % (pos + 1), pre, "ltr",
                              fin_cell, "ltr", match=match,
                              pre_src=IPA_SRC_DATASET if pre else "",
                              final_src=fin_src, op_html=released_chip,
                              op_state="" if released_chip is not None
                              else examples_state))
        if fin and translation:
            rows.append(_diff_row("ترجمه مثال %d" % (pos + 1), "", "rtl",
                                  translation, "rtl",
                                  op_state=trans_state))
    rows.append(_diff_row("مترادف‌ها", "", "ltr",
                          ", ".join(card.get("synonyms") or []), "ltr",
                          op_state=_delta_op_state(rec, "synonyms")))
    rows.append(_diff_row("متضادها", "", "ltr",
                          ", ".join(card.get("antonyms") or []), "ltr",
                          op_state=_delta_op_state(rec, "antonyms")))
    rows.append(_diff_row("نکته گرامری", "", "rtl",
                          card.get("grammar_tip") or "", "rtl",
                          op_state=_delta_op_state(rec, "grammar_tip")))
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
    # R32 v8: dataset POS chip row (anchored entry POS first, 1-3 tags;
    # rec["pos"] may be a list (v8) or a legacy pool string).
    pos_row = ""
    pos_raw = rec.get("pos")
    pos_tags = [t.strip() for t in (
        pos_raw if isinstance(pos_raw, list)
        else ([pos_raw] if pos_raw else []))
        if isinstance(t, str) and t.strip()][:3]
    if pos_tags:
        pos_chips = " ".join(
            '<span class="tchip">%s</span>' % esc(t) for t in pos_tags)
        pos_src = (rec.get("pos_src") or "").strip()
        if pos_src:
            pos_chips += ' <span class="srctag"><span class="en">[%s]</span></span>' % esc(pos_src)
        pos_row = ('<div class="dh-row"><div class="dh-label" dir="rtl" '
                   'lang="fa">نقش دستوری</div>'
                   '<div class="blk" dir="ltr" lang="en">%s</div></div>'
                   % pos_chips)
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
        "%s%s"
        '<div class="dh-row"><div class="dh-label" dir="rtl" lang="fa">'
        "مدل</div>%s</div>"
        '<div class="dh-row chips-row">%s</div>'
        "</div>"
        % (_blk_en(sense_id if sense_id else "—"),
           _blk_en(en_def if en_def else "—"),
           _blk_en("[%s]" % en_source) if en_source else "",
           cand_row, also_row,
           _topic_chips_html(rec),
           pos_row, type_row,
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
        ":root{--ink:#241f18;--muted:#6f6455;--line:#d8cbb4;"
        "--paper:#efe7d8;--card:#f6f0e3;--soft:#e7dcc6;--accent:#8a5a2b;"
        "--kept:#33602a;--kept-soft:#dcebd3;"
        "--filled:#2f5b88;--filled-soft:#dbe7f4;"
        "--improved:#7c5515;--improved-soft:#f5e8cb;"
        "--error:#8f2f2f;--error-soft:#f4dbdb;"
        "--taggray:#6b6b6b;--taggray-soft:#e3e0d8;--radius:12px;}\n"
        "*{box-sizing:border-box;}\n"
        "body{font-family:Vazirmatn,\"Segoe UI\",Tahoma,sans-serif;margin:0;"
        "color:var(--ink);line-height:2.1;background:var(--paper);}\n"
        ".wrap{max-width:920px;margin:0 auto;padding:0 1.4em 4em;}\n"
        "nav.top{position:sticky;top:0;background:var(--paper);"
        "border-bottom:1px solid var(--line);padding:.7em 1.4em;z-index:10;"
        "display:flex;gap:1em;flex-wrap:wrap;}\n"
        "nav.top a{color:var(--accent);text-decoration:none;font-size:.85em;}\n"
        "nav.top a:hover{text-decoration:underline;}\n"
        "nav.top a:focus-visible{outline:2px solid var(--accent);"
        "outline-offset:2px;}\n"
        "@media (max-width:640px){nav.top{position:static;display:flex;"
        "flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;"
        "padding:.5em;}nav.top a{flex-shrink:0;white-space:nowrap;}}\n"
        "h1{font-size:1.6em;margin:1.4em 0 .4em;}\n"
        "h2{font-size:1.2em;margin-top:1.8em;margin-bottom:.6em;}\n"
        "h3{font-size:1.05em;margin-top:2em;margin-bottom:.8em;"
        "border-bottom:2px solid var(--accent);padding-bottom:.4em;}\n"
        "section.card h3{font-size:1em;margin-top:1.8em;}\n"
        ".en{direction:ltr;unicode-bidi:isolate;"
        "font-family:Consolas,monospace;font-size:.88em;}\n"
        ".nums{font-variant-numeric:tabular-nums;direction:ltr;"
        "unicode-bidi:isolate;}\n"
        ".card{border:1px solid var(--line);border-radius:var(--radius);"
        "padding:1.4em 1.6em;margin:1.8em 0;background:var(--card);}\n"
        ".badge{border-radius:4px;padding:0.15em 0.6em;font-size:0.85em;}\n"
        ".ok{background:var(--kept-soft);color:var(--kept);} "
        ".bad{background:var(--error-soft);color:var(--error);}\n"
        ".chip{display:inline-block;font-size:.8em;border-radius:20px;"
        "padding:.15em .9em;white-space:nowrap;}\n"
        ".chip.done{background:var(--kept-soft);color:var(--kept);"
        "border:1px solid var(--kept);}\n"
        ".chip.pass{background:var(--card);color:var(--accent);"
        "border:1px solid var(--accent);}\n"
        ".chip.open{background:var(--improved-soft);color:var(--improved);"
        "border:1px solid var(--improved);}\n"
        ".tchip{display:inline-block;font-size:.82em;border-radius:20px;"
        "padding:.15em .9em;border:1px solid var(--line);"
        "background:var(--soft);}\n"
        ".tchip.primary{border-color:var(--accent);color:var(--accent);"
        "font-weight:700;}\n"
        ".blk{margin:.3em 0;overflow-wrap:anywhere;}\n"
        ".blk.empty{color:var(--muted);}\n"
        ".blk.lead{font-size:1.2em;}\n"
        ".fld-label{font-weight:700;margin-top:1em;}\n"
        ".srctag{font-size:.78em;color:var(--taggray);}\n"
        ".srctag .en{background:var(--taggray-soft);border-radius:4px;"
        "padding:0 .4em;}\n"
        ".strip{border:1px solid var(--line);border-radius:var(--radius);"
        "padding:1em 1.2em;margin:1.2em 0;background:var(--card);}\n"
        ".srow{margin:.7em 0;}\n"
        ".slabel{font-weight:700;margin-bottom:.3em;}\n"
        ".sblocks{display:flex;flex-wrap:wrap;gap:.4em 1.2em;}\n"
        ".dhead{border:1px solid var(--line);border-radius:var(--radius);"
        "padding:1em 1.2em;margin:1.2em 0;background:var(--soft);}\n"
        ".dh-row{display:flex;flex-wrap:wrap;gap:.4em 1.2em;"
        "align-items:baseline;margin:.5em 0;}\n"
        ".dh-label{font-weight:700;min-width:5em;}\n"
        ".chips-row{display:flex;flex-wrap:wrap;gap:.5em;}\n"
        ".dh-row.also{font-size:.9em;color:var(--muted);}\n"
        ".diff{display:grid;gap:.5em;margin:1.2em 0;}\n"
        ".diff-row{display:grid;grid-template-columns:7em 1fr auto 1fr;"
        "gap:.8em;align-items:start;border-bottom:1px dashed var(--line);"
        "padding:.6em 0;}\n"
        ".diff-row:nth-child(even){background:rgba(255,255,255,.28);}\n"
        ".diff-head{font-weight:700;border-bottom:2px solid var(--line);}\n"
        ".diff-label{font-weight:700;}\n"
        ".diff-pre,.diff-fin{min-width:0;}\n"
        ".op{display:inline-block;font-size:.78em;border-radius:20px;"
        "padding:.15em .8em;white-space:nowrap;border:1px solid var(--line);}\n"
        ".op.keep,.op.kept{background:var(--kept-soft);color:var(--kept);"
        "border-color:var(--kept);}\n"
        ".op.model,.op.filled{background:var(--filled-soft);"
        "color:var(--filled);border-color:var(--filled);}\n"
        ".op.review,.op.improved{background:var(--improved-soft);"
        "color:var(--improved);border-color:var(--improved);}\n"
        ".op.error{background:var(--error-soft);color:var(--error);"
        "border-color:var(--error);}\n"
        ".op.none{color:var(--muted);}\n"
        "@media (max-width: 600px){"
        ".diff-row{grid-template-columns:1fr;gap:.3em;}"
        ".diff-head{display:none;}"
        ".card{padding:1em;}}\n"
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
        pos_raw = rec.get("pos", "")
        pos_list = [t for t in (pos_raw if isinstance(pos_raw, list)
                                else ([pos_raw] if pos_raw else []))
                    if isinstance(t, str) and t.strip()]
        items.append({
            "kind": rec.get("kind") or "word",
            "text": text,
            "pos": pos_list,
            "pos_src": rec.get("pos_src", "none"),
            "abbrev_expansion": rec.get("abbrev_expansion") or "",
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


# Sentinel for main() review transports: _DEFAULT means the real
# call_responses leg; None means skip the gate (hermetic tests).
_DEFAULT_REVIEW_TRANSPORT = object()


def main(argv=None, _content_transport=_DEFAULT_REVIEW_TRANSPORT,
         _grammar_transport=_DEFAULT_REVIEW_TRANSPORT):
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
    # R31 v8 content gate (pre-step): batched appropriateness review of
    # dataset examples; flagged examples land in item["content_flags"] and
    # are released by split_frozen_by_containment at generate time. Resume
    # via content_review_progress.json; fail-open keep on review errors.
    run_logger.stage_start("content-gate")
    try:
        flagged_n, = run_content_gate(
            sample, api_key,
            transport=(call_responses
                       if _content_transport is _DEFAULT_REVIEW_TRANSPORT
                       else _content_transport),
            progress_path=out_dir / "content_review_progress.json",
            model_calls=model_calls)
    except AuthError:
        raise
    except Exception:
        flagged_n = 0
    run_logger.stage_end("content-gate", ok=len(sample), fail=flagged_n)
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
    # R30 v8 grammar fact-review (post-step): batched check of valid
    # records' tips; rejected tips get 1 focused regen of the tip field
    # only, then the outcome is recorded on rec["grammar_review"].
    # Resume via review_grammar_progress.json; fail-closed (original tip
    # kept on review errors).
    run_logger.stage_start("grammar-review")
    try:
        checked_n, regens_n = review_records_grammar(
            records, api_key,
            transport=(call_responses
                       if _grammar_transport is _DEFAULT_REVIEW_TRANSPORT
                       else _grammar_transport),
            progress_path=out_dir / "review_grammar_progress.json",
            model_calls=model_calls)
    except AuthError:
        raise
    except Exception:
        checked_n, regens_n = 0, 0
    run_logger.stage_end("grammar-review", ok=checked_n, fail=regens_n)
    for item in sample:
        key = item_key(item)
        if key in done:
            done[key] = next(
                (r for r in records if r.get("key") == key), done[key])
    prog_path.write_text(json.dumps(
        {"done": done, "failed": [k for k, v in done.items() if not v.get("valid")],
         "model_calls": model_calls}, ensure_ascii=False), encoding="utf-8")
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
