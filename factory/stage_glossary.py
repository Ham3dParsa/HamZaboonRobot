"""Precard naming glossary (v13 coherence, ticket T1).

SOLE owner of the old-code <-> domain-name mapping for the precard
line. Human-readable language lives here; every other module keeps
working on old ids until its own rename ticket migrates it over.

Contract: .opencode/plans/lexicon/plan-v13-coherence.md (LOCKED).
Rules honored here: English-only identifiers/comments (Finglish display
tags are ASCII data, never code words), ASCII slugs, and one sentence
per G-gate / live R-rule.

NOTHING imports this yet (T1 is additive-only on purpose — a parallel
agent owns the neighboring seam). Later tickets migrate callers:
T2 on-disk progress files, T4 telemetry keys, T5 reason slugs.
"""

# Old stage ids, kept as history + shim keys (never emitted anywhere
# a human looks after the rename tickets land).
STAGE_IDS = ("s0", "s0b", "s1", "s2", "s3", "s4", "s5")

# Canonical domain names, one per stage. New code, logs, console,
# telemetry, and files speak these.
STAGE_NAMES = {
    "s0": "preprocess",
    "s0b": "inflection",
    "s1": "anchor",
    "s2": "judge",
    "s3": "vectors",
    "s4": "label",
    "s5": "enrich",
}

# Finglish console tags, ASCII-only (Windows terminal safe). Console
# shows "name (finglish)", e.g. "inflection (sarf)".
STAGE_FINGLESH = {
    "s0": "pishpardazesh",
    "s0b": "sarf",
    "s1": "langar",
    "s2": "davari",
    "s3": "bordar",
    "s4": "barchasb",
    "s5": "ghanasazi",
}

# New on-disk progress filenames (T2 writes these; old files are read
# only as a resume fallback and never written again).
STAGE_FILES = {
    "s0": "preprocess.json",
    "s0b": "inflection.json",
    "s1": "anchor.json",
    "s2": "judge.json",
    "s3": "vectors.json",
    "s4": "label.json",
    "s5": "enrich.json",
}

# Gate ids (G1-G6) -> domain slug + one-line rule sentence each.
GATE_NAMES = {
    "G1": "case-fold-gate",
    "G2": "inflection-form-gate",
    "G3": "interjection-gate",
    "G4": "abbreviation-gate",
    "G5": "demonym-gate",
    "G6": "obsolete-gate",
}

GATE_RULES = {
    "G1": "Fold case in the sample builder so lookups match any casing.",
    "G2": "Drop entries whose every gloss is a mechanical inflection reference.",
    "G3": "Drop interjection-only entries; they carry no flashcard value.",
    "G4": "Drop all-caps/multi-sense abbreviations; quarantine lone suspects.",
    "G5": "Drop demonym/geo adjective glosses until the travel phase owns them.",
    "G6": "Drop entries whose every sense is tagged obsolete.",
}

# Live R-rules referenced on the precard path + one-line sentences.
RULE_NAMES = {
    "R4": "proper-noun-rule",
    "R20": "zipf-floor-rule",
    "R34": "cross-reference-rule",
    "R35": "level-aware-zipf-rule",
    "R36": "inflection-review-rule",
    "R42": "cloze-suitability-rule",
    "R44": "superlative-redirect-rule",
}

RULE_SENTENCES = {
    "R4": "Proper-noun lemmas are name-only and never become cards.",
    "R20": "Words below the zipf floor drop unless academically tagged.",
    "R34": "Cross-reference stubs resolve through the target entry.",
    "R35": "Zipf floors relax by pool level (C1/C2 may be rarer).",
    "R36": "Inflection-stub anchors go to the batched LLM micro-pass.",
    "R42": "Examples must pass the four cloze gates (archaic/dialogue/zipf/density).",
    "R44": "Superlative-pattern stubs redirect onto a real base lemma.",
}

# Canonical drop/keep reason slugs (T5 renames the log surface to these;
# values after a colon, e.g. "r20-zipf-low:2.10", are measurements).
REASON_SLUGS = (
    "r4-name-only",
    "r20-zipf-low",
    "applied-keep-false",
    "zipf-unknown-kept",
    "g2-inflection-form",
    "g3-interjection",
    "g4-abbrev",
    "g5-demonym",
    "g6-obsolete",
    "quarantine-g4-abbrev",
    "pick-proper-noun",
    "anchor-proper-noun",
    "inflection-drop",
    "superlative-redirect",
    "review-uncertain",
    "not-inflection",
    "s0b-no-transport",
    "s1-fallback",
    "failed-no-entry",
    "cloze-archaic",
    "cloze-dialogue",
    "cloze-zipf",
    "cloze-density",
    "type-pending",
)

# --- Read shims (old -> new; new code writes new, reads old) ---

# Old stage id -> domain name (progress resume, telemetry backfill).
OLD_STAGE_TO_NEW = dict(STAGE_NAMES)

# Domain name -> old stage id (accept names where ids were required).
NEW_STAGE_TO_OLD = {name: sid for sid, name in STAGE_NAMES.items()}

# Old progress filename -> new filename (prefer new, fallback old).
OLD_PROGRESS_FILE_TO_NEW = {
    "s0.json": "preprocess.json",
    "s0b.json": "inflection.json",
    "s1.json": "anchor.json",
    "s2.json": "judge.json",
    "s3.json": "vectors.json",
    "s4.json": "label.json",
    "s5.json": "enrich.json",
    "s4_topup_cache.json": "label_topup_cache.json",
}

# Old gate id -> domain slug (log/telemetry backfill).
OLD_GATE_TO_NEW = dict(GATE_NAMES)


def normalize_stage(pick):
    """Stage id from an old id or a domain name (case-insensitive).

    Both directions resolve here: "s2" -> "s2" and "judge" -> "s2".
    Unknown input passes through untouched (callers fail closed).
    """
    key = (pick or "").strip().lower()
    if key in STAGE_IDS:
        return key
    return NEW_STAGE_TO_OLD.get(key, pick)


def stage_label(stage):
    """Console label: domain name + Finglish tag, ASCII-only."""
    name = STAGE_NAMES.get(stage)
    if name is None:
        return stage
    return "%s (%s)" % (name, STAGE_FINGLESH.get(stage, stage))
