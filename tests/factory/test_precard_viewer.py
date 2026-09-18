"""Tests for factory/precard/viewer.py (precard run viewer).

Hermetic: tmp_path only, no network, no keys. Fixtures mirror the real
pipeline line outputs (precard.jsonl rows carry the v14.1 fanout fields).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

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
           "register": "neutral", "lexical_type": "word",
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
        "precards": 0, "precards_pct": 0.0, "lemmas": 0,
        "evidenced_precards": 0, "evidenced_denominator": 0,
        "evidenced_pct": 0.0}
    assert stats["cefr_method"] == {"pool-fallback": 10}
    assert stats["topic_path"] == {"(unknown)": 10}
    assert stats["example_source"] == {"sense": 10}


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


def test_dist_drawer_has_nine_labeled_groups(tmp_path):
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
                    "6 \u00b7 pool-vs-sense CEFR mismatch",
                    "7 \u00b7 CEFR provenance",
                    "8 \u00b7 topic s4 paths",
                    "9 \u00b7 example sourcing"):
        assert heading in html
    assert html.count('class="dist-group"') == 9
    assert "lemma-level (exists)" in html
    assert "row-level" in html
    assert "lemma counts overlap" in html
    assert "nine metric groups" in html


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
    paths = ["llm", "fallback", "leg1", "cache"]
    sources = ["sense", "lemma", "pool"]
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
                "sense_cefr_method": "wn-single" if idx % 3 == 0
                else "pool-fallback",
                "stage_calls": {"s4_path": paths[idx % 4]},
                "example_fallback": sources[idx % 3],
                "register": "informal" if idx % 17 == 0 else "neutral",
                "lexical_type": "colloquial" if idx % 29 == 0 else "word",
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
    assert stats["mismatch"]["evidenced_precards"] == 24
    assert stats["mismatch"]["evidenced_denominator"] == 164
    assert stats["mismatch"]["evidenced_pct"] == 14.6
    assert stats["cefr_method"] == {
        "pool-fallback": 327, "wn-single": 164}
    assert stats["topic_path"] == {
        "llm": 123, "fallback": 123, "leg1": 123, "cache": 122}
    assert stats["example_source"] == {
        "sense": 164, "lemma": 164, "pool": 163}
    assert "evidenced-only" in html
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
    assert stats["cefr_method"] == {}
    assert stats["topic_path"] == {}
    assert stats["example_source"] == {}
    assert stats["mismatch"]["evidenced_denominator"] == 0
    assert "<b>0</b> lemmas" in html
    assert "no drops recorded" in html
    assert "no rows" in html
    assert html.count('class="dist-group"') == 9


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


def test_register_filter_wiring_and_units(tmp_path):
    """Issue #729 item 4 + follow-up F1: one combined style select with
    field-origin prefixes, kept-only counts, any-sense match, labeled
    units. JS runs client-side; assert wiring."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert '<select id="registerFilter"' in html
    assert "each style counts kept-only lemmas" in html
    assert "All Styles (${RAW_LEMMAS.length})" in html
    assert "lemmaStyles" in html
    assert "register:${s.register}" in html
    assert "type:${s.lexical_type}" in html
    assert 'field === "register" ? s.register === want' in html
    assert "kept lemmas)" in html
    assert "opt.textContent = `${v} (${styleCounts[v]} kept lemmas)`" in html
    assert "${style}" not in html


