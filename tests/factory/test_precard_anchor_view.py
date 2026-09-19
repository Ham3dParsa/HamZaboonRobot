"""Q-anchor decision table (hermetic, no Kaikki reads, no network).

Pins the S1 anchor decision — ranking, filtering, drop verdicts — through
the anchor(item, index) view on a hand-built fixture. Score gaps are kept
> FREQ_TIE_EPS by file-decay/register penalties alone so live wordfreq
never decides a row; every expectation is absolute (no logic copied from
the implementation).
"""

import pytest

from factory.precard.anchor import anchor, anchor_rank_item


def _row(pos, gloss_tags, ipa=""):
    senses = [{"glosses": [g], "tags": list(t), "examples": []}
              for g, t in gloss_tags]
    sounds = [{"ipa": ipa}] if ipa else []
    return {"pos": pos,
            "entry": {"pos": pos, "sounds": sounds, "senses": senses}}


def _index():
    return {
        "apple": [_row("noun", [("a round fruit", []),
                                ("a tech company", [])], "/aɪpa/")],
        "rundle": [_row("propn", [("A surname.", [])])],
        "actlike": [_row("propn", [("A territory.", [])]),
                    _row("noun", [("a deed", [])])],
        "coarse": [_row("noun", [("a coarse insult", ["vulgar"])])],
        "gillianlike": [_row("noun", [("A female given name.", [])])],
        "renamelike": [_row("noun", [("A female given name.", []),
                                     ("a sweet fruit treat", [])])],
        "color": [_row("noun", [(u'Alternative spelling of "colour".',
                                 [])])],
        "colour": [_row("noun", [("a hue", [])])],
        "quux": [_row("noun", [(u'Alternative spelling of "zzznomatch".',
                                [])])],
    }


def _read_entry(row):
    return row["entry"]


def _item(text, level="B1"):
    return {"kind": "word", "text": text, "pool_level": level}


def test_anchor_keep_matches_rank_item():
    """Kept items: the view returns the rank verbatim (no mutation)."""
    index = _index()
    item = _item("apple", "A1")
    ranked, warnings = anchor(item, index, _read_entry)
    assert warnings == []
    assert "dropped" not in ranked
    assert ranked["top"] == {"sense_id": "apple#0",
                             "gloss": "a round fruit"}
    assert ranked == anchor_rank_item(dict(item), index, _read_entry)


def test_anchor_proper_noun_drop():
    index = _index()
    ranked, _ = anchor(_item("rundle"), index, _read_entry)
    assert ranked["dropped"] == "anchor-proper-noun"
    assert ranked["anchor_pos"] == "propn"


def test_anchor_proper_reroute():
    """File-order propn top re-anchors to the first non-proper sense."""
    index = _index()
    ranked, warnings = anchor(_item("actlike"), index, _read_entry)
    assert "dropped" not in ranked
    assert ranked["top"] == {"sense_id": "actlike#1", "gloss": "a deed"}
    assert ranked["anchor_pos"] == "noun"
    assert ranked.get("rerouted_from_proper") is True
    assert any("re-anchored off proper top -> actlike#1" in w
               for w in warnings)


def test_anchor_vulgar_drop():
    index = _index()
    ranked, _ = anchor(_item("coarse"), index, _read_entry)
    assert ranked["dropped"] == "vulgar-anchor"


def test_anchor_name_gloss_drop():
    index = _index()
    ranked, _ = anchor(_item("gillianlike"), index, _read_entry)
    assert ranked["dropped"] == "anchor-name-gloss"


def test_anchor_name_gloss_reroute():
    index = _index()
    ranked, warnings = anchor(_item("renamelike"), index, _read_entry)
    assert "dropped" not in ranked
    assert ranked["top"] == {"sense_id": "renamelike#1",
                             "gloss": "a sweet fruit treat"}
    assert ranked.get("rerouted_from_name") is True
    assert any("re-anchored off name top -> renamelike#1" in w
               for w in warnings)


def test_anchor_xref_resolved():
    index = _index()
    ranked, warnings = anchor(_item("color"), index, _read_entry)
    assert "dropped" not in ranked
    assert ranked["top"] == {"sense_id": "colour#0", "gloss": "a hue"}
    assert ranked["xref_method"] == "xref-resolved"
    assert warnings == []
    assert ranked == anchor_rank_item(
        {"kind": "word", "text": "color", "pool_level": "B1"},
        index, _read_entry)


def test_anchor_xref_unresolvable_drop():
    index = _index()
    ranked, _ = anchor(_item("quux"), index, _read_entry)
    assert ranked["dropped"] == "no-real-def"
    assert ranked.get("xref_unresolvable") is True


if __name__ == "__main__":
    pytest.main([__file__])
