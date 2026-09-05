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
    LEVEL_GUIDANCE,
    anchor_entry_pos_for_entries,
    anchor_item_en,
    assign_topic,
    batch_log_line,
    build_also_sense,
    build_completion_flags,
    build_prompts,
    build_timings,
    compute_quotas,
    en_word_count,
    example_contains_head,
    example_containment_ok,
    fa_field_ok,
    filter_examples_by_length,
    first_entry_ipa,
    generate_card,
    headword_leak_scan,
    is_fa_dominant,
    is_proper_noun_lemma,
    load_cards_jsonl,
    load_phrase_types,
    load_topic_vectors,
    main,
    meta_leak_scan,
    pick_anchor_sense,
    render_diff_header,
    render_final_card,
    render_gallery,
    resolve_dataset_examples,
    resolve_phrase_en_def,
    resolve_word_en_def,
    richness_counters,
    sample_phrases,
    sample_words,
    similarity_note,
    single_topic_vector,
    top_sense_candidates,
    translation_fidelity_ok,
    validate_card_obj,
    RunLogger,
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
         "sense_id": "apple#1", "en_def": "a fruit", "en_source": "dataset",
         "topic": "Food & Drink", "topic_method": "v16b-exact",
         "model_d": "", "literal_fa": "", "proper_noun": None,
         "leaks": [], "fa_dominant": True, "headword_leaks": [],
         "completion_flags": {"fields_filled": ["fa_meaning"],
                               "sense_review": True,
                               "nothing_to_complete": False},
         "similarity_note": 0.0,
         "card": dict(VALID_CARD, word="apple"), "valid": True,
         "reason": "", "error": ""},
        {"key": "w:b", "kind": "word", "text": "brave", "pool_level": "A2",
         "bot_level": "beginner", "model_used": "m1",
         "sense_id": "brave#0", "en_def": "showing courage",
         "en_source": "dataset", "topic": "Traits",
         "topic_method": "v16b-exact", "model_d": "", "literal_fa": "",
         "proper_noun": None, "leaks": [], "fa_dominant": True,
         "headword_leaks": [],
         "completion_flags": {"fields_filled": ["fa_meaning"],
                               "sense_review": True,
                               "nothing_to_complete": False},
         "similarity_note": 0.0,
         "card": dict(VALID_CARD, word="brave"), "valid": True,
         "reason": "", "error": ""},
        {"key": "p:c", "kind": "phrase", "text": "give up", "pool_level": "B1",
         "bot_level": "intermediate", "model_used": "", "card": None,
         "sense_id": "", "en_def": "", "topic": "", "topic_method": "",
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
    # Stage strip rows present (pipeline order).
    for row in ("استخر", "لنگر حس", "موضوع", "پیش‌کارت",
                "تکمیل مدل", "کنترل‌ها"):
        assert row in html_out
    # Final-card learner block present + separated from the audit strip.
    assert "کارت نهایی" in html_out
    assert 'class="final' in html_out
    assert "<details>" in html_out  # en-def + raw-JSON collapsibles
    # Sticky mini-nav: exactly one anchor per card, zero-based.
    assert html_out.count('href="#card-') == 3
    for idx in range(3):
        assert 'id="card-%d"' % idx in html_out
    assert 'id="card-3"' not in html_out


def test_render_only_rebuilds_html_without_touching_inputs(tmp_path):
    from card_pilot import render_only
    cards = [{"key": "w:a", "kind": "word", "text": "apple",
              "pool_level": "A1", "bot_level": "beginner",
              "model_used": "m1", "card": dict(VALID_CARD, word="apple"),
              "valid": True, "reason": "", "error": ""}]
    (tmp_path / "cards.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in cards),
        encoding="utf-8")
    (tmp_path / "timings.json").write_text(json.dumps({"n_items": 1}),
                                           encoding="utf-8")
    before_cards = (tmp_path / "cards.jsonl").read_bytes()
    before_timings = (tmp_path / "timings.json").read_bytes()
    report = tmp_path / "sub" / "gallery.html"
    assert render_only(str(tmp_path), str(report)) == 1
    assert report.exists()
    assert (tmp_path / "cards.jsonl").read_bytes() == before_cards
    assert (tmp_path / "timings.json").read_bytes() == before_timings
    html_out = report.read_text(encoding="utf-8")
    assert 'id="card-0"' in html_out


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

    item = {"kind": "word", "text": "resilient", "pool_level": "A1"}
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
          "sense_id": "apple#1",
          "en_source": "dataset", "topic": "Food & Drink",
          "topic_method": "v16b-exact", "model_d": "", "literal_fa": None,
          "proper_noun": None,
          "completion_flags": {"fields_filled": ["fa_meaning"],
                               "sense_review": True,
                               "nothing_to_complete": False},
          "similarity_note": 0.0,
          "card": dict(VALID_CARD, word="apple"), "valid": True,
          "reason": "", "error": ""}],
        {"date_tehran": "d", "commit": "c", "model_calls": {"m1": 1},
         "timings": timings})
    assert "a fruit" in html_out  # en_def with source tag
    assert "Food &amp; Drink" in html_out  # topic chip
    assert "v16b-exact" in html_out  # one-line method note
    assert "gloss_resolve" in html_out  # timings table
    assert "apple#1" in html_out  # R6 sense anchor block
    assert "fields_filled" in html_out or "تکمیل شکاف" in html_out

    topic = assign_topic("apple", "a fruit",
                         lookup=lambda text, gloss: "Food & Drink")
    assert topic == {"label": "Food & Drink", "method": "v16b-exact",
                     "vector": [{"label": "Food & Drink", "weight": 1.0}]}


