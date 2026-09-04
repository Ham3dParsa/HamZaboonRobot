"""Hermetic tests for factory/card_pilot.py (card-gen pilot).

No network, no real pools: sampling uses inline rows, transport is an
injected stub, dry-run points at tmp fixtures.
"""

import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "factory"))
import card_pilot
from card_pilot import (
    assign_topic,
    build_prompts,
    build_timings,
    compute_quotas,
    generate_card,
    is_proper_noun_lemma,
    load_cards_jsonl,
    main,
    meta_leak_scan,
    render_gallery,
    resolve_phrase_en_def,
    resolve_word_en_def,
    sample_phrases,
    sample_words,
    validate_card_obj,
)
from llm_json import AuthError

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

VALID_CARD = {
    "word": "resilient",
    "phonetic": "IPA: /rɪˈzɪl.jənt/",
    "fa_meaning": "تاب‌آور",
    "fa_explanation": "کسی که پس از سختی به حالت عادی برمی‌گردد.",
    "synonyms": ["tough", "hardy"],
    "antonyms": ["fragile"],
    "examples": ["She is a resilient learner.", "Trees here are resilient."],
    "example_translations": ["او یادگیرنده‌ای تاب‌آور است.", "درختان اینجا تاب‌آورند."],
    "grammar_tip": "صفت است و معمولا با be می‌آید.",
}


def make_pool(per_level=6):
    return [{"lemma": "w-%s-%02d" % (lv, i), "pos": "noun", "cefr": lv}
            for lv in LEVELS for i in range(per_level)]


def make_judged(per_level=3):
    return [{"phrase": "p-%s-%02d" % (lv, i), "freq": 5,
             "verdict_level": lv, "failed_flag": False}
            for lv in LEVELS for i in range(per_level)]


def test_quotas_sum_and_spread():
    quotas = compute_quotas(14)
    assert sum(quotas.values()) == 14
    assert all(2 <= v <= 3 for v in quotas.values())
    assert compute_quotas(6) == {lv: 1 for lv in LEVELS}


def test_sampling_deterministic_same_seed():
    pool, judged = make_pool(), make_judged()
    words_a = sample_words(pool, 14, seed=7)
    words_b = sample_words(pool, 14, seed=7)
    assert [w["text"] for w in words_a] == [w["text"] for w in words_b]
    assert len(words_a) == 14
    phrases_a = sample_phrases(judged, 6, seed=7)
    phrases_b = sample_phrases(judged, 6, seed=7)
    assert [p["text"] for p in phrases_a] == [p["text"] for p in phrases_b]
    assert sorted(p["pool_level"] for p in phrases_a) == LEVELS


def test_generate_success_mocked():
    item = {"kind": "word", "text": "resilient", "pool_level": "B2"}
    calls = {}

    def transport(api_key, model, system, user):
        assert "resilient" in user  # user prompt is the item text
        assert "JSON" in system  # real prompt builder output
        return json.dumps(VALID_CARD)

    rec = generate_card(item, "key", transport=transport, model_calls=calls)
    assert rec["valid"] is True
    assert rec["card"]["word"] == "resilient"
    assert rec["model_used"] == card_pilot.MODELS[0]
    assert calls[card_pilot.MODELS[0]] == 1


def test_validation_fail_recorded_not_raised():
    item = {"kind": "word", "text": "xyz", "pool_level": "A1"}

    def transport(api_key, model, system, user):
        return "this is not json at all {{{"

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is False
    assert rec["card"] is None
    assert rec["error"]  # failure recorded with reason, no raise


def test_auth_aborts_loud():
    item = {"kind": "word", "text": "xyz", "pool_level": "A1"}

    def transport(api_key, model, system, user):
        raise AuthError("401")

    with pytest.raises(AuthError):
        generate_card(item, "key", transport=transport, model_calls={})


