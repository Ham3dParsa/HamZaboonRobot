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
    _atomic_write_text,
    _read_model_calls,
    anchor_entry_pos_for_entries,
    anchor_item_en,
    anchor_pos_tags,
    append_telemetry_history,
    assign_topic,
    batch_log_line,
    build_also_sense,
    build_completion_flags,
    build_precard_values,
    build_prompts,
    build_timings,
    compute_quotas,
    detect_xref,
    en_word_count,
    example_contains_head,
    example_containment_ok,
    fa_field_ok,
    filter_examples_by_length,
    first_entry_ipa,
    generate_card,
    headword_leak_scan,
    inflection_review,
    is_delta_response,
    is_fa_dominant,
    is_inflection_gloss,
    is_proper_noun_lemma,
    load_cards_jsonl,
    load_phrase_types,
    load_topic_vectors,
    main,
    merge_precard_delta,
    meta_leak_scan,
    parse_abbrev_expansion,
    pick_anchor_sense,
    regen_grammar_tip,
    render_diff_header,
    render_diff_table,
    render_final_card,
    render_gallery,
    resolve_dataset_examples,
    resolve_phrase_en_def,
    resolve_word_en_def,
    review_dataset_examples,
    review_grammar_tips,
    review_records_grammar,
    richness_counters,
    run_content_gate,
    sample_phrases,
    sample_words,
    score_senses,
    similarity_note,
    single_topic_vector,
    split_frozen_by_containment,
    top_sense_candidates,
    translation_fidelity_ok,
    validate_card_obj,
    validate_delta_response,
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
    "examples": ["She is a resilient student studying daily here.",
                 "Resilient trees grow strong after every storm."],
    "example_translations": ["او دانش‌آموز تاب‌آوری است که هر روز در اینجا درس می‌خواند.",
                             "درختان تاب‌آور پس از هر طوفان قوی رشد می‌کنند."],
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
    # Stage stepper: exactly 4 steps in pipeline order (R45 v12).
    for step in ("دیتاست خام", "گیت‌ها", "مدل", "نهایی"):
        assert step in html_out
    assert html_out.count('class="step"') == 3 * 4
    # Old 6-row strip labels retired (diff-header/bidi labels untouched).
    for row in ("استخر", "کنترل‌ها"):
        assert row not in html_out
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
    "e": ["She is a resilient student today.",
          "Trees here are resilient every day."],
    "t": ["او دانش‌آموز تاب‌آوری است امروز.",
          "درختان اینجا هر روز تاب‌آور هستند."],
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
                     "vector": [{"label": "Food & Drink", "weight": 1.0}],
                     "topic_path": "leg1"}


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
            "en_def": "tough resilience after hard times",
            "sense_id": "resilient#1"}

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
                   "vector": [{"label": "Food & Drink", "weight": 1.0}],
                   "topic_path": "leg1"}
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
                                     "weight": 1.0}],
                         "topic_path": "llm"}
    assert prog.exists()  # pilot resume separate from v16b originals
    # No transport -> Other stays Other, still tagged v16b-exact.
    other = assign_topic("zebra", "an animal",
                         lookup=lambda t, g: None)
    assert other == {"label": "Other / Abstract", "method": "v16b-exact",
                     "vector": [{"label": "Other / Abstract",
                                 "weight": 1.0}],
                     "topic_path": "fallback"}


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
              "Classroom example shows resilient habits for the "
              "pilot test case today"]
    frozen_fa = ["او پس از زمستان سخت تاب‌آوری چشمگیری نشان داد امروز.",
                 "این مثال تاب‌آوری عادت‌های روزمره او را نشان می‌دهد امروز."]
    item = {"kind": "word", "text": "resilient", "pool_level": "B2",
            "en_def": "remarkable resilience after hard times",
            "sense_id": "resilient#1",
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
    assert "#efe7d8" in html_out and "#241f18" in html_out  # v8 palette
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
    # R38 v10: file-index decay pre-score orders the window — the clean
    # idx1 sense (0.707) beats the penalized idx0 alt stub (0.50) and the
    # idx3 clean tie (0.50); the penalized slang sense ranks last.
    # Hermetic: zipf_fn=None-signal forces the freq tie-breaker neutral
    # so the idx0/idx3 tie falls back to file order (deterministic).
    def read_entry(row):
        return row["entry"]

    nofreq = lambda w: None
    cands = top_sense_candidates("Bank", four_sense_entries(), "noun",
                                 read_entry, zipf_fn=nofreq)
    assert [c["sense_id"] for c in cands] == [
        "bank#1", "bank#0", "bank#3"]
    assert cands[-1]["gloss"] == "fourth gloss here"
    assert top_sense_candidates("Bank", [], "noun", read_entry) == []

    item = {"kind": "word", "text": "Bank", "pos": "noun"}
    anchor_item_en(item, {"bank": four_sense_entries()}, read_entry,
                   zipf_fn=nofreq)
    assert item["sense_id"] == "bank#1"  # anchor unchanged (top scorer)
    assert item["sense_candidates"] == cands  # audit trail rides along
    assert item["also_sense"] == {
        "sense_id": "bank#0", "gloss": "Alternative spelling of xyz",
        "topic": None, "topic_method": card_pilot.ALSO_TOPIC_UNASSIGNED}

    # Cheap vector leg fills the also-sense topic; no LLM involved.
    item2 = {"kind": "word", "text": "Bank", "pos": "noun"}
    anchor_item_en(item2, {"bank": four_sense_entries()}, read_entry,
                   zipf_fn=nofreq,
                   vector_lookup={"bank#0": [{"label": "Finance",
                                              "weight": 1.0}]})
    assert item2["also_sense"] == {
        "sense_id": "bank#0", "gloss": "Alternative spelling of xyz",
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
    # Guidance line REMOVED from gallery cards (owner: review noise).
    # No pool level => no guidance anywhere.
    assert "راهنما:" not in html_out
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


# ---------------- v8 R28: token-optimized delta I/O ----------------

FROZEN_EX = ("She showed remarkable resilience after the long difficult "
             "winter season here today")
FROZEN_EX2 = ("Classroom example shows resilient habits for the "
              "pilot test case today")
FROZEN_FA = "او پس از زمستان سخت تاب‌آوری چشمگیری نشان داد امروز."
NEW_EX = "Trees here show great resilience every single day"
NEW_FA = "درختان اینجا هر روز تاب‌آوری چشمگیری از خود نشان می‌دهند."


def _delta_item(n_frozen=1):
    frozen = [FROZEN_EX, FROZEN_EX2][:n_frozen]
    return {"kind": "word", "text": "resilient", "pool_level": "B2",
            "en_def": "tough resilience after hard times",
            "sense_id": "resilient#1",
            "ipa": "/rɪˈzɪl.jənt/", "ipa_src": card_pilot.IPA_SRC_DATASET,
            "dataset_examples": list(frozen)}


def _delta_filled(new_example=True, translations=None):
    filled = {"fa_meaning": "تاب‌آور",
              "fa_explanation": "کسی که پس از سختی به حالت عادی برمی‌گردد.",
              "synonyms": ["tough"], "antonyms": ["fragile"],
              "example_translations": translations or [FROZEN_FA, NEW_FA],
              "grammar_tip": "صفت است و معمولا با be می‌آید."}
    if new_example:
        filled["examples"] = [NEW_EX]
    return filled


def test_delta_prompt_contract_forbids_echo():
    _, user, _ = build_prompts(_delta_item())
    assert "NEVER echo" in user
    assert "Return ONLY" in user
    assert '"kept"' in user and '"filled"' in user
    assert '"improved"' in user and '"improved_flag"' in user
    assert "/rɪˈzɪl.jənt/" in user  # pre-card values quoted, never echoed
    assert FROZEN_EX in user


def test_validate_delta_response_shape():
    ok, kept, filled, improved, flag, reason = validate_delta_response(
        {"kept": ["phonetic"], "filled": {"m": "تاب‌آور"},
         "improved": {}, "improved_flag": False})
    assert ok is True and reason == ""
    assert kept == ["phonetic"] and filled == {"fa_meaning": "تاب‌آور"}
    assert improved == {} and flag is False
    assert is_delta_response(
        {"kept": [], "filled": {}}) is True
    assert is_delta_response(dict(VALID_CARD)) is False
    for bad in ({"kept": "phonetic", "filled": {}},
                {"kept": [], "filled": []},
                {"kept": [], "filled": {},
                 "improved": {}, "improved_flag": "yes"},
                {"kept": [], "filled": {}, "improved": []},
                "not-an-object"):
        ok, *_ = validate_delta_response(bad)
        assert ok is False


def test_merge_precard_delta_correctness():
    precard = build_precard_values(_delta_item())
    assert precard == {"phonetic": "/rɪˈzɪl.jənt/",
                       "examples": [FROZEN_EX]}
    obj, report = merge_precard_delta(
        _delta_item(), precard, ["phonetic"], _delta_filled(), {}, False)
    assert report["kept_tamper"] is False
    assert report["filled_keys"] == sorted(_delta_filled())
    assert obj["phonetic"] == "/rɪˈzɪl.jənt/"  # stored value wins
    assert obj["examples"] == [FROZEN_EX, NEW_EX]  # frozen + missing slot
    assert obj["fa_meaning"] == "تاب‌آور"
    # Improved overrides a wrong pre-card value.
    obj2, report2 = merge_precard_delta(
        _delta_item(), precard, [], {},
        {"phonetic": "/better/"}, True)
    assert obj2["phonetic"] == "/better/"
    assert report2["improved_keys"] == ["phonetic"]
    assert report2["improved_flag"] is True


def test_merge_precard_delta_kept_tamper_discarded():
    precard = build_precard_values(_delta_item(n_frozen=2))
    tampered = _delta_filled()
    tampered["phonetic"] = "/WRONG/"
    obj, report = merge_precard_delta(
        _delta_item(n_frozen=2), precard, ["phonetic", "examples"],
        tampered, {}, False)
    assert report["kept_tamper"] is True
    assert report["tampered"] == ["phonetic", "examples"]
    assert obj["phonetic"] == "/rɪˈzɪl.jənt/"  # tamper discarded
    assert "phonetic" not in report["filled_keys"]


def test_generate_card_delta_end_to_end():
    item = _delta_item()

    def transport(api_key, model, system, user):
        return json.dumps({"kept": ["phonetic"],
                           "filled": _delta_filled(),
                           "improved": {}, "improved_flag": False})

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True
    assert rec["card"]["examples"] == [FROZEN_EX, NEW_EX]
    assert rec["examples_src"] == ["dataset", "model"]
    flags = rec["completion_flags"]
    assert flags["delta_kept"] == ["phonetic"]
    assert "fa_meaning" in flags["delta_filled"]
    assert flags["delta_improved"] == []
    assert flags["kept_tamper"] is False
    # Diff still computed by us: kept + filled chips render.
    html_out = render_diff_table(rec, rec["card"])
    assert 'class="op kept"' in html_out
    assert 'class="op filled"' in html_out


def test_generate_card_delta_kept_tamper_flagged_but_valid():
    item = _delta_item(n_frozen=2)

    def transport(api_key, model, system, user):
        filled = {"fa_meaning": "تاب‌آور",
                  "fa_explanation": "کسی که پس از سختی برمی‌گردد.",
                  "synonyms": ["tough"], "antonyms": ["fragile"],
                  "example_translations": [FROZEN_FA, FROZEN_FA],
                  "grammar_tip": "صفت است.",
                  "phonetic": "/WRONG/"}  # kept-field alteration
        return json.dumps({"kept": ["phonetic", "examples"],
                           "filled": filled,
                           "improved": {}, "improved_flag": False})

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True  # tamper discarded, dataset value kept
    assert rec["completion_flags"]["kept_tamper"] is True
    assert rec["examples_src"] == ["dataset", "dataset"]


def test_generate_card_delta_compact_aliases():
    item = {"kind": "word", "text": "resilient", "pool_level": "A1",
            "ipa_src": "model", "dataset_examples": []}

    def transport(api_key, model, system, user):
        return json.dumps({
            "kept": [], "improved": {}, "improved_flag": False,
            "filled": {
                "m": "تاب‌آور", "x": "کسی که برمی‌گردد.",
                "s": ["tough"], "a": ["fragile"],
                "e": ["She is a resilient student here today.",
                      "Trees here are resilient every day now"],
                "t": ["او یادگیرنده‌ای تاب‌آور است امروز.",
                      "درختان اینجا هر روز تاب‌آور هستند اکنون."],
                "g": "صفت است."}})

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True
    assert rec["card"]["fa_meaning"] == "تاب‌آور"
    assert rec["examples_src"] == ["model", "model"]


# ---------------- v8 R29: abbreviations ----------------

def test_parse_abbrev_expansion_variants():
    assert parse_abbrev_expansion("Initialism of television") == "television"
    assert parse_abbrev_expansion("Abbreviation of National Health Service",
                                  ) == "National Health Service"
    assert parse_abbrev_expansion("Short for mathematics.") == "mathematics"
    assert parse_abbrev_expansion("Contraction of do not") == "do not"
    assert parse_abbrev_expansion("initialism of as soon as possible",
                                  ) == "as soon as possible"  # case-insensitive
    assert parse_abbrev_expansion("able to recover quickly") == ""
    assert parse_abbrev_expansion("A word that is short for nothing here "
                                  "in prose") == ""  # anchored: no mid match
    assert parse_abbrev_expansion("") == ""


def test_abbrev_dataset_first_and_model_fill_gap():
    def read_entry(row):
        return row["entry"]

    index = {"tv": [{"pos": "noun",
                     "entry": {"pos": "noun", "sounds": [],
                               "senses": [{"glosses": [
                                   "Initialism of television"],
                                   "tags": []}]}}]}
    item = {"kind": "word", "text": "TV", "pos": "noun"}
    anchor_item_en(item, index, read_entry)
    assert item["abbrev_expansion"] == "television"
    _, user, _ = build_prompts(dict(item, pool_level="A1"))
    assert '"abbrev_expansion"' in user and "television" in user

    gap = {"kind": "word", "text": "TV", "pool_level": "A1",
           "ipa_src": "model", "dataset_examples": []}
    _, gap_user, _ = build_prompts(gap)
    assert "abbrev_expansion" in gap_user  # model fills only if missing

    def transport(api_key, model, system, user):
        filled = _delta_filled(new_example=False)
        filled["examples"] = [
            "She is a resilient student here today.",
            "Trees here are resilient every day now"]
        filled["example_translations"] = [
            "او یادگیرنده‌ای تاب‌آور است امروز.",
            "درختان اینجا هر روز تاب‌آور هستند اکنون."]
        filled["abbrev_expansion"] = "television"
        return json.dumps({"kept": [], "filled": filled,
                           "improved": {}, "improved_flag": False})

    rec = generate_card(dict(gap, text="resilient"), "key",
                        transport=transport, model_calls={})
    assert rec["valid"] is True
    assert rec["abbrev_expansion"] == "television"


# ---------------- v8 R30: grammar fact-review ----------------

def _review_reply(rows):
    return json.dumps({"results": rows})


def test_review_grammar_tips_mocked():
    items = [{"key": "w:a", "text": "a", "en_def": "g",
              "grammar_tip": "tip-a"},
             {"key": "w:b", "text": "b", "en_def": "g",
              "grammar_tip": "tip-b"}]

    def transport(api_key, model, system, user):
        assert "fact-checker" in system
        return _review_reply([
            {"key": "w:a", "ok": True, "problem": ""},
            {"key": "w:b", "ok": False,
             "problem": "نام اشتباه برای ed-",
             "extra": "ignored"}])

    verdicts = review_grammar_tips(items, transport, "k", model_calls={})
    assert verdicts["w:a"] == {"ok": True, "problem": "",
                               "model": card_pilot.MODELS[0]}
    assert verdicts["w:b"]["ok"] is False
    assert "ed" in verdicts["w:b"]["problem"]

    def garbage(api_key, model, system, user):
        return "not json {{{"

    fallen = review_grammar_tips(items[:1], garbage, "k", model_calls={})
    assert fallen == {"w:a": {"ok": True, "problem": "",
                              "model": "review-fallback"}}


def test_review_records_grammar_regen_once_with_resume(tmp_path):
    rec = {"key": "w:r", "kind": "word", "text": "resilient",
           "pool_level": "A1", "en_def": "able to recover quickly",
           "card": dict(VALID_CARD), "valid": True}
    calls = []

    def transport(api_key, model, system, user):
        calls.append(system)
        if system == card_pilot.GRAMMAR_REGEN_SYS:
            return json.dumps({"grammar_tip": "نکته اصلاح‌شده درباره صفت."})
        return _review_reply([{"key": "w:r", "ok": False,
                               "problem": "قاعده نادرست"}])

    prog = str(tmp_path / "grammar_prog.json")
    checked, regens = review_records_grammar(
        [rec], "k", transport=transport, model_calls={}, progress_path=prog)
    assert (checked, regens) == (1, 1)
    assert rec["card"]["grammar_tip"] == "نکته اصلاح‌شده درباره صفت."
    assert rec["grammar_review"]["verdict"] == "rejected"
    assert rec["grammar_review"]["regen"] is True

    def boom(api_key, model, system, user):
        raise AssertionError("resume must not re-call")

    rec2 = {"key": "w:r", "kind": "word", "text": "resilient",
            "pool_level": "A1", "en_def": "able to recover quickly",
            "card": dict(VALID_CARD), "valid": True}
    checked, regens = review_records_grammar(
        [rec2], "k", transport=boom, model_calls={}, progress_path=prog)
    assert (checked, regens) == (0, 0)  # resumed, tip re-applied
    assert rec2["card"]["grammar_tip"] == "نکته اصلاح‌شده درباره صفت."


def test_grammar_review_fail_closed_keeps_tip():
    rec = {"key": "w:r", "kind": "word", "text": "resilient",
           "pool_level": "A1", "en_def": "g",
           "card": dict(VALID_CARD), "valid": True}

    def down(api_key, model, system, user):
        raise RuntimeError("provider down")

    checked, regens = review_records_grammar(
        [rec], "k", transport=down, model_calls={})
    assert (checked, regens) == (1, 0)
    assert rec["card"]["grammar_tip"] == VALID_CARD["grammar_tip"]
    assert rec["grammar_review"]["verdict"] == "ok"  # fail-closed


def test_regen_grammar_tip_returns_empty_on_failure():
    def down(api_key, model, system, user):
        raise RuntimeError("down")

    assert regen_grammar_tip("w", "g", "bad", "p", "k", down) == ""


# ---------------- v8 R31: dataset-example content gate ----------------

def test_review_dataset_examples_mocked():
    items = [{"key": "w:a", "examples": ["A clean example here today.",
                                         "Another calm sentence for all."]}]

    def transport(api_key, model, system, user):
        assert "appropriateness" in system
        return _review_reply([{"key": "w:a",
                               "flagged": ["A clean example here today.",
                                           "not-a-member example"],
                               "reason": "creepy"}])

    verdicts = review_dataset_examples(items, transport, "k",
                                       model_calls={})
    assert verdicts["w:a"]["flagged"] == ["A clean example here today."]
    assert verdicts["w:a"]["reason"] == "creepy"

    def garbage(api_key, model, system, user):
        return "garbage {{{"

    fallen = review_dataset_examples(items, garbage, "k", model_calls={})
    assert fallen == {"w:a": {"flagged": [], "reason": "",
                              "model": "review-fallback"}}


def test_content_flag_releases_example_and_grows_need():
    frozen = [FROZEN_EX, FROZEN_EX2]
    item = {"kind": "word", "text": "resilient", "pool_level": "B2",
            "en_def": "remarkable resilience after hard times",
            "sense_id": "resilient#1",
            "ipa_src": "model",
            "dataset_examples": list(frozen),
            "content_flags": {FROZEN_EX2: "content-flag: creepy"}}
    kept, released = split_frozen_by_containment(item)
    assert kept == [FROZEN_EX]  # flagged joins released_containment
    assert FROZEN_EX2 in released
    _, user, _ = build_prompts(item)
    assert "never reuse" in user  # flagged never-reuse line

    def transport(api_key, model, system, user_text):
        return json.dumps(dict(
            VALID_CARD,
            examples=[FROZEN_EX, NEW_EX],
            example_translations=[FROZEN_FA, NEW_FA]))

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True
    assert FROZEN_EX2 in rec["completion_flags"]["released_containment"]
    assert rec["examples_src"] == ["dataset", "model"]
    assert rec["content_flags"] == {FROZEN_EX2: "content-flag: creepy"}


def test_run_content_gate_resume(tmp_path):
    items = [{"kind": "word", "text": "apple", "pool_level": "A1",
              "dataset_examples": ["A calm apple example here today."]}]
    calls = []

    def transport(api_key, model, system, user):
        calls.append(user)
        return _review_reply([{"key": "w:apple", "flagged": [],
                               "reason": ""}])

    prog = str(tmp_path / "content_prog.json")
    assert run_content_gate(items, "k", transport=transport,
                            model_calls={}, progress_path=prog) == (0,)
    assert items[0]["content_flags"] == {}
    n_calls = len(calls)
    assert n_calls > 0
    assert run_content_gate(items, "k", transport=transport,
                            model_calls={}, progress_path=prog) == (0,)
    assert len(calls) == n_calls  # resume: no new calls


# ---------------- v8 R32: POS ----------------

def _pos_index():
    def rows(pos, glosses):
        return {"pos": pos,
                "entry": {"pos": pos, "sounds": [],
                          "senses": [{"glosses": [g], "tags": []}
                                     for g in glosses]}}
    return {"bank": [
        rows("noun", ["Alternative spelling of xyz"]),
        rows("noun", ["a financial institution"]),
        rows("verb", ["to tilt an aircraft"]),
        rows("adj", ["financial in nature"])]}


def test_anchor_pos_tags_anchored_first_capped():
    def read_entry(row):
        return row["entry"]

    tags = anchor_pos_tags("Bank", _pos_index()["bank"], "noun",
                           read_entry)
    assert tags[0] == "noun"  # anchored entry POS first
    assert tags == ["noun", "verb", "adj"]  # distinct, capped at 3
    assert anchor_pos_tags("Bank", _pos_index()["bank"], "noun",
                           read_entry, limit=2) == ["noun", "verb"]
    assert anchor_pos_tags("Bank", [], "noun", read_entry) == []


def test_anchor_item_sets_pos_and_src():
    def read_entry(row):
        return row["entry"]

    item = {"kind": "word", "text": "Bank", "pos": "noun"}
    anchor_item_en(item, _pos_index(), read_entry)
    assert item["sense_id"] == "bank#1"  # anchor unchanged
    assert item["pos"] == ["noun", "verb", "adj"]
    assert item["pos_src"] == "dataset"
    bare = {"kind": "word", "text": "zzz", "pos": "noun"}
    anchor_item_en(bare, {}, read_entry)
    assert bare["pos"] == [] and bare["pos_src"] == "none"


def test_pos_gallery_chip_row_and_record():
    rec = {"key": "w:b", "kind": "word", "text": "bank",
           "pool_level": "A1", "bot_level": "beginner", "model_used": "m1",
           "sense_id": "bank#1", "en_def": "a financial institution",
           "en_source": "dataset", "topic": "Finance",
           "topic_method": "v16b-exact",
           "pos": ["noun", "verb"], "pos_src": "dataset",
           "card": dict(VALID_CARD, word="bank"), "valid": True,
           "reason": "", "error": ""}
    html_out = render_diff_header(rec)
    assert "نقش دستوری" in html_out
    assert "noun" in html_out and "verb" in html_out
    assert "[dataset]" in html_out
    # Legacy pool-string pos still renders, no crash.
    legacy = render_diff_header(dict(rec, pos="noun", pos_src="none"))
    assert "نقش دستوری" in legacy

    item = {"kind": "word", "text": "resilient", "pool_level": "A1",
            "pos": ["adj"], "pos_src": "dataset",
            "ipa_src": "model", "dataset_examples": []}

    def transport(api_key, model, system, user):
        return json.dumps(dict(VALID_CARD))

    got = generate_card(item, "key", transport=transport, model_calls={})
    assert got["valid"] is True
    assert got["pos"] == ["adj"] and got["pos_src"] == "dataset"


# ---------------- v8 R33: gallery theme ----------------

def test_gallery_v8_theme_and_op_colors():
    html_out = render_gallery(
        [{"key": "w:a", "kind": "word", "text": "apple", "pool_level": "A1",
          "bot_level": "beginner", "model_used": "m1",
          "card": dict(VALID_CARD, word="apple"), "valid": True,
          "reason": "", "error": ""}],
        {"date_tehran": "d", "commit": "c", "model_calls": {"m1": 1}})
    assert "#efe7d8" in html_out and "#241f18" in html_out  # darker pastel
    for token in ("--kept-soft", "--filled-soft", "--improved-soft",
                  "--error-soft", ".op.kept", ".op.filled", ".op.improved",
                  ".op.error"):
        assert token in html_out  # op color system
    assert "nth-child(even)" in html_out  # diff rows zebra
    assert "min-width:0" in html_out  # no overflow at 1440/390
    assert "@media (max-width: 600px)" in html_out  # 390px stacking
    assert 'name="viewport"' in html_out
    # Kept affordances: RTL/Vazirmatn/.en/sticky nav/details/no externals.
    assert 'dir="rtl"' in html_out and "Vazirmatn" in html_out
    assert 'class="en"' in html_out and "position:sticky" in html_out
    assert "<details>" in html_out
    assert "<link" not in html_out and 'href="http' not in html_out


def test_gallery_delta_improved_chip_and_error_badge():
    card = dict(VALID_CARD, word="apple")
    rec = {"key": "w:apple", "kind": "word", "text": "apple",
           "pool_level": "A1", "bot_level": "beginner", "model_used": "m1",
           "sense_id": "apple#1", "en_def": "a fruit",
           "en_source": "dataset", "topic": "Food", "topic_method": "t",
           "ipa": "/æpəl/", "ipa_src": "dataset",
           "dataset_examples": list(card["examples"]),
           "examples_src": ["dataset", "model"],
           "completion_flags": {"fields_filled": ["fa_meaning"],
                                 "sense_review": True,
                                 "nothing_to_complete": False,
                                 "released_containment": [],
                                 "delta_filled": ["fa_meaning"],
                                 "delta_improved": ["phonetic"],
                                 "delta_kept": ["examples"],
                                 "kept_tamper": False},
           "card": card, "valid": True, "reason": "", "error": ""}
    html_out = render_diff_table(rec, card)
    assert 'class="op improved"' in html_out
    assert 'class="op filled"' in html_out
    assert 'class="op kept"' in html_out


# ---------------- v9 R34: cross-reference senses ----------------

def test_detect_xref_patterns():
    # General patterns, case-insensitive, whole-gloss anchored.
    assert detect_xref("Alternative form of colour.") == "colour"
    assert detect_xref('Alternative spelling of "colour".') == "colour"
    assert detect_xref("SYNONYM OF happiness") == "happiness"
    assert detect_xref("Variant of flavor.") == "flavor"
    assert detect_xref("See bag.") == "bag"
    assert detect_xref("see also bag") == "bag"
    # R36 inflection stubs are NOT xref.
    assert detect_xref("plural of cat") is None
    assert detect_xref("past of go") is None
    assert detect_xref("comparative of big") is None
    # Prose glosses never match (anchored ^...$).
    assert detect_xref("a fruit") is None
    assert detect_xref("to see someone off at the station") is None
    assert detect_xref("") is None


def test_register_penalty_bare_alternative_form():
    # R34 v9: v14-pattern gap fixed — the bare stub scores 0.50 like its
    # qualified siblings. Owner run_v14_phase1.register_penalty untouched.
    assert card_pilot._v14_register_penalty(
        [], "Alternative form of xyz") == 0.50
    assert card_pilot._v14_register_penalty(
        [], "Alternative spelling of xyz") == 0.50
    assert card_pilot._v14_register_penalty(
        [], "a financial institution") == 1.0


def _xref_index():
    def rows(glosses, ipa="/x/"):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [{"ipa": ipa}],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": []}
                                      for g in glosses]}}]
    return {
        "color": rows(["Alternative spelling of colour."]),
        "colour": rows(["a hue such as red or blue", "a dye"]),
        "ghost": rows(["See specter."]),
    }