def test_anchor_prefers_higher_scored_sense_over_first_gloss():
    # First gloss is an alt-form stub (v14 penalty 0.50); the clean second
    # sense must win even though it is not first.
    def read_entry(row):
        return row["entry"]

    entries = [
        {"pos": "noun", "entry": {"pos": "noun", "senses": [
            {"glosses": ["Alternative spelling of xyz"], "tags": []}]}},
        {"pos": "noun", "entry": {"pos": "noun", "senses": [
            {"glosses": ["able to recover quickly"], "tags": []}]}},
    ]
    assert resolve_word_en_def(entries, "noun", read_entry) == \
        "able to recover quickly"
    sid, gloss = pick_anchor_sense("resilient", entries, "noun", read_entry)
    assert gloss == "able to recover quickly"
    assert sid == "resilient#1"
    # Slang tag (0.60) also loses to a clean sense.
    slang = [{"pos": "noun", "entry": {"pos": "noun", "senses": [
        {"glosses": ["first slang gloss"], "tags": ["slang"]},
        {"glosses": ["clean second gloss"], "tags": []}]}}]
    assert resolve_word_en_def(slang, "noun", read_entry) == \
        "clean second gloss"


def test_fa_dominant_pass_fail():
    assert is_fa_dominant("تاب‌آور",
                          "کسی که پس از سختی برمی‌گردد.") is True
    assert is_fa_dominant("resilient meaning", "explanation here") is False
    assert is_fa_dominant("", "") is False


def test_headword_leak_detect():
    leaking = dict(VALID_CARD, fa_explanation="resilient بودن یعنی تاب‌آوری")
    assert headword_leak_scan("resilient", "word", leaking) == ["resilient"]
    clean = dict(VALID_CARD)
    assert headword_leak_scan("resilient", "word", clean) == []
    # Phrases: any component token len>=3 leaks; short tokens ignored.
    phrase_leak = dict(VALID_CARD, fa_meaning="give یعنی دادن")
    assert "give" in headword_leak_scan("give up", "phrase", phrase_leak)
    assert headword_leak_scan("give up", "phrase", clean) == []
    assert "on" not in headword_leak_scan("go on", "phrase",
                                          dict(VALID_CARD,
                                               fa_meaning="on یعنی روشن"))

    # R7 prompt rules present + violation -> 1 regen then valid=False.
    item = {"kind": "word", "text": "resilient", "pool_level": "B2"}
    _, user, _ = build_prompts(item)
    assert "Persian-script" in user
    assert "headword" in user.lower()

    def fa_fail(api_key, model, system, user):
        return json.dumps(dict(VALID_CARD, fa_meaning="resilient",
                               fa_explanation="plain english explanation"))

    rec = generate_card(item, "key", transport=fa_fail, model_calls={})
    assert rec["valid"] is False
    assert rec["reason"] == "fa-dominant" or "headword-leak" in rec["reason"] \
        or rec["reason"] == "fa-dominant"

    states = [dict(VALID_CARD, fa_meaning="resilient",
                       fa_explanation="english",
                       grammar_tip="An english grammar note here"),
                  dict(VALID_CARD)]
    states_rev = list(reversed(states))

    def once_bad(api_key, model, system, user):
        return json.dumps(states_rev.pop())

    rec = generate_card(
        {"kind": "word", "text": "resilient", "pool_level": "A1"}, "key",
        transport=once_bad, model_calls={})
    assert rec["valid"] is True
    assert rec["regen"] is True


def test_generate_card_regen_once_shared_budget():
    # V7: containment/fidelity join the same single regen budget — a card
    # failing containment then returning clean passes with regen=True.
    bad = dict(
        VALID_CARD,
        examples=["Trees are green here today.",
                  "Birds sing sweetly every morning."],
        example_translations=["درختان امروز سبز هستند.",
                              "پرندگان هر صبح زیبا می‌خوانند."])
    states = [bad, dict(VALID_CARD)]

    def once_bad(api_key, model, system, user):
        return json.dumps(states.pop(0))

    rec = generate_card({"kind": "word", "text": "resilient",
                         "pool_level": "A1"}, "key",
                        transport=once_bad, model_calls={})
    assert rec["valid"] is True
    assert rec["regen"] is True


