"""Sense-screening pruner: R1 proper -> R2 hard -> R4 niche -> R3 twin.

Hermetic: synthetic fixtures only (no Kaikki dump, no network), plus a
read-only pass over the pinned 204-row golden fixture (no imports beyond
stdlib + prune).
"""

import json
import os

from factory.precard import anchor, prune


def _sense(sid, gloss, tags=None, topics=None, categories=None,
           examples=None, form_of=None, pos=None, flags=None):
    sense = {"sense_id": sid, "glosses": [gloss]}
    if tags is not None:
        sense["tags"] = tags
    if topics is not None:
        sense["topics"] = topics
    if categories is not None:
        sense["categories"] = categories
    if examples is not None:
        sense["examples"] = examples
    if form_of is not None:
        sense["form_of"] = form_of
    if pos is not None:
        sense["pos"] = pos
    if flags is not None:
        sense["flags"] = flags
    return sense


def test_obsolete_tags_are_anchored_frozen_set():
    # R1: the pruner imports the frozen set, never redefines it.
    assert prune.OBSOLETE_TAGS is anchor.OBSOLETE_TAGS
    assert set(prune.OBSOLETE_TAGS) == {
        "obsolete", "archaic", "dated", "historical"}


def test_r2_obsolete_drop_casefolded():
    senses = [
        _sense("w#0", "To gain.", tags=["Obsolete"]),
        _sense("w#1", "To gain memorably.", tags=["ARCHAIC"]),
        _sense("w#2", "To keep gaining.", tags=["dated"]),
        _sense("w#3", "To gain once.", tags=["Historical"]),
        _sense("w#4", "To gain daily.", tags=["transitive"]),
        _sense("w#5", "To gain weekly."),
    ]
    kept, dropped = prune.prune_hard_drops(senses)
    assert [s["sense_id"] for s in kept] == ["w#4", "w#5"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "obsolete"), ("w#1", "obsolete"),
        ("w#2", "obsolete"), ("w#3", "obsolete")]


def test_r2_formof_and_xref_stubs_drop():
    senses = [
        _sense("w#0", "Plural of w.", tags=["form-of"]),
        _sense("w#1", "Third-person singular of w.",
               form_of=[{"word": "w"}]),
        _sense("w#2", 'Alternative spelling of "w".'),
        _sense("w#3", "See w for details."),
        _sense("w#4", "To w; see also the notes for flavor."),
        _sense("w#5", "To gain."),
    ]
    kept, dropped = prune.prune_hard_drops(senses)
    assert [s["sense_id"] for s in kept] == ["w#4", "w#5"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "form-of"), ("w#1", "form-of"),
        ("w#2", "xref"), ("w#3", "xref")]


def test_r3_twins_keep_richest_examples():
    senses = [
        _sense("w#0", "To gain.", examples=[]),
        _sense("w#1", "  to   GAIN.  ",
               examples=[{"text": "She gains daily."}]),
        _sense("w#2", "To gain.",
               examples=[{"text": "a"}, {"text": "b"}]),
        _sense("w#3", "To keep."),
    ]
    before = [dict(s) for s in senses]
    kept, dropped = prune.dedup_twins(senses)
    assert [s["sense_id"] for s in kept] == ["w#2", "w#3"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "twin-of:w#2"), ("w#1", "twin-of:w#2")]
    # Input list never mutated (same objects, same order, same length).
    assert senses == before and len(senses) == 4


def test_r3_empty_glosses_never_cluster():
    senses = [_sense("w#0", ""), _sense("w#1", "   "),
              _sense("w#2", "To gain.")]
    kept, dropped = prune.dedup_twins(senses)
    assert [s["sense_id"] for s in kept] == ["w#0", "w#1", "w#2"]
    assert dropped == []


