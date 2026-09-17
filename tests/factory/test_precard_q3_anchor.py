"""Q3 dual-anchor (locked): per-sense headword-anchored example acceptance.

Hermetic (no network): zipf injected, enrich_item direct, no transports.
Locked rule: minimum 2 headword-anchored examples per sense, length
3-18 level-aware (A: 3-10, B: 7-15, C: 10-18), no weird characters,
model fills ONLY the shortfall (synthetic-needed True only when zero
accepted examples exist). Tiers sense/lemma/pool + cloze gates kept.
"""

from factory.precard import enrich as E


ZIPF_PASS = lambda t: 5.0  # noqa: E731 - hermetic: every token clears floors


def _idx_from_senses(lemma, senses_examples, ipa="/aipa/"):
    """Index with one lemma whose senses carry the given example lists."""
    senses = [{"glosses": ["g%d" % i], "tags": [],
               "examples": [{"text": ex} for ex in examples]}
              for i, examples in enumerate(senses_examples)]
    index = {lemma: [{"pos": "noun",
                      "entry": {"pos": "noun", "sounds": [{"ipa": ipa}],
                                "senses": senses}}]}

    def read_entry(row):
        return row["entry"]

    return index, read_entry


def test_q3_gout_like_shared_example_each_sense_keeps_own():
    """Gout-like: same example string on two senses isolates per sense.

    Each sense enriches from its OWN sense texts (dual-anchor = sense
    tier + headword), so both picks return the shared string with
    fallback "sense" — never stolen/cross-counted across senses.
    """
    shared = "His painful gout kept him in bed for days"
    assert E.en_word_count(shared) == 9
    index, read_entry = _idx_from_senses("gout", [[shared], [shared]])
    item = {"kind": "word", "text": "gout", "pool_level": "B1"}
    out0 = E.enrich_item(item, {"sense_id": "gout#0", "gloss": "g0"},
                         index, read_entry, {}, zipf_fn=ZIPF_PASS)
    out1 = E.enrich_item(item, {"sense_id": "gout#1", "gloss": "g1"},
                         index, read_entry, {}, zipf_fn=ZIPF_PASS)
    assert out0["dataset_examples"] == [shared]
    assert out1["dataset_examples"] == [shared]
    assert out0["example_fallback"] == "sense"
    assert out1["example_fallback"] == "sense"
    assert out0["example_synthetic_needed"] is False
    assert out1["example_synthetic_needed"] is False


def test_q3_outside_like_distinct_senses_keep_own():
    """Outside-like: distinct senses anchor own-first, tiers preserved.

    The picked sense's own example fills slot 0 (sense tier); the
    sibling-sense example backfills slot 1 via the kept lemma tier
    (R3 preservation) — ownership is ordered, never stolen.
    """
    ex0 = "The children play outside every day"
    ex1 = "She waited outside the shop for an hour"
    index, read_entry = _idx_from_senses("outside", [[ex0], [ex1]])
    item = {"kind": "word", "text": "outside", "pool_level": "A1"}
    out0 = E.enrich_item(item, {"sense_id": "outside#0", "gloss": "g0"},
                         index, read_entry, {}, zipf_fn=ZIPF_PASS)
    out1 = E.enrich_item(item, {"sense_id": "outside#1", "gloss": "g1"},
                         index, read_entry, {}, zipf_fn=ZIPF_PASS)
    assert out0["dataset_examples"] == [ex0, ex1]
    assert out1["dataset_examples"] == [ex1, ex0]
    assert out0["example_fallback"] == "sense"
    assert out1["example_fallback"] == "sense"


def test_q3_headword_presence_enforced():
    """Examples without the headword never count (even when short)."""
    good = "She eats a fresh red apple every morning"
    bad = "She eats a fresh red fruit every morning"
    assert E.example_has_headword(good, "apple") is True
    assert E.example_has_headword(bad, "apple") is False
    index, read_entry = _idx_from_senses("apple", [[good, bad]])
    item = {"kind": "word", "text": "apple", "pool_level": "A1"}
    out = E.enrich_item(item, {"sense_id": "apple#0", "gloss": "g0"},
                        index, read_entry, {}, zipf_fn=ZIPF_PASS)
    assert out["dataset_examples"] == [good]
    # Sense with zero headword-anchored examples -> empty + flag stays.
    index2, read2 = _idx_from_senses("apple", [[bad]])
    out2 = E.enrich_item(item, {"sense_id": "apple#0", "gloss": "g0"},
                         index2, read2, {}, zipf_fn=ZIPF_PASS)
    assert out2["dataset_examples"] == []
    assert out2["example_fallback"] == "synthetic-needed"
    assert out2["example_synthetic_needed"] is True