def test_gapfill_flags_and_similarity_note():
    _, user, _ = build_prompts({"kind": "word", "text": "x",
                                "pool_level": "A1",
                                "en_def": "able to recover quickly"})
    assert "Fill ONLY empty/missing fields" in user
    assert "do NOT restate the given en_def" in user
    assert "REVIEW synonyms/antonyms/examples" in user
    flags = build_completion_flags(VALID_CARD)
    assert flags["sense_review"] is True
    assert "fa_meaning" in flags["fields_filled"]
    assert isinstance(flags["nothing_to_complete"], bool)
    assert similarity_note("able to recover quickly",
                           "able to recover quickly") == 1.0
    assert 0.0 <= similarity_note("able to recover quickly",
                                  "something else") <= 1.0

    item = {"kind": "word", "text": "resilient", "pool_level": "B2",
            "en_def": "able to recover quickly", "sense_id": "resilient#1"}

    def transport(api_key, model, system, user):
        return json.dumps(dict(COMPACT_CARD))

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True
    assert rec["completion_flags"]["sense_review"] is True
    assert rec["completion_flags"]["fields_filled"]
    assert isinstance(rec["similarity_note"], float)
    assert rec["sense_id"] == "resilient#1"


def test_topic_v16b_exact_topup_leg_mocked(tmp_path):
    # Deterministic leg hit -> v16b-exact tag, no LLM.
    hit = assign_topic("apple", "a fruit",
                       lookup=lambda t, g: "Food & Drink")
    assert hit == {"label": "Food & Drink", "method": "v16b-exact",
                   "vector": [{"label": "Food & Drink", "weight": 1.0}]}
    # Other -> LLM top-up leg by import (mocked transport), resume separate.
    prog = tmp_path / "pilot_topic_progress.json"

    def llm_transport(api_key, model, user_text):
        return json.dumps({"results": [
            {"lemma": "zebra",
             "senses": [{"sense_id": "zebra#0", "topic_id": 9,
                         "topic_label": "Animals & Living Beings",
                         "confidence": 0.9,
                         "vector": [{"topic_id": 9,
                                     "topic_label": "Animals & Living Beings",
                                     "weight": 1.0}]}]}]})

    relabeled = assign_topic("zebra", "an animal", sense_id="zebra#0",
                             lookup=lambda t, g: None,
                             llm_transport=llm_transport,
                             progress_path=prog, api_key="k",
                             model_calls={})
    assert relabeled == {"label": "Animals & Living Beings",
                         "method": "v16b-exact",
                         "vector": [{"label": "Animals & Living Beings",
                                     "weight": 1.0}]}
    assert prog.exists()  # pilot resume separate from v16b originals
    # No transport -> Other stays Other, still tagged v16b-exact.
    other = assign_topic("zebra", "an animal",
                         lookup=lambda t, g: None)
    assert other == {"label": "Other / Abstract", "method": "v16b-exact",
                     "vector": [{"label": "Other / Abstract",
                                 "weight": 1.0}]}


def test_anchor_item_sets_sense_id_and_en_def():
    def read_entry(row):
        return row["entry"]

    item = {"kind": "word", "text": "Bank", "pos": "noun"}
    index = {"bank": [
        {"pos": "noun", "entry": {"pos": "noun", "senses": [
            {"glosses": ["Alternative spelling of xyz"], "tags": []}]}},
        {"pos": "noun", "entry": {"pos": "noun", "senses": [
            {"glosses": ["a financial institution"], "tags": []}]}},
    ]}
    anchor_item_en(item, index, read_entry)
    assert item["en_def"] == "a financial institution"
    assert item["sense_id"] == "bank#1"


def test_ipa_resolve_prefers_anchored_entry_sounds():
    # R10: IPA comes from the ANCHORED sense's entry (same read as the
    # gloss anchor) — here the second entry wins the anchor, so its IPA
    # wins even though the first entry also has sounds.
    def read_entry(row):
        return row["entry"]

    entries = [
        {"pos": "noun", "entry": {"pos": "noun",
                                  "sounds": [{"ipa": "/first/"}],
                                  "senses": [{"glosses": ["Alternative spelling of xyz"],
                                              "tags": []}]}},
        {"pos": "noun", "entry": {"pos": "noun",
                                  "sounds": [{"enpr": "skipped"},
                                             {"ipa": "/second/"}],
                                  "senses": [{"glosses": ["able to recover quickly"],
                                              "tags": []}]}},
    ]
    item = {"kind": "word", "text": "resilient", "pos": "noun"}
    anchor_item_en(item, {"resilient": entries}, read_entry)
    assert item["sense_id"] == "resilient#1"
    assert item["en_def"] == "able to recover quickly"
    assert item["ipa"] == "/second/"  # first ipa string of anchored entry
    assert item["ipa_src"] == "dataset"
    # No sounds anywhere -> gap left for the model.
    nosound = [{"pos": "noun", "entry": {"pos": "noun", "sounds": [],
                                         "senses": [{"glosses": ["plain gloss"],
                                                     "tags": []}]}}]
    bare = {"kind": "word", "text": "xyz", "pos": "noun"}
    anchor_item_en(bare, {"xyz": nosound}, read_entry)
    assert bare["ipa"] == ""
    assert bare["ipa_src"] == "model"
    assert first_entry_ipa({}) == ""
    # Dataset IPA is preserved via the compact "ph" key in the prompt.
    _, user, _ = build_prompts(dict(item, pool_level="B2"))
    assert "/second/" in user
    assert '"ph"' in user
    _, user_bare, _ = build_prompts(dict(bare, pool_level="A1"))
    assert '"ph"' not in user_bare