def test_r3_tie_break_is_file_order():
    senses = [_sense("w#0", "To gain."), _sense("w#1", "To gain.")]
    kept, dropped = prune.dedup_twins(senses)
    assert [s["sense_id"] for s in kept] == ["w#0"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#1", "twin-of:w#0")]


def test_r4_niche_only_drops_mixed_or_empty_survive():
    senses = [
        _sense("w#0", "A rope.", topics=["Nautical"]),
        _sense("w#1", "A shield.", topics=["heraldry"],
               categories=[{"name": "Heraldry"}]),
        _sense("w#2", "A shot.", topics=["billiards", "sports"]),
        _sense("w#3", "A bug.", topics=["Entomology"],
               categories=["entomology"]),
        _sense("w#4", "A game.", topics=["Cricket", "sports"]),
        _sense("w#5", "A word."),
    ]
    kept, dropped, stats = prune.prune_niche(senses)
    assert [s["sense_id"] for s in kept] == ["w#2", "w#4", "w#5"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "niche"), ("w#1", "niche"), ("w#3", "niche")]
    # Stats count all other topics seen (calibration feed).
    assert stats["sports"] == 2
    assert stats["nautical"] == 1
    assert stats["heraldry"] == 1


def test_r1_proper_noun_drops_casefolded():
    senses = [
        _sense("w#0", "A surname.", pos="name"),
        _sense("w#1", "A village in England.", pos="Name"),
        _sense("w#2", "A river.", pos="NAME"),
        _sense("w#3", "To gain.", pos="verb"),
        _sense("w#4", "To gain."),
    ]
    kept, dropped = prune.prune_proper_nouns(senses)
    assert [s["sense_id"] for s in kept] == ["w#3", "w#4"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "DROP_PROPER_NOUN"), ("w#1", "DROP_PROPER_NOUN"),
        ("w#2", "DROP_PROPER_NOUN")]


def test_r1_obscure_acronym_shape_wins_over_proper():
    senses = [
        _sense("w#0", "Initialism of Strategic Energy Board.",
               tags=["abbreviation", "alt-of", "initialism"], pos="name"),
        _sense("w#1", "Initialism of Stock Exchange of Nowhere.",
               tags=["Abbreviation", "Initialism"], pos="NAME"),
        _sense("w#2", "A surname.", pos="name"),
    ]
    kept, dropped = prune.prune_proper_nouns(senses)
    assert kept == []
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "DROP_OBSCURE_ACRONYM"),
        ("w#1", "DROP_OBSCURE_ACRONYM"),
        ("w#2", "DROP_PROPER_NOUN")]