def test_xref_resolve_hit():
    # Bare-xref top sense resolves to the TARGET top gloss/sense_id,
    # tagged xref-resolved with the origin recorded.
    def read_entry(row):
        return row["entry"]

    item = {"kind": "word", "text": "color", "pos": "noun"}
    anchor_item_en(item, _xref_index(), read_entry)
    assert item["en_def"] == "a hue such as red or blue"
    assert item["sense_id"] == "colour#0"
    assert item["xref_method"] == "xref-resolved"
    assert item["xref_resolved_from"] == "color#0"
    assert item["xref_unresolvable"] is False
    assert item["ipa"] == "/x/"  # target entry sounds


def test_xref_unresolvable_drop_flag():
    # No target entry ("specter" absent) -> flagged, gloss kept as-is
    # (S1 drops it as no-real-def; the helper itself never drops).
    def read_entry(row):
        return row["entry"]

    item = {"kind": "word", "text": "ghost", "pos": "noun"}
    anchor_item_en(item, _xref_index(), read_entry)
    assert item["xref_unresolvable"] is True
    assert item["xref_method"] == ""
    assert item["en_def"] == "See specter."


def test_xref_one_hop_max():
    # Target whose own top is a bare xref -> unresolvable (no chains).
    def read_entry(row):
        return row["entry"]

    index = {"aaa": [{"pos": "noun",
                      "entry": {"pos": "noun", "sounds": [],
                                "senses": [{"glosses": ["See bbb."],
                                            "tags": [],
                                            "examples": []}]}}],
             "bbb": [{"pos": "noun",
                      "entry": {"pos": "noun", "sounds": [],
                                "senses": [{"glosses": ["See ccc."],
                                            "tags": [],
                                            "examples": []}]}}],
             "ccc": [{"pos": "noun",
                      "entry": {"pos": "noun", "sounds": [],
                                "senses": [{"glosses": ["a real thing"],
                                            "tags": [],
                                            "examples": []}]}}]}
    item = {"kind": "word", "text": "aaa", "pos": "noun"}
    anchor_item_en(item, index, read_entry)
    assert item["xref_unresolvable"] is True
    assert item["sense_id"] == "aaa#0"