def test_q3_level_aware_length_bands():
    """A: 3-10, B: 7-15, C: 10-18 (outer 3-18 for unknown levels)."""
    short5 = "She eats fresh apple daily"
    mid8 = "She eats a fresh red apple every morning"
    long12 = "She eats a fresh red apple every single morning with her family"
    assert E.en_word_count(short5) == 5
    assert E.en_word_count(mid8) == 8
    assert E.en_word_count(long12) == 12
    assert E.example_level_band("A1") == (3, 10)
    assert E.example_level_band("b2") == (7, 15)
    assert E.example_level_band("C1") == (10, 18)
    assert E.example_level_band("") == (3, 18)
    assert E.example_level_band("??") == (3, 18)
    # A1: 5 and 8 accept, 12 rejects.
    assert E.example_accepted(short5, "apple", "word", "A1") is True
    assert E.example_accepted(mid8, "apple", "word", "A1") is True
    assert E.example_accepted(long12, "apple", "word", "A1") is False
    # B1: 5 rejects, 8 and 12 accept.
    assert E.example_accepted(short5, "apple", "word", "B1") is False
    assert E.example_accepted(mid8, "apple", "word", "B1") is True
    assert E.example_accepted(long12, "apple", "word", "B1") is True
    # C1: 8 rejects, 12 accepts.
    assert E.example_accepted(mid8, "apple", "word", "C1") is False
    assert E.example_accepted(long12, "apple", "word", "C1") is True
    # End-to-end: A1 sense holding only a 12-word example -> synthetic.
    index, read_entry = _idx_from_senses("apple", [[long12]])
    out = E.enrich_item({"kind": "word", "text": "apple",
                         "pool_level": "A1"},
                        {"sense_id": "apple#0", "gloss": "g0"},
                        index, read_entry, {}, zipf_fn=ZIPF_PASS)
    assert out["dataset_examples"] == []
    assert out["example_synthetic_needed"] is True


def test_q3_weird_character_rejection():
    """Pollution regression: URLs, @-markers, emoji/scripts never accept."""
    base = "She eats a fresh apple daily now"
    assert E.example_accepted(base, "apple", "word", "A1") is True
    url = "She eats a fresh apple daily http://evil.example"
    at = "Contact foo@bar for a fresh apple daily now"
    emoji = "She eats a fresh apple daily now \U0001F34E"
    assert E.example_has_weird_chars(url) is True
    assert E.example_has_weird_chars(at) is True
    assert E.example_has_weird_chars(emoji) is True
    assert E.example_has_weird_chars(base) is False
    assert E.example_accepted(url, "apple", "word", "A1") is False
    assert E.example_accepted(at, "apple", "word", "A1") is False
    assert E.example_accepted(emoji, "apple", "word", "A1") is False
    # End-to-end: sense with only a weird example -> synthetic-needed.
    index, read_entry = _idx_from_senses("apple", [[url]])
    out = E.enrich_item({"kind": "word", "text": "apple",
                         "pool_level": "A1"},
                        {"sense_id": "apple#0", "gloss": "g0"},
                        index, read_entry, {}, zipf_fn=ZIPF_PASS)
    assert out["dataset_examples"] == []
    assert out["example_fallback"] == "synthetic-needed"
    assert out["example_synthetic_needed"] is True


def test_q3_shortfall_only_model_flag():
    """Dataset keeps what it earned; the model fills only the shortfall.

    1 accepted -> 1 kept, flag False (1 slot for the model); 0 -> []
    with flag True; 3 accepted -> capped at N_EXAMPLES (2).
    """
    ex1 = "She eats a fresh red apple every morning"
    ex2 = "The little boy eats a red apple daily now"
    ex3 = "Her mother buys a fresh apple every day"
    for ex in (ex1, ex2, ex3):
        assert E.example_accepted(ex, "apple", "word", "A1") is True, ex
    index, read_entry = _idx_from_senses("apple", [[ex1]])
    one = E.enrich_item({"kind": "word", "text": "apple",
                         "pool_level": "A1"},
                        {"sense_id": "apple#0", "gloss": "g0"},
                        index, read_entry, {}, zipf_fn=ZIPF_PASS)
    assert one["dataset_examples"] == [ex1]
    assert one["example_synthetic_needed"] is False
    index3, read3 = _idx_from_senses("apple", [[ex1, ex2, ex3]])
    three = E.enrich_item({"kind": "word", "text": "apple",
                           "pool_level": "A1"},
                          {"sense_id": "apple#0", "gloss": "g0"},
                          index3, read3, {}, zipf_fn=ZIPF_PASS)
    assert three["dataset_examples"] == [ex1, ex2]
    assert three["example_synthetic_needed"] is False
    assert three["example_fallback"] == "sense"