def test_example_length_filter_drops_short_and_long():
    # R13: dataset filter 8-20 words inclusive (English word count).
    short = "She runs daily now"  # 4 words -> dropped
    keep8 = "One two three four five six seven eight"  # 8 -> kept
    keep20 = " ".join(["word"] * 20)  # 20 -> kept
    drop21 = " ".join(["word"] * 21)  # 21 -> dropped
    assert en_word_count(short) == 4
    assert en_word_count(keep8) == 8
    assert filter_examples_by_length(
        [short, keep8, keep20, drop21]) == [keep8, keep20]
    # Tatoeba leg is already length-suitable: only >20w is capped.
    assert filter_examples_by_length([short], loose_cap=True) == [short]
    assert filter_examples_by_length([drop21], loose_cap=True) == []


def test_dataset_examples_anchor_then_tatoeba():
    # R11: anchored-sense kaikki examples first, then the tatoeba lemma
    # list, until 2 examples.
    def read_entry(row):
        return row["entry"]

    kaikki_ok = ("She showed remarkable resilience after the long "
                 "difficult winter season here today")  # 12 words
    sense = {"glosses": ["able to recover quickly"], "tags": [],
             "examples": [{"text": "Too short here"},  # 3w -> dropped
                          {"text": kaikki_ok}]}
    index = {"resilient": [{"pos": "adj",
                            "entry": {"pos": "adj", "sounds": [],
                                      "senses": [sense]}}]}
    tatoeba_extra = ("Tatoeba fallback example sentence for the pilot "
                     "test case here today please")
    item = {"kind": "word", "text": "resilient", "pos": "adj"}
    resolve_dataset_examples(item, index, read_entry,
                             {"resilient": [tatoeba_extra]})
    assert item["dataset_examples"] == [kaikki_ok, tatoeba_extra]


def test_frozen_dataset_examples_preserved_end_to_end():
    # R11: frozen dataset examples survive generation untouched (mocked
    # transport); per-example sources recorded; prompt fills only gaps.
    frozen = ["She showed remarkable resilience after the long difficult "
              "winter season here today",
              "Tatoeba fallback example shows resilient habits for the "
              "pilot test case today"]
    frozen_fa = ["او پس از زمستان سخت تاب‌آوری چشمگیری نشان داد امروز.",
                 "این مثال تاب‌آوری عادت‌های روزمره او را نشان می‌دهد امروز."]
    item = {"kind": "word", "text": "resilient", "pool_level": "B2",
            "en_def": "able to recover quickly", "sense_id": "resilient#1",
            "ipa_src": "model", "dataset_examples": list(frozen)}
    _, user, _ = build_prompts(item)
    assert "FROZEN" in user
    assert "Both example slots are filled" in user
    assert "~15 words max" in user

    def transport(api_key, model, system, user_text):
        return json.dumps(dict(
            VALID_CARD,
            examples=list(frozen),
            example_translations=list(frozen_fa)))

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True
    assert rec["card"]["examples"] == frozen  # never rewritten
    assert rec["examples_src"] == ["dataset", "dataset"]
    assert rec["dataset_examples"] == frozen
    assert rec["long_example"] == []  # both <= 20w, no flag

    # Partial fill: one frozen slot + one model slot.
    partial = dict(item, dataset_examples=[frozen[0]])
    _, user2, _ = build_prompts(partial)
    assert "Fill ONLY the 1 missing example slot" in user2

    def transport2(api_key, model, system, user_text):
        return json.dumps(dict(
            VALID_CARD,
            examples=[frozen[0], "Trees here show great resilience every day"],
            example_translations=[
                frozen_fa[0],
                "درختان هر روز تاب‌آوری چشمگیری از خود نشان می‌دهند اینجا."]))

    rec2 = generate_card(partial, "key", transport=transport2,
                         model_calls={})
    assert rec2["valid"] is True
    assert rec2["examples_src"] == ["dataset", "model"]


