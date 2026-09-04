"""Hermetic tests for TICKET F3 (no network, synthetic data only).

Covers the AWL HTML parser (factory/fetch_awl.py) and the coverage math
(factory/awl_coverage.py) on inline fixtures. Real W: data is never touched.
"""

import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from awl_coverage import (AUDIT_FREQUENT_ZIPF, decide_verdict,
                           family_coverage, is_vowelless_word, load_awl,
                           pool_awl_fraction, vowelless_audit)
from sample_lemmas import pack_has_cefr_hit
from fetch_awl import clean_headword, parse_sublist_html

PAGE = ("<h2>The Academic Word List</h2>"
        "<p>analyse</p><ul><li>analysed</li><li>analysis</li></ul>"
        "<p>data</p>"
        "<p>approach</p><ul><li>approached</li><li>approaches</li></ul>")


def test_parse_sublist_html_families():
    parsed = parse_sublist_html(PAGE)
    assert parsed == {"analyse": ["analyse", "analysed", "analysis"],
                      "data": ["data"],
                      "approach": ["approach", "approached", "approaches"]}


def test_clean_headword_markers():
    assert clean_headword(" Analyse* ") == "analyse"
    assert clean_headword("run (-s)") == "run"
    assert clean_headword("  ") is None


def _pack():
    return {"cefrj_fallback": {"rhythm|noun": "B2"},
            "evp_index": {"crypt|noun": ["C1"]},
            "evp_lemma_index": {"rhythm": ["B2"], "crypt": ["C1"]}}


def test_pack_has_cefr_hit_single_source():
    # G2: awl_coverage reuses sample_lemmas.pack_has_cefr_hit (no duplicate).
    # Unified semantics: missing structures are silent False; only valid
    # CEFR levels count (an evp entry with a junk level is not a hit).
    import awl_coverage

    assert not hasattr(awl_coverage, "pack_hit")
    assert awl_coverage.pack_has_cefr_hit is pack_has_cefr_hit
    pack = _pack()
    assert pack_has_cefr_hit("rhythm", "noun", pack) is True
    assert pack_has_cefr_hit("crypt", "noun", pack) is True
    assert pack_has_cefr_hit("crypt", None, pack) is True
    assert pack_has_cefr_hit("xyzzy", "noun", pack) is False
    assert pack_has_cefr_hit("", "noun", pack) is False
    assert pack_has_cefr_hit("rhythm", "noun", {}) is False
    junk = {"cefrj_fallback": {},
            "evp_index": {"xyzzy|noun": ["Z9"]},
            "evp_lemma_index": {}}
    assert pack_has_cefr_hit("xyzzy", "noun", junk) is False


def test_is_vowelless_word():
    assert is_vowelless_word("rhythm") is True
    assert is_vowelless_word("crypts") is True
    assert is_vowelless_word("analysis") is False
    assert is_vowelless_word("all in all") is False
    assert is_vowelless_word("co-op") is False
    assert is_vowelless_word("x") is False
    assert is_vowelless_word(None) is False


def test_family_coverage_and_pool_fraction():
    families = {"analyse": ["analyse", "analysed", "analysis"],
                "data": ["data"],
                "approach": ["approach", "approached"]}
    pool_easiest = {"analysis": "B2", "data": "A1"}
    summary, per_cefr = family_coverage(families, pool_easiest)
    assert summary == {"families": 3, "hit": 2, "miss": 1,
                       "pct": 200.0 / 3}
    assert per_cefr["A1"] == 1 and per_cefr["B2"] == 1
    rows = [("Analysis", "noun", "B2"), ("data", "noun", "A1"),
            ("other", "noun", "A1")]
    pool = pool_awl_fraction(rows, {"analyse", "analysis", "data"})
    assert pool == {"rows": 3, "awl_rows": 2, "pct": 200.0 / 3}


def test_family_coverage_empty():
    summary, per_cefr = family_coverage({}, {})
    assert summary["pct"] == 0.0 and summary["hit"] == 0
    assert sum(per_cefr.values()) == 0