def test_r1_initialism_without_name_context_survives_proper_leg():
    # Same gloss shape under a common pos is NOT an obscure acronym
    # (and not a proper drop either) — the shape rule needs pos == name.
    senses = [
        _sense("w#0", "Initialism of Simulated Emergency Test.",
               tags=["abbreviation", "alt-of", "initialism"], pos="noun"),
        _sense("w#1", "Initialism of Something.", pos="name"),
    ]
    kept, dropped = prune.prune_proper_nouns(senses)
    assert [s["sense_id"] for s in kept] == ["w#0"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#1", "DROP_PROPER_NOUN")]


def test_r2_dialectal_flag_on_kept_never_a_drop():
    senses = [
        _sense("w#0", "To sit.", tags=["UK", "dialectal"]),
        _sense("w#1", "To suit.", tags=["Scotland"]),
        _sense("w#2", "To rest.", tags=["Midwestern-US", "dialectal"]),
        # Bare UK is standard national use, NOT dialectal (golden rows
        # 196/198 are UK-only KEEP_STANDARD_UK): no flag.
        _sense("w#3", "A class group.", tags=["UK"]),
        _sense("w#4", "To gain.", tags=["transitive"]),
    ]
    before = [dict(s) for s in senses]
    kept, dropped, stats = prune.prune_senses(senses, lemma="w")
    # Nothing drops on dialect alone.
    assert [s["sense_id"] for s in kept] == [
        "w#0", "w#1", "w#2", "w#3", "w#4"]
    assert dropped == []
    by_id = {s["sense_id"]: s for s in kept}
    for sid in ("w#0", "w#1", "w#2"):
        assert "dialectal" in by_id[sid]["flags"]
    assert by_id["w#3"]["flags"] == []
    assert by_id["w#4"]["flags"] == []
    # Additive only: every other key byte-identical to the input row.
    for orig in before:
        row = by_id[orig["sense_id"]]
        for key, value in orig.items():
            assert row[key] == value
    # Inputs never mutated (no flags leaked into callers).
    assert senses == before
    assert all("flags" not in s for s in senses)


def test_r2_dialectal_flag_preserves_existing_flags():
    senses = [_sense("w#0", "To sit.", tags=["Scotland"],
                     flags=["kept-audit"])]
    kept, _, _ = prune.prune_senses(senses, lemma="w")
    assert kept[0]["flags"] == ["kept-audit", "dialectal"]


def test_r4_example_counts_over_input():
    senses = [
        _sense("w#0", "To gain.", examples=[{"text": "She gains."}]),
        _sense("w#1", "To keep."),
        _sense("w#2", "A rope.", topics=["nautical"],
               examples=[{"text": "Rope."}]),
    ]
    _, _, stats = prune.prune_senses(senses, lemma="w")
    assert stats["example_counts"] == {"with_example": 2, "zero_example": 1}


def test_chain_proper_leg_wins_over_twin():
    # Identical glosses where one twin is a proper name: the proper leg
    # drops it FIRST, so the common sense survives with no twin drop.
    senses = [
        _sense("w#0", "A surname.", pos="name"),
        _sense("w#1", "A surname.", pos="noun"),
    ]
    kept, dropped, _ = prune.prune_senses(senses, lemma="w")
    assert [s["sense_id"] for s in kept] == ["w#1"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "DROP_PROPER_NOUN")]


def test_full_chain_order_and_stats():
    senses = [
        _sense("w#0", "To gain.", tags=["obsolete"]),
        _sense("w#1", "A rope.", topics=["nautical"]),
        _sense("w#2", "To keep.", examples=[{"text": "Keep it."}]),
        _sense("w#3", "To  KEEP."),
    ]
    kept, dropped, stats = prune.prune_senses(senses, lemma="w")
    assert [s["sense_id"] for s in kept] == ["w#2"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "obsolete"), ("w#1", "niche"),
        ("w#3", "twin-of:w#2")]
    assert stats["total"] == 4
    assert stats["kept"] == 1 and stats["dropped"] == 3
    assert stats["reason_counts"] == {
        "obsolete": 1, "niche": 1, "twin-of": 1}
    assert stats["topics_seen"] == {"nautical": 1}
    assert stats["example_counts"] == {"with_example": 1, "zero_example": 3}
    assert kept[0]["flags"] == []


def test_chain_is_pure_no_io():
    senses = [_sense("w#0", "To gain.", tags=["slang"])]
    before = [dict(s) for s in senses]
    kept, dropped, stats = prune.prune_senses(senses, lemma="w")
    assert [s["sense_id"] for s in kept] == ["w#0"]
    assert dropped == []
    assert kept[0]["flags"] == []
    assert senses == before  # inputs never mutated
    assert stats["total"] == 1
    assert stats["example_counts"] == {"with_example": 0, "zero_example": 1}


_GOLDEN = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "sense_screening_golden_204.json"))

# Pinned consensus deviations: (lemma, file-order position) the chain
# KEEPs while the golden fixture DROPs. Any behavior change must update
# this set deliberately, never silently.
_DIALECTAL_DEVIATIONS = frozenset({
    ("wear", 15), ("wear", 16), ("wear", 17), ("wear", 18),
    ("set", 24), ("set", 25), ("set", 39), ("set", 45),
})
_HYPER_NICHE_DEVIATIONS = frozenset({
    ("book", 7), ("book", 8), ("book", 12), ("book", 13),
    ("book", 14), ("book", 16),
    ("well", 21), ("well", 22), ("well", 23), ("well", 24),
    ("well", 25), ("well", 27), ("well", 31),
    ("set", 57), ("set", 59), ("set", 60), ("set", 64),
    ("set", 67), ("set", 98),
})
_FORM_OF_DEVIATIONS = frozenset({("set", 99)})
_ALLOWED_DEVIATIONS = (_DIALECTAL_DEVIATIONS | _HYPER_NICHE_DEVIATIONS
                       | _FORM_OF_DEVIATIONS)


