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
    compute_quotas,
    generate_card,
    load_cards_jsonl,
    main,
    render_gallery,
    sample_phrases,
    sample_words,
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