def test_rate_limit_recorded_not_raised():
    import urllib.error
    item = {"kind": "word", "text": "xyz", "pool_level": "A1"}
    calls = {}

    def transport(api_key, model, system, user):
        raise urllib.error.HTTPError("http://x", 429, "Too Many Requests", {}, None)

    rec = generate_card(item, "key", transport=transport, model_calls=calls)
    assert rec["valid"] is False
    assert "429" in rec["error"]  # recorded, never raised
    assert sum(calls.values()) == len(card_pilot.MODELS) * card_pilot.MAX_ATTEMPTS


def test_dry_run_writes_nothing(tmp_path):
    pool_path = tmp_path / "lemmas.csv"
    with open(pool_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["lemma", "pos", "cefr"])
        writer.writeheader()
        writer.writerows(make_pool(per_level=4))
    log_path = tmp_path / "judge.jsonl"
    with open(log_path, "w", encoding="utf-8") as handle:
        for row in make_judged(per_level=2):
            handle.write(json.dumps(row) + "\n")
    out_dir = tmp_path / "out"
    rc = main(["--dry-run", "--n-words", "6", "--n-phrases", "6",
               "--out-dir", str(out_dir),
               "--word-pool", str(pool_path), "--phrase-log", str(log_path)])
    assert rc == 0
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_gallery_renders_sections_from_stub_jsonl(tmp_path):
    records = [
        {"key": "w:a", "kind": "word", "text": "apple", "pool_level": "A1",
         "bot_level": "beginner", "model_used": "m1",
         "card": dict(VALID_CARD, word="apple"), "valid": True,
         "reason": "", "error": ""},
        {"key": "w:b", "kind": "word", "text": "brave", "pool_level": "A2",
         "bot_level": "beginner", "model_used": "m1",
         "card": dict(VALID_CARD, word="brave"), "valid": True,
         "reason": "", "error": ""},
        {"key": "p:c", "kind": "phrase", "text": "give up", "pool_level": "B1",
         "bot_level": "intermediate", "model_used": "", "card": None,
         "valid": False, "reason": "boom", "error": "boom"},
    ]
    stub = tmp_path / "cards.jsonl"
    with open(stub, "w", encoding="utf-8") as handle:
        for rec in records:
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
    cards = load_cards_jsonl(str(stub))
    html_out = render_gallery(cards, {"date_tehran": "d", "commit": "c",
                                      "model_calls": {"m1": 2}})
    assert html_out.count('class="card"') == 3
    assert "تأیید شد" in html_out
    assert "dir=\"rtl\"" in html_out
    for text in ("apple", "brave", "give up"):
        assert text in html_out


COMPACT_CARD = {
    "w": "resilient", "ph": "IPA: /riˈzɪl.jənt/",
    "m": "تاب‌آور", "x": "کسی که پس از سختی برمی‌گردد.",
    "s": ["tough"], "a": ["fragile"],
    "e": ["She is resilient.", "Trees are resilient."],
    "t": ["او تاب‌آور است.", "درختان تاب‌آورند."],
    "g": "صفت است.",
    "d": "able to recover quickly (preserved from dictionary)",
    "literal_fa": "تسلیم شدن کلمه‌به‌کلمه",
}


def test_en_def_preserved_in_prompt_and_compact_validates():
    item = {"kind": "word", "text": "resilient", "pool_level": "B2",
            "en_def": "able to recover quickly"}
    system, user, _ = build_prompts(item)
    assert "resilient" in user
    assert "able to recover quickly" in user  # en_def preserved in prompt
    assert '"d"' in user  # compact EN-definition key instructed
    assert "JSON" in system
    # Compact keys (incl. extra "d") still pass the REAL validator via
    # _expand_card_aliases — bot path reused, never forked.
    ok, card, _ = validate_card_obj(dict(COMPACT_CARD))
    assert ok is True
    assert card["word"] == "resilient"


