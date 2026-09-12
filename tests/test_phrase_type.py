"""Hermetic tests for factory/lexicon/phrase_judge.py --type-pass.

No network, no real W: paths: transport is an injected mock, all files
live in tmp_path.
"""

import csv
import json
from factory.lexicon import phrase_judge
from factory.lexicon.phrase_judge import (
    APPLIED_KEEP_TYPES,
    PHRASE_TYPES,
    RateLimited,
    applied_keep_for,
    call_with_backoff,
    grade_type_batch,
    main,
    validate_type_results,
)

PHRASES = ["break the ice", "give up", "strong coffee", "Tehran",
           "photosynthesis rate"]


def type_reply(phrases, types):
    return json.dumps({"results": [
        {"phrase": p, "phrase_type": t, "proper_noun": t == "proper-noun",
         "applied_keep": True}
        for p, t in zip(phrases, types)]})


def test_applied_keep_mapping_covers_all_types():
    assert set(PHRASE_TYPES) == {
        "idiom", "phrasal-verb", "collocation", "proverb", "slang",
        "applied", "proper-noun", "term", "abbreviation", "other"}
    for phrase_type in ("idiom", "phrasal-verb", "collocation", "proverb",
                        "slang", "applied"):
        assert applied_keep_for(phrase_type) is True
    for phrase_type in ("proper-noun", "term", "other"):
        assert applied_keep_for(phrase_type) is False
    assert APPLIED_KEEP_TYPES == {
        "idiom", "phrasal-verb", "collocation", "proverb", "slang",
        "applied"}


def test_applied_keep_abbreviation_en_only():
    # R29 v8: "abbreviation" keeps for EN (default) but drops for
    # other languages; every other label is lang-independent.
    assert applied_keep_for("abbreviation") is True
    assert applied_keep_for("abbreviation", "en") is True
    assert applied_keep_for("abbreviation", "fa") is False
    assert applied_keep_for("abbreviation", "de") is False
    assert applied_keep_for("idiom", "fa") is True
    assert applied_keep_for("other", "en") is False
    ok, normed = validate_type_results(
        json.loads(type_reply(["TV"], ["abbreviation"])), ["TV"])
    assert ok is True
    assert normed == [{"phrase": "TV", "phrase_type": "abbreviation",
                       "proper_noun": False, "applied_keep": True}]


def test_type_parse_recomputes_applied_keep():
    # Model says applied_keep=true for a proper noun; the deterministic
    # rule wins (false).
    ok, normed = validate_type_results(
        json.loads(type_reply(["Tehran"], ["proper-noun"])), ["Tehran"])
    assert ok is True
    assert normed == [{"phrase": "Tehran", "phrase_type": "proper-noun",
                       "proper_noun": True, "applied_keep": False}]
    ok, normed = validate_type_results(
        json.loads(type_reply(["give up"], ["phrasal-verb"])), ["give up"])
    assert ok is True
    assert normed[0]["applied_keep"] is True
    # Rejects: bad type, non-bool proper_noun, phrase mismatch, count.
    bad = {"results": [{"phrase": "x", "phrase_type": "nope",
                        "proper_noun": False, "applied_keep": False}]}
    assert validate_type_results(bad, ["x"]) == (False, None)
    bad_bool = {"results": [{"phrase": "x", "phrase_type": "idiom",
                             "proper_noun": "yes",
                             "applied_keep": True}]}
    assert validate_type_results(bad_bool, ["x"]) == (False, None)
    assert validate_type_results({"results": []}, ["x"]) == (False, None)
    assert validate_type_results({"nope": 1}, ["x"]) == (False, None)


def test_grade_type_batch_uses_type_prompt_and_chain():
    seen = {}

    def transport(api_key, model, prompt, sys_text=""):
        seen.setdefault("sys", sys_text)
        assert "phrase_type" in prompt
        assert "proper-noun" in prompt
        if model == phrase_judge.MODELS[0]:
            raise ValueError("boom")  # first model fails -> chain moves on
        return type_reply(PHRASES[:2], ["idiom", "phrasal-verb"])

    verdicts, model_used, calls = grade_type_batch(
        PHRASES[:2], "key", 0, transport)
    assert model_used == phrase_judge.MODELS[1]
    assert [v["phrase_type"] for v in verdicts] == ["idiom", "phrasal-verb"]
    assert [v["applied_keep"] for v in verdicts] == [True, True]
    assert "lexicographer typing" in seen["sys"]


