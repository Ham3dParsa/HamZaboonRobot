"""Red-first tests for factory/lexicon/cefr_bridge.py (kaikki->WordNet sense-CEFR bridge).

Covers (plain asserts, hermetic — inline TSV fixture in tmp dirs, no W:, no network):
  (a) single-candidate lookup: run verb -> (B1, wn-single);
  (b) POS filtering: peer noun -> B2, peer verb -> C1 (no cross-POS leak);
  (c) satellite-adj (%5) joins the adj bucket: better adj sees the %5 row;
  (d) EVP guideword-in-gloss disambiguation: good adj + "quality" gloss
      -> (B1, wn-evp-gloss);
  (e) min-level fallback: good adj + gloss with no guideword hit
      -> (A2, wn-lemma-min);
  (f) unmapped lemma -> (None, unmapped);
  (g) missing TSV file fails closed (empty map, skipped count, no raise);
  (h) malformed TSV lines are skipped + counted, good rows still load;
  (i) underscore sensekeys ("credit_card%1") map to the spaced lemma;
  (j) enrich_item wiring: precard row carries additive sense_cefr +
      sense_cefr_method (mapped for a fixture lemma, unmapped for junk).

Locked contract R1-R8 (owner "locked"): cascade
EVP-intersection -> single -> min -> unmapped; stdlib only; no schema change.
"""

import pytest

from factory.lexicon import cefr_bridge as B

TSV_ROWS = [
    "run%2:31:00::\tB1\n",
    "peer%1:09:00::\tB2\n",
    "peer%2:31:00::\tC1\n",
    "better%3:00:00:good:00\tA2\n",
    "better%3:00:01:improved:00\tB1\n",
    "better%5:00:00:altered:00\tC1\n",
    "good%3:00:00:quality:00\tA2\n",
    "good%3:00:01:advantage:00\tB1\n",
    "good%5:00:00:thorough:00\tC1\n",
    "credit_card%1:06:00::\tA1\n",
]

EVP = {
    # lemma -> [(guideword, cefr)] (same shape as load_evp_guidewords output)
    "good": [("quality", "B1"), ("advantage", "B2")],
}


@pytest.fixture()
def bridge(tmp_path):
    path = tmp_path / "wordnet_sensekey_cefr.tsv"
    path.write_text("".join(TSV_ROWS), encoding="utf-8")
    B.clear_cache()
    yield B.load_tsv(str(path))[0]
    B.clear_cache()


def test_single_candidate_run_verb(bridge):
    assert B.sense_cefr_for("run", "verb", "to move fast", bridge) == (
        "B1", "wn-single")


def test_pos_filtering_no_cross_pos_leak(bridge):
    assert B.sense_cefr_for("peer", "noun", "a person", bridge) == (
        "B2", "wn-single")
    assert B.sense_cefr_for("peer", "verb", "to look", bridge) == (
        "C1", "wn-single")


def test_satellite_adj_joins_adj_bucket(bridge):
    # better adj sees 3 rows (A2/B1/C1 incl. the %5 satellite); no EVP hit
    # on this gloss, so the min-level fallback fires over all three.
    assert B.sense_cefr_for("better", "adj", "comparative gloss", bridge) == (
        "A2", "wn-lemma-min")


def test_evp_guideword_disambiguation(bridge):
    assert B.sense_cefr_for(
        "good", "adj", "of high quality and value", bridge, EVP) == (
        "B1", "wn-evp-gloss")


def test_min_level_fallback_without_evp_hit(bridge):
    assert B.sense_cefr_for(
        "good", "adjective", "a pleasant day outside", bridge, EVP) == (
        "A2", "wn-lemma-min")


def test_unmapped_lemma(bridge):
    assert B.sense_cefr_for("dvd", "noun", "a disc", bridge, EVP) == (
        None, "unmapped")


def test_missing_tsv_fails_closed(tmp_path):
    B.clear_cache()
    try:
        bridge, stats = B.load_tsv(
            str(tmp_path / "no-such-file.tsv"))
        assert bridge == {}
        assert stats["rows"] == 0
        assert B.sense_cefr_for("run", "verb", "to move fast",
                                bridge) == (None, "unmapped")
    finally:
        B.clear_cache()