# ---------------- v9 R36: inflection judge ----------------

def test_is_inflection_gloss():
    assert is_inflection_gloss("plural of cat") is True
    assert is_inflection_gloss("past of go") is True
    assert is_inflection_gloss("comparative of big") is True
    assert is_inflection_gloss("Alternative spelling of colour.") is False
    assert is_inflection_gloss("a hue such as red") is False


def _inflect_items():
    return [{"key": "w:cats", "text": "cats", "gloss": "plural of cat"},
            {"key": "w:went", "text": "went", "gloss": "past of go"}]


def test_inflection_review_keep_and_drop():
    def transport(api_key, model, sys_text, user_text):
        assert "keep" in user_text
        return json.dumps({"results": [
            {"key": "w:cats", "keep": False,
             "reason": "regular plural, use cat"},
            {"key": "w:went", "keep": True,
             "reason": "irregular, own learner value"}]})

    out = inflection_review(_inflect_items(), transport, "k", {})
    assert out["w:cats"] == {"keep": False,
                             "reason": "regular plural, use cat",
                             "model": card_pilot.MODELS[0],
                             "uncertain": False}
    assert out["w:went"]["keep"] is True
    assert out["w:went"]["uncertain"] is False


def test_inflection_review_uncertain_keep():
    # Transport garbage -> fail-closed keep flagged review-uncertain
    # (never drop on uncertainty).
    def garbage(api_key, model, sys_text, user_text):
        return "not json at all {{{"

    out = inflection_review(_inflect_items()[:1], garbage, "k", {})
    assert out["w:cats"]["keep"] is True
    assert out["w:cats"]["uncertain"] is True
    assert out["w:cats"]["model"] == "review-fallback"


