"""Hermetic tests for TICKET F3 (no network, synthetic data only).

Covers the AWL HTML parser (factory/fetch_awl.py) and the coverage math
(factory/awl_coverage.py) on inline fixtures. Real W: data is never touched.
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from awl_coverage import (decide_verdict, family_coverage, is_vowelless_word,
                          pack_hit, pool_awl_fraction)
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


def test_pack_hit_fallback_and_evp():
    pack = _pack()
    assert pack_hit("rhythm", "noun", pack) is True
    assert pack_hit("crypt", "noun", pack) is True
    assert pack_hit("crypt", None, pack) is True
    assert pack_hit("xyzzy", "noun", pack) is False
    assert pack_hit("", "noun", pack) is False


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


def test_decide_verdict_thresholds():
    assert decide_verdict(80.0, 0, 0).startswith("PROCEED")
    assert "allowlist follow-up" in decide_verdict(80.0, 3, 5)
    assert "ADJUST" in decide_verdict(80.0, 150, 5)
    assert "ADJUST" in decide_verdict(80.0, 7, 90)
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
