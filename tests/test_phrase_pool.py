"""Hermetic tests for factory/lexicon/phrase_pool.py + factory/lexicon/phrase_judge.py (TICKET F4).

No network, no real W: dump, no LLM calls: the index fixture and the tiny
evp stub are built inline in tmp_path; judge transport is a mock fn.
"""

import csv
import json
import os
import sys

import pytest

from factory.lexicon.phrase_judge import grade_batch, load_phrases, validate_results
from factory.lexicon.phrase_pool import collect, load_token_levels, main as pool_main, rank


def write_index(path, words):
    with open(path, "w", encoding="utf-8") as handle:
        for word in words:
            handle.write(json.dumps({"word": word, "pos": "noun",
                                     "offset": 0, "length": 1},
                                    ensure_ascii=False) + "\n")


def write_pack(pack_dir, entries):
    os.makedirs(pack_dir, exist_ok=True)
    with open(os.path.join(pack_dir, "evp_sense.json"), "w",
              encoding="utf-8") as handle:
        handle.write(json.dumps({"_meta": {}, "entries": entries}))
    with open(os.path.join(pack_dir, "pack.json"), "w",
              encoding="utf-8") as handle:
        handle.write(json.dumps({}))


@pytest.fixture()
def env(tmp_path):
    pack = str(tmp_path / "pack")
    write_pack(pack, {
        "take|verb|care": {"cefr": "A1"},
        "care|noun|worry": {"cefr": "A2"},
        "lot|noun|amount": {"cefr": "A1"},
    })
    index = str(tmp_path / "index.jsonl")
    write_index(index, [
        "take care", "take care", "take care",  # freq 3
        "lot of trouble", "lot of trouble",    # freq 2
        "Take  Care",                          # dedup collapse -> take care (freq 4)
        "hello",                               # 1 word -> shape skip
        "one two three four five six",         # 6 words -> token-gate skip
        "catch22 club",                        # digit -> shape skip (drop wins)
        "don't stop",                          # apostrophe -> shape skip
        "co-op deal",                          # non-alpha token -> token-gate skip
        "a b",                                 # 1-char token -> token-gate skip
        "by and by",                           # kept, no evp hit -> UNLEVELLED
    ])
    return {"pack": pack, "index": index,
            "out_csv": os.path.join(pack, "phrases.csv"),
            "manifest": os.path.join(pack, "pack.json")}


def run_pool(env, *extra):
    return pool_main(["--index", env["index"], "--out-dir", env["pack"],
                      "--top-n", "500", *extra])