# ---------------- v9 R37: frequency leg ----------------

def _freq_entries():
    def rows(glosses):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": []}
                                      for g in glosses]}}]
    # Two clean senses, all else equal (same tags/POS/length class).
    return rows(["aaa bbb ccc common thing here",
                 "zzz qqq xxx obscure thing here"])


def test_freq_leg_common_outranks_rare():
    # Injected zipf: common words score high, rare words low.
    def read_entry(row):
        return row["entry"]

    def zipf_fn(word):
        return 6.0 if word in ("aaa", "bbb", "ccc", "common") else 1.0

    scored = score_senses("w", _freq_entries(), "noun", read_entry,
                          zipf_fn=zipf_fn)
    assert scored[0][4] == "aaa bbb ccc common thing here"
    assert scored[0][0] > scored[1][0]
    # Ties (no zipf signal) preserve file order — old behavior kept.
    tied = score_senses("w", _freq_entries(), "noun", read_entry,
                        zipf_fn=lambda w: None)
    assert [idx for _, idx, _, _, _ in tied] == [0, 1]

def test_delta_kept_alias_canonicalized():
    from card_pilot import merge_precard_delta, validate_delta_response
    ok, kept, filled, improved, flag, reason = validate_delta_response(
        {"kept": ["ph"], "filled": {"phonetic": "/WRONG/"},
         "improved": {}, "improved_flag": False})
    assert ok, reason
    assert kept == ["phonetic"]
    full, report = merge_precard_delta({}, {}, kept, filled, improved, flag)
    assert report.get("kept_tamper") is True
    assert full.get("phonetic") != "/WRONG/"

