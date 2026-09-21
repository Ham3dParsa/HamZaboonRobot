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
LEGACY_STAGE_CODES = ("s0", "s0b", "s1", "s2", "s3", "s4", "s5")

# Canonical domain names, one per stage. New code, logs, console,
# telemetry, and files speak these.
STAGE_NAMES = {
    "s0": "preprocess",
    "s0b": "inflection-review",
    "s1": "anchor",
    "s2": "sense-judge",
    "s3": "vectors",
    "s4": "topic-label",
    "s5": "enrich",
}

# Finglish console tags, ASCII-only (Windows terminal safe). Console
# shows "name (finglish)", e.g. "inflection-review (Barresie-Sarf)".
STAGE_FINGLESH = {
    "s0": "PishPardazesh",
    "s0b": "Barresie-Sarf",
    "s1": "Langar",
    "s2": "Davarie-Mana",
    "s3": "Bordar",
    "s4": "Barchasbe-Mozu'",
    "s5": "GhaniSazi",
}

# New on-disk progress filenames (T2 writes these; old files are read
# only as a resume fallback and never written again).
STAGE_FILES = {
    "s0": "preprocess.json",
    "s0b": "inflection-review.json",
    "s1": "anchor.json",
    "s2": "sense-judge.json",
    "s3": "vectors.json",
    "s4": "topic-label.json",
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
    "R22-R25": "pipeline-range-rule",
    "R29": "abbrev-expansion-rule",
    "R32": "pos-carrier-rule",
    "R34": "cross-reference-rule",
    "R35": "level-aware-zipf-rule",
    "R36": "inflection-review-rule",
    "R42": "cloze-suitability-rule",
    "R44": "superlative-redirect-rule",
}

RULE_SENTENCES = {
    "R4": "Proper-noun lemmas are name-only and never become cards.",
    "R20": "Words below the zipf floor drop unless academically tagged.",
    "R22-R25": "Locked end-to-end sample-to-precard pipeline range.",
    "R29": "Abbreviation expansions parse dataset-first from the gloss.",
    "R32": "POS carriers (pos/pos_src) come from the anchored entry.",
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
    "r4-country-blocklist",
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
    "anchor-name-gloss",
    "vulgar-anchor",
    "no-real-def",
    "inflection-drop",
    "inflection-keep",
    "superlative-redirect",
    "review-error",
    "review-uncertain",
    "review-has-independent-sense",
    "not-inflection",
    "s0b-no-transport",
    "s1-fallback",
    "failed-no-entry",
    "cloze-archaic",
    "cloze-dialogue",
    "cloze-zipf",
    "cloze-density",
    "type-pending",
    "g7-nonlatin",
    "brand-product",
)

# --- Read shims (old -> new; new code writes new, reads old) ---

# Old stage id -> domain name (progress resume, telemetry backfill).
LEGACY_OLD_STAGE_TO_NEW = dict(STAGE_NAMES)

# Domain name -> old stage id (accept names where ids were required).
# Legacy v13 short names stay accepted (read shim, never written).
LEGACY_NEW_STAGE_TO_OLD = {name: sid for sid, name in STAGE_NAMES.items()}
LEGACY_NEW_STAGE_TO_OLD.update({
    "inflection": "s0b",
    "judge": "s2",
    "label": "s4",
})

# Old progress filename -> new filename (prefer new, fallback old).
# Intermediate v13 names (inflection/judge/label.json) sit in the chain
# too: resume walks new -> intermediate -> sX.json, oldest last.
LEGACY_OLD_PROGRESS_FILE_TO_NEW = {
    "s0.json": "preprocess.json",
    "s0b.json": "inflection-review.json",
    "s1.json": "anchor.json",
    "s2.json": "sense-judge.json",
    "s3.json": "vectors.json",
    "s4.json": "topic-label.json",
    "s5.json": "enrich.json",
    "s4_topup_cache.json": "label_topup_cache.json",
    "inflection.json": "inflection-review.json",
    "judge.json": "sense-judge.json",
    "label.json": "topic-label.json",
}

# Old gate id -> domain slug (log/telemetry backfill).
LEGACY_OLD_GATE_TO_NEW = dict(GATE_NAMES)

# Old/new on-disk names of the S4 label top-up cache (T2 reads the old
# name as a resume fallback and writes the new one; callers import these
# so neither literal is embedded outside this module).
TOPUP_OLD_NAME = "s4_topup_cache.json"
TOPUP_NEW_NAME = LEGACY_OLD_PROGRESS_FILE_TO_NEW[TOPUP_OLD_NAME]


def stage_label(stage):
    """Console label: domain name + Finglish tag, ASCII-only."""
    name = STAGE_NAMES.get(stage)
    if name is None:
        return stage
    return "%s (%s)" % (name, STAGE_FINGLESH.get(stage, stage))