def test_topic_vector_recorded(tmp_path):
    # R12: full 1-3 entry vector from leg-2/file lookup; single-label
    # path unchanged; record carries it through generation.
    vec = [{"label": "Sports & Leisure", "weight": 0.6},
           {"label": "Other / Abstract", "weight": 0.4}]
    hit = assign_topic("sprint", "to run fast",
                       lookup=lambda t, g: "Sports & Leisure",
                       sense_id="sprint#3",
                       vector_lookup={"sprint#3": vec})
    assert hit["vector"] == vec
    assert hit["label"] == "Sports & Leisure"
    single = assign_topic("y", "g", lookup=lambda t, g: "Foo")
    assert single["vector"] == [{"label": "Foo", "weight": 1.0}]
    assert single_topic_vector("Foo") == [{"label": "Foo", "weight": 1.0}]
    # File loader shape: topic_vectors-v16b.json list form.
    pool = tmp_path / "topic_vectors.json"
    pool.write_text(json.dumps(
        [{"lemma": "sprint",
          "vectors": [{"sense_id": "sprint#3",
                       "vector": [{"topic_id": 14,
                                   "topic_label": "Sports & Leisure",
                                   "weight": 0.6},
                                  {"topic_id": 16,
                                   "topic_label": "Other / Abstract",
                                   "weight": 0.4}]}]}]), encoding="utf-8")
    mapping = load_topic_vectors(str(pool))
    assert mapping["sprint#3"] == vec
    assert load_topic_vectors(str(tmp_path / "missing.json")) == {}

    item = {"kind": "word", "text": "sprint", "pool_level": "B1",
            "topic": "Sports & Leisure", "topic_method": "v16b-exact",
            "topic_vector": vec, "ipa_src": "model"}

    def transport(api_key, model, system, user):
        return json.dumps(dict(
            VALID_CARD, word="sprint",
            examples=["She won the race with a final sprint today.",
                      "His sprint to the finish line amazed everyone here."],
            example_translations=[
                "او با یک دوی سرعت نهایی امروز در مسابقه پیروز شد.",
                "دوی سرعت او تا خط پایان همه حاضران را شگفت‌زده کرد."]))

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True
    assert rec["topic_vector"] == vec


def test_gallery_diff_operation_chips():
    # R14: diff rows carry pre-card | operation | final; warm palette;
    # topic vector shows primary + weighted secondary.
    card = dict(VALID_CARD, word="apple")
    rec = {"key": "w:apple", "kind": "word", "text": "apple",
           "pool_level": "A1", "bot_level": "beginner", "model_used": "m1",
           "sense_id": "apple#1", "en_def": "a fruit",
           "en_source": "dataset", "topic": "Food & Drink",
           "topic_method": "v16b-exact",
           "topic_vector": [{"label": "Food & Drink", "weight": 0.6},
                            {"label": "Health", "weight": 0.4}],
           "ipa": "/æpəl/", "ipa_src": "dataset",
           "dataset_examples": list(card["examples"]),
           "examples_src": ["dataset", "dataset"],
           "long_example": [],
           "model_d": "", "literal_fa": "", "proper_noun": None,
           "leaks": [], "fa_dominant": True, "headword_leaks": [],
           "completion_flags": {"fields_filled": ["fa_meaning"],
                                 "sense_review": True,
                                 "nothing_to_complete": False},
           "similarity_note": 0.0, "card": card, "valid": True,
           "reason": "", "error": ""}
    html_out = render_gallery(
        [rec], {"date_tehran": "d", "commit": "c",
                "model_calls": {"m1": 1}})
    assert "نگه‌داشت" in html_out  # dataset-kept operations
    assert "پرشده" in html_out  # model-filled fa fields
    assert "پیش‌کارت" in html_out and "عملیات" in html_out
    assert "نهایی" in html_out
    assert "[dataset]" in html_out  # per-value source tags
    assert "#faf7f0" in html_out and "#b3552e" in html_out  # warm palette
    assert "600px" in html_out  # narrow-screen stacking
    assert "tchip primary" in html_out
    assert "0.40" in html_out  # secondary weight, tabular-nums


def test_grammar_tip_under_fa_dominant():
    # R15: grammar_tip counted with fa_meaning+fa_explanation combined.
    assert is_fa_dominant("تاب‌آور", "کسی که برمی‌گردد.",
                          "صفت است.") is True
    assert is_fa_dominant("تاب‌آور", "کسی که برمی‌گردد.",
                          "Use be with adjectives always here") is False
    assert is_fa_dominant("", "") is False  # backward-compat default
    _, user, _ = build_prompts({"kind": "word", "text": "x",
                                "pool_level": "A1"})
    assert "grammar_tip" in user
    assert "Persian-script" in user

    latin_tip = ("This is a long english only grammar explanation about "
                 "adjectives with many latin words and no persian at all")
    states = [dict(VALID_CARD, grammar_tip=latin_tip), dict(VALID_CARD)]

    def once_bad(api_key, model, system, user_text):
        return json.dumps(states.pop(0))

    rec = generate_card({"kind": "word", "text": "resilient",
                         "pool_level": "A1"}, "key",
                        transport=once_bad, model_calls={})
    assert rec["valid"] is True  # 1 regen, then clean
    assert rec["regen"] is True
    assert rec["fa_dominant"] is True

    def always_latin(api_key, model, system, user_text):
        return json.dumps(dict(VALID_CARD, grammar_tip=latin_tip))

    rec = generate_card({"kind": "word", "text": "resilient",
                         "pool_level": "A1"}, "key",
                        transport=always_latin, model_calls={})
    assert rec["valid"] is False
    assert rec["reason"] == "fa-dominant"


