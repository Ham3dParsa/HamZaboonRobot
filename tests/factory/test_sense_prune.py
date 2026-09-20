"""Sense-screening pruner: R2 hard drops, R3 twin dedup, R4 niche guard.

Hermetic: synthetic fixtures only (no Kaikki dump, no network).
"""

from factory.precard import anchor, prune


def _sense(sid, gloss, tags=None, topics=None, categories=None,
           examples=None, form_of=None):
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


def test_chain_is_pure_no_io():
    senses = [_sense("w#0", "To gain.", tags=["slang"])]
    kept, dropped, stats = prune.prune_senses(senses, lemma="w")
    assert kept == senses and dropped == []
    assert stats["total"] == 1
