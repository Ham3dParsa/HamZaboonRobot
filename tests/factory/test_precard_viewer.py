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


def _stats_blob(html):
    start = html.find("const STATS = ") + len("const STATS = ")
    assert start > len("const STATS = ")
    end = html.find(";\nconst KNOWN_TOPICS", start)
    assert end > start
    return json.loads(html[start:end])


def test_stats_const_embedded_once_with_mini_counts(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert html.count("const STATS = ") == 1
    stats = _stats_blob(html)
    assert stats["lemmas_total"] == 10
    assert stats["lemmas_kept"] == 7
    assert stats["lemmas_dropped"] == 3
    assert stats["precards_total"] == 10
    assert stats["kept_rate_pct"] == 70
    assert stats["drops_by_reason"] == [
        ["anchor-drop", 1], ["pick-proper-noun", 1],
        ["sense-judge-drop", 1]]
    assert stats["ppc"]["mean"] == 1.43
    assert stats["ppc"]["median"] == 1
    assert stats["ppc"]["p90"] == 2
    assert stats["ppc"]["hist"] == {"1": 4, "2": 3, "3": 0, "4+": 0}
    assert stats["cefr_lemma"]["A1"] == 7
    assert stats["cefr_lemma_overlap"] == 0
    assert stats["cefr_precard"]["A1"] == 10
    assert stats["topic_lemma"] == {"Food & Drink": 7}
    assert stats["topic_precard"] == {"Food & Drink": 10}
    assert stats["synthetic"] == {
        "precards": 1, "precards_pct": 10.0,
        "lemmas": 1, "lemmas_pct": 14.3}
    assert stats["mismatch"] == {
        "precards": 0, "precards_pct": 0.0, "lemmas": 0}


def test_header_strip_names_every_unit(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert '<div class="header-strip"' in html
    assert "<b>10</b> lemmas" in html
    assert "<b>7</b> kept" in html
    assert "<b>3</b> dropped" in html
    assert "<b>10</b> precards" in html
    assert "kept rate <b>70%</b>" in html
    assert "title=\"drops by reason (dropped.log):" in html
    assert "sense-judge-drop: 1 dropped lemmas" in html


def test_dist_drawer_has_six_labeled_groups(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert '<details class="dist-drawer"' in html
    for heading in ("1 \u00b7 precards per kept lemma",
                    "2 \u00b7 kept vs dropped",
                    "3 \u00b7 senses by CEFR",
                    "4 \u00b7 senses by topic",
                    "5 \u00b7 synthetic examples needed",
                    "6 \u00b7 pool-vs-sense CEFR mismatch"):
        assert heading in html
    assert html.count('class="dist-group"') == 6
    assert "lemma-level (exists)" in html
    assert "row-level" in html
    assert "lemma counts overlap" in html


def test_label_rule_no_bare_counts(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert "sense(s) extracted" not in html
    assert "precards (kept-only senses)" in html
    assert "each topic counts kept-only lemmas" in html
    assert "lowest CEFR across senses" in html
    assert "carry no senses" in html
    for raw in ("${lemmaCefr}", "${nPrecards}", "${filteredPrecards}",
                "${hint}", "${item.senses.length} sense"):
        assert raw not in html
    assert "${escapeHtml(hint)}" in html


def test_scrollbars_follow_theme_without_new_palette(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert "color-scheme: light" in html
    assert "color-scheme: dark" in html
    assert "scrollbar-gutter: stable" in html
    assert "scrollbar-width: thin" in html
    assert "scrollbar-color: var(--text-muted) transparent" in html
    assert "::-webkit-scrollbar" in html
    assert "background-clip: content-box" in html
    start = html.find("/* Themed scrollbars")
    end = html.find("/* Header strip")
    assert start > 0 and end > start
    assert "#" not in html[start:end]


def _v141_shape_run(tmp_path):
    """Synthetic 276-lemma / 185-kept / 491-row run mirroring the v141
    totals quoted in issue #726 (491 rows / 276 lemmas / 185 kept)."""
    run_dir = tmp_path / "run-v141"
    run_dir.mkdir()
    kept = ["w:kept%03d" % i for i in range(185)]
    dropped = ["w:drop%03d" % i for i in range(91)]
    sample_path = run_dir / "sample.json"
    sample_path.write_text(
        json.dumps([{"key": k} for k in kept + dropped]),
        encoding="utf-8")
    levels = ["A1", "A2", "B1", "B2", "C1", "C2"]
    labels = ["Food & Drink", "Travel", "Work"]
    rows = []
    idx = 0
    for j, key in enumerate(kept):
        for _ in range(3 if j < 121 else 2):
            sense = levels[idx % 6]
            pool = "C2" if idx % 7 == 0 and sense != "C2" else (
                "A1" if idx % 7 == 0 else sense)
            rows.append({
                "key": key, "text": key.split(":", 1)[1],
                "sense_id": "%s#%d" % (key, idx),
                "sense_cefr": sense, "pool_level": pool,
                "topic_vector": [] if idx % 13 == 0 else [
                    {"label": labels[idx % 3], "weight": 1.0}],
                "example_synthetic_needed": idx % 11 == 0})
            idx += 1
    assert idx == 491
    precard_path = run_dir / "precard.jsonl"
    precard_path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    heads = ["sense-judge-drop: no surviving sense",
             "anchor-drop/low-score", "pick-proper-noun/city-geo"]
    dropped_path = run_dir / "dropped.log"
    dropped_path.write_text(
        "\n".join("%s: %s" % (k, heads[i % 3])
                  for i, k in enumerate(dropped)) + "\n",
        encoding="utf-8")
    run_log_path = run_dir / "run.log"
    run_log_path.write_text("", encoding="utf-8")
    return {"run_dir": run_dir, "sample": sample_path,
            "precard": precard_path, "dropped": dropped_path,
            "run_log": run_log_path}


def test_stats_match_v141_shape_totals(tmp_path):
    fix = _v141_shape_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    stats = _stats_blob(html)
    assert stats["lemmas_total"] == 276
    assert stats["lemmas_kept"] == 185
    assert stats["lemmas_dropped"] == 91
    assert stats["precards_total"] == 491
    assert stats["kept_rate_pct"] == 67
    assert stats["drops_by_reason"] == [
        ["sense-judge-drop", 31], ["anchor-drop", 30],
        ["pick-proper-noun", 30]]
    assert stats["ppc"]["mean"] == 2.65
    assert stats["ppc"]["median"] == 3
    assert stats["ppc"]["p90"] == 3
    assert stats["ppc"]["hist"] == {"1": 0, "2": 64, "3": 121, "4+": 0}
    assert stats["cefr_precard"] == {
        "A1": 82, "A2": 82, "B1": 82, "B2": 82, "C1": 82, "C2": 81,
        "\u2014": 0}
    assert sum(stats["cefr_precard"].values()) == 491
    assert sum(stats["cefr_lemma"].values()) >= 185
    assert sum(stats["cefr_lemma"].values()) - 185 >= stats[
        "cefr_lemma_overlap"]
    assert stats["untagged_precards"] == 38
    assert sum(stats["topic_precard"].values()) == 491 - 38
    assert stats["synthetic"]["precards"] == 45
    assert stats["synthetic"]["precards_pct"] == 9.2
    assert 0 < stats["synthetic"]["lemmas"] <= 185
    assert stats["mismatch"]["precards"] == 71
    assert stats["mismatch"]["precards_pct"] == 14.5
    assert 0 < stats["mismatch"]["lemmas"] <= 185
    assert "<b>276</b> lemmas" in html
    assert "kept rate <b>67%</b>" in html
    assert "<b>491</b> precards" in html


def test_stats_empty_run_has_zeroed_header_and_drawer(tmp_path):
    html = viewer.build_html(tmp_path / "empty-run",
                             precard=tmp_path / "a.jsonl",
                             sample=tmp_path / "b.json",
                             dropped=tmp_path / "c.log",
                             run_log=tmp_path / "d.log")
    stats = _stats_blob(html)
    assert stats["lemmas_total"] == 0
    assert stats["precards_total"] == 0
    assert stats["kept_rate_pct"] == 0
    assert stats["drops_by_reason"] == []
    assert "<b>0</b> lemmas" in html
    assert "no drops recorded" in html
    assert html.count('class="dist-group"') == 6


def test_missing_cefr_renders_single_dash_row(tmp_path):
    """OC review round 1 (PR 727): a precard without CEFR must render
    exactly one missing-CEFR row in the drawer CEFR table."""
    run_dir = tmp_path / "run-missing"
    run_dir.mkdir()
    sample_path = run_dir / "sample.json"
    sample_path.write_text(json.dumps([{"key": "w:bare"}]),
                           encoding="utf-8")
    precard_path = run_dir / "precard.jsonl"
    precard_path.write_text(
        json.dumps({"key": "w:bare", "text": "bare",
                    "sense_id": "bare#1"}) + "\n",
        encoding="utf-8")
    for name in ("dropped.log", "run.log"):
        (run_dir / name).write_text("", encoding="utf-8")
    html = viewer.build_html(
        run_dir, precard=precard_path, sample=sample_path,
        dropped=run_dir / "dropped.log", run_log=run_dir / "run.log")
    stats = _stats_blob(html)
    assert stats["cefr_precard"]["\u2014"] == 1
    assert stats["cefr_lemma"]["\u2014"] == 1
    assert html.count("<td>\u2014</td>") == 1