def four_sense_entries():
    return [{"pos": "noun", "entry": {"pos": "noun", "sounds": [],
                                      "senses": [
        {"glosses": ["Alternative spelling of xyz"], "tags": []},
        {"glosses": ["clean second gloss"], "tags": []},
        {"glosses": ["third gloss here"], "tags": ["slang"]},
        {"glosses": ["fourth gloss here"], "tags": []}]}}]


def test_top_sense_candidates_ranked():
    # R17: ranked top-3 [{sense_id, gloss, score}] from the same scorer.
    def read_entry(row):
        return row["entry"]

    cands = top_sense_candidates("Bank", four_sense_entries(), "noun",
                                 read_entry)
    assert [(c["sense_id"], c["score"]) for c in cands] == [
        ("bank#1", 1.0), ("bank#3", 1.0), ("bank#2", 0.6)]
    assert cands[0]["gloss"] == "clean second gloss"
    assert top_sense_candidates("Bank", [], "noun", read_entry) == []

    item = {"kind": "word", "text": "Bank", "pos": "noun"}
    anchor_item_en(item, {"bank": four_sense_entries()}, read_entry)
    assert item["sense_id"] == "bank#1"  # anchor unchanged
    assert item["sense_candidates"] == cands  # audit trail rides along
    assert item["also_sense"] == {
        "sense_id": "bank#3", "gloss": "fourth gloss here",
        "topic": None, "topic_method": card_pilot.ALSO_TOPIC_UNASSIGNED}

    # Cheap vector leg fills the also-sense topic; no LLM involved.
    item2 = {"kind": "word", "text": "Bank", "pos": "noun"}
    anchor_item_en(item2, {"bank": four_sense_entries()}, read_entry,
                   vector_lookup={"bank#3": [{"label": "Finance",
                                              "weight": 1.0}]})
    assert item2["also_sense"] == {
        "sense_id": "bank#3", "gloss": "fourth gloss here",
        "topic": "Finance", "topic_method": "v16b-exact"}

    # R18: single sense -> None, card unchanged.
    assert build_also_sense([{"sense_id": "x#0", "gloss": "g",
                              "score": 1.0}]) is None
    assert build_also_sense([]) is None


def test_also_sense_gallery_line_present_and_absent():
    # R18: "نیز:" line under the anchor; single-sense cards unchanged.
    base = {"key": "w:b", "kind": "word", "text": "bank",
            "pool_level": "A1", "bot_level": "beginner", "model_used": "m1",
            "sense_id": "bank#1", "en_def": "clean second gloss",
            "en_source": "dataset", "topic": "Finance",
            "topic_method": "v16b-exact",
            "sense_candidates": [
                {"sense_id": "bank#1", "gloss": "clean second gloss",
                 "score": 1.0},
                {"sense_id": "bank#3", "gloss": "fourth gloss here",
                 "score": 1.0}],
            "also_sense": {"sense_id": "bank#3",
                           "gloss": "fourth gloss here", "topic": None,
                           "topic_method": card_pilot.ALSO_TOPIC_UNASSIGNED},
            "card": dict(VALID_CARD, word="bank"), "valid": True,
            "reason": "", "error": ""}
    html_out = render_diff_header(base)
    assert "نامزدها" in html_out  # R17 ranked candidates
    assert "bank#3" in html_out
    assert "نیز:" in html_out  # R18 second-sense line
    assert card_pilot.ALSO_TOPIC_UNASSIGNED in html_out

    single = dict(base, sense_candidates=[base["sense_candidates"][0]],
                  also_sense=None)
    html_single = render_diff_header(single)
    assert "نیز:" not in html_single  # unchanged


def test_richness_counters_and_header():
    # R17: {ipa_dataset_pct, examples_dataset_pct, topics_non_other_pct}.
    cards = [
        {"ipa_src": "dataset", "examples_src": ["dataset", "model"],
         "topic": "Food & Drink"},
        {"ipa_src": "model", "examples_src": ["model", "model"],
         "topic": "Other / Abstract"},
        {"ipa_src": "dataset", "examples_src": [], "topic": ""},
    ]
    assert richness_counters(cards) == {
        "ipa_dataset_pct": 66.7, "examples_dataset_pct": 25.0,
        "topics_non_other_pct": 33.3}
    assert richness_counters([]) == {
        "ipa_dataset_pct": 0.0, "examples_dataset_pct": 0.0,
        "topics_non_other_pct": 0.0}
    html_out = render_gallery(
        cards, {"date_tehran": "d", "commit": "c", "model_calls": {},
                "timings": {"n_items": 3,
                            "richness": richness_counters(cards)}})
    assert "ipa_dataset" in html_out
    assert "66.7" in html_out
    plain = render_gallery(cards, {"date_tehran": "d", "commit": "c",
                                   "model_calls": {}})
    assert "غنای دیتاست" not in plain  # absent without richness


