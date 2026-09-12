"""Hermetic tests for R42 v11 cloze-suitability gates (LOCKED).

Factory-only, reuse by import, no network, no real pools/files. stdlib +
wordfreq only; zipf lookups are injected (deterministic) except one
live-wordfreq integration check on common words.

- Each gate: pass/fail unit (archaic thou FAIL / smack PASS, dialogue
  quote FAIL, zipf hard-word-in-A1 FAIL / excluded-headword PASS,
  density thin FAIL).
- End-to-end: dataset release (split_frozen -> released_containment
  with cloze-<gate> reason) + model regen (single shared-budget regen
  via mocked transport, then record) + gallery cloze-<gate> chip.
"""

import json
from factory.pipeline import card_pilot
from factory.pipeline.card_pilot import (
    cloze_archaic_ok,
    cloze_check_example,
    cloze_density_ok,
    cloze_dialogue_ok,
    cloze_zipf_floor,
    cloze_zipf_ok,
    generate_card,
    prefer_cloze_passing,
    render_diff_table,
    split_frozen_by_containment,
)

HEAD = "resilient"


def _zipf(mapping, default=5.0):
    def get(word):
        return float(mapping.get(word, default))
    return get


# ---------------- R42a: archaic ----------------

def test_archaic_thou_fails():
    assert cloze_archaic_ok("Thou art a brave student here today.") is False
    assert cloze_archaic_ok("Wherefore did he leave so early today?") is False


def test_archaic_smack_passes_modern_word():
    # "smack" was on the Gemini candidate list but is a modern word
    # (to hit / a loud kiss sound), deliberately NOT in ARCHAIC_WORDS.
    assert "smack" not in card_pilot.ARCHAIC_WORDS
    assert cloze_archaic_ok(
        "He smacked the ball hard over the fence today.") is True


def test_archaic_whole_word_only():
    assert cloze_archaic_ok("The earth is round and blue today.") is True
    assert cloze_archaic_ok("The art class meets here every day.") is False


# ---------------- R42b: dialogue/comic ----------------

def test_dialogue_quote_fails():
    assert cloze_dialogue_ok('She said "hello" to them today.') is False
    assert cloze_dialogue_ok("She said \u201chello\u201d to them.") is False


def test_dialogue_bang_patterns_fail():
    assert cloze_dialogue_ok("Wow!! Students study here daily.") is False
    assert cloze_dialogue_ok("What!? Students study here daily.") is False
    assert cloze_dialogue_ok("Wow! Great! Students study here.") is False
    assert cloze_dialogue_ok("Wait... students study here daily.") is False


def test_dialogue_single_bang_passes():
    assert cloze_dialogue_ok(
        "Students study hard here every day!") is True


def test_dialogue_mid_sentence_capitals():
    assert cloze_dialogue_ok(
        "The Student Studies hard every day here.") is False
    assert cloze_dialogue_ok(
        "Students visit London every year here today.") is True
    # The pronoun I never counts as a mid-sentence capital.
    assert cloze_dialogue_ok(
        "I think I study hard every day here.") is True


# ---------------- R42c: zipf floor ----------------

def test_zipf_floors_level_relative():
    assert cloze_zipf_floor("A1") == 3.5
    assert cloze_zipf_floor("a2") == 3.5
    assert cloze_zipf_floor("B1") == 3.0
    assert cloze_zipf_floor("B2") == 2.5
    assert cloze_zipf_floor("C1") == 2.5
    assert cloze_zipf_floor("C2") == 2.5
    assert cloze_zipf_floor("") == 3.0  # unknown: stated default


def test_zipf_hard_word_in_a1_fails():
    fn = _zipf({"sesquipedalian": 1.0})
    assert cloze_zipf_ok("The student learned sesquipedalian terms today.",
                         HEAD, "word", "A1", fn) is False
    # Same sentence clears the B2 floor for ordinary words only when
    # the hard word itself is above it.
    fn2 = _zipf({"sesquipedalian": 2.0})
    assert cloze_zipf_ok("The student learned sesquipedalian terms today.",
                         HEAD, "word", "B2", fn2) is False


def test_zipf_excluded_headword_passes():
    # Any inflection of the headword (5-char stem containment either
    # direction) is excluded from the floor check.
    fn = _zipf({"photosynthesis": 1.0, "photosynthetic": 1.0})
    assert cloze_zipf_ok(
        "Photosynthesis helps plants grow every day here.",
        "photosynthesis", "word", "A1", fn) is True


def test_zipf_unknown_reading_fails_open():
    assert cloze_zipf_ok("Students study hard every day here.", HEAD,
                         "word", "A1", lambda w: None) is True


def test_zipf_live_wordfreq_common_words_pass():
    # Integration: the real wordfreq path (local data, no network)
    # passes ordinary words at every floor.
    assert cloze_zipf_ok("Students study hard here every day.",
                         HEAD, "word", "A1") is True


# ---------------- R42d: clue density ----------------

def test_density_thin_fails():
    assert cloze_density_ok("It is on in at to be or as") is False
    assert cloze_density_ok("") is False


def test_density_rich_passes():
    assert cloze_density_ok(
        "The resilient student studies hard every evening.") is True


# ---------------- combined check + precedence ----------------

