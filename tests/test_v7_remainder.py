"""Hermetic tests for the v7 REMAINDER (owner-locked).

Factory-only, reuse by import, no network, no real pools/files.

- Containment-release (locked A): failing examples released (need grows,
  released_containment[] recorded, آزادشده chip); passing stay frozen.
- R25: production grammar line + shared level_prompt_guidance (anchored
  pre-card level only).
- R26: --only / --stages / --rekey + dry-run per-stage needs.
- R27: telemetry math, missing-usage tolerance, key-value scan.
- Gallery final-head: headword + IPA header on final cards.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "factory"))
import card_pilot
import phrase_judge
import precard_pipeline
import telemetry
from card_pilot import (
    GRAMMAR_TIP_FA_RULE,
    OP_RELEASED,
    build_completion_flags,
    build_prompts,
    generate_card,
    render_diff_table,
    render_final_card,
    render_gallery,
    split_frozen_by_containment,
)
from services.ai.prompts import level_prompt_guidance

VALID_RESILIENT = {
    "word": "resilient",
    "phonetic": "IPA: /rɪˈzɪl.jənt/",
    "fa_meaning": "تاب‌آور",
    "fa_explanation": "کسی که پس از سختی به حالت عادی برمی‌گردد.",
    "synonyms": ["tough"],
    "antonyms": ["fragile"],
    "examples": ["She is a resilient learner studying daily here today.",
                 "Resilient trees grow here despite the cold wind today."],
    "example_translations": [
        "او یادگیرنده‌ای تاب‌آور است که هر روز در اینجا درس می‌خواند.",
        "درختان تاب‌آور با وجود باد سرد امروز در اینجا رشد می‌کنند."],
    "grammar_tip": "صفت است و معمولا با be می‌آید.",
}


def test_containment_split_releases_failing_freezes_passing():
    item = {"kind": "word", "text": "resilient",
            "dataset_examples": ["She is a resilient learner studying daily here.",
                                 "The sky is blue today."]}
    kept, released = split_frozen_by_containment(item)
    assert kept == ["She is a resilient learner studying daily here."]
    assert released == ["The sky is blue today."]
    item2 = {"kind": "word", "text": "resilient",
             "dataset_examples": ["She is a resilient learner studying daily here.",
                                  "Trees here are resilient."]}
    kept2, released2 = split_frozen_by_containment(item2)
    assert released2 == []
    assert kept2 == item2["dataset_examples"]


def test_containment_release_prompt_grows_need_and_flags():
    item = {"kind": "word", "text": "resilient", "pool_level": "B2",
            "dataset_examples": ["She is a resilient learner studying daily here.",
                                 "The sky is blue today."]}
    _, user, _ = build_prompts(item)
    assert "She is a resilient learner studying daily here." in user  # frozen kept
    assert "Released examples" in user
    assert "The sky is blue today." in user  # released, not frozen
    assert "Fill ONLY the 1 missing example slot(s)" in user  # need grew

    def transport(api_key, model, system, prompt):
        return json.dumps(dict(VALID_RESILIENT))

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True
    assert rec["completion_flags"]["released_containment"] == [
        "The sky is blue today."]


def test_containment_passing_stays_frozen_no_release():
    item = {"kind": "word", "text": "resilient", "pool_level": "B2",
            "dataset_examples": ["She is a resilient learner studying daily here.",
                                 "Trees here are resilient."]}
    _, user, _ = build_prompts(item)
    assert "Released examples" not in user
    assert "Both example slots are filled by the frozen dataset" in user

    def transport(api_key, model, system, prompt):
        return json.dumps(dict(VALID_RESILIENT))

    rec = generate_card(item, "key", transport=transport, model_calls={})
    assert rec["valid"] is True
    assert rec["completion_flags"]["released_containment"] == []


def test_completion_flags_always_carries_released_key():
    flags = build_completion_flags(VALID_RESILIENT)
    assert flags["released_containment"] == []
    flags2 = build_completion_flags(VALID_RESILIENT, ["x"])
    assert flags2["released_containment"] == ["x"]


def test_gallery_released_op_chip_and_frozen_keep_chip():
    rec = {"kind": "word", "text": "resilient",
           "dataset_examples": ["She is a resilient learner studying daily here.",
                                "The sky is blue today."],
           "examples_src": ["dataset", "model"],
           "completion_flags": {"released_containment":
                                ["The sky is blue today."]},
           "en_def": "", "model_d": "", "en_source": "",
           "ipa": "", "ipa_src": "model"}
    html_out = render_diff_table(rec, dict(VALID_RESILIENT))
    assert OP_RELEASED in html_out  # verbatim "آزادشده (containment)"


def test_r25_grammar_line_uses_shared_level_guidance():
    assert "نکته گرامری به فارسی بنویس" in GRAMMAR_TIP_FA_RULE
    assert "معادل انگلیسی" in GRAMMAR_TIP_FA_RULE
    item_b2 = {"kind": "word", "text": "resilient", "pool_level": "B2"}
    _, user_b2, bot_level = build_prompts(item_b2)
    assert bot_level == "intermediate"  # anchored pre-card level, never generic
    assert GRAMMAR_TIP_FA_RULE in user_b2
    assert level_prompt_guidance("intermediate") in user_b2
    item_a1 = {"kind": "word", "text": "apple", "pool_level": "A1"}
    _, user_a1, _ = build_prompts(item_a1)
    assert level_prompt_guidance("beginner") in user_a1
    assert level_prompt_guidance("intermediate") not in user_a1


# ------------------------------------------------------------- R26 ---

def _sample_file(tmp_path):
    path = tmp_path / "sample.json"
    path.write_text(json.dumps([
        {"kind": "word", "text": "apple", "pos": "noun",
         "pool_level": "A1"},
        {"kind": "word", "text": "pear", "pos": "noun",
         "pool_level": "A2"},
    ]), encoding="utf-8")
    return str(path)


def _entry():
    return {"pos": "noun", "sounds": [{"ipa": "/x/"}],
            "senses": [{"glosses": ["a fruit"], "tags": [],
                        "examples": []}]}


def _run_only_s1(tmp_path, extra=()):
    sample = _sample_file(tmp_path)
    out = str(tmp_path / "precard.jsonl")
    prog = str(tmp_path / "prog")
    index = {"apple": [{"pos": "noun", "offset": 0, "length": 1}],
             "pear": [{"pos": "noun", "offset": 0, "length": 1}]}
    seen = []

    def read_entry(row):
        seen.append(row)
        return _entry()

    argv = ["--sample", sample, "--out", out, "--progress-dir", prog,
            "--only", "s1"] + list(extra)
    code = precard_pipeline.main(
        argv, _judge_transport=None, _topic_transport=None,
        _assign_transport=None, _sleep_fn=lambda s: None, _index=index,
        _read_entry=read_entry, _tatoeba={}, _zipf_fn=lambda t: 5.0,
        _awl_set=set(), _type_map={}, _type_log_available=False)
    return code, out, prog, seen


def test_r26_only_one_stage_runs():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        import pathlib
        tmp_path = pathlib.Path(tmp)
        code, out, prog, seen = _run_only_s1(tmp_path)
        assert code == 0
        assert seen  # s1 ranked via the injected read_entry
        s1 = json.loads(
            (tmp_path / "prog" / "s1.json").read_text(encoding="utf-8"))
        assert set(s1["done"]) == {"w:apple", "w:pear"}
        assert s1["done"]["w:apple"]["anchor_pos"] == "noun"
        for stage in ("s2", "s3", "s4", "s5"):
            later = json.loads(
                (tmp_path / "prog" / ("%s.json" % stage)).read_text(
                    encoding="utf-8"))
            assert later["done"] == {}
        lines = [line for line in
                 open(out, encoding="utf-8").read().splitlines()
                 if line.strip()]
        assert len(lines) == 2  # survivors assemble even with stages skipped


def test_r26_rekey_forces_redo_and_resume_skips():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        import pathlib
        tmp_path = pathlib.Path(tmp)
        _, _, prog, _ = _run_only_s1(tmp_path)
        # Resume without rekey: injected read_entry never called again.
        _, _, _, seen2 = _run_only_s1(tmp_path)
        assert seen2 == []
        # Rekey one key: only that key is re-ranked.
        rekey = tmp_path / "rekey.txt"
        rekey.write_text("w:apple\n", encoding="utf-8")
        code, _, _, seen3 = _run_only_s1(
            tmp_path, extra=("--rekey", str(rekey)))
        assert code == 0
        # One item re-ranked = its 4 anchor reads (anchor + candidates +
        # R32 pos-tags x2; R34 v9: S1 reuses the probe anchor_pos instead
        # of a separate anchor-pos re-read); a full re-rank would be 8.
        # Pear stayed resumed.
        assert len(seen3) == 4
        s1 = json.loads(
            (tmp_path / "prog" / "s1.json").read_text(encoding="utf-8"))
        assert set(s1["done"]) == {"w:apple", "w:pear"}


def test_r26_dry_run_prints_per_stage_needs(tmp_path, capsys):
    sample = _sample_file(tmp_path)
    code = precard_pipeline.main(
        ["--sample", sample, "--out", str(tmp_path / "p.jsonl"),
         "--progress-dir", str(tmp_path / "prog"), "--dry-run",
         "--only", "S1"],
        _judge_transport=None, _topic_transport=None,
        _assign_transport=None, _sleep_fn=lambda s: None, _index={},
        _read_entry=lambda row: None, _tatoeba={},
        _zipf_fn=lambda t: 5.0, _awl_set=set(), _type_map={},
        _type_log_available=False)
    assert code == 0
    out = capsys.readouterr().out
    assert "need s1: 2 todo" in out
    assert "stage s2: skipped (not selected)" in out


def test_r26_only_and_stages_exclusive(tmp_path):
    sample = _sample_file(tmp_path)
    with pytest.raises(SystemExit):
        precard_pipeline.main(
            ["--sample", sample, "--out", str(tmp_path / "p.jsonl"),
             "--progress-dir", str(tmp_path / "prog"), "--dry-run",
             "--only", "s1", "--stages", "s1"],
            _judge_transport=None, _topic_transport=None,
            _assign_transport=None, _sleep_fn=lambda s: None, _index={},
            _read_entry=lambda row: None, _tatoeba={},
            _zipf_fn=lambda t: 5.0, _awl_set=set(), _type_map={},
            _type_log_available=False)


# ------------------------------------------------------------- R27 ---

def test_telemetry_math_and_missing_usage():
    store = telemetry.new_store()
    telemetry.record_call(store, stage="s2", batch_id=0, key_idx=0,
                          model="m1", prompt_tokens=10,
                          completion_tokens=20, latency_s=0.5, outcome="ok")
    telemetry.record_call(store, stage="s2", batch_id=1, key_idx=1,
                          model="m1", prompt_tokens=5, completion_tokens=5,
                          latency_s=0.1, outcome="ok")
    telemetry.record_call(store, stage="s3", batch_id=0, key_idx=0,
                          model="m2", latency_s=0.2, outcome="fallback")
    summary = telemetry.summarize(store)
    assert summary["records"] == 3
    assert summary["by_stage"]["s2"] == {"calls": 2, "prompt_tokens": 15,
                                         "completion_tokens": 25}
    assert summary["by_stage"]["s3"] == {"calls": 1, "prompt_tokens": 0,
                                         "completion_tokens": 0}
    assert summary["by_model"]["m1"]["calls"] == 2
    assert summary["by_key_idx"]["0"]["calls"] == 2
    assert summary["by_key_idx"]["1"]["calls"] == 1
    # Missing usage tolerated everywhere.
    assert telemetry.extract_usage({}) == (None, None)
    assert telemetry.extract_usage(None) == (None, None)
    assert telemetry.extract_usage({"usage": {"input_tokens": 7}}) == (7, None)
    assert telemetry.extract_usage(
        {"usage": {"prompt_tokens": 3, "completion_tokens": 4}}) == (3, 4)


def test_telemetry_key_value_never_persisted(tmp_path):
    store = telemetry.new_store()
    with pytest.raises(TypeError):
        telemetry.record_call(store, stage="s2", batch_id=0,
                              key_idx="SECRET-KEY-VALUE", model="m1")
    telemetry.record_call(store, stage="s2", batch_id=0, key_idx=0,
                          model="m1", prompt_tokens=1, completion_tokens=2,
                          outcome="ok")
    dest = tmp_path / "telemetry_summary.json"
    telemetry.write_summary(str(dest), store)
    blob = dest.read_text(encoding="utf-8")
    assert "SECRET-KEY-VALUE" not in blob
    assert not telemetry.key_file_contains_value(str(dest), "SECRET-KEY-VALUE")
    assert telemetry.key_file_contains_value(str(dest), '"records"')


def test_phrase_judge_tuple_transport_surfaces_usage():
    batch = [{"phrase": "take care", "freq": 9, "prefill": "A1"}]

    def transport(key, model, prompt):
        assert key == "k"
        return (json.dumps({"results": [
            {"phrase": "take care", "level": "A1", "confidence": 0.9,
             "literal": True}]}),
            {"input_tokens": 11, "output_tokens": 22})

    store = []
    verdicts, model, _ = phrase_judge.grade_batch(
        batch, "k", 3, transport, telemetry=store)
    assert verdicts[0]["level"] == "A1"
    assert len(store) == 1
    assert store[0]["prompt_tokens"] == 11
    assert store[0]["completion_tokens"] == 22
    assert store[0]["batch_id"] == 3
    assert store[0]["key_idx"] == 0
    assert store[0]["outcome"] == "ok"


def test_generate_card_telemetry_records_attempts():
    item = {"kind": "word", "text": "resilient", "pool_level": "B2"}
    store = []

    def transport(api_key, model, system, prompt):
        return json.dumps(dict(VALID_RESILIENT))

    rec = generate_card(item, "k", transport=transport, model_calls={},
                        telemetry=store, tele_batch=2)
    assert rec["valid"] is True
    assert store
    assert all(e["stage"] == "card" and e["key_idx"] == 0 for e in store)
    assert all(e["outcome"] == "ok" for e in store)
    assert store[0]["batch_id"] == 2
    assert store[0]["model"] == card_pilot.MODELS[0]


def test_gallery_telemetry_table_and_final_head():
    summary = telemetry.summarize([
        {"stage": "card", "batch_id": 0, "key_idx": 0, "model": "m1",
         "prompt_tokens": 4, "completion_tokens": 8}])
    table = telemetry.render_telemetry_table(summary)
    assert "فراخوانی" in table
    assert telemetry.render_telemetry_table(None) == ""
    assert telemetry.render_telemetry_table({"records": 0}) == ""
    rec = {"key": "w:resilient", "kind": "word", "text": "resilient",
           "pool_level": "B2", "bot_level": "intermediate",
           "model_used": "m1", "sense_id": "resilient#1",
           "en_def": "able to recover", "en_source": "dataset",
           "topic": "Traits", "topic_method": "v16b-exact",
           "completion_flags": build_completion_flags(dict(VALID_RESILIENT)),
           "similarity_note": 0.0, "leaks": [], "fa_dominant": True,
           "headword_leaks": [], "valid": True, "reason": "",
           "error": "", "card": dict(VALID_RESILIENT)}
    final = render_final_card(rec, dict(VALID_RESILIENT))
    assert 'class="final-head"' in final  # bot-style header present
    assert "resilient" in final  # headword
    assert "rɪˈzɪl" in final  # IPA beside the headword
    gallery = render_gallery(
        [rec], {"date_tehran": "d", "commit": "c", "model_calls": {"m1": 1},
                "telemetry": summary})
    assert "فراخوانی" in gallery