def test_r3_twin_union_merges_topics_and_categories():
    # Winner = richest examples; union is winner-first, losers in file
    # order; empty/dup entries deduped; dict+string shapes preserved.
    senses = [
        _sense("w#0", "To gain.", topics=["beta", "alpha", ""],
               categories=["BetaCat", {"name": "AlphaCat"}]),
        _sense("w#1", "  to   GAIN.  ", topics=["gamma"],
               categories=[{"name": "GammaCat"}, "BetaCat"],
               examples=[{"text": "She gains daily."}]),
        _sense("w#2", "To gain.", topics=["alpha"],
               categories=[{"name": "AlphaCat"}],
               examples=[{"text": "a"}, {"text": "b"}]),
        _sense("w#3", "To keep."),
    ]
    kept, dropped = prune.dedup_twins(senses)
    assert [s["sense_id"] for s in kept] == ["w#2", "w#3"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "twin-of:w#2"), ("w#1", "twin-of:w#2")]
    winner = kept[0]
    assert winner["topics"] == ["alpha", "beta", "gamma"]
    assert winner["categories"] == [
        {"name": "AlphaCat"}, "BetaCat", {"name": "GammaCat"}]
    # Dict and string shapes preserved as-is (no stringification).
    assert isinstance(winner["categories"][0], dict)
    assert isinstance(winner["categories"][1], str)


def test_r3_twin_union_winner_copy_purity():
    senses = [
        _sense("w#0", "To gain.", topics=["beta"],
               categories=["BetaCat"]),
        _sense("w#1", "To gain.", topics=["alpha"],
               categories=[{"name": "AlphaCat"}],
               examples=[{"text": "a"}, {"text": "b"}]),
        _sense("w#2", "To keep."),
    ]
    before = [{"sid": s["sense_id"], "topics": list(s.get("topics", [])),
               "categories": [dict(c) if isinstance(c, dict) else c
                              for c in s.get("categories", [])]}
              for s in senses]
    kept, dropped = prune.dedup_twins(senses)
    assert [s["sense_id"] for s in kept] == ["w#1", "w#2"]
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "twin-of:w#1")]
    # Winner is an enriched COPY: input rows (incl. nested lists) unmutated.
    winner = kept[0]
    assert winner is not senses[1]
    assert winner["topics"] == ["alpha", "beta"]
    assert senses[1]["topics"] == ["alpha"]
    assert senses[0]["topics"] == ["beta"]
    assert senses[1]["categories"] == [{"name": "AlphaCat"}]
    for snap, sense in zip(before, senses):
        assert sense["sense_id"] == snap["sid"]
        assert list(sense.get("topics", [])) == snap["topics"]
        assert sense.get("categories", []) == snap["categories"]
    # No-drop rows unaffected: same object, byte-identical content.
    assert kept[1] is senses[2]
    assert kept[1] == senses[2]


def test_r3_twin_union_missing_keys():
    # Winner without topics/categories gains them from losers; rows with
    # no signal anywhere keep their sparse shape (no empty lists added).
    senses = [
        _sense("w#0", "To gain.", topics=["beta"],
               categories=["BetaCat"]),
        _sense("w#1", "To gain.",
               examples=[{"text": "a"}, {"text": "b"}]),
    ]
    kept, dropped = prune.dedup_twins(senses)
    assert [s["sense_id"] for s in kept] == ["w#1"]
    assert kept[0]["topics"] == ["beta"]
    assert kept[0]["categories"] == ["BetaCat"]
    assert "topics" not in senses[1] and "categories" not in senses[1]
    # All-empty: key present on winner collapses to [], absent stays absent.
    senses = [_sense("w#0", "To gain.", topics=[""]),
              _sense("w#1", "To gain.", topics=[""],
                     examples=[{"text": "a"}])]
    kept, _ = prune.dedup_twins(senses)
    assert kept[0]["topics"] == []
    assert senses[1]["topics"] == [""]  # input unmutated


