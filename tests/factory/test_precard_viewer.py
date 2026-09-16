"""Tests for factory/precard/viewer.py (precard run viewer).

Hermetic: tmp_path only, no network, no keys. Fixtures mirror the real
pipeline line outputs (precard.jsonl rows carry the v14.1 fanout fields).
"""

import json
import subprocess
import sys
from pathlib import Path

from factory.precard import viewer
from factory.precard.pipeline import DEFAULT_OUT, DEFAULT_SAMPLE

ROOT = Path(viewer.__file__).resolve().parents[2]

SAMPLE_KEYS = ["w:apple", "w:book", "w:zebra", "w:ghost", "w:teacup",
               "w:umbrella", "w:violin"]


def _row(key, text, sense_id, **extra):
    rec = {"key": key, "kind": "word", "text": text,
           "pool_level": "A1", "sense_id": sense_id,
           "en_def": "def of %s" % text, "ipa": "/%s/" % text,
           "dataset_examples": ["ex %s" % text],
           "example_fallback": "sense", "example_synthetic_needed": False,
           "pos": ["noun"], "sense_cefr": "A1",
           "sense_cefr_method": "pool-fallback",
           "pre_card_id": "id-%s" % sense_id, "fanout_n": 1,
           "stage_calls": {"s2": "m", "s4": "v16b-exact", "s5": "full"},
           "topic_vector": [{"label": "Food & Drink", "weight": 1.0}]}
    rec.update(extra)
    return rec


def _mini_run(tmp_path):
    run_dir = tmp_path / "run-x"
    run_dir.mkdir()
    sample = [{"kind": "word", "text": k.split(":", 1)[1], "key": k,
               "pool_level": "A1"} for k in SAMPLE_KEYS]
    sample_path = run_dir / "sample.json"
    sample_path.write_text(json.dumps(sample), encoding="utf-8")
    rows = [_row("w:apple", "apple", "apple#1"),
            _row("w:apple", "apple", "apple#2"),
            _row("w:book", "book", "book#1"),
            _row("w:zebra", "zebra", "zebra#1",
                 example_synthetic_needed=True, dataset_examples=[]),
            _row("w:teacup", "teacup", "teacup#1"),
            _row("w:umbrella", "umbrella", "umbrella#1"),
            _row("w:violin", "violin", "violin#1"),
            _row("w:violin", "violin", "violin#2"),
            _row("w:extra", "extra", "extra#1"),
            _row("w:extra", "extra", "extra#2")]
    precard_path = run_dir / "precard.jsonl"
    precard_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                            encoding="utf-8")
    dropped_path = run_dir / "dropped.log"
    dropped_path.write_text(
        "=== sense_judge drops ===\n"
        "# auditor comment\n"
        "w:ghost: sense-judge-drop: no surviving sense\n"
        "w:extra2: anchor-drop/low-score\n", encoding="utf-8")
    run_log_path = run_dir / "run.log"
    run_log_path.write_text(
        "[STAGE sense_judge] drop w:Paris:pick-proper-noun/city-geo done\n",
        encoding="utf-8")
    return {"run_dir": run_dir, "sample": sample_path,
            "precard": precard_path, "dropped": dropped_path,
            "run_log": run_log_path}


def _blob(html):
    start = html.find("const RAW_LEMMAS = ") + len("const RAW_LEMMAS = ")
    end = html.find("/*PRECARD_VIEWER_DATA_END*/")
    assert start > 0 and end > start
    payload = html[start:end].strip()
    assert payload.endswith(";")
    return json.loads(payload[:-1])