def test_coherence_headword_family_passes_with_correct_anchor():
    # R41b tri-state: paraphrase gap (no token overlap) is UNDECIDED
    # (None) — the micro-pass decides. Only overlap passes outright.
    from card_pilot import sense_coherence_check
    assert sense_coherence_check(
        "To touch with the lips", {"examples": ["They kissed goodbye."],
         "fa_meaning": "", "fa_explanation": "", "example_translations": [],
         "synonyms": []}, headword="kiss") is None


def test_coherence_headword_family_fallback_passes():
    # F3: the headword param joins the anchor side — a paraphrase
    # anchor with zero gloss-token overlap still PASSES when the card
    # carries headword-family words (exact headword token here).
    from card_pilot import sense_coherence_check
    card = {"examples": ["Resilient trees grow strong after every storm."],
            "fa_meaning": "", "fa_explanation": "",
            "example_translations": [], "synonyms": []}
    anchor = "Having the ability to recover quickly"
    assert sense_coherence_check(anchor, card) is None  # no headword
    assert sense_coherence_check(anchor, card, headword="resilient") is True


# ---------------- v12 R43: context-aware متوسط ----------------

def test_r43_frequency_adjective_passes():
    # متوسط as a frequency/size adjective with no metadata marker nearby.
    card = dict(VALID_CARD,
                fa_explanation="میزان متوسط بارش در این منطقه زیاد است.")
    assert meta_leak_scan(card) == []