def test_method_source_filter_wiring_and_units(tmp_path):
    """Follow-up F2: method + source selects, kept-only counts,
    any-sense match, labeled units. JS runs client-side; assert wiring."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert '<select id="methodFilter"' in html
    assert '<select id="sourceFilter"' in html
    assert "each method counts kept-only lemmas" in html
    assert "each source counts kept-only lemmas" in html
    assert "All Methods (${RAW_LEMMAS.length})" in html
    assert "All Sources (${RAW_LEMMAS.length})" in html
    assert "(s.sense_cefr_method || \"(unknown)\") === method" in html
    assert "(s.example_fallback || \"(unknown)\") === source" in html
    assert "CEFR/topic/style/method/source filter never matches" in html
    assert "${method}" not in html
    assert "${source}" not in html


def test_strings_catalog_key_parity_and_placeholders():
    assert set(viewer.STRINGS["fa"]) == set(viewer.STRINGS["en"])
    assert len(viewer.STRINGS["en"]) >= 80
    for key in ("strip", "drops.tip", "count", "count.title", "g1.kv",
                "g2.kv", "g5.kv", "g6.kv", "g6.ev", "title", "opt.kept",
                "pill.all", "pill.level"):
        assert (set(re.findall(r"\{[A-Za-z]+\}", viewer.STRINGS["fa"][key]))
                == set(re.findall(r"\{[A-Za-z]+\}",
                                  viewer.STRINGS["en"][key])))
    for key, markers in (("strip", ("{N}", "{K}", "{D}", "{P}", "{R}")),
                         ("title", ("{run}",)),
                         ("drops.tip", ("{H}", "{N}")),
                         ("g5.kv", ("{P}", "{PP}", "{M}", "{MP}"))):
        for marker in markers:
            assert marker in viewer.STRINGS["fa"][key]
            assert marker in viewer.STRINGS["en"][key]


def test_default_lang_is_en(tmp_path):
    fix = _mini_run(tmp_path)
    kwargs = {"precard": fix["precard"], "sample": fix["sample"],
              "dropped": fix["dropped"], "run_log": fix["run_log"]}
    assert viewer.build_html(fix["run_dir"], **kwargs) == viewer.build_html(
        fix["run_dir"], lang="en", **kwargs)


def test_inject_en_toggle_inserts_single_line():
    """Hermetic replacement for the origin/main golden test (CI checkouts
    lack the origin/main ref): the EN toggle injection adds exactly one
    line and changes nothing else."""
    page = ("<header>\n"
            "      </button>\n    </div>\n  </header>\n"
            "<p>body</p>")
    got = viewer._inject_en_toggle(page, "precard-viewer.fa.html")
    assert got.count(">FA</a>") == 1
    assert "precard-viewer.fa.html" in got
    assert got.replace(viewer._en_toggle("precard-viewer.fa.html"),
                       "") == page


def test_en_twin_links_to_fa_sibling_default(tmp_path):
    """Round 2 item 1: default twins link both ways (EN->FA, FA->EN)."""
    fix = _mini_run(tmp_path)
    rc = viewer.main(["--run-dir", str(fix["run_dir"]),
                      "--sample", str(fix["sample"])])
    assert rc == 0
    en_html = (fix["run_dir"] / "precard-viewer.html").read_text(
        encoding="utf-8")
    fa_html = (fix["run_dir"] / "precard-viewer.fa.html").read_text(
        encoding="utf-8")
    assert 'href="precard-viewer.fa.html"' in en_html
    assert ">FA</a>" in en_html
    assert 'href="precard-viewer.html"' in fa_html


def test_en_twin_links_to_fa_sibling_custom_out(tmp_path):
    """Round 2 item 1: custom --out names work via _fa_sibling logic."""
    fix = _mini_run(tmp_path)
    custom = fix["run_dir"] / "custom-viewer.html"
    rc = viewer.main(["--run-dir", str(fix["run_dir"]),
                      "--sample", str(fix["sample"]),
                      "--out", str(custom)])
    assert rc == 0
    want_fa = viewer._fa_sibling(custom).name
    assert want_fa != "precard-viewer.fa.html"
    en_html = custom.read_text(encoding="utf-8")
    assert 'href="%s"' % want_fa in en_html
    assert ">FA</a>" in en_html
    assert viewer._fa_sibling(custom).exists()
    fa_html = viewer._fa_sibling(custom).read_text(encoding="utf-8")
    assert 'href="%s"' % custom.name in fa_html


def test_fa_hero_and_sidebar_badges_use_pishkart(tmp_path):
    """Round 2 item 2: hero + sidebar badges read '{N} پیش‌کارت'."""
    fix = _mini_run(tmp_path)
    fa_html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                                sample=fix["sample"], dropped=fix["dropped"],
                                run_log=fix["run_log"], lang="fa")
    assert "${escapeHtml(item.senses.length)} پیش‌کارت</span>" in fa_html
    assert "${escapeHtml(nPrecards)} پیش‌کارت</span>" in fa_html
    assert "${escapeHtml(item.senses.length)} precards</span>" not in fa_html
    assert "${escapeHtml(nPrecards)} precards</span>" not in fa_html


def test_fa_g7_g8_g9_cells_use_pishkart(tmp_path):
    """Round 2 item 2: g7/g8/g9 row cells read '{N} پیش‌کارت ({P}٪)'."""
    fix = _mini_run(tmp_path)
    fa_html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                                sample=fix["sample"], dropped=fix["dropped"],
                                run_log=fix["run_log"], lang="fa")
    assert "10 پیش‌کارت (" in fa_html
    assert re.search(r"[0-9]+ پیش‌کارت", fa_html)
    assert "٪" in fa_html
    assert " precards (" not in fa_html


def test_fa_option_titles_unified_pattern(tmp_path):
    """Round 2 item 3: style/method/source per-option titles share the
    unified '{v}: {N} لمای نگه‌داشته‌شده با معنی منطبق' pattern."""
    fix = _mini_run(tmp_path)
    fa_html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                                sample=fix["sample"], dropped=fix["dropped"],
                                run_log=fix["run_log"], lang="fa")
    assert ("`${v}: ${styleCounts[v]} "
            "لمای نگه‌داشته‌شده با معنی منطبق`") in fa_html
    assert ("`${v}: ${methodCounts[v]} "
            "لمای نگه‌داشته‌شده با معنی منطبق`") in fa_html
    assert ("`${v}: ${sourceCounts[v]} "
            "لمای نگه‌داشته‌شده با معنی منطبق`") in fa_html
    for leftover in ("kept-only lemmas with any sense carrying it",
                     "kept-only lemmas with any sense using it",
                     "kept-only lemmas with any sense from it"):
        assert leftover not in fa_html
    assert "register:${s.register}" in fa_html
    assert "type:${s.lexical_type}" in fa_html


def test_fa_build_rtl_shell_and_chrome(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"], lang="fa")
    assert '<html lang="fa" dir="rtl"' in html
    assert "استودیو پیش‌کارت" in html
    assert "در حال بارگذاری…" in html
    assert "یک واژه را از فهرست کناری انتخاب کنید" in html
    assert "نرخ ماندگاری" in html
    assert '[dir="rtl"]' in html


def test_cli_lang_flag_builds_twin_files(tmp_path):
    fix = _mini_run(tmp_path)
    rc = viewer.main(["--run-dir", str(fix["run_dir"]),
                      "--sample", str(fix["sample"]), "--lang", "fa"])
    assert rc == 0
    assert (fix["run_dir"] / "precard-viewer.html").exists()
    assert (fix["run_dir"] / "precard-viewer.fa.html").exists()
    fa_html = (fix["run_dir"] / "precard-viewer.fa.html").read_text(
        encoding="utf-8")
    assert '<html lang="fa" dir="rtl"' in fa_html


def test_cli_help_lists_lang_flag():
    proc = subprocess.run(
        [sys.executable, "-m", "factory.precard.viewer", "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    assert "--lang" in proc.stdout


def test_fa_embeds_ui_strings_next_to_stats(tmp_path):
    fix = _mini_run(tmp_path)
    en_html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                                sample=fix["sample"], dropped=fix["dropped"],
                                run_log=fix["run_log"], lang="en")
    fa_html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                                sample=fix["sample"], dropped=fix["dropped"],
                                run_log=fix["run_log"], lang="fa")
    assert "const UI_STRINGS = " not in en_html
    assert fa_html.count("const UI_STRINGS = ") == 1
    anchor = fa_html.find("const STATS = ")
    strings_at = fa_html.find("const UI_STRINGS = ")
    assert anchor > 0 and strings_at > anchor
    for ref in ('UI_STRINGS["empty.h"]', "UI_STRINGS['empty.h']",
                'UI_STRINGS["count"]', "UI_STRINGS['count']"):
        if ref in fa_html:
            break
    else:
        raise AssertionError("FA JS has no UI_STRINGS lookups")


def test_no_catalog_en_literals_in_fa(tmp_path):
    fix = _mini_run(tmp_path)
    fa_html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                                sample=fix["sample"], dropped=fix["dropped"],
                                run_log=fix["run_log"], lang="fa")
    for literal in ("Precard Studio", "Loading...",
                    "Search lemma or key... (press /)",
                    "Select a word from the left list",
                    "All Topics", "All Statuses", "Kept Only",
                    "Dropped Only", "Needs Synthetic Ex", "All Styles",
                    "All Methods", "All Sources", "Original Order",
                    "Senses (High to Low)", "CEFR Level",
                    "No matching lemmas found",
                    "Try adjusting your filters or search query.",
                    "precard viewer",                     "precard rows skipped",
                    "sample order skipped", "dropped list skipped",
                    "run-log scan skipped", "Copy ID", "Copy Sense",
                    "Copied!", "Pipeline:"):
        assert literal not in fa_html
    assert ">DROP<" not in fa_html
    assert "حذف" in fa_html


@pytest.mark.parametrize("lang,units", [
    ("en", ("precards (kept-only senses)",
             "each topic counts kept-only lemmas",
             "lowest CEFR across senses",
             "carry no senses",
             "kept-only rows",
             "kept lemmas / all lemmas")),
    ("fa", ("فقط معنی‌های نگه‌داشته‌شده",
             "فقط لِماهای نگه‌داشته‌شده را می‌شمارد",
             "پایین‌ترین CEFR",
             "معنی‌ای ندارند",
             "فقط ردیف‌های نگه‌داشته‌شده",
             "لِماهای نگه‌داشته‌شده / همه لِماها")),
])
def test_label_rule_units_both_langs(tmp_path, lang, units):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"], lang=lang)
    for unit in units:
        assert unit in html
    assert re.search(r"[0-9]", html)


def test_v141_shape_fa_header_numbers(tmp_path):
    fix = _v141_shape_run(tmp_path)
    fa_html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                                sample=fix["sample"], dropped=fix["dropped"],
                                run_log=fix["run_log"], lang="fa")
    assert "<b>276</b>" in fa_html
    assert "<b>185</b>" in fa_html
    assert "<b>91</b>" in fa_html
    assert "<b>491</b>" in fa_html
    assert "67٪" in fa_html or "67%" in fa_html
    assert "لِما" in fa_html
    assert "پیش‌کارت" in fa_html
    assert "نرخ ماندگاری" in fa_html


def test_fa_prose_uses_offline_sans_stack(tmp_path):
    """Charts v2: EN stays fully offline; FA charts path may load
    Vazirmatn via CDN with an offline-safe fallback stack (layout
    identical without the font, no global overrides)."""
    fix = _mini_run(tmp_path)
    en_html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                                sample=fix["sample"], dropped=fix["dropped"],
                                run_log=fix["run_log"], lang="en")
    fa_html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                                sample=fix["sample"], dropped=fix["dropped"],
                                run_log=fix["run_log"], lang="fa")
    assert "fonts.googleapis.com" not in en_html
    assert "family=Vazirmatn" in fa_html
    assert "'Vazirmatn', \"Segoe UI\", system-ui" in fa_html
    assert '[dir="rtl"] .dist-group table' in fa_html
    assert '[dir="rtl"] .header-strip' in fa_html
    assert '"Segoe UI", system-ui, sans-serif' in fa_html


def test_main_fails_closed_on_broken_template(tmp_path, monkeypatch):
    """OC review round 1 (PR 748): a missing chrome anchor must exit
    non-zero with a message, not an unhandled traceback."""
    fix = _mini_run(tmp_path)
    monkeypatch.setattr(
        viewer, "_HTML_TEMPLATE",
        viewer._HTML_TEMPLATE.replace(
            "      </button>\n    </div>\n  </header>", "GONE"))
    rc = viewer.main(["--run-dir", str(fix["run_dir"]),
                      "--sample", str(fix["sample"])])
    assert rc != 0


def test_fa_custom_out_twin_links_and_help(tmp_path):
    """OC review round 1 (PR 748): --lang fa --out writes both twins with
    cross-pointing escaped hrefs; --help documents twin behavior."""
    fix = _mini_run(tmp_path)
    out = fix["run_dir"] / "custom-fa.html"
    rc = viewer.main(["--run-dir", str(fix["run_dir"]),
                      "--sample", str(fix["sample"]),
                      "--lang", "fa", "--out", str(out)])
    assert rc == 0
    fa_html = out.read_text(encoding="utf-8")
    en_twin = out.parent / viewer._en_sibling(out).name
    assert en_twin.exists()
    en_html = en_twin.read_text(encoding="utf-8")
    assert 'href="%s"' % en_twin.name in fa_html
    assert 'href="%s"' % out.name in en_html


def test_metrics_drawer_open_by_default(tmp_path):
    """Tabs restructure: the relocated drawer must render open inside the
    Metrics pane, otherwise the tab shows only its summary line."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert '<details class="dist-drawer" id="distDrawer" open>' in html
    proc = subprocess.run(
        [sys.executable, "-m", "factory.precard.viewer", "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    assert "both twins" in proc.stdout


def test_colliding_out_refuses_to_overwrite_twin(tmp_path):
    """OC review round 2 (PR 748): --lang en --out x.fa.html resolves
    both twins to one path — refuse with exit 2 instead of overwriting."""
    fix = _mini_run(tmp_path)
    out = fix["run_dir"] / "custom.fa.html"
    rc = viewer.main(["--run-dir", str(fix["run_dir"]),
                      "--sample", str(fix["sample"]),
                      "--lang", "en", "--out", str(out)])
    assert rc == 2


def test_fa_twin_links_to_en_sibling_custom_out(tmp_path):
    fix = _mini_run(tmp_path)
    out = fix["run_dir"] / "custom-viewer.html"
    rc = viewer.main(["--run-dir", str(fix["run_dir"]),
                      "--sample", str(fix["sample"]),
                      "--out", str(out)])
    assert rc == 0
    fa_html = (fix["run_dir"] / "custom-viewer.fa.html").read_text(
        encoding="utf-8")
    assert 'href="custom-viewer.html"' in fa_html


def test_drop_suffix_stripped_at_reader_with_band_field(tmp_path):
    """OC blocking W1: enriched lines ("w:X: reason [entry=B1]") must not
    leak the suffix into viewer reason grouping — the reader strips it
    and carries the band as a separate entry_band field. Legacy lines
    keep entry_band None."""
    fix = _mini_run(tmp_path)
    fix["dropped"].write_text(
        "=== preprocess drops ===\n"
        "w:suffixed: r4-name-only [entry=B1]\n"
        "w:legacy: g2-inflection-form\n"
        "w:colonless [entry=A1]\n",
        encoding="utf-8")
    dropped = viewer._load_dropped(fix["dropped"], None)
    assert dropped["w:suffixed"] == {
        "reason": "r4-name-only", "entry_band": "B1"}
    assert dropped["w:legacy"] == {
        "reason": "g2-inflection-form", "entry_band": None}
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    stats = _stats_blob(html)
    heads = dict(stats["drops_by_reason"])
    assert heads.get("r4-name-only") == 1, stats["drops_by_reason"]
    assert heads.get("g2-inflection-form") == 1, stats["drops_by_reason"]
    assert not any("[entry=" in head for head, _ in
                   stats["drops_by_reason"])
    lemmas = _blob(html)
    suf = [e for e in lemmas if e["key"] == "w:suffixed"][0]
    assert suf["dropped"] is True
    assert suf["drop_reason"] == "r4-name-only"
    assert suf["entry_band"] == "B1"
    leg = [e for e in lemmas if e["key"] == "w:legacy"][0]
    assert leg["drop_reason"] == "g2-inflection-form"
    assert leg["entry_band"] is None


def test_colonless_reason_head_never_carries_suffix():
    """W1 companion: a colon-less reason with a suffix must group under
    its bare head, never the whole suffixed string."""
    assert viewer._drop_reason("failed-no-entry [entry=B1]") == \
        "failed-no-entry"
    assert viewer._drop_band("failed-no-entry [entry=B1]") == "B1"
    assert viewer._reason_head(
        viewer._drop_reason("failed-no-entry [entry=B1]")) == \
        "failed-no-entry"


def test_unmapped_rows_not_counted_as_evidenced():
    """OC round 2 W1: unmapped rows are not evidenced — only wn-single /
    wn-evp-gloss count, so an empty sense_cefr vs pool mismatch stays
    out of the evidenced denominator."""
    rows = {
        "w:a": [{"sense_cefr": "B1", "pool_level": "A1",
                 "sense_cefr_method": "wn-single",
                 "stage_calls": {}, "topic_vector": []}],
        "w:b": [{"sense_cefr": "", "pool_level": "A1",
                 "sense_cefr_method": "unmapped",
                 "stage_calls": {}, "topic_vector": []}],
        "w:c": [{"sense_cefr": "A1", "pool_level": "A1",
                 "sense_cefr_method": "unmapped",
                 "stage_calls": {}, "topic_vector": []}],
    }
    stats = viewer._compute_stats(rows, {})
    assert stats["mismatch"]["precards"] == 1
    assert stats["mismatch"]["evidenced_denominator"] == 1
    assert stats["mismatch"]["evidenced_precards"] == 1
    assert stats["mismatch"]["evidenced_pct"] == 100.0


def test_evp_gloss_counts_as_evidenced():
    """OC round 2 W1: wn-evp-gloss is evidenced alongside wn-single."""
    rows = {
        "w:a": [{"sense_cefr": "B1", "pool_level": "A1",
                 "sense_cefr_method": "wn-evp-gloss",
                 "stage_calls": {}, "topic_vector": []}],
        "w:b": [{"sense_cefr": "", "pool_level": "A1",
                 "sense_cefr_method": "pool-fallback",
                 "stage_calls": {}, "topic_vector": []}],
    }
    stats = viewer._compute_stats(rows, {})
    assert stats["mismatch"]["precards"] == 1
    assert stats["mismatch"]["evidenced_denominator"] == 1
    assert stats["mismatch"]["evidenced_precards"] == 1


def _charts_section(html):
    sec = html.find('<section id="chartsPane"')
    assert sec >= 0, "charts pane section missing"
    end = html.find("\n  </section>", sec)
    assert end > sec
    return html[sec:end]


def _build_both(tmp_path, lang):
    fix = _mini_run(tmp_path)
    return viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"], lang=lang)


def test_charts_tab_shell_ids_and_default_hidden(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert 'id="tabReview"' in html
    assert 'id="tabMetrics"' in html
    assert 'id="tabCharts"' in html
    assert (html.find('id="tabReview"')
            < html.find('id="tabMetrics"')
            < html.find('id="tabCharts"'))
    assert 'id="reviewPane"' in html
    assert 'id="reviewPane" hidden' not in html
    assert '<section id="metricsPane" hidden' in html
    assert '<section id="chartsPane" hidden' in html
    assert ">Review<" in html and ">Metrics<" in html and ">Charts<" in html
    assert "function switchView(" in html
    start = html.find("function switchView(")
    assert "localStorage" not in html[start:start + 1200]
    assert html.count('aria-selected="true"') == 1


def test_charts_kpi_values_bound_to_mini_stats(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    charts = _charts_section(html)
    for card in ("kpiKept", "kpiFanout", "kpiMismatch", "kpiSynthetic"):
        assert ('id="%s"' % card) in charts
    assert "Lemma kept rate" in charts
    assert "Mean precards" in charts
    assert "Evidenced mismatch" in charts
    assert "Synthetic needed" in charts
    assert ">70%<" in charts
    assert ">1.43<" in charts
    assert "409" not in charts
    assert "337" not in charts
    assert re.search(r"(?<![0-9.])67(?![0-9.])", charts) is None


def test_charts_widths_math_exact_mini(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    charts = _charts_section(html)
    assert 'stroke-dasharray="70.0 100"' in charts
    for reason in ("anchor-drop", "pick-proper-noun", "sense-judge-drop"):
        match = re.search(reason + r".*?width:([0-9.]+)%", charts, re.S)
        assert match and match.group(1) == "100.0", reason
    match = re.search(r"2 precards.*?width:([0-9.]+)%", charts, re.S)
    assert match and match.group(1) == "75.0"
    match = re.search(r"Food &amp; Drink.*?width:([0-9.]+)%", charts, re.S)
    assert match and match.group(1) == "100.0"


def test_charts_use_theme_vars_only(tmp_path):
    """Charts v2: oklch accent tokens (allowlisted) + theme vars only;
    no hex/rgb anywhere in charts CSS or inline styles."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    charts = _charts_section(html)
    assert "oklch" not in charts and "rgb(" not in charts
    assert re.search(r"#[0-9a-fA-F]{3,8}", charts) is None
    for style in re.findall(r'style="([^"]+)"', charts):
        for decl in style.split(";"):
            decl = decl.strip()
            if not decl:
                continue
            assert re.fullmatch(r"(width|height):[0-9.]+%", decl), decl
    start = html.find("/* Charts tab")
    end = html.find(".viewer-banner {")
    assert start > 0 and end > start
    css = html[start:end]
    assert "rgb(" not in css
    assert re.search(r"#[0-9a-fA-F]{3,8}", css) is None
    tokens = {
        "oklch(.699.137106.2)",
        "oklch(.699.137166.2)",
        "oklch(.699.137286.2)",
        "oklch(.699.137346.2)",
        "oklch(.130.020286.2)",
        "oklch(.290.035286.2)",
        "oklch(.55.137106.2)",
        "oklch(.55.137166.2)",
        "oklch(.55.137286.2)",
        "oklch(.55.12346.2)",
        "oklch(.96.008286)",
        "oklch(.85.02286)",
    }
    found = re.findall(r"oklch\([^)]*\)", css)
    assert found, "charts v2 must define oklch accent tokens"
    norm = {re.sub(r"\s+", "", t) for t in found}
    assert norm <= tokens, norm - tokens
    assert "var(--accent)" in css
    assert "var(--charts-gold)" in css


def test_charts_catalog_additions_only(tmp_path):
    assert set(viewer.STRINGS["fa"]) == set(viewer.STRINGS["en"])
    for key in ("tab.review", "tab.metrics", "tab.charts", "kpi.kept",
                "kpi.fanout", "kpi.mismatch", "kpi.synthetic"):
        assert key in viewer.STRINGS["en"]
        assert key in viewer.STRINGS["fa"]
    assert viewer.STRINGS["en"]["tab.metrics"] == "Metrics"
    assert viewer.STRINGS["fa"]["tab.review"] == "بررسی"
    assert viewer.STRINGS["fa"]["tab.metrics"] == "سنجه‌ها"
    assert viewer.STRINGS["fa"]["tab.charts"] == "نمودارها"
    assert viewer.STRINGS["fa"]["kpi.kept"] == "نرخ ماندگاری لماها"
    assert viewer.STRINGS["fa"]["kpi.fanout"] == "میانگین پیش‌کارت"
    assert viewer.STRINGS["fa"]["kpi.mismatch"] == "مغایرت مدرک‌دار"
    assert viewer.STRINGS["fa"]["kpi.synthetic"] == "نیاز به مثال ساختگی"


def test_fa_charts_chrome_uses_approved_strings(tmp_path):
    fa_html = _build_both(tmp_path, "fa")
    charts = _charts_section(fa_html)
    for text in ("بررسی", "نمودارها", "نرخ ماندگاری لماها",
                 "میانگین پیش‌کارت", "مغایرت مدرک‌دار",
                 "نیاز به مثال ساختگی", "سطح لِما · سطح ردیفی"):
        assert text in fa_html, text
    assert "گروه سنجه" not in charts
    assert ">۷۰٪<" in charts
    assert ">۱.۴۳<" in charts
    for literal in (">Review<", ">Charts<", "Lemma kept rate",
                    "Mean precards", "Evidenced mismatch",
                    "Synthetic needed"):
        assert literal not in fa_html, literal
    assert "metric group" not in charts
    # CEFR codes (A1...) and width math stay Latin verbatim
    # (never rewritten).
    assert re.search(r"[0-9]", charts)


@pytest.mark.parametrize("lang,units", [
    ("en", ("kept lemmas / all lemmas", "row-level",
             "lemma-level (exists)", "dropped lemmas")),
    ("fa", ("لِماهای نگه‌داشته‌شده / همه لِماها", "سطح ردیفی",
             "وجودی", "لِماهای حذف‌شده")),
])
def test_charts_label_units_both_langs(tmp_path, lang, units):
    html = _build_both(tmp_path, lang)
    charts = _charts_section(html)
    for unit in units:
        assert unit in charts, unit


def test_unmapped_sense_renders_cefr_none_placeholder(tmp_path):
    """OC round 2 W2: unmapped rows render a cefr-none/— chip, never
    an empty `cefr-` class span."""
    run_dir = tmp_path / "run-unmapped-chip"
    run_dir.mkdir()
    sample_path = run_dir / "sample.json"
    sample_path.write_text(json.dumps([{"key": "w:bare"}]),
                           encoding="utf-8")
    precard_path = run_dir / "precard.jsonl"
    precard_path.write_text(
        json.dumps(_row("w:bare", "bare", "bare#1", sense_cefr="",
                        sense_cefr_method="unmapped")) + "\n",
        encoding="utf-8")
    for name in ("dropped.log", "run.log"):
        (run_dir / name).write_text("", encoding="utf-8")
    html = viewer.build_html(
        run_dir, precard=precard_path, sample=sample_path,
        dropped=run_dir / "dropped.log", run_log=run_dir / "run.log")
    assert "cefr-none" in html
    assert 'class="cefr-tag cefr-"' not in html
    assert "unmapped sense CEFR" in html


def test_evidenced_note_matches_allowlist(tmp_path):
    """Reviewer round: the rendered evidenced note must state the
    allowlist (wn-single / wn-evp-gloss only), never the stale
    deny-list wording that claimed unmapped counts."""
    run_dir = tmp_path / "run-note"
    run_dir.mkdir()
    sample_path = run_dir / "sample.json"
    sample_path.write_text(json.dumps([{"key": "w:bare"}]),
                           encoding="utf-8")
    precard_path = run_dir / "precard.jsonl"
    precard_path.write_text(
        json.dumps(_row("w:bare", "bare", "bare#1", sense_cefr="",
                        sense_cefr_method="unmapped")) + "\n",
        encoding="utf-8")
    for name in ("dropped.log", "run.log"):
        (run_dir / name).write_text("", encoding="utf-8")
    html = viewer.build_html(
        run_dir, precard=precard_path, sample=sample_path,
        dropped=run_dir / "dropped.log", run_log=run_dir / "run.log")
    assert "wn-single / wn-evp-gloss only" in html
    assert "other than pool-fallback" not in html


def test_fa_evidenced_note_matches_allowlist(tmp_path):
    """OC round: the FA drawer note must state the same allowlist —
    unmapped excluded, pool levels shown separately."""
    run_dir = tmp_path / "run-note-fa"
    run_dir.mkdir()
    sample_path = run_dir / "sample.json"
    sample_path.write_text(json.dumps([{"key": "w:bare"}]),
                           encoding="utf-8")
    precard_path = run_dir / "precard.jsonl"
    precard_path.write_text(
        json.dumps(_row("w:bare", "bare", "bare#1", sense_cefr="",
                        sense_cefr_method="unmapped")) + "\n",
        encoding="utf-8")
    for name in ("dropped.log", "run.log"):
        (run_dir / name).write_text("", encoding="utf-8")
    html = viewer.build_html(
        run_dir, precard=precard_path, sample=sample_path,
        dropped=run_dir / "dropped.log", run_log=run_dir / "run.log",
        lang="fa")
    assert "wn-single / wn-evp-gloss فقط" in html
    assert "از پول کپی" not in html


def _pane_segment(html, start_id, stop_id):
    start = html.find('id="%s"' % start_id)
    assert start >= 0, start_id
    stop = html.find('id="%s"' % stop_id, start + 1)
    assert stop > start, stop_id
    return html[start:stop]


def test_metrics_tab_hosts_drawer_review_keeps_filters(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert html.count('id="distDrawer"') == 1
    assert html.count('<div class="dist-grid">') == 1
    review = _pane_segment(html, "reviewPane", "metricsPane")
    assert 'class="filter-bar"' in review
    assert 'class="split-workspace"' in review
    assert 'id="distDrawer"' not in review
    metrics = _pane_segment(html, "metricsPane", "chartsPane")
    assert 'id="distDrawer"' in metrics
    assert metrics.count('class="dist-group"') == 9
    assert 'class="filter-bar"' not in metrics
    assert 'class="split-workspace"' not in metrics


def test_fa_tabs_three_labels_and_metrics_drawer(tmp_path):
    fa_html = _build_both(tmp_path, "fa")
    assert (fa_html.find("بررسی")
            < fa_html.find("سنجه‌ها")
            < fa_html.find("نمودارها"))
    assert ">Metrics<" not in fa_html
    review = _pane_segment(fa_html, "reviewPane", "metricsPane")
    assert 'id="distDrawer"' not in review
    metrics = _pane_segment(fa_html, "metricsPane", "chartsPane")
    assert 'id="distDrawer"' in metrics
    assert metrics.count('class="dist-group"') == 9


def test_switch_view_handles_three_panes_stateless(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    start = html.find("function switchView(")
    end = html.find("</script>", start)
    body = html[start:end]
    assert "localStorage" not in body
    for pane in ("reviewPane", "metricsPane", "chartsPane"):
        assert body.count('getElementById("%s")' % pane) == 1
    for tab in ("tabReview", "tabMetrics", "tabCharts"):
        assert body.count('getElementById("%s")' % tab) == 2


def test_charts_deprosed_legends_not_prose_en(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    charts = _charts_section(html)
    for prose in ("evidenced-only",
                  "lemma counts overlap", "stage_calls.s4_path",
                  "example_fallback", "sense_cefr_method",
                  "shown separately", "never overlap",
                  "(same two columns as g3)"):
        assert prose not in charts, prose
    for legend in ("kept lemmas / all lemmas",
                   "precards, row-level", "precards bucket",
                   "dropped lemmas", "lemma-level (exists)"):
        assert legend in charts, legend
    # Reference round (R3/R4): KPI metas carry real counts; the median/P90
    # words now live in the fanout meta + health footer, not the drawer.
    assert "7 kept \u00b7 3 dropped" in charts
    assert re.search(r"median \d+ \u00b7 P90 \d+", charts)
    assert re.search(r"\d+ of \d+ evidenced", charts)
    assert re.search(r"\d+ without real example", charts)
    assert "production health:" in charts
    for prose in ("lemma counts overlap", "evidenced-only",
                  "stage_calls.s4_path"):
        assert prose in html


def test_charts_deprosed_legends_not_prose_fa(tmp_path):
    fa_html = _build_both(tmp_path, "fa")
    charts = _charts_section(fa_html)
    for prose in ("هم‌پوشانی",
                  "فقط مدرک‌دارها", "۲+ بازه"):
        assert prose not in charts, prose
    for legend in ("لِماهای نگه‌داشته‌شده / همه لِماها",
                   "پیش‌کارتها، سطح ردیفی", "بازه پیش‌کارت"):
        assert legend in charts, legend
    # Reference round (R3/R4): metas carry real counts (FA digits).
    assert "۷ نگه\u200cداشته \u00b7 \u06f3 حذف" in charts
    assert re.search(r"میانه \d+ \u00b7 صدک \u06f9\u06f0: \d+", charts)
    assert re.search(r"\d+ از \d+ مدرک\u200cدار", charts)
    assert re.search(r"\d+ بدون مثال واقعی", charts)
    assert "سلامت تولید:" in charts
    assert "هم‌پوشانی" in fa_html


@pytest.mark.parametrize("lang,legends", [
    ("en", ("kept lemmas / all lemmas",
             "precards, row-level", "precards bucket")),
    ("fa", ("لِماهای نگه‌داشته‌شده / همه لِماها",
             "پیش‌کارتها، سطح ردیفی", "بازه پیش‌کارت")),
])
def test_charts_legends_reuse_catalog_only(tmp_path, lang, legends):
    catalog = json.dumps(viewer.STRINGS[lang], ensure_ascii=False)
    for legend in legends:
        assert legend in catalog, legend


def test_charts_kpi_strip_rails_and_scale(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    charts = _charts_section(html)
    for rail in ("rail-gold", "rail-mint", "rail-purple", "rail-rose"):
        assert rail in charts, rail
    start = html.find("/* Charts tab")
    css = html[start:html.find(".viewer-banner {", start)]
    assert "minmax(180px, 1fr)" in css
    assert "font-size: 24px" in css and "font-weight: 900" in css
    assert "width: 4px" in css


def test_charts_retention_donut_and_rows(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    charts = _charts_section(html)
    assert "kept of all lemmas" in charts
    assert "kept lemmas" in charts
    assert "dropped lemmas" in charts
    assert "<b>7</b>" in charts
    assert "<b>3</b>" in charts
    start = html.find("/* Charts tab")
    css = html[start:html.find(".viewer-banner {", start)]
    assert "width: 120px" in css and "height: 120px" in css
    assert "var(--charts-gold)" in css


def test_charts_pareto_grid_ltr_title(tmp_path):
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    charts = _charts_section(html)
    assert "charts-pareto" in charts
    start = html.find("/* Charts tab")
    css = html[start:html.find(".viewer-banner {", start)]
    assert "140px 1fr auto" in css
    assert "direction: ltr" in css
    assert "border-radius: 99px" in css
    assert "var(--charts-rose)" in css


def test_fa_charts_kpi_persian_digits(tmp_path):
    fa_html = _build_both(tmp_path, "fa")
    charts = _charts_section(fa_html)
    assert ">۷۰٪<" in charts
    assert ">۱.۴۳<" in charts
    assert ">70%<" not in charts
    assert "Vazirmatn" in fa_html
    assert "fonts.googleapis.com" in fa_html


def _v2_stats():
    return {
        "lemmas_total": 10, "lemmas_kept": 7, "lemmas_dropped": 3,
        "precards_total": 12, "kept_rate_pct": 70,
        "drops_by_reason": [["anchor-drop", 2], ["sense-judge-drop", 1]],
        "ppc": {"mean": 1.71, "median": 2, "p90": 3,
                "hist": {"1": 3, "2": 3, "3": 1, "4+": 0}},
        "cefr_lemma": {"A1": 4, "B1": 3, "C1": 2},
        "cefr_precard": {"A1": 6, "B1": 4, "C1": 2},
        "topic_lemma": {"Food & Drink": 5, "Travel": 2},
        "topic_precard": {"Food & Drink": 9, "Travel": 3},
        "untagged_precards": 0,
        "synthetic": {"precards": 2, "precards_pct": 16.7,
                      "lemmas": 2, "lemmas_pct": 28.6},
        "mismatch": {"precards": 3, "precards_pct": 25.0, "lemmas": 2,
                     "evidenced_precards": 1, "evidenced_denominator": 4,
                     "evidenced_pct": 25.0},
        "cefr_method": {"pool-fallback": 8, "wn-single": 4},
        "topic_path": {"llm": 5, "fallback": 4, "leg1": 3},
        "example_source": {"sense": 6, "lemma": 4, "pool": 2},
    }


def test_charts_cefr_badges_and_pairs(tmp_path):
    en = viewer._render_charts(_v2_stats(), "en")
    for band in ("charts-cefr-badge a", "charts-cefr-badge b",
                 "charts-cefr-badge c"):
        assert band in en, band
    assert "4 / 6" in en
    assert "charts-fill lemma" in en
    assert "charts-fill precard" in en
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    start = html.find("/* Charts tab")
    css = html[start:html.find(".viewer-banner {", start)]
    assert "var(--charts-mint)" in css
    assert "var(--charts-purple)" in css
    assert "flex: none" in css
    fa = viewer._render_charts(_v2_stats(), "fa")
    assert "۴ / ۶" in fa
    assert "A1" in fa


def test_charts_s4_rail_segments_and_legend():
    en = viewer._render_charts(_v2_stats(), "en")
    assert "charts-rail" in en
    assert "charts-rail-grid" in en
    assert "share of precards" in en
    assert 'style="width:41.7%"' in en
    fa = viewer._render_charts(_v2_stats(), "fa")
    assert "سهم از پیش‌کارت‌ها" in fa
    assert "۵" in fa


def test_charts_topics_cards_and_untagged_badge():
    en = viewer._render_charts(_v2_stats(), "en")
    assert "charts-topics" in en
    assert "charts-fill topic" in en
    assert "0 untagged" in en
    fa = viewer._render_charts(_v2_stats(), "fa")
    assert "۰ بدون برچسب" in fa


def test_charts_pillars_grid_and_units():
    en = viewer._render_charts(_v2_stats(), "en")
    assert "charts-pillars" in en
    assert "charts-pillar-stage" in en
    assert "precard(s)" in en
    fa = viewer._render_charts(_v2_stats(), "fa")
    assert "پیش‌کارت" in fa


def _advanced_filters_block(html):
    start = html.find('id="advancedFilters"')
    assert start > 0
    open_tag = html.rfind("<details", 0, start)
    return html[open_tag:html.find("</details>", start)]


def test_advanced_filters_collapsible_structure(tmp_path):
    """T-C (viewer-batch): CEFR pills + all selects fold into a
    <details> with a labeled summary + count span; search stays on top
    outside; every control id is preserved."""
    fix = _mini_run(tmp_path)
    kwargs = {"precard": fix["precard"], "sample": fix["sample"],
              "dropped": fix["dropped"], "run_log": fix["run_log"]}
    for lang in ("en", "fa"):
        html = viewer.build_html(fix["run_dir"], lang=lang, **kwargs)
        assert ('<details class="advanced-filters" '
                'id="advancedFilters" open>') in html
        assert "<summary>" in html
        assert 'id="activeFilterCount"' in html
        ids = ("cefrPills", "topicFilter", "statusFilter",
               "registerFilter", "methodFilter", "sourceFilter",
               "sortOrder")
        for sel in ids:
            assert ('id="%s"' % sel) in html
        assert (html.find('id="searchInput"')
                < html.find('id="advancedFilters"'))
        block = _advanced_filters_block(html)
        for sel in ids:
            assert ('id="%s"' % sel) in block
        assert 'id="searchInput"' not in block
        assert 'id="sortOrder"' in block
    en_html = viewer.build_html(fix["run_dir"], lang="en", **kwargs)
    assert "<span>Advanced filters</span>" in en_html
    fa_html = viewer.build_html(fix["run_dir"], lang="fa", **kwargs)
    assert "<span>فیلترهای پیشرفته</span>" in fa_html
    assert ".advanced-filters" in en_html
    flat = re.search(r"\.advanced-filters \{(.*?)\}", en_html, re.S).group(1)
    assert "display: contents" in flat
    summary_css = re.search(
        r"\.advanced-filters > summary \{(.*?)\}",
        en_html, re.S).group(1)
    assert "display: none" in summary_css
    media = en_html[en_html.find("@media (max-width:640px)"):]
    assert ".advanced-filters" in media
    phone_block = re.search(
        r"\.advanced-filters \{(.*?)\}", media, re.S).group(1)
    assert "min-width: 0" in phone_block
    phone_summary = re.search(
        r"\.advanced-filters > summary \{(.*?)\}", media, re.S).group(1)
    assert "min-height: 40px" in phone_summary
    assert 'matchMedia("(max-width: 640px)")' in en_html
    assert 'getElementById("advancedFilters")' in en_html
    assert 'removeAttribute("open")' in en_html
    assert 'addEventListener("change", syncAdvFilters)' in en_html
    assert "syncAdvFilters();" in en_html


def test_advanced_filters_counter_hook(tmp_path):
    """T-C (viewer-batch): applyFilters recomputes the active-filter
    count (non-ALL among CEFR pills + 5 filter selects) into the count
    span; FA renders it through the strings catalog, never English."""
    fix = _mini_run(tmp_path)
    kwargs = {"precard": fix["precard"], "sample": fix["sample"],
              "dropped": fix["dropped"], "run_log": fix["run_log"]}
    en_html = viewer.build_html(fix["run_dir"], lang="en", **kwargs)
    assert 'currentCefrFilter !== "ALL" ? 1 : 0' in en_html
    assert "`${nActive} active filters`" in en_html
    assert 'getElementById("activeFilterCount")' in en_html
    fa_html = viewer.build_html(fix["run_dir"], lang="fa", **kwargs)
    assert 'tr("filters.active", {N: nActive})' in fa_html
    assert "active filters" not in fa_html


def test_advanced_filters_strings_bilingual():
    """T-C (viewer-batch): the 4 new catalog keys (2 per lang) with
    matching placeholders."""
    assert (viewer.STRINGS["en"]["filters.advanced"]
            == "Advanced filters")
    assert (viewer.STRINGS["fa"]["filters.advanced"]
            == "فیلترهای پیشرفته")
    assert (viewer.STRINGS["en"]["filters.active"]
            == "{N} active filters")
    assert (viewer.STRINGS["fa"]["filters.active"]
            == "{N} فیلتر فعال")


def test_charts_pane_scrolls_without_trapping(tmp_path):
    """T-A (viewer-batch): the detail (charts) pane keeps its internal
    scroll (overflow-y:auto) and can shrink inside the workspace grid
    (min-height:0), mirroring the drawer-grid precedent."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    pane = re.search(r"\n\.detail-pane \{(.*?)\}", html, re.S).group(1)
    assert "overflow-y: auto" in pane
    assert "min-height: 0" in pane


def test_charts_tab_pane_scrolls_without_trapping(tmp_path):
    """Owner eyeball round: the charts tab pane itself must scroll —
    its content exceeds small viewports with no other scroller."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    charts = re.search(r"\n#chartsPane \{(.*?)\}", html, re.S).group(1)
    assert "overflow-y: auto" in charts
    assert "min-height: 0" in charts


def test_drawer_grid_scrolls_with_workspace_floor(tmp_path):
    """T1 (plan-precard-viewer-responsive R1): drawer grid caps at 38vh
    with internal scroll; workspace never collapses below 200px."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    grid_match = re.search(r"\.dist-grid \{(.*?)\}", html, re.S)
    assert grid_match is not None
    grid = grid_match.group(1)
    assert "max-height: 38vh" in grid
    assert "overflow-y: auto" in grid
    assert "min-height: 0" in grid
    workspace = re.search(r"\.split-workspace \{(.*?)\}", html, re.S).group(1)
    assert "min-height: 200px" in workspace


def test_filter_pills_scroll_horizontally(tmp_path):
    """T-E (viewer-batch): the CEFR pill row scrolls on the x axis
    (with touch momentum) instead of trapping overflow."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    pills = re.search(r"\n\.filter-pills \{(.*?)\}", html, re.S).group(1)
    assert "overflow-x: auto" in pills
    assert "-webkit-overflow-scrolling: touch" in pills
    assert "min-width: 0" in pills


def test_light_surfaces_deepened_dark_identical(tmp_path):
    """T-D (viewer-batch): light secondary surfaces/borders deepen a
    notch for element separation; the dark theme is byte-identical."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    root = html[html.find(":root {"):html.find('[data-theme="dark"]')]
    assert "--bg-surface-hover: #eef0f3;" in root
    assert "--bg-surface-active: #e0e3e8;" in root
    assert "--border-subtle: #d4d7dd;" in root
    assert "--border-strong: #b4b9c1;" in root
    for old in ("#f8f9fa", "#eaebee", "#e2e4e9", "#c8cbd2"):
        assert old not in root
    dark = html[html.find('[data-theme="dark"] {'):
                html.find("/* Themed scrollbars")]
    for line in ("--bg-page: #121316;",
                 "--bg-surface: #191a1f;",
                 "--bg-surface-hover: #22232a;",
                 "--bg-surface-active: #2b2d35;",
                 "--border-subtle: #292b34;",
                 "--border-strong: #3a3d4a;",
                 "--text-primary: #f3f4f6;",
                 "--accent: #38bdf8;"):
        assert line in dark


def test_phone_kpi_density_two_columns(tmp_path):
    """T-B (viewer-batch): phone-only KPI strip compacts to a 2-column
    grid with smaller values and tighter padding."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert "@media (max-width:640px)" in html
    media = html[html.find("@media (max-width:640px)"):]
    strip = re.search(r"#chartsPane \.kpi-strip \{(.*?)\}", media, re.S).group(1)
    assert "grid-template-columns: 1fr 1fr" in strip
    value = re.search(r"#chartsPane \.kpi-value \{(.*?)\}", media, re.S).group(1)
    size = re.search(r"font-size:\s*(\d+)px", value)
    assert size is not None and 18 <= int(size.group(1)) <= 20


def test_phone_stacking_media_query(tmp_path):
    """T2 (plan-precard-viewer-responsive R2): phone-only (<=640px)
    single-column stacking; kbd hints hidden."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    assert "@media (max-width:640px)" in html
    media = html[html.find("@media (max-width:640px)"):]
    assert "grid-template-columns: 1fr" in media
    assert re.search(
        r"\.shortcut-hint,\s*\.kbd-key\s*\{[^}]*display:\s*none",
        media)
    ws_media = re.search(
        r"\.split-workspace\s*\{([^}]*)\}", media)
    assert ws_media is not None
    assert "overflow-y: auto" in ws_media.group(1)


def _ref_stats():
    """Reference-fidelity round: v2 shape with 6 drop reasons so the
    pareto rollup has something to roll up."""
    stats = _v2_stats()
    stats["drops_by_reason"] = [["r%d" % i, count] for i, count in
                                enumerate((30, 21, 18, 9, 9, 8))]
    return stats


def test_ref_donut_two_segments():
    """R2: kept + dropped arcs (reference ring), shares sum to 100."""
    en = viewer._render_charts(_ref_stats(), "en")
    assert en.count("charts-donut-fg") == 2
    assert 'stroke-dasharray="70.0 100"' in en
    assert 'stroke-dasharray="30.0 100"' in en


def test_ref_kpi_meta_real_counts():
    """R3: KPI third line carries real STATS counts, both langs."""
    en = viewer._render_charts(_ref_stats(), "en")
    assert "7 kept \u00b7 3 dropped" in en
    assert "median 2 \u00b7 P90 3" in en
    assert "1 of 4 evidenced" in en
    assert "2 without real example" in en
    fa = viewer._render_charts(_ref_stats(), "fa")
    assert "\u06f7 نگه\u200cداشته \u00b7 \u06f3 حذف" in fa
    assert "میانه \u06f2 \u00b7 صدک \u06f9\u06f0: \u06f3" in fa


def test_ref_pareto_other_rollup():
    """R5: top-4 reasons stay; the rest roll into one others row."""
    en = viewer._render_charts(_ref_stats(), "en")
    assert "charts-row-others" in en
    assert "others (2 methods)" in en
    assert ">17<" in en
    assert "r5" not in en
    fa = viewer._render_charts(_ref_stats(), "fa")
    assert "سایر (۲ متد)" in fa


def test_ref_fanout_fullwidth_and_bench():
    """R4: fan-out spans the grid; health footer shows mean/med/P90."""
    en = viewer._render_charts(_ref_stats(), "en")
    assert "charts-panel-full" in en
    assert "production health:" in en
    assert "mean 1.71 \u00b7 median 2 \u00b7 P90 3" in en
    fa = viewer._render_charts(_ref_stats(), "fa")
    assert "سلامت تولید:" in fa
    assert "میانگین" in fa


def test_ref_no_colhead_class():
    """Owner eyeball: no redundant caption rows left in charts."""
    for lang in ("en", "fa"):
        assert "charts-colhead" not in viewer._render_charts(
            _ref_stats(), lang)


def test_ref_cefr_guide_words(tmp_path):
    """Guide row keeps the required unit words (no test breakage)."""
    assert "lemma-level (exists)" in viewer._render_charts(
        _ref_stats(), "en")
    assert "وجودی" in viewer._render_charts(_ref_stats(), "fa")


def test_ref_panel_css(tmp_path):
    """Reference panel anatomy: shadow, head divider, full-width span,
    centered donut overlay."""
    fix = _mini_run(tmp_path)
    html = viewer.build_html(fix["run_dir"], precard=fix["precard"],
                             sample=fix["sample"], dropped=fix["dropped"],
                             run_log=fix["run_log"])
    start = html.find("/* Charts tab")
    css = html[start:html.find(".viewer-banner {", start)]
    panel = re.search(r"\.charts-panel \{(.*?)\}", css, re.S).group(1)
    assert "box-shadow:" in panel
    assert "border-radius: 16px" in panel
    head = re.search(r"\.charts-panel-head \{(.*?)\}", css, re.S).group(1)
    assert "border-bottom:" in head
    full = re.search(r"\.charts-panel-full \{(.*?)\}", css, re.S).group(1)
    assert "grid-column: 1 / -1" in full
    assert ".charts-donut-center" in css


def test_ref_catalog_keys_both_langs():
    """New reference strings exist in EN + FA (eyeball-flagged)."""
    for key in ("charts.kpi_kept_meta", "charts.kpi_fanout_meta",
                "charts.kpi_mismatch_meta", "charts.kpi_synth_meta",
                "charts.others", "charts.bench", "charts.bench_vals",
                "charts.pareto_head", "charts.cefr_guide_lemma",
                "charts.cefr_guide_precard", "charts.cefr_pair",
                "charts.s4_head", "charts.prov_head", "charts.prov_total"):
        assert key in viewer.STRINGS["en"], key
        assert key in viewer.STRINGS["fa"], key


def test_ref_others_width_clamped():
    """OC round: a rest-sum larger than the top reason still caps at
    100% — no pareto track overflow."""
    stats = _v2_stats()
    stats["drops_by_reason"] = [["r%d" % i, count] for i, count in
                                enumerate((10, 9, 9, 9, 9, 9))]
    en = viewer._render_charts(stats, "en")
    assert "others (2 methods)" in en
    assert ">18<" in en
    widths = [float(w) for w in
              re.findall(r"charts-fill drop\" style=\"width:([0-9.]+)%", en)]
    assert widths and all(w <= 100.0 for w in widths)


def test_ref_empty_donut_no_full_drop():
    """OC round: an empty dataset renders an empty ring, never a
    solid full-drop circle."""
    stats = _v2_stats()
    stats.update({"lemmas_total": 0, "lemmas_kept": 0,
                  "lemmas_dropped": 0, "kept_rate_pct": 0})
    en = viewer._render_charts(stats, "en")
    assert re.search(r'stroke-dasharray="100', en) is None