def test_meta_leak_scan_leak_and_clean():
    leaking = dict(VALID_CARD, fa_explanation="good for beginners at A1 سطح")
    hits = meta_leak_scan(leaking)
    assert hits  # EN + FA level words detected
    assert meta_leak_scan(VALID_CARD) == []

    item = {"kind": "word", "text": "xyz", "pool_level": "A1"}
    states = [dict(VALID_CARD, fa_explanation="for beginners"),
              dict(VALID_CARD)]

    def transport(api_key, model, system, user):
        return json.dumps(states.pop(0))

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True  # regenerated once, then clean
    assert rec["regen"] is True

    def always_leak(api_key, model, system, user):
        return json.dumps(dict(VALID_CARD, fa_explanation="for beginners"))

    rec = generate_card(item, "key", transport=always_leak, model_calls={})
    assert rec["valid"] is False
    assert rec["reason"].startswith("meta-leak")


def test_proper_noun_pos_drop():
    # Stub POS data (no hardcoded name list in card_pilot): Mohammad/Corbyn
    # style entries carry only name/propn, a normal word passes.
    assert is_proper_noun_lemma("Mohammad", {"name"}) is True
    assert is_proper_noun_lemma("Corbyn", {"name", "propn"}) is True
    assert is_proper_noun_lemma("apple", {"noun", "verb", "name"}) is False
    assert is_proper_noun_lemma("apple", {"noun"}) is False
    assert is_proper_noun_lemma("give up", {"verb"}) is False
    assert is_proper_noun_lemma("Mohammad", set()) is False

    def read_entry(row):
        return row["entry"]

    entries = [{"pos": "name",
                "entry": {"senses": [{"glosses": ["a male given name"]}]}}]
    assert resolve_word_en_def(entries, "name", read_entry) == "a male given name"
    assert resolve_phrase_en_def(
        {"give up": [{"pos": "verb",
                      "entry": {"senses": [{"glosses": ["to surrender"]}]}}]},
        "give up", read_entry) == "to surrender"

    pool = [{"lemma": "w-%s" % lv, "pos": "noun", "cefr": lv}
            for lv in LEVELS]
    pos_sets = {("w-%s" % lv).lower(): ({"name"} if lv == "A1" else {"noun"})
                for lv in LEVELS}
    sample = sample_words(pool, 6, seed=7, pos_sets=pos_sets)
    assert all(w["text"] != "w-A1" for w in sample)  # name-only drops
    assert any(w["text"] == "w-B1" for w in sample)  # normal word passes

    judged = [{"phrase": "p-%s" % lv, "freq": 5, "verdict_level": lv,
               "failed_flag": False} for lv in LEVELS]
    phrases = sample_phrases(judged, 6, seed=7)
    assert all(p["proper_noun"] is None for p in phrases)  # null = not judged


def test_timings_payload_keys():
    timings = build_timings(1.0, 2.0, 3.0,
                            [{"key": "w:a", "seconds": 0.5}],
                            0.25, 0.1, 20)
    assert {"sample", "gloss_resolve", "generate", "validate", "render"} \
        <= set(timings)
    assert timings["generate"]["total"] == 3.0
    assert timings["generate"]["per_card"] == [{"key": "w:a", "seconds": 0.5}]
    assert "extrapolated_3500" in timings

    html_out = render_gallery(
        [{"key": "w:a", "kind": "word", "text": "apple", "pool_level": "A1",
          "bot_level": "beginner", "model_used": "m1", "en_def": "a fruit",
          "en_source": "dataset", "topic": "Food & Drink",
          "topic_method": "v16-prototype", "model_d": "", "literal_fa": None,
          "proper_noun": None,
          "card": dict(VALID_CARD, word="apple"), "valid": True,
          "reason": "", "error": ""}],
        {"date_tehran": "d", "commit": "c", "model_calls": {"m1": 1},
         "timings": timings})
    assert "a fruit" in html_out  # en_def with source tag
    assert "Food &amp; Drink" in html_out  # topic chip
    assert "v16-prototype" in html_out  # one-line method note
    assert "gloss_resolve" in html_out  # timings table

    topic = assign_topic("apple", "a fruit",
                         lookup=lambda text, gloss: "Food & Drink")
    assert topic == {"label": "Food & Drink", "method": "v16-prototype"}