def test_phrase_type_display_both_paths(tmp_path):
    # Phrase display: known type chip + flag vs missing log = unjudged.
    log = tmp_path / "phrase_type_log.jsonl"
    with open(str(log), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"phrase": "give up",
                                 "phrase_type": "phrasal-verb",
                                 "proper_noun": False, "applied_keep": True,
                                 "model": "m"}) + "\n")
    mapping = load_phrase_types(str(log))
    assert mapping == {"give up": {"phrase_type": "phrasal-verb",
                                   "applied_keep": True}}
    assert load_phrase_types(str(tmp_path / "missing.jsonl")) == {}
    assert load_phrase_types(str(tmp_path / "nope" / "x.jsonl")) == {}

    phrase = {"key": "p:g", "kind": "phrase", "text": "give up",
              "pool_level": "B1", "bot_level": "intermediate",
              "model_used": "m1", "card": None, "valid": False,
              "reason": "boom", "error": "boom"}
    known = render_diff_header(dict(phrase), mapping)
    assert "phrasal-verb" in known
    assert "applied_keep" in known
    unjudged = render_diff_header(dict(phrase), {})
    assert "نوع: قضاوت‌نشده" in unjudged
    assert "phrasal-verb" not in unjudged
    word = dict(phrase, kind="word", text="apple")
    assert "نوع عبارت" not in render_diff_header(word, mapping)


# ---------------- V7: per-field fa, containment, fidelity ----------------

def test_fa_dominant_per_field_closes_combined_loophole():
    # V7: an English-heavy fa_meaning masked by a long Persian
    # fa_explanation under the old combined count now fails per-field.
    assert is_fa_dominant(
        "resilient tough hardy learner trait",
        "کسی که پس از سختی‌های فراوان زندگی به حالت عادی و طبیعی برمی‌گردد."
    ) is False
    assert is_fa_dominant("تاب‌آور", "کسی که برمی‌گردد.") is True
    # Loanword leniency: at most 3 Latin chars in fa_meaning pass.
    assert is_fa_dominant("تلویزیون TV", "وسیله‌ای برای تماشای برنامه‌ها."
                          ) is True
    assert fa_field_ok("تلویزیون TV", max_latin=3) is True
    assert fa_field_ok("plain english explanation") is False
    assert fa_field_ok("") is False
    assert fa_field_ok("123") is False  # digits only: no Persian script
    assert fa_field_ok("صفت است و معمولا با be می‌آید.") is True


def test_example_containment_word_and_phrase():
    # Words: exact headword or crude stem ("resilience" for "resilient",
    # "running" for "run"); phrases: substring, case-insensitive.
    assert example_contains_head("She is a resilient learner.",
                                 "resilient", "word") is True
    assert example_contains_head("She showed great resilience daily.",
                                 "resilient", "word") is True
    assert example_contains_head("He is running late today.",
                                 "run", "word") is True
    assert example_contains_head("Trees are green here today.",
                                 "resilient", "word") is False
    assert example_containment_ok("resilient", "word", VALID_CARD) is True
    assert example_contains_head("Never GIVE UP hope.", "give up",
                                 "phrase") is True
    assert example_contains_head("Never surrender hope.", "give up",
                                 "phrase") is False
    assert example_containment_ok(
        "give up", "phrase",
        {"examples": ["Never give up hope.", "Do not give up yet."]}
    ) is True
    assert example_containment_ok("give up", "phrase", {"examples": []}
                                  ) is False


def test_example_containment_regen_once_then_invalid():
    bad = dict(
        VALID_CARD,
        examples=["Trees are green here today.",
                  "Birds sing sweetly every morning."],
        example_translations=["درختان امروز سبز هستند.",
                              "پرندگان هر صبح زیبا می‌خوانند."])
    states = [bad, dict(VALID_CARD)]

    def once_bad(api_key, model, system, user):
        return json.dumps(states.pop(0))

    rec = generate_card({"kind": "word", "text": "resilient",
                         "pool_level": "A1"}, "key",
                        transport=once_bad, model_calls={})
    assert rec["valid"] is True
    assert rec["regen"] is True

    def always_bad(api_key, model, system, user):
        return json.dumps(bad)

    rec = generate_card({"kind": "word", "text": "resilient",
                         "pool_level": "A1"}, "key",
                        transport=always_bad, model_calls={})
    assert rec["valid"] is False
    assert rec["reason"] == "example-containment"


