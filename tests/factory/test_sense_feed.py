"""sense_feed tests: single shared screened→items join (P2 extraction).

Contract: load_senses(screened_path, table_path) returns runner-shaped
items [{sense_id, lemma, definition, example, tags, candidates[]}]
with the same tolerant parse + mechanical join + honest empties the
batch builder always had (moved verbatim, not reinvented).
"""

from __future__ import annotations

import json

from factory.linking import sense_feed


def _write(path, senses, table_rows=()):
    with open(path[0], "w", encoding="utf-8") as handle:
        for entry in senses:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    with open(path[1], "w", encoding="utf-8") as handle:
        handle.write("kaikki_sense_id\twordnet_sensekey\tmethod\tevidence\tprovenance\n")
        for kid, skey in table_rows:
            handle.write("%s\t%s\tLINK:2-sig\te\tp\n" % (kid, skey))


def _sense(short, full):
    return {"lemma": "run", "sense": {
        "sense_id": short, "id": full, "glosses": ["move fast"],
        "examples": [{"text": "run fast"}], "tags": ["verb"]}}


def test_load_senses_join_and_shape(tmp_path):
    screened = str(tmp_path / "s.jsonl")
    table = str(tmp_path / "t.tsv")
    _write((screened, table), [_sense("run#0", "en-run-1")],
           [("en-run-1", "run%2:38:00::")])
    (item,) = sense_feed.load_senses(screened, table)
    assert item["sense_id"] == "run#0"
    assert item["definition"] == "move fast"
    assert item["candidates"] == [{"synset_id": "run%2:38:00::",
                                   "definition": "", "example": "",
                                   "tags": []}]


def test_load_senses_tolerant_and_missing(tmp_path):
    screened = str(tmp_path / "s.jsonl")
    table = str(tmp_path / "t.tsv")
    _write((screened, table),
           [_sense("run#0", "en-run-1"), "junk", {"lemma": "x"}])
    items = sense_feed.load_senses(screened, table)
    assert [it["sense_id"] for it in items] == ["run#0"]
    assert sense_feed.load_senses(str(tmp_path / "nope.jsonl"), table) == []