def test_r43_level_marker_window_fails():
    # درجه (a pure marker, no unconditional pattern) inside the 2-word
    # window -> leak; the required سطح متوسط case fires as well.
    card = dict(VALID_CARD, fa_explanation="این درجه متوسط بالا است.")
    assert meta_leak_scan(card)
    card = dict(VALID_CARD, fa_explanation="این کتاب سطح متوسط زبان است.")
    assert meta_leak_scan(card)


def test_r43_marker_outside_window_passes():
    # درجه three words away -> no leak (window is ±2). درجه has no
    # unconditional pattern, isolating the contextual rule.
    card = dict(VALID_CARD,
                fa_explanation="متوسط در این کلاس درجه بالا است.")
    assert meta_leak_scan(card) == []


def test_r43_mf_style_tip_passes():
    # Grammar tip using متوسط descriptively (no marker) stays clean.
    card = dict(VALID_CARD,
                grammar_tip="این واژه در متن‌های متوسط کاربرد دارد.")
    assert meta_leak_scan(card) == []


def test_r43_other_level_words_still_unconditional():
    assert meta_leak_scan(dict(VALID_CARD, fa_meaning="برای مبتدی‌ها")) \
        != []
    assert meta_leak_scan(dict(VALID_CARD,
                               fa_explanation="good for beginners")) != []
    assert meta_leak_scan(dict(VALID_CARD, fa_explanation="level A1")) \
        != []
    assert meta_leak_scan(dict(VALID_CARD, fa_explanation="سطح دشوار")) \
        != []


def test_r43_zwnj_joined_tokens():
    # ZWNJ-joined متوسط with no marker nearby stays clean (pass).
    card = dict(VALID_CARD,
                fa_explanation="می\u200cمتوسط بارش در این منطقه زیاد است.")
    assert meta_leak_scan(card) == []
    # سطح + ZWNJ + متوسط is a level leak (fail).
    card = dict(VALID_CARD,
                fa_explanation="این کتاب سطح\u200cمتوسط زبان است.")
    assert meta_leak_scan(card) != []


# ---------------- v12 R44: superlative redirect helpers ----------------

def test_r44_parse_superlative_base():
    from card_pilot import is_superlative_gloss, parse_superlative_base
    assert parse_superlative_base("superlative of good.") == "good"
    assert parse_superlative_base("comparative of big") == "big"
    assert parse_superlative_base("a round fruit") == ""
    assert parse_superlative_base("plural of cat") == ""
    assert is_superlative_gloss("superlative of good") is True
    assert is_superlative_gloss("plural of cat") is False
    # F4: mid-sentence mentions never parse (^ anchor).
    assert parse_superlative_base(
        "This entry is the superlative of good") == ""
    assert parse_superlative_base("not a superlative of good") == ""
    # F4: base must be a single alpha token.
    assert parse_superlative_base("superlative of well known") == ""
    assert parse_superlative_base("superlative of good-form") == ""
    assert parse_superlative_base("superlative of") == ""
    assert parse_superlative_base("comparative form of big") == "big"


def test_r44_review_prompt_has_idiom_line():
    assert "do one's best" in card_pilot.INFLECTION_REVIEW_SYS


# ---------------- v12 R45: gallery invalid chips/stepper/debug ----------------

def _r45_base_rec(**over):
    rec = {"key": "w:apple", "kind": "word", "text": "apple",
           "pool_level": "A1", "bot_level": "beginner",
           "model_used": "m1", "sense_id": "apple#1", "en_def": "a fruit",
           "en_source": "dataset", "topic": "Food", "topic_method": "t",
           "ipa": "/ipa/", "ipa_src": "dataset",
           "dataset_examples": [], "examples_src": [],
           "model_d": "", "literal_fa": "", "proper_noun": None,
           "leaks": [], "fa_dominant": True, "headword_leaks": [],
           "long_example": [],
           "completion_flags": {"fields_filled": ["fa_meaning"],
                                 "sense_review": True,
                                 "nothing_to_complete": False},
           "similarity_note": 0.123, "stage_calls": {"s0b": "kept"},
           "model_calls": {"m1": 1}}
    rec.update(over)
    return rec