def test_screen_for_linking_returns_link_ready_kept_and_drops():
    senses = [
        _sense("w#0", "To gain.", tags=["obsolete"]),
        _sense("w#1", "To keep.", topics=["sports"],
               examples=[{"text": "Keep it."}]),
        _sense("w#2", "To  KEEP.", topics=["games"]),
        _sense("w#3", "To rest."),
    ]
    before = [dict(s) for s in senses]
    link_inputs, screening_drops, stats = prune.screen_for_linking(
        senses, lemma="w")
    kept, dropped, stats2 = prune.prune_senses(senses, lemma="w")
    # Link-ready kept == full-chain kept (union-enriched twin winner).
    assert link_inputs == kept
    assert [s["sense_id"] for s in link_inputs] == ["w#1", "w#3"]
    assert link_inputs[0]["topics"] == ["sports", "games"]
    assert link_inputs[0]["flags"] == []
    # Drops metadata: exactly {sense_id, reason} per drop, chain order.
    assert screening_drops == [
        {"sense_id": "w#0", "reason": "obsolete"},
        {"sense_id": "w#2", "reason": "twin-of:w#1"}]
    for drop in screening_drops:
        assert set(drop) == {"sense_id", "reason"}
    assert [(d["sense_id"], d["reason"]) for d in dropped] == [
        ("w#0", "obsolete"), ("w#2", "twin-of:w#1")]
    assert stats == stats2
    # Pure: inputs never mutated.
    assert senses == before


def test_chain_golden_conformance():
    # Every fixture row through prune_senses, per lemma in file order.
    with open(_GOLDEN, encoding="utf-8") as fh:
        rows = json.load(fh)
    assert len(rows) == 204
    by_lemma = {}
    for row in rows:
        by_lemma.setdefault(row["lemma"], []).append(row)
    over_drops = []
    under_drops = []
    kept_by_pos = {}
    for lemma, lemma_rows in by_lemma.items():
        senses = [{
            "gloss": row["gloss"], "tags": row["tags"],
            "topics": row["topics"], "categories": row["categories"],
            "pos": row["pos"],
            "examples": [{"text": "e"}] * row["example_count"],
        } for row in lemma_rows]
        for pos, sense in enumerate(senses):
            kept_by_pos[(lemma, pos)] = prune.with_dialectal_flags(sense)
        pairs = prune._pair_up(senses, lemma)
        kept_p, dropped = prune._proper_pairs(pairs)
        kept_p, hard = prune._hard_pairs(kept_p)
        dropped += hard
        kept_p, niche = prune._niche_pairs(kept_p)
        dropped += niche
        kept_p, twins = prune._twins_pairs(kept_p)
        dropped += twins
        survived = {int(sid.split("#")[1]) for sid, _ in kept_p}
        for pos, row in enumerate(lemma_rows):
            if pos in survived:
                if row["verdict"] != "KEEP":
                    under_drops.append((lemma, pos))
            elif row["verdict"] == "KEEP":
                over_drops.append((lemma, pos))
    # Zero over-drops: the chain never drops a consensus-KEEP sense.
    assert over_drops == []
    # Under-drops pin exactly to the allowed deviation set.
    assert set(under_drops) == _ALLOWED_DEVIATIONS
    # Bare-UK consensus-KEEP rows carry no dialectal flag (golden 196/198).
    for key in (("set", 94), ("set", 96)):
        assert kept_by_pos[key]["flags"] == []