def test_malformed_lines_skipped_and_counted(tmp_path):
    path = tmp_path / "wordnet_sensekey_cefr.tsv"
    path.write_text(
        "run%2:31:00::\tB1\n"
        "garbage-without-tab\n"
        "alsobad%9:xx\n"
        "\n"
        "peer%1:09:00::\tB2\n",
        encoding="utf-8")
    B.clear_cache()
    try:
        bridge, stats = B.load_tsv(str(path))
        assert stats["rows"] == 2
        assert stats["skipped"] == 2
        assert B.sense_cefr_for("run", "verb", "x", bridge) == (
            "B1", "wn-single")
    finally:
        B.clear_cache()


def test_undecodable_bytes_fail_closed(tmp_path):
    # Bad bytes poison the whole read chunk, so no rows survive — but
    # nothing raises: callers degrade to "unmapped".
    path = tmp_path / "wordnet_sensekey_cefr.tsv"
    path.write_bytes("run%2:31:00::\tB1\n".encode("utf-8") + b"\xff\xfe\n")
    B.clear_cache()
    try:
        bridge, stats = B.load_tsv(str(path))
        assert bridge == {}
        assert stats["rows"] == 0
        assert B.sense_cefr_for("run", "verb", "x", bridge) == (
            None, "unmapped")
    finally:
        B.clear_cache()


def test_non_string_evp_file_values_skipped(tmp_path):
    import json
    path = tmp_path / "evp_sense.json"
    path.write_text(json.dumps({"entries": {
        "good|adj|quality": {"guideword": "quality", "cefr": "B1"},
        "bad|noun|num": {"guideword": 123, "cefr": "B2"},
        "bad2|noun|lst": {"guideword": ["x"], "cefr": "B2"},
        "bad3|noun|noncefr": {"guideword": "ok", "cefr": None},
        "notadict": [1, 2],
    }}), encoding="utf-8")
    assert B.load_evp_guidewords(str(path)) == {"good": [("quality", "B1")]}
    assert B.load_evp_guidewords(str(tmp_path / "missing.json")) == {}


def test_non_string_evp_and_gloss_fail_closed(bridge):
    # Non-string EVP values / glosses never raise; matching degrades.
    evp = {"good": [("quality", "B1"), (123, "B2"), ("ok", None),
                    (None, "A1")]}
    assert B.sense_cefr_for("good", "adj", "of high quality", bridge,
                            evp) == ("B1", "wn-evp-gloss")
    assert B.sense_cefr_for("good", "adj", ["not", "a", "string"],
                            bridge, evp) == ("A2", "wn-lemma-min")
    assert B.sense_cefr_for("good", "adj", 123, bridge, evp) == (
        "A2", "wn-lemma-min")


def test_underscore_sensekey_maps_to_spaced_lemma(bridge):
    assert B.sense_cefr_for("credit card", "noun", "plastic money",
                            bridge) == ("A1", "wn-single")


def test_enrich_item_carries_additive_bridge_fields(tmp_path, monkeypatch):
    from factory.pipeline import precard_pipeline as P
    tsv = tmp_path / "wordnet_sensekey_cefr.tsv"
    tsv.write_text("".join(TSV_ROWS), encoding="utf-8")
    monkeypatch.setattr(B, "DEFAULT_TSV", str(tsv))
    monkeypatch.setattr(B, "DEFAULT_EVP", str(
        tmp_path / "no-evp.json"))
    B.clear_cache()
    try:
        item = {"kind": "word", "text": "run", "pos": "verb",
                "pool_level": "A1"}
        out = P.enrich_item(
            item, {"sense_id": "", "gloss": ""}, {}, lambda row: {},
            {}, phrase_entry=None)
        assert out["sense_cefr"] == "B1"
        assert out["sense_cefr_method"] == "wn-single"
        junk = dict(item, text="dvd")
        out2 = P.enrich_item(
            junk, {"sense_id": "", "gloss": ""}, {}, lambda row: {},
            {}, phrase_entry=None)
        assert out2["sense_cefr"] is None
        assert out2["sense_cefr_method"] == "unmapped"
    finally:
        B.clear_cache()