def test_cloze_check_reasons_first_failure_wins():
    ok, reason = cloze_check_example(
        "Thou art here", HEAD, "word", "B2", _zipf({}))
    assert (ok, reason) == (False, "cloze-archaic")
    ok, reason = cloze_check_example(
        'She said "hi" to them.', HEAD, "word", "B2", _zipf({}))
    assert (ok, reason) == (False, "cloze-dialogue")
    ok, reason = cloze_check_example(
        "It is on in at to be or as", HEAD, "word", "B2", _zipf({}))
    assert (ok, reason) == (False, "cloze-density")
    ok, reason = cloze_check_example(
        "The resilient student studies hard every evening.",
        HEAD, "word", "B2", _zipf({}))
    assert (ok, reason) == (True, "")


def test_prefer_cloze_passing_order_and_backfill():
    good1 = PASSING
    good2 = "Resilient trees grow strong after every winter storm here."
    bad = FAILING
    assert prefer_cloze_passing(
        [bad, good1, good2], HEAD, "word", "B2", 2,
        _zipf({})) == [good1, good2]
    # Fewer passing than limit: failures backfill in original order.
    assert prefer_cloze_passing(
        [bad], HEAD, "word", "B2", 2, _zipf({})) == [bad]


# ---------------- end-to-end: dataset release ----------------

PASSING = "The resilient student studies hard every evening here."
FAILING = "Thou art a resilient learner studying daily here today."


def test_split_releases_cloze_fail_with_reason():
    item = {"kind": "word", "text": HEAD, "pool_level": "B2",
            "dataset_examples": [PASSING, FAILING]}
    kept, released = split_frozen_by_containment(item, _zipf({}))
    assert kept == [PASSING]
    assert released == [FAILING]
    assert item["content_flags"] == {FAILING: "cloze-archaic"}
    # An existing R31 flag always wins (never overwritten).
    item2 = {"kind": "word", "text": HEAD, "pool_level": "B2",
             "dataset_examples": [FAILING],
             "content_flags": {FAILING: "content-flag: creepy"}}
    kept2, released2 = split_frozen_by_containment(item2, _zipf({}))
    assert kept2 == [] and released2 == [FAILING]
    assert item2["content_flags"] == {FAILING: "content-flag: creepy"}


# ---------------- end-to-end: model regen via shared budget ----------------

CLEAN_CARD = {
    "word": HEAD,
    "phonetic": "IPA: /rɪˈzɪl.jənt/",
    "fa_meaning": "تاب‌آور",
    "fa_explanation": "کسی که پس از سختی به حالت عادی برمی‌گردد.",
    "synonyms": ["tough"],
    "antonyms": ["fragile"],
    "examples": [PASSING,
                 "Resilient trees grow strong after every storm."],
    "example_translations": [
        "دانش‌آموز تاب‌آور هر عصر سخت درس می‌خواند.",
        "درختان تاب‌آور پس از هر طوفان قوی رشد می‌کنند."],
    "grammar_tip": "صفت است و معمولا با be می‌آید.",
}

CLOZE_BAD_CARD = dict(
    CLEAN_CARD,
    examples=[FAILING, CLEAN_CARD["examples"][1]])


def _item():
    return {"kind": "word", "text": HEAD, "pool_level": "B2",
            "ipa_src": "model", "dataset_examples": []}


def test_generate_card_cloze_regen_once_then_valid():
    states = [dict(CLOZE_BAD_CARD), dict(CLEAN_CARD)]

    def transport(api_key, model, system, user):
        return json.dumps(states.pop(0))

    rec = generate_card(_item(), "key", transport=transport, model_calls={},
                        cloze_zipf_fn=_zipf({}))
    assert rec["valid"] is True
    assert rec["regen"] is True


def test_generate_card_cloze_fail_twice_records_reason():
    def transport(api_key, model, system, user):
        return json.dumps(dict(CLOZE_BAD_CARD))

    rec = generate_card(_item(), "key", transport=transport, model_calls={},
                        cloze_zipf_fn=_zipf({}))
    assert rec["valid"] is False
    assert rec["reason"] == "cloze-archaic"
    assert rec["regen"] is True  # single shared-budget regen was spent


# ---------------- end-to-end: gallery chip ----------------

def test_gallery_cloze_op_chip():
    rec = {"kind": "word", "text": HEAD,
           "dataset_examples": [PASSING, FAILING],
           "examples_src": ["dataset", "model"],
           "content_flags": {FAILING: "cloze-archaic"},
           "completion_flags": {"released_containment": [FAILING]},
           "en_def": "", "model_d": "", "en_source": "",
           "ipa": "", "ipa_src": "model"}
    html_out = render_diff_table(rec, dict(CLEAN_CARD))
    assert "cloze-archaic" in html_out


# ---------------- S5 preference (reuse by import) ----------------

def test_s5_prefers_cloze_passing_examples():
    from factory.pipeline.precard_pipeline import enrich_item

    good2 = "Resilient trees grow strong after every winter storm here."
    sense = {"glosses": ["able to recover quickly"], "tags": [],
             "examples": [{"text": "Too short here"},
                          {"text": FAILING},
                          {"text": PASSING},
                          {"text": good2}]}
    index = {"resilient": [{"pos": "adj",
                            "entry": {"pos": "adj", "sounds": [],
                                      "senses": [sense]}}]}

    def read_entry(row):
        return row["entry"]

    item = {"kind": "word", "text": HEAD, "pos": "adj",
            "pool_level": "B2"}
    enriched = enrich_item(
        item, {"sense_id": "resilient#0", "gloss": sense["glosses"][0]},
        index, read_entry, {}, zipf_fn=_zipf({}))
    assert enriched["dataset_examples"] == [PASSING, good2]