def test_r45_invalid_aborted_chip_not_model():
    from card_pilot import render_diff_table
    rec = _r45_base_rec(card=None, valid=False, reason="boom",
                        error="boom")
    html_out = render_diff_table(rec, {})
    assert "لغوشده" in html_out
    assert "پرشده" not in html_out


def test_r45_invalid_rejected_chip_not_model():
    from card_pilot import render_diff_table
    card = dict(VALID_CARD, word="apple")
    rec = _r45_base_rec(card=card, valid=False, reason="meta-leak: x")
    html_out = render_diff_table(rec, card)
    assert "رد در گیت" in html_out
    assert "پرشده" not in html_out


def test_r45_final_empty_block_stays():
    rec = _r45_base_rec(card=None, valid=False, reason="boom",
                        error="boom")
    html_out = render_gallery(
        [rec], {"date_tehran": "d", "commit": "c",
                "model_calls": {"m1": 1}})
    assert "لغوشده" in html_out
    assert "کارتی برای نمایش نیست" in html_out


def test_r45_stepper_has_four_steps():
    from card_pilot import render_stage_strip
    html_out = render_stage_strip(_r45_base_rec(card={}, valid=True))
    assert html_out.count('class="step"') == 4
    for step in ("دیتاست خام", "گیت‌ها", "مدل", "نهایی"):
        assert step in html_out


def test_r45_debug_details_and_no_internal_keys_in_flow():
    rec = _r45_base_rec(card=dict(VALID_CARD, word="apple"), valid=True,
                        reason="", error="",
                        content_flags={"ex": "cloze-density"})
    html_out = render_gallery(
        [rec], {"date_tehran": "d", "commit": "c",
                "model_calls": {"m1": 1}})
    assert "دیباگ فنی" in html_out
    assert '<details class="debug">' in html_out
    assert "cloze-density" in html_out  # gate verdict in step 2
    main_flow = html_out.split('<details class="debug">')[0]
    for key in ("stage_calls", "similarity_note", "model_calls"):
        assert key not in main_flow
    assert ">F4<" not in main_flow
    assert "stage_calls" in html_out  # only inside debug
    # Stepper stacks under 640px; invalid chips styled; no externals.
    assert "@media (max-width:640px)" in html_out
    assert ".op.aborted" in html_out and ".op.rejected" in html_out
    assert "<link" not in html_out and 'href="http' not in html_out

def test_fa_script_rejects_cjk():
    from card_pilot import fa_alpha_check, fa_field_ok, fa_script_ok
    assert fa_script_ok("ناچیز از نظر 규모 مالی") is False
    assert fa_field_ok("ناچیز از نظر 규모 مالی") is False
    assert fa_alpha_check({"fa_meaning": "ناچیز از نظر 규모 مالی",
                           "fa_explanation": "فارسی",
                           "example_translations": []}) is False
    assert fa_script_ok("معنی فارسی تمیز") is True
    assert fa_field_ok("معنی فارسی تمیز") is True


# T2 review-findings triage (KILO-1/2/3, OPENCODE criticals + warnings):
# telemetry history, hermetic dry-run, CEFR guard, topic cache key,
# render_only progress precedence, telemetry table render, atomic writes.


def _tele_rec(stage, batch_id):
    return {"ts": "t", "stage": stage, "batch_id": batch_id, "key_idx": 0,
            "model": "m", "prompt_tokens": 1, "completion_tokens": 2,
            "latency_s": 0.1, "outcome": "ok", "http_status": 200}


def test_telemetry_history_multi_run_accumulates(tmp_path):
    out = tmp_path / "out"
    run1 = [_tele_rec("card", 0), _tele_rec("card", 1)]
    all1, corrupt1 = append_telemetry_history(out, run1)
    assert corrupt1 == 0
    assert len(all1) == 2
    run2 = [_tele_rec("card", 2)]
    all2, corrupt2 = append_telemetry_history(out, run2)
    assert corrupt2 == 0
    # Summary covers ALL runs (KILO-2: no history loss on resume).
    assert len(all2) == 3
    assert [r["batch_id"] for r in all2] == [0, 1, 2]


