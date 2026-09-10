"""Tests for factory/stage_glossary.py (v13 T1, additive-only)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "factory"))

import stage_glossary as g


def test_stage_ids_match_names_both_directions():
    assert set(g.STAGE_IDS) == set(g.STAGE_NAMES)
    for sid in g.STAGE_IDS:
        name = g.STAGE_NAMES[sid]
        assert g.NEW_STAGE_TO_OLD[name] == sid
        assert g.OLD_STAGE_TO_NEW[sid] == name


def test_normalize_stage_old_id_direction():
    for sid in g.STAGE_IDS:
        assert g.normalize_stage(sid) == sid
        assert g.normalize_stage(sid.upper()) == sid


def test_normalize_stage_new_name_direction():
    for sid in g.STAGE_IDS:
        name = g.STAGE_NAMES[sid]
        assert g.normalize_stage(name) == sid
        assert g.normalize_stage(name.upper()) == sid


def test_normalize_stage_unknown_passes_through():
    assert g.normalize_stage("nope") == "nope"
    assert g.normalize_stage(" Nope ") == "nope"
    assert g.normalize_stage("") == ""
    assert g.normalize_stage(None) == ""
    assert g.normalize_stage(5) == 5


def test_gates_have_names_and_sentences():
    assert set(g.GATE_NAMES) == {"G1", "G2", "G3", "G4", "G5", "G6"}
    for gid, slug in g.GATE_NAMES.items():
        assert slug.isascii() and " " not in slug
        sentence = g.GATE_RULES[gid]
        assert sentence and sentence.isascii()
        assert g.OLD_GATE_TO_NEW[gid] == slug


def test_rules_have_names_and_sentences():
    assert set(g.RULE_NAMES) == set(g.RULE_SENTENCES)
    assert {"R4", "R20", "R22-R25", "R29", "R32", "R34", "R36", "R42"} <= set(
        g.RULE_NAMES)
    for rid, slug in g.RULE_NAMES.items():
        assert slug.isascii() and " " not in slug
        assert g.RULE_SENTENCES[rid].isascii()


def test_reason_slugs_ascii_and_unique():
    assert len(set(g.REASON_SLUGS)) == len(g.REASON_SLUGS)
    for slug in g.REASON_SLUGS:
        assert slug.isascii() and " " not in slug


def test_reason_slugs_cover_pipeline_literals():
    """Every drop/keep slug the pipeline actually emits (reason/dropped
    assignments, measured r20/applied-keep bases, G-gate returns, cloze
    gates) must exist in REASON_SLUGS — the T5 log rename has no gaps."""
    import re

    here = os.path.dirname(__file__)
    with open(os.path.join(here, "..", "factory", "precard_pipeline.py"),
              encoding="utf-8") as handle:
        src = handle.read()
    emitted = set(re.findall(r'\["(?:reason|dropped)"\]\s*=\s*'
                             r'"([a-z][a-z0-9-]*)"', src))
    emitted.update(re.findall(r'"reason":\s*"([a-z][a-z0-9-]*)"', src))
    for lit in ("r20-zipf-low", "applied-keep-false",
                "g2-inflection-form", "g3-interjection", "g4-abbrev",
                "g5-demonym", "g6-obsolete", "pick-proper-noun",
                "inflection-keep", "s1-fallback", "failed-no-entry",
                "type-pending"):
        assert lit in src, lit
        emitted.add(lit)
    with open(os.path.join(here, "..", "factory", "card_pilot.py"),
               encoding="utf-8") as handle:
        card_pilot = handle.read()
    for lit in re.findall(r'"(cloze-[a-z]+)"', card_pilot):
        emitted.add(lit)
    missing = sorted(s for s in emitted if s not in g.REASON_SLUGS)
    assert not missing, missing
    # The three reviewer-caught literals, pinned explicitly.
    assert {"no-real-def", "vulgar-anchor",
            "inflection-keep"} <= set(g.REASON_SLUGS)


def test_stage_names_match_live_pipeline():
    """Parity pin: glossary duplicates the live pipeline's stage tables
    until T2-T5 migrate callers over (no migration in T1)."""
    import precard_pipeline as live

    assert dict(g.STAGE_NAMES) == dict(live.STAGE_NAMES)
    assert dict(g.STAGE_FINGLESH) == dict(live.STAGE_FINGLESH)
    for sid in g.STAGE_IDS:
        assert g.stage_label(sid) == live.stage_label(sid)


def test_progress_shim_covers_every_stage_plus_topup():
    for sid in g.STAGE_IDS:
        assert g.STAGE_FILES[sid].isascii()
    assert set(g.OLD_PROGRESS_FILE_TO_NEW) == {
        "s0.json", "s0b.json", "s1.json", "s2.json",
        "s3.json", "s4.json", "s5.json", "s4_topup_cache.json",
    }
    assert (g.OLD_PROGRESS_FILE_TO_NEW["s4_topup_cache.json"]
            == "label_topup_cache.json")


def test_stage_label_ascii():
    assert g.stage_label("s0b") == "inflection (sarf)"
    assert g.stage_label("unknown") == "unknown"