def test_fail_open_missing_precard(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=tmp_path / "nope.jsonl",
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert "precard rows skipped" in html
    lemmas = _blob(html)
    assert any(entry["key"] == "w:ghost" and entry["dropped"] for entry in lemmas)


def test_fail_open_missing_sample(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=tmp_path / "nope.json",
                             dropped=fix["dropped"], run_log=fix["run_log"])
    assert "sample order skipped" in html
    lemmas = _blob(html)
    assert {entry["key"] for entry in lemmas} >= {"w:apple", "w:ghost"}


def test_fail_open_missing_dropped(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"],
                             dropped=tmp_path / "nope.log",
                             run_log=fix["run_log"])
    assert "dropped list skipped" in html
    lemmas = _blob(html)
    assert all(entry["key"] != "w:extra2" for entry in lemmas)
    assert any(entry["key"] == "w:apple" for entry in lemmas)


def test_fail_open_missing_run_log(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=tmp_path / "nope.log")
    assert "run-log scan skipped" in html
    lemmas = _blob(html)
    assert all(entry["key"] != "w:Paris" for entry in lemmas)


def test_fail_open_all_missing(tmp_path):
    html = viewer.build_html(tmp_path / "empty-run",
                             precard=tmp_path / "a.jsonl",
                             sample=tmp_path / "b.json",
                             dropped=tmp_path / "c.log",
                             run_log=tmp_path / "d.log")
    assert html.count('<div class="viewer-banner">') == 4
    assert _blob(html) == []


def test_markers_once_and_no_gallery_data(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert html.count("PRECARD_VIEWER_DATA_START") == 1
    assert html.count("PRECARD_VIEWER_DATA_END") == 1
    assert "GALLERY_DATA" not in html


def test_golden_mini_run_dir(tmp_path, capsys):
    fix = _mini_run(tmp_path)
    rc = viewer.main(["--run-dir", str(fix["run_dir"]),
                      "--sample", str(fix["sample"])])
    assert rc == 0
    out = fix["run_dir"] / "precard-viewer.html"
    assert out.exists()
    summary = capsys.readouterr().out
    assert summary == "wrote %s rows=10 lemmas=10\n" % out
    html = out.read_text(encoding="utf-8")
    assert "<title>precard viewer \u2014 run-x</title>" in html
    assert "no surviving sense" in html
    assert "pick-proper-noun/city-geo" in html
    lemmas = _blob(html)
    assert [entry["key"] for entry in lemmas] == [
        "w:apple", "w:book", "w:zebra", "w:ghost", "w:teacup",
        "w:umbrella", "w:violin", "w:extra", "w:extra2", "w:Paris"]
    apple = lemmas[0]
    assert apple["dropped"] is False and len(apple["senses"]) == 2
    ghost = [entry for entry in lemmas if entry["key"] == "w:ghost"][0]
    assert ghost["dropped"] is True
    assert ghost["drop_reason"] == "sense-judge-drop: no surviving sense"
    assert ghost["senses"] == []


def test_limit_trims_sample_order(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"], limit=2)
    keys = [entry["key"] for entry in _blob(html)]
    assert keys[:2] == ["w:apple", "w:book"]
    assert len(keys) == 10
    assert "w:ghost" in keys


def test_reference_parity_grouping(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    lemmas = _blob(html)
    rows = [json.loads(line) for line in
            fix["precard"].read_text(encoding="utf-8").splitlines()]
    for entry in lemmas:
        if entry["dropped"]:
            continue
        want = [rec for rec in rows if rec["key"] == entry["key"]]
        assert [s["sense_id"] for s in entry["senses"]] == [
            rec["sense_id"] for rec in want]
        for sense in entry["senses"]:
            for field in ("pre_card_id", "fanout_n", "stage_calls",
                          "example_fallback", "sense_cefr_method",
                          "topic_vector"):
                assert field in sense


def test_sample_dict_shape_and_key_fallback(tmp_path):
    fix = _mini_run(tmp_path)
    sample = {"items": [{"key": "w:violin"},
                        {"kind": "word", "text": "apple"}]}
    sample_path = fix["run_dir"] / "dict-sample.json"
    sample_path.write_text(json.dumps(sample), encoding="utf-8")
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=sample_path, dropped=fix["dropped"],
                             run_log=fix["run_log"])
    keys = [entry["key"] for entry in _blob(html)]
    assert keys[:2] == ["w:violin", "w:apple"]


def test_title_escaped(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"], title="<b>x</b>")
    assert "<title>&lt;b&gt;x&lt;/b&gt;</title>" in html
    assert "<title><b>" not in html


def test_defaults_follow_pipeline():
    assert viewer._default_run_dir() == Path(DEFAULT_OUT).parent
    assert DEFAULT_SAMPLE.endswith("sample.json")


def test_docstring_has_no_banned_words():
    assert "proof" not in viewer.__doc__.lower()
    assert "report" not in viewer.__doc__.lower()


def test_cli_help_lists_interface_flags():
    proc = subprocess.run(
        [sys.executable, "-m", "factory.precard.viewer", "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    for flag in ("--run-dir", "--precard", "--sample", "--dropped",
                 "--run-log", "--out", "--limit", "--title"):
        assert flag in proc.stdout


def test_script_hardening_escapes_data_and_declares_state(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert "function escapeHtml(value)" in html
    assert "let filteredList = [];" in html
    assert "let selectedIndex = -1;" in html
    assert 'let currentCefrFilter = "ALL";' in html
    assert "data-copy-text" in html
    assert "onclick=\"copyText('" not in html
    for raw in ("${item.text}", "${item.key}", "${item.drop_reason}",
                "${s.en_def}", "${s.sense_id}", "${s.pre_card_id}",
                "${topCefr}", "${s.sense_cefr}"):
        assert raw not in html


def test_all_topics_option_shows_lemma_count(tmp_path):
    """Owner review (PR 718 comment): the ALL topic option must render
    a lemma count (RAW_LEMMAS.length, consistent with CEFR ALL), not
    the distinct-topic count (Object.keys(topicCounts).length)."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert "All Topics (${RAW_LEMMAS.length})" in html
    assert "Object.keys(topicCounts).length" not in html