def write_judge_log(path, phrases):
    with open(path, "w", encoding="utf-8") as handle:
        for phrase in phrases:
            handle.write(json.dumps({"phrase": phrase, "freq": 5,
                                     "prefill": "B1",
                                     "verdict_level": "B1",
                                     "confidence": 0.9, "literal": False,
                                     "model_used": "m",
                                     "failed_flag": False}) + "\n")


def test_type_pass_end_to_end_and_resume(tmp_path, monkeypatch):
    # Hermetic: transports are mocked, so a dummy key satisfies the
    # fail-closed env loader (CI has no factory/.env).
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    judge_log = tmp_path / "judge_log.jsonl"
    write_judge_log(str(judge_log), PHRASES)
    out = tmp_path / "phrase_type_log.jsonl"
    prog = tmp_path / "phrase_type_progress.json"
    calls = {"n": 0}

    # Deterministic mock: answer exactly the requested phrases by echoing
    # the batch back — extract from the JSON embedded in prompt.
    def echo_transport(api_key, model, prompt, sys_text=""):
        calls["n"] += 1
        start = prompt.rindex("[")  # batch JSON trails the template text
        batch = json.loads(prompt[start:].strip())
        return json.dumps({"results": [
            {"phrase": row["phrase"], "phrase_type": "collocation",
             "proper_noun": False, "applied_keep": False}
            for row in batch]})

    rc = main(["--type-pass", "--out", str(judge_log),
               "--type-out", str(out), "--type-progress", str(prog)],
              transport=echo_transport)
    assert rc == 0
    lines = [json.loads(line) for line in
             open(str(out), encoding="utf-8") if line.strip()]
    assert [line["phrase"] for line in lines] == PHRASES
    for line in lines:
        assert set(line) == {"phrase", "phrase_type", "proper_noun",
                             "applied_keep", "model"}
        assert line["phrase_type"] == "collocation"
        assert line["applied_keep"] is True  # rule recomputed, not model echo
        assert line["model"] == phrase_judge.MODELS[0]
    saved = json.loads(open(str(prog), encoding="utf-8").read())
    assert saved["done_batches"] == saved["total_batches"] == 1
    assert set(saved["done_phrases"]) == set(PHRASES)

    # Resume: everything done -> transport never called again.
    calls["n"] = 0
    rc = main(["--type-pass", "--out", str(judge_log),
               "--type-out", str(out), "--type-progress", str(prog)],
              transport=echo_transport)
    assert rc == 0
    assert calls["n"] == 0
    assert len([line for line in open(str(out), encoding="utf-8")
                if line.strip()]) == len(PHRASES)  # no duplicates


def test_type_pass_falls_back_to_phrases_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    phrases_csv = tmp_path / "phrases.csv"
    with open(str(phrases_csv), "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["phrase", "freq",
                                                    "prefill"])
        writer.writeheader()
        writer.writerow({"phrase": "break the ice", "freq": 9,
                         "prefill": "B1"})
    out = tmp_path / "phrase_type_log.jsonl"
    prog = tmp_path / "phrase_type_progress.json"

    def echo_transport(api_key, model, prompt, sys_text=""):
        start = prompt.rindex("[")  # batch JSON trails the template text
        batch = json.loads(prompt[start:].strip())
        return json.dumps({"results": [
            {"phrase": row["phrase"], "phrase_type": "idiom",
             "proper_noun": False, "applied_keep": True}
            for row in batch]})

    rc = main(["--type-pass",
               "--out", str(tmp_path / "missing-judge-log.jsonl"),
               "--phrases", str(phrases_csv),
               "--type-out", str(out), "--type-progress", str(prog)],
              transport=echo_transport)
    assert rc == 0
    lines = [json.loads(line) for line in
             open(str(out), encoding="utf-8") if line.strip()]
    assert lines == [{"phrase": "break the ice", "phrase_type": "idiom",
                      "proper_noun": False, "applied_keep": True,
                      "model": phrase_judge.MODELS[0]}]