def test_telemetry_history_corrupt_lines_counted_not_silent(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    hist = out / "telemetry_records.jsonl"
    hist.write_text(json.dumps(_tele_rec("card", 0)) + "\n"
                    + "{corrupt prior-run line\n"
                    + json.dumps(_tele_rec("card", 1)) + "\n",
                    encoding="utf-8")
    all_tele, corrupt = append_telemetry_history(out, [_tele_rec("card", 2)])
    # KILO-1: corrupt lines are counted + warned, valid lines all kept.
    assert corrupt == 1
    assert [r["batch_id"] for r in all_tele] == [0, 1, 2]


def test_telemetry_history_unreadable_falls_back_to_current_run(tmp_path):
    # out_dir is an existing FILE: mkdir fails -> current run preserved.
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    run = [_tele_rec("card", 9)]
    all_tele, _ = append_telemetry_history(blocker, run)
    assert all_tele == run


def test_dry_run_missing_phrase_log_stays_hermetic(tmp_path, capsys):
    pool_path = tmp_path / "lemmas.csv"
    with open(pool_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["lemma", "pos", "cefr"])
        writer.writeheader()
        writer.writerows(make_pool(per_level=4))
    out_dir = tmp_path / "out"
    rc = main(["--dry-run", "--n-words", "6", "--n-phrases", "6",
               "--out-dir", str(out_dir),
               "--word-pool", str(pool_path),
               "--phrase-log", str(tmp_path / "no-such-log.jsonl")])
    assert rc == 0
    assert "dry-run" in capsys.readouterr().out
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_build_prompts_unknown_level_clean_exit():
    # Unknown pool_level raises ValueError (an Exception, never
    # SystemExit/BaseException) so generate_card records it per-card
    # and the pilot loop continues instead of aborting the whole run.
    item = {"kind": "word", "text": "wibble", "pool_level": "XX"}
    with pytest.raises(ValueError) as exc:
        build_prompts(item)
    assert "XX" in str(exc.value)


def test_generate_card_unknown_level_records_invalid():
    # Per-card recorded failure: no raise, valid=False with a
    # bad-pool-level reason, pilot-safe to continue the loop.
    from card_pilot import generate_card
    item = {"kind": "word", "text": "wibble", "pool_level": "XX"}
    rec = generate_card(item, "key", transport=lambda *a: "{}",
                        model_calls={})
    assert rec["valid"] is False
    assert rec["reason"].startswith("bad-pool-level")
    assert "XX" in rec["reason"]


def test_assign_topic_cache_key_includes_sense_id(tmp_path):
    prog = tmp_path / "topic_prog.json"
    sid_a = "rock#1"
    key_a = "rock\tsolid stone\t%s" % sid_a
    prog.write_text(json.dumps({
        key_a: {"label": "Cached-A",
                "vector": [{"label": "Cached-A", "weight": 1.0}]}}),
        encoding="utf-8")
    vec_b = [{"label": "Vec-B", "weight": 1.0}]
    got_a = assign_topic("rock", "solid stone", lookup=lambda t, g: None,
                         sense_id=sid_a, progress_path=prog,
                         vector_lookup={sid_a: vec_b})
    assert got_a["label"] == "Cached-A"
    # Same text+gloss, different sense: must NOT hit sid A's entry.
    sid_b = "rock#2"
    got_b = assign_topic("rock", "solid stone", lookup=lambda t, g: None,
                         sense_id=sid_b, progress_path=prog,
                         vector_lookup={sid_b: vec_b})
    assert got_b["vector"] == vec_b
    assert got_b["label"] != "Cached-A"


def test_read_model_calls_prefers_precard_progress(tmp_path):
    (tmp_path / "progress.json").write_text(
        json.dumps({"model_calls": {"sampling-model": 5}}),
        encoding="utf-8")
    (tmp_path / "precard_progress.json").write_text(
        json.dumps({"model_calls": {"precard-model": 7}}),
        encoding="utf-8")
    assert _read_model_calls(tmp_path) == {"precard-model": 7}


def test_read_model_calls_falls_back_to_progress(tmp_path):
    (tmp_path / "progress.json").write_text(
        json.dumps({"model_calls": {"m1": 3}}), encoding="utf-8")
    assert _read_model_calls(tmp_path) == {"m1": 3}


def test_gallery_telemetry_table_renders():
    from telemetry import summarize
    summary = summarize([_tele_rec("card", 0)])
    html_out = render_gallery(
        [{"key": "w:a", "kind": "word", "text": "apple",
          "pool_level": "A1", "bot_level": "beginner",
          "model_used": "m", "card": dict(VALID_CARD, word="apple"),
          "valid": True, "reason": "", "error": ""}],
        {"date_tehran": "d", "commit": "c", "model_calls": {"m": 1},
         "telemetry": summary})
    # OPENCODE W9: the shadowed tele_table name used to swallow
    # UnboundLocalError so the table NEVER rendered.
    assert "تله‌متری فراخوانی‌ها" in html_out


def test_atomic_write_no_truncated_file(tmp_path):
    dest = tmp_path / "sub" / "progress.json"
    _atomic_write_text(dest, '{"done": {}}')
    assert json.loads(dest.read_text(encoding="utf-8")) == {"done": {}}
    assert not dest.with_name(dest.name + ".tmp").exists()


def test_run_logger_close_idempotent_and_reopen(tmp_path):
    log = tmp_path / "run.log"
    logger = RunLogger(log)
    logger.stage_start("sample")
    logger.stage_end("sample", ok=1, fail=0)
    logger.close()
    logger.close()  # idempotent: no raise
    logger.log("after close reopens")  # reopen path still works
    logger.close()
    assert "stage sample start" in log.read_text(encoding="utf-8")


def test_review_tuple_usage_captured():
    """T1: tuple (text, usage) review transports surface tokens (None-tolerated)."""
    items = [{"key": "w:a", "text": "apple", "en_def": "a fruit",
              "grammar_tip": "tip"}]

    def tuple_transport(api_key, model, sys_text, user_text):
        return (json.dumps({"results": [{"key": "w:a", "ok": True,
                                         "problem": ""}]}),
                {"input_tokens": 21, "output_tokens": 4})

    tele = []
    out = review_grammar_tips(items, tuple_transport, "k", telemetry=tele)
    assert out["w:a"]["ok"] is True
    assert tele and tele[0]["outcome"] == "ok"
    assert tele[0]["prompt_tokens"] == 21
    assert tele[0]["completion_tokens"] == 4
    # Plain-text transports record None tokens without failing.
    tele2 = []
    review_grammar_tips(
        items,
        lambda a, m, s, t: json.dumps({"results": [{"key": "w:a",
                                                    "ok": True,
                                                    "problem": ""}]}),
        "k", telemetry=tele2)
    assert tele2 and tele2[0]["prompt_tokens"] is None
    assert tele2[0]["completion_tokens"] is None


def test_inflection_tuple_usage_captured():
    """T1: S0b review leg surfaces tuple usage into telemetry."""
    items = [{"key": "w:cats", "text": "cats",
              "gloss": "plural of cat"}]

    def tuple_transport(api_key, model, sys_text, user_text):
        return (json.dumps({"results": [{"key": "w:cats", "keep": True,
                                         "reason": "irregular"}]}),
                {"input_tokens": 9, "output_tokens": 2})

    tele = []
    out = inflection_review(items, tuple_transport, "k", telemetry=tele)
    assert out["w:cats"]["keep"] is True
    assert tele and tele[0]["outcome"] == "ok"
    assert tele[0]["prompt_tokens"] == 9
    assert tele[0]["completion_tokens"] == 2


def test_assign_topic_path_and_token_telemetry():
    """T1: leg-1 vs LLM vs fallback paths counted with token capture."""
    tele = []
    hit = assign_topic("apple", "a fruit",
                       lookup=lambda t, g: "Food & Drink",
                       telemetry=tele)
    assert hit["topic_path"] == "leg1"
    assert tele and tele[-1]["outcome"] == "ok"
    assert tele[-1]["model"] == "deterministic"

    def llm(api_key, model, user_text):
        return (json.dumps({"results": [{"lemma": "zebra", "senses": [
            {"sense_id": "zebra#0", "topic_id": 9,
             "topic_label": "Animals & Living Beings", "confidence": 0.9,
             "vector": [{"topic_id": 9,
                         "topic_label": "Animals & Living Beings",
                         "weight": 1.0}]}]}]}),
                {"input_tokens": 30, "output_tokens": 9})

    tele2 = []
    got = assign_topic("zebra", "an animal", sense_id="zebra#0",
                       lookup=lambda t, g: None, llm_transport=llm,
                       api_key="k", model_calls={}, telemetry=tele2)
    assert got["topic_path"] == "llm"
    assert got["label"] == "Animals & Living Beings"
    assert tele2[-1]["prompt_tokens"] == 30
    assert tele2[-1]["completion_tokens"] == 9

    tele3 = []
    bad = assign_topic("zebra", "an animal", sense_id="zebra#0",
                       lookup=lambda t, g: None,
                       llm_transport=lambda a, m, t: "garbage",
                       api_key="k", model_calls={}, telemetry=tele3)
    assert bad["topic_path"] == "fallback"
    assert tele3 and tele3[-1]["outcome"] == "fallback"