def read_csv_rows(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_shape_routing_and_counters(env, capsys):
    assert run_pool(env) == 0
    out = capsys.readouterr().out
    assert "'skipped_shape': 3" in out  # hello, catch22 club, don't stop
    assert "'skipped_token_gate': 3" in out  # 6-word, co-op, a b
    assert "'unique': 3" in out


def test_dedup_collapse_and_freq_ordering(env):
    assert run_pool(env) == 0
    rows = read_csv_rows(env["out_csv"])
    assert [row["phrase"] for row in rows] == [
        "take care", "lot of trouble", "by and by"]
    assert [row["freq"] for row in rows] == ["4", "2", "1"]
    assert [row["rank"] for row in rows] == ["1", "2", "3"]


def test_top_n_ordering_by_freq(env):
    assert run_pool(env, "--top-n", "2") == 0
    rows = read_csv_rows(env["out_csv"])
    assert len(rows) == 2
    assert rows[0]["phrase"] == "take care"


def test_prefill_max_component_and_unlevelled(env):
    assert run_pool(env) == 0
    by_phrase = {row["phrase"]: row for row in read_csv_rows(env["out_csv"])}
    # take(A1) + care(A2) -> hardest = A2; lot(A1) -> A1.
    assert by_phrase["take care"]["prefill"] == "A2"
    assert by_phrase["lot of trouble"]["prefill"] == "A1"
    assert by_phrase["by and by"]["prefill"] == "UNLEVELLED"


def test_pack_manifest_phrases_section(env):
    assert run_pool(env, "--top-n", "7") == 0
    with open(env["manifest"], encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert manifest["phrases"] == {"file": "phrases.csv", "top_n": 7,
                                   "shape": "2-5", "source": "kaikki-index"}


def test_dry_run_writes_nothing(env, capsys):
    manifest_before = open(env["manifest"], encoding="utf-8").read()
    assert run_pool(env, "--dry-run") == 0
    assert "dry-run" in capsys.readouterr().out
    assert not os.path.exists(env["out_csv"])
    assert open(env["manifest"], encoding="utf-8").read() == manifest_before


def test_collect_prefill_unit(tmp_path):
    pack = str(tmp_path / "pack")
    write_pack(pack, {"zeta|noun|s1": {"cefr": "B2"},
                      "zeta|verb|s2": {"cefr": "A1"}})
    levels = load_token_levels(pack)
    assert levels == {"zeta": "B2"}  # hardest wins per token
    index = str(tmp_path / "index.jsonl")
    write_index(index, ["zeta alpha", "unknown words here"])
    _, phrases = collect(index, levels)
    assert phrases["zeta alpha"]["prefill"] == "B2"
    assert phrases["unknown words here"]["prefill"] == "UNLEVELLED"
    assert rank(phrases, 500)[0]["rank"] == 1


# --- judge validation unit tests (no network) ---


def test_validate_results_accepts_good_batch():
    data = {"results": [
        {"phrase": "take care", "level": "A1", "confidence": 0.9,
         "literal": True},
        {"phrase": "lot of trouble", "level": "A2", "confidence": 0.5,
         "literal": False}]}
    ok, normed = validate_results(data, ["take care", "lot of trouble"])
    assert ok and normed is not None
    assert normed[0]["level"] == "A1"
    assert normed[1]["literal"] is False


def test_validate_results_rejects():
    good = {"phrase": "take care", "level": "A1", "confidence": 0.9,
            "literal": True}
    cases = [
        ({"results": [{**good, "level": "D7"}]}, ["take care"]),  # bad level
        ({"results": [{**good, "confidence": 1.5}]}, ["take care"]),  # bad conf
        ({"results": [{**good, "confidence": "high"}]}, ["take care"]),
        ({"results": [{**good, "literal": "yes"}]}, ["take care"]),  # non-bool
        ({"results": [good]}, ["take care", "lot of trouble"]),  # count mismatch
        ({"results": [{**good, "phrase": "other"}]}, ["take care"]),  # phrase
        ({"results": "nope"}, ["take care"]),
        (["not", "a", "dict"], ["take care"]),
    ]
    for data, want in cases:
        ok, normed = validate_results(data, want)
        assert (ok, normed) == (False, None), data


def test_grade_batch_uses_transport_mock():
    batch = [{"phrase": "take care", "freq": 4, "prefill": "A2"}]

    def fake_transport(api_key, model, user_text):
        assert "take care" in user_text
        return json.dumps({"results": [
            {"phrase": "take care", "level": "B1", "confidence": 0.7,
             "literal": False}]})

    verdicts, model_used, calls = grade_batch(batch, "KEY", 0,
                                              transport=fake_transport)
    assert verdicts[0]["level"] == "B1"
    assert verdicts[0]["attempts"] == 1
    assert model_used.startswith("muse-spark")
    assert sum(calls.values()) == 1


def test_grade_batch_retry_prefix_on_invalid_json():
    batch = [{"phrase": "take care", "freq": 4, "prefill": "A2"}]
    seen = []

    def flaky(api_key, model, user_text):
        seen.append(user_text)
        if len(seen) == 1:
            return "not json at all"
        return json.dumps({"results": [
            {"phrase": "take care", "level": "A1", "confidence": 1.0,
             "literal": True}]})

    verdicts, _, _ = grade_batch(batch, "KEY", 0, transport=flaky)
    assert verdicts[0]["attempts"] == 2
    assert seen[1].startswith("Your last reply was not valid JSON.")


def test_grade_batch_exhaustion_raises_lookup():
    def dead(api_key, model, user_text):
        raise RuntimeError("boom")

    with pytest.raises(LookupError):
        grade_batch([{"phrase": "take care", "freq": 1,
                       "prefill": "A2"}], "KEY", 3, transport=dead)


def test_progress_resume_skips_done(tmp_path):
    # Resume contract: phrases already in done_phrases are never re-sent
    # to the transport; only pending phrases are graded.
    from factory.lexicon import phrase_judge as judge_mod

    phrases_csv = str(tmp_path / "phrases.csv")
    with open(phrases_csv, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["phrase", "freq", "rank", "prefill"])
        for num in range(10):
            writer.writerow([f"phrase {chr(97 + num)}{chr(98 + num)}",
                             str(10 - num), str(num + 1), "A1"])
    progress = str(tmp_path / "progress.json")
    out = str(tmp_path / "judge_log.jsonl")
    rows = load_phrases(phrases_csv)
    first_batch = rows[:8]
    done = {row["phrase"]: {"level": "A1", "confidence": 0.9,
                            "literal": True, "model": "mock", "attempts": 1}
            for row in first_batch}
    with open(progress, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"done_batches": 1, "total_batches": 2,
                                 "done_phrases": done, "failed_phrases": [],
                                 "model_calls": {}}))
    sent: list[str] = []

    def fake_transport(api_key, model, user_text):
        sent.append(user_text)
        pending = rows[8:]
        return json.dumps({"results": [
            {"phrase": row["phrase"], "level": "A2", "confidence": 0.8,
             "literal": True} for row in pending]})

    monkeypatch_env = {"OPENCODE_ZEN_API_KEY": "KEY"}
    old = dict(os.environ)
    os.environ.update(monkeypatch_env)
    try:
        argv = ["--phrases", phrases_csv, "--out", out,
                "--progress", progress]
        # Patch sleep out via module attr; run main with mock transport.
        judge_mod.SLEEP = 0
        assert judge_mod.main(argv, transport=fake_transport) == 0
    finally:
        os.environ.clear()
        os.environ.update(old)
        judge_mod.SLEEP = 2.5
    assert len(sent) == 1  # only the second batch went out
    for row in first_batch:
        assert row["phrase"] not in sent[0]
    with open(progress, encoding="utf-8") as handle:
        saved = json.load(handle)
    assert len(saved["done_phrases"]) == 10
    assert saved["failed_phrases"] == []