def test_translation_fidelity_gate_and_prompt_line():
    assert translation_fidelity_ok(VALID_CARD) is True
    short = dict(VALID_CARD, example_translations=["کوتاه.", "کم."])
    assert translation_fidelity_ok(short) is False
    assert translation_fidelity_ok(
        {"examples": ["a b"], "example_translations": []}) is False
    _, user, _ = build_prompts({"kind": "word", "text": "x",
                                "pool_level": "A1"})
    assert "preserve all named entities" in user

    states = [short, dict(VALID_CARD)]

    def once_short(api_key, model, system, user_text):
        return json.dumps(states.pop(0))

    rec = generate_card({"kind": "word", "text": "resilient",
                         "pool_level": "A1"}, "key",
                        transport=once_short, model_calls={})
    assert rec["valid"] is True
    assert rec["regen"] is True

    def always_short(api_key, model, system, user_text):
        return json.dumps(short)

    rec = generate_card({"kind": "word", "text": "resilient",
                         "pool_level": "A1"}, "key",
                        transport=always_short, model_calls={})
    assert rec["valid"] is False
    assert rec["reason"] == "translation-fidelity"


# ---------------- V7: metadata merge (record siblings) ----------------

def test_validator_tolerates_but_strips_extra_metadata_keys():
    # services.ai.ai.validate_card tolerates unknown keys (no error) but
    # returns a fresh dict — extras are stripped, so V7 metadata lives as
    # sibling keys on the RECORD, never inside the validated card.
    obj = dict(COMPACT_CARD, sense_id="resilient#1",
               topic_vector=[{"label": "Traits", "weight": 1.0}],
               pool_level="B2")
    ok, card, _ = validate_card_obj(obj)
    assert ok is True
    assert "sense_id" not in card
    assert "topic_vector" not in card
    assert "pool_level" not in card


def test_metadata_merged_on_record_after_validation():
    item = {"kind": "word", "text": "resilient", "pool_level": "B2",
            "sense_id": "resilient#1",
            "topic": "Traits", "topic_method": "v16b-exact",
            "topic_vector": [{"label": "Traits", "weight": 1.0}],
            "ipa_src": "model"}

    def transport(api_key, model, system, user):
        return json.dumps(dict(VALID_CARD))

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True
    assert rec["sense_id"] == "resilient#1"  # code merge, no prompt change
    assert rec["topic_vector"] == [{"label": "Traits", "weight": 1.0}]
    assert rec["pool_level"] == "B2"


# ---------------- V7: compact progress logging ----------------

def test_batch_log_line_format():
    assert batch_log_line("s1", 1, 4, 7, 1, {"m": 3}) == \
        "Ss1 batch 1/4 ok=7 fail=1 model=3"
    assert batch_log_line("gen", 2, 2, 1, 0, 5) == \
        "Sgen batch 2/2 ok=1 fail=0 model=5"
    assert batch_log_line("s0", 1, 1, 0, 0, {}) == \
        "Ss0 batch 1/1 ok=0 fail=0 model=0"


def test_run_logger_writes_stage_lines(tmp_path):
    logger = RunLogger(str(tmp_path / "run.log"))
    logger.stage_start("generate")
    logger.stage_end("generate", ok=1, fail=0)
    logger.close()
    text = (tmp_path / "run.log").read_text(encoding="utf-8")
    assert "stage generate start" in text
    assert "stage generate end ok=1 fail=0 secs=" in text


# ---------------- V7: final-card header ----------------

def test_final_card_header_headword_ipa_guidance_meta():
    card = dict(VALID_CARD, word="resilient")
    rec = {"text": "resilient", "pool_level": "B2",
           "sense_id": "resilient#1", "topic": "Traits",
           "en_def": "able to recover quickly"}
    html_out = render_final_card(rec, card)
    # Block starts with headword + IPA together (bot-style header).
    assert "final-head" in html_out
    assert html_out.index("final-head") < html_out.index("fld-label")
    assert "resilient" in html_out
    assert "rɪˈzɪl" in html_out
    # Level-conditioned guidance from the anchored pool level only.
    assert LEVEL_GUIDANCE["B2"] in html_out
    # Record-sibling metadata shown.
    assert "resilient#1" in html_out
    assert "Traits" in html_out
    # Unknown pool level -> no guidance line, no generic user-level text.
    unknown = render_final_card(dict(rec, pool_level=""), card)
    assert LEVEL_GUIDANCE["B2"] not in unknown
    assert "راهنما:" not in unknown
    assert "beginner" not in unknown
    assert "intermediate" not in unknown


def test_anchor_entry_pos_reports_anchored_pos():
    def read_entry(row):
        return row["entry"]

    entries = [
        {"pos": "noun", "entry": {"pos": "noun", "sounds": [],
                                  "senses": [{"glosses": [
                                      "Alternative spelling of xyz"],
                                      "tags": []}]}},
        {"pos": "name", "entry": {"pos": "name", "sounds": [],
                                  "senses": [{"glosses": ["A tech company"],
                                              "tags": []}]}},
    ]
    # The clean name-entry sense outscores the penalized noun gloss, so
    # the anchored entry POS is "name" (S1 drops it; helper only reports).
    assert anchor_entry_pos_for_entries(
        "Apple", entries, "noun", read_entry) == "name"
    noun_only = [entries[0]]
    assert anchor_entry_pos_for_entries(
        "Apple", noun_only, "noun", read_entry) == "noun"
    assert anchor_entry_pos_for_entries(
        "Apple", [], "noun", read_entry) == ""
