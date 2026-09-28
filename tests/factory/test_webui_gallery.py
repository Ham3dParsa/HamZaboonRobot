"""P02 gallery build module tests (frozen ``GET /api/gallery?run=`` contract).

TDD RED: written before ``factory/webui/gallery.py`` exists. Fixtures are
small and synthetic (never real run data, never network, never a model).
"""

import csv
import json
import os
import time
from pathlib import Path

import pytest

import factory.webui.gallery as gallery

TSV_HEADER = ["kaikki_sense_id", "wordnet_sensekey", "method", "evidence",
              "lemma", "kaikki_gloss"]

TSV_ROWS = [
    {"kaikki_sense_id": "en-run-en-verb-A",
     "wordnet_sensekey": "run%2:38:00::",
     "method": "LINK:2-sig", "evidence": "Sa:j=0.40+Sd:hyp=move",
     "lemma": "run", "kaikki_gloss": "To move fast."},
    {"kaikki_sense_id": "en-run-en-verb-B",
     "wordnet_sensekey": "-",
     "method": "UNMAPPED", "evidence": "0sig",
     "lemma": "run", "kaikki_gloss": "To own something."},
]

VERDICTS_DOC = {"verdicts": [
    {"kid": "en-run-en-verb-A", "lemma": "run", "verdict": "LINK",
     "winner_index": 1, "winner_sensekey": "run%2:38:00::",
     "wordnet_evidence": "move fast || words: run",
     "votes": [
         {"ok": True, "verdict": "LINK", "winner_index": 1},
         {"ok": True, "verdict": "LINK", "winner_index": 1},
     ]},
]}


def _write_run_dir(run_dir, tsv_name="link_table.tsv",
                   verdicts_name="verdicts.json"):
    run_dir = Path(str(run_dir))
    run_dir.mkdir(parents=True, exist_ok=True)
    tsv_path = run_dir / tsv_name
    with open(tsv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TSV_HEADER,
                                delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(TSV_ROWS)
    verdicts_path = run_dir / verdicts_name
    with open(verdicts_path, "w", encoding="utf-8") as handle:
        json.dump(VERDICTS_DOC, handle, ensure_ascii=False)
    return tsv_path, verdicts_path


def test_build_gallery_from_run_dir(tmp_path):
    run_dir = tmp_path / "run_demo"
    _write_run_dir(run_dir)
    out = gallery.build_gallery(str(run_dir))
    page = Path(str(out)).read_text(encoding="utf-8")
    assert Path(str(out)).name == "gallery.html"
    assert Path(str(out)).parent == run_dir
    assert "To move fast." in page
    assert "<html" in page


def test_build_gallery_cache_hit_no_rebuild(tmp_path):
    run_dir = tmp_path / "run_cached"
    _write_run_dir(run_dir)
    out_first = gallery.build_gallery(str(run_dir))
    mtime_first = os.path.getmtime(str(out_first))
    time.sleep(0.02)
    out_second = gallery.build_gallery(str(run_dir))
    assert str(out_second) == str(out_first)
    assert os.path.getmtime(str(out_second)) == mtime_first


def test_build_gallery_missing_tsv_raises_honest_error(tmp_path):
    run_dir = tmp_path / "run_empty"
    run_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError) as excinfo:
        gallery.build_gallery(str(run_dir))
    assert str(excinfo.value).strip() != ""
    assert not (run_dir / "gallery.html").exists()


def test_build_gallery_old_run_shaped_dir(tmp_path):
    # Old-run naming (Readme-style): versioned TSV + judge verdicts file.
    run_dir = tmp_path / "run20"
    _write_run_dir(run_dir, tsv_name="link_table_run20_v3.tsv",
                   verdicts_name="judge_verdicts_run20.json")
    out = gallery.build_gallery(str(run_dir))
    page = Path(str(out)).read_text(encoding="utf-8")
    assert Path(str(out)).name == "gallery.html"
    assert "To move fast." in page


def test_gallery_sources_explicit_paths(tmp_path):
    run_dir = tmp_path / "run_explicit"
    tsv_path, verdicts_path = _write_run_dir(run_dir)
    sources = gallery.gallery_sources({"tsv": str(tsv_path),
                                       "verdicts": str(verdicts_path)})
    assert Path(str(sources["tsv"])) == tsv_path
    assert Path(str(sources["verdicts"])) == verdicts_path
    assert Path(str(sources["out_html"])).name == "gallery.html"