def test_vowelless_audit_dedupes_pack_by_lemma(tmp_path):
    # G3: one lemma with N POS rows counts once in pack_real/pack_samples
    # (lemma counting, mirroring seen_kept) — never N rows.
    index = str(tmp_path / "index.jsonl")
    rows = [("rhythm", "noun"), ("rhythm", "verb"), ("rhythm", "noun"),
            ("crypt", "noun"), ("analysis", "noun")]
    with open(index, "w", encoding="utf-8") as handle:
        for word, pos in rows:
            handle.write(json.dumps({"word": word, "pos": pos}) + "\n")
    pack = {"cefrj_fallback": {"rhythm|noun": "B2", "rhythm|verb": "B1",
                               "crypt|noun": "C1"},
            "evp_index": {}, "evp_lemma_index": {},
            "zipf_cutoffs": [5.2, 4.6, 4.0, 3.5, 3.0]}
    audit = vowelless_audit(index, pack, "en")
    assert audit["vowelless_rows"] == 4  # rows: rhythm x3 + crypt
    assert audit["pack_real"] == 2  # lemmas: rhythm + crypt, not 4 rows
    assert sorted(audit["pack_samples"]) == ["crypt", "rhythm"]
    assert audit["kept_unique"] == 2
    assert set(audit["kept_levels"]) == set(
        ["A1", "A2", "B1", "B2", "C1", "C2"])


def test_audit_frequent_floor_name_and_value():
    # G5: audit floor renamed for clarity; value/behavior unchanged (>= 4.0,
    # stricter than the sampler keep-rule floor 3.0 in sample_lemmas).
    import awl_coverage
    from sample_lemmas import FREQUENT_ZIPF_MIN

    assert AUDIT_FREQUENT_ZIPF == 4.0
    assert not hasattr(awl_coverage, "FREQUENT_ZIPF")
    assert FREQUENT_ZIPF_MIN == 3.0


def test_decide_verdict_thresholds():
    assert decide_verdict(80.0, 0, 0).startswith("PROCEED")
    assert "allowlist follow-up" in decide_verdict(80.0, 3, 5)
    assert "ADJUST" in decide_verdict(80.0, 150, 5)
    assert "ADJUST" in decide_verdict(80.0, 7, 90)


def test_decide_verdict_unknown_when_wordfreq_missing():
    # frequent_n==0 with the library absent means UNKNOWN, never measured
    # zero — the verdict must not claim "no recall cost".
    verdict = decide_verdict(80.0, 0, 0, False)
    assert verdict.startswith("UNKNOWN")
    assert "no vowel-gate recall cost" not in verdict


def test_load_awl_rejects_non_list_members(tmp_path):
    bad = tmp_path / "awl.json"
    bad.write_text(json.dumps({"families": {"analyse": 123}}),
                   encoding="utf-8")
    with pytest.raises(SystemExit):
        load_awl(str(bad))
    bad.write_text(json.dumps({"families": {"analyse": "analysed"}}),
                   encoding="utf-8")
    with pytest.raises(SystemExit):
        load_awl(str(bad))
    assert "exam lists" in decide_verdict(30.0, 0, 0)


def test_loaders_roundtrip(tmp_path):
    from awl_coverage import load_awl, load_pool
    awl_path = str(tmp_path / "awl.json")
    with open(awl_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(
            {"metadata": {"source_url": "x"},
             "families": {"Analyse": ["Analyse", "ANALYSIS"]}}))
    families, meta = load_awl(awl_path)
    assert families == {"analyse": ["analyse", "analysis"]}
    assert meta["source_url"] == "x"
    pool_path = str(tmp_path / "pool.csv")
    with open(pool_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["lemma", "pos", "cefr"])
        writer.writerow(["Analysis", "noun", "B2"])
        writer.writerow(["", "noun", "A1"])
    rows, easiest = load_pool(pool_path)
    assert rows == [("Analysis", "noun", "B2")]
    assert easiest == {"analysis": "B2"}


def test_load_awl_fail_closed(tmp_path):
    import pytest

    from awl_coverage import load_awl
    missing_key = str(tmp_path / "no_families.json")
    with open(missing_key, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"metadata": {}}))
    with pytest.raises(SystemExit) as excinfo:
        load_awl(missing_key)
    assert "families" in str(excinfo.value)
    assert missing_key in str(excinfo.value)
    not_dict = str(tmp_path / "families_list.json")
    with open(not_dict, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"families": ["analyse"]}))
    with pytest.raises(SystemExit) as excinfo:
        load_awl(not_dict)
    assert "families" in str(excinfo.value)
    assert not_dict in str(excinfo.value)


