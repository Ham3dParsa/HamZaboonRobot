"""Tests for factory/core/stage_glossary.py (v13 T1, additive-only)."""

import os
from factory.core import stage_glossary as g
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
    """Every drop/keep slug the v1.4.1 pipeline actually emits (reason/dropped
    assignments, measured r20/applied-keep bases, G-gate returns, cloze
    gates) must exist in REASON_SLUGS — the cutover source rename
    (factory/precard/*) has no gaps."""
    import re

    here = os.path.dirname(__file__)
    parts = []
    for name in ("anchor", "enrich", "judge", "topics", "pipeline",
                 "ids", "transport", "progress", "accounting"):
        with open(os.path.join(here, "..", "factory", "precard",
                               name + ".py"),
                  encoding="utf-8") as handle:
            parts.append(handle.read())
    src = "\n".join(parts)
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
    with open(os.path.join(here, "..", "factory", "pipeline",
                              "card_pilot.py"),
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
    """Cutover pin: every legacy stage token the glossary knows resolves
    in the live v1.4.1 registry — no stage left behind, no orphan id."""
    from factory.precard import progress as live
    assert len(live.STAGES) == len(g.STAGE_IDS) == 7
    for sid in g.STAGE_IDS:
        assert live.normalize_stage(sid) in live.STAGES
    for name in g.NEW_STAGE_TO_OLD:
        assert live.normalize_stage(name) in live.STAGES
    for stage in live.STAGES:
        assert live.normalize_stage(stage) == stage
        assert live.display(stage).isascii()


def test_progress_shim_covers_every_stage_plus_topup():
    for sid in g.STAGE_IDS:
        assert g.STAGE_FILES[sid].isascii()
    assert g.STAGE_FILES["s0b"] == "inflection-review.json"
    assert g.STAGE_FILES["s2"] == "sense-judge.json"
    assert g.STAGE_FILES["s4"] == "topic-label.json"
    assert set(g.OLD_PROGRESS_FILE_TO_NEW) == {
        "s0.json", "s0b.json", "s1.json", "s2.json",
        "s3.json", "s4.json", "s5.json", "s4_topup_cache.json",
        "inflection.json", "judge.json", "label.json",
    }
    assert (g.OLD_PROGRESS_FILE_TO_NEW["s4_topup_cache.json"]
            == "label_topup_cache.json")


def test_stage_label_ascii():
    assert g.stage_label("s0b") == "inflection-review (Barresie-Sarf)"
    assert g.stage_label("s2") == "sense-judge (Davarie-Mana)"
    assert g.stage_label("s4") == "topic-label (Barchasbe-Mozu')"
    assert g.stage_label("s0") == "preprocess (PishPardazesh)"
    assert g.stage_label("unknown") == "unknown"