def test_type_pass_dry_run_writes_nothing(tmp_path):
    judge_log = tmp_path / "judge_log.jsonl"
    write_judge_log(str(judge_log), PHRASES[:2])
    out = tmp_path / "phrase_type_log.jsonl"
    prog = tmp_path / "phrase_type_progress.json"
    rc = main(["--type-pass", "--dry-run", "--out", str(judge_log),
               "--type-out", str(out), "--type-progress", str(prog)],
              transport=None)
    assert rc == 0
    assert not out.exists()
    assert not prog.exists()

def test_backoff_rotates_keys_then_succeeds(monkeypatch):
    import urllib.error
    from factory.lexicon.phrase_judge import KeyRing
    calls = []
    sleeps = []
    monkeypatch.setattr(phrase_judge.time, "sleep", sleeps.append)

    def transport(api_key, model, prompt, sys_text=None):
        calls.append(api_key)
        if api_key == "k1":
            raise urllib.error.HTTPError("http://x", 429, "throttled", {}, None)
        return "ok"

    ring = KeyRing(["k1", "k2"])
    assert call_with_backoff(transport, "k1", "m", "p", ring=ring) == "ok"
    assert calls == ["k1", "k2"]
    assert sleeps == [5]


def test_backoff_non_consecutive_429s_do_not_exhaust(monkeypatch):
    # F1: a success between 429s resets the ring streak — two
    # non-consecutive 429s on two keys must NOT raise RateLimited
    # (without the reset the second 429 completes the circle and raises).
    import urllib.error
    from factory.lexicon.phrase_judge import KeyRing
    monkeypatch.setattr(phrase_judge.time, "sleep", lambda s: None)
    script = iter(["429", "ok-k2", "429", "ok-k1"])

    def transport(api_key, model, prompt, sys_text=None):
        if next(script) == "429":
            raise urllib.error.HTTPError(
                "http://x", 429, "throttled", {}, None)
        return "ok-%s" % api_key

    ring = KeyRing(["k1", "k2"])
    assert call_with_backoff(transport, "k1", "m", "p", ring=ring) == "ok-k2"
    assert call_with_backoff(transport, "k1", "m", "p", ring=ring) == "ok-k1"


def test_backoff_stops_when_all_keys_429(monkeypatch):
    import urllib.error
    import pytest
    from factory.lexicon.phrase_judge import KeyRing
    monkeypatch.setattr(phrase_judge.time, "sleep", lambda s: None)

    def transport(api_key, model, prompt, sys_text=None):
        raise urllib.error.HTTPError("http://x", 429, "throttled", {}, None)

    with pytest.raises(RateLimited):
        call_with_backoff(transport, "k1", "m", "p",
                          ring=KeyRing(["k1", "k2"]))

def test_cefr_grade_propagates_ratelimited():
    import urllib.error
    import pytest
    from factory.lexicon.phrase_judge import KeyRing, RateLimited, grade_batch

    def transport(api_key, model, prompt, sys_text=None):
        raise urllib.error.HTTPError("http://x", 429, "throttled", {}, None)

    batch = [{"phrase": "time flies", "freq": 5, "prefill": "B1"}]
    with pytest.raises(RateLimited):
        grade_batch(batch, "k1", 0, transport, ring=KeyRing(["k1", "k2"]))


def test_keyring_empty_keys_fail_loud_not_zero_division():
    # OPENCODE critical (a): KeyRing([]) used to ZeroDivisionError in
    # rotate() (and IndexError in current). Must fail with a clear error.
    import pytest
    from factory.lexicon.phrase_judge import KeyRing
    with pytest.raises(ValueError):
        KeyRing([])
    with pytest.raises(ValueError):
        KeyRing(["", ""])
    ring = KeyRing(["k1"])
    assert ring.current == "k1"
    assert ring.rotate() is False  # single key: full circle -> exhausted