def _write_vowelless_index(tmp_path, words):
    index = str(tmp_path / "index.jsonl")
    with open(index, "w", encoding="utf-8") as handle:
        for word, pos in words:
            handle.write(json.dumps({"word": word, "pos": pos}) + "\n")
    return index


def test_vowelless_audit_wordfreq_missing(tmp_path, monkeypatch, capsys):
    import sys as _sys

    import awl_coverage

    monkeypatch.setitem(_sys.modules, "wordfreq", None)
    index = _write_vowelless_index(tmp_path, [("rhythm", "noun")])
    pack = {"cefrj_fallback": {"rhythm|noun": "B2"},
            "evp_index": {}, "evp_lemma_index": {},
            "zipf_cutoffs": [5.2, 4.6, 4.0, 3.5, 3.0]}
    audit = awl_coverage.vowelless_audit(index, pack, "en")
    assert audit["wordfreq_available"] is False
    assert audit["kept_unique"] == 1  # pack hit keeps without wordfreq
    assert audit["frequent_n"] == 0
    assert audit["frequent"] == []


def test_vowelless_audit_wordfreq_present(tmp_path, monkeypatch):
    import sys as _sys

    import awl_coverage

    class _FakeWordfreq:
        @staticmethod
        def zipf_frequency(lemma, lang):
            return 6.0

    monkeypatch.setitem(_sys.modules, "wordfreq", _FakeWordfreq)
    index = _write_vowelless_index(tmp_path, [("rhythm", "noun")])
    pack = {"cefrj_fallback": {"rhythm|noun": "B2"},
            "evp_index": {}, "evp_lemma_index": {},
            "zipf_cutoffs": [5.2, 4.6, 4.0, 3.5, 3.0]}
    audit = awl_coverage.vowelless_audit(index, pack, "en")
    assert audit["wordfreq_available"] is True
    assert audit["frequent_n"] == 1


def test_vowelless_audit_zipf_errors_non_frequent(tmp_path, monkeypatch):
    import sys as _sys

    import awl_coverage

    class _RaisingWordfreq:
        @staticmethod
        def zipf_frequency(lemma, lang):
            raise ValueError("no frequency")

    monkeypatch.setitem(_sys.modules, "wordfreq", _RaisingWordfreq)
    index = _write_vowelless_index(tmp_path, [("rhythm", "noun")])
    pack = {"cefrj_fallback": {"rhythm|noun": "B2"},
            "evp_index": {}, "evp_lemma_index": {},
            "zipf_cutoffs": [5.2, 4.6, 4.0, 3.5, 3.0]}
    audit = awl_coverage.vowelless_audit(index, pack, "en")
    assert audit["wordfreq_available"] is True
    assert audit["kept_unique"] == 1
    assert audit["frequent_n"] == 0
    assert audit["frequent"] == []


def test_main_report_na_when_wordfreq_missing(tmp_path, monkeypatch):
    import sys as _sys

    from awl_coverage import main

    monkeypatch.setitem(_sys.modules, "wordfreq", None)
    awl_path = str(tmp_path / "awl.json")
    with open(awl_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"families": {"data": ["data"]}}))
    pool_path = str(tmp_path / "pool.csv")
    with open(pool_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["lemma", "pos", "cefr"])
        writer.writerow(["data", "noun", "A1"])
    index_path = str(tmp_path / "index.jsonl")
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"word": "rhythm", "pos": "noun"}) + "\n")
    pack_dir = str(tmp_path / "pack")
    os.makedirs(pack_dir, exist_ok=True)
    with open(os.path.join(pack_dir, "evp_sense.json"), "w",
              encoding="utf-8") as handle:
        handle.write(json.dumps({"entries": {}}))
    with open(os.path.join(pack_dir, "cefrj_pos.json"), "w",
              encoding="utf-8") as handle:
        handle.write(json.dumps({"fallback": {"rhythm|noun": "B2"}}))
    with open(os.path.join(pack_dir, "pack.json"), "w",
              encoding="utf-8") as handle:
        handle.write(json.dumps({"cefr": {"zipf_cutoffs":
                                          [5.2, 4.6, 4.0, 3.5, 3.0]}}))
    report_path = str(tmp_path / "report.md")
    assert main(["--awl", awl_path, "--pool", pool_path,
                 "--index", index_path, "--pack", pack_dir,
                 "--report", report_path]) == 0
    with open(report_path, encoding="utf-8") as handle:
        assert "N/A (wordfreq unavailable)" in handle.read()
