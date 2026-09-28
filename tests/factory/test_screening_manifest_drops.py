"""T01 — manifest drop_reasons aggregation (twin-R3 / proper-R2 / other).

Locked rule: manifest gains ``drop_reasons`` counted from the drops
sidecar ``reason`` strings (twin/dedup/dup→twin_r3;
proper/propn/name→proper_r2; rest→other); invariant
twin+proper+other == dropped_total. Missing/unreadable sidecar → key
absent (never zeros). Server summary surfaces the key verbatim and
drops it when absent (legacy manifests render ``—`` downstream).

Hermetic: fake screen_fn, tmp dirs, Flask test client. No Kaikki, no
processes, no network, no secret values.
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.linking import export_screened as export
from factory.webui import server as webui


def _fake_screen_fn(senses, lemma=None):
    """2 twin + 1 proper + 2 other drops, 1 kept per lemma."""
    kept = [{"sense_id": "%s#1" % lemma, "gloss": "keep"}]
    drops = [
        {"sense_id": "%s#2" % lemma, "reason": "twin-of:%s#1" % lemma},
        {"sense_id": "%s#3" % lemma, "reason": "twin-of:%s#1" % lemma},
        {"sense_id": "%s#4" % lemma, "reason": "DROP_PROPER_NOUN"},
        {"sense_id": "%s#5" % lemma, "reason": "obsolete"},
        {"sense_id": "%s#6" % lemma, "reason": "form-of"},
    ]
    return kept, drops, {}


def test_manifest_sums_and_invariant(tmp_path, monkeypatch):
    """Golden: known drops → manifest sums + invariant holds."""
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", str(tmp_path))
    out_dir = str(tmp_path / "screened")
    manifest = export.export_words(["run", "take"], out_dir, index={},
                                   raw_path=str(tmp_path),
                                   screen_fn=_fake_screen_fn)
    reasons = manifest.get("drop_reasons")
    assert reasons == {"twin_r3": 4, "proper_r2": 2, "other": 4}
    assert (reasons["twin_r3"] + reasons["proper_r2"] + reasons["other"]
            == manifest["dropped_total"] == 10)
    assert manifest["kept_total"] == 2
    # On-disk manifest carries the same key (summary reader source).
    with open(os.path.join(out_dir, "screened.manifest.json"),
              encoding="utf-8") as handle:
        stored = json.load(handle)
    assert stored["drop_reasons"] == reasons


def test_absent_sidecar_means_absent_key(tmp_path):
    """Missing/unreadable sidecar → aggregate None (never zeros)."""
    assert export.aggregate_drop_reasons(
        str(tmp_path / "nope" / "screened.drops.jsonl")) is None
    # A present-but-empty sidecar aggregates to honest zeros.
    drops = tmp_path / "screened.drops.jsonl"
    drops.write_text("", encoding="utf-8")
    assert export.aggregate_drop_reasons(str(drops)) == {
        "twin_r3": 0, "proper_r2": 0, "other": 0}


def test_reason_taxonomy_table():
    """Classifier covers the controller's existing reason classes."""
    assert export.classify_drop_reason("twin-of:run#1") == "twin_r3"
    assert export.classify_drop_reason("dedup-winner") == "twin_r3"
    assert export.classify_drop_reason("dup-gloss") == "twin_r3"
    assert export.classify_drop_reason("DROP_PROPER_NOUN") == "proper_r2"
    assert export.classify_drop_reason("obsolete") == "other"
    assert export.classify_drop_reason("form-of") == "other"
    assert export.classify_drop_reason("xref") == "other"
    assert export.classify_drop_reason("niche") == "other"
    assert export.classify_drop_reason("") == "other"


def test_summary_surfaces_verbatim_and_drops_when_absent(tmp_path):
    """Server summary passes drop_reasons through; legacy → no key."""
    out_new = tmp_path / "new"
    out_new.mkdir()
    (out_new / "screened.manifest.json").write_text(json.dumps({
        "kept_total": 1, "dropped_total": 5,
        "per_lemma": [],
        "drop_reasons": {"twin_r3": 2, "proper_r2": 1, "other": 2}}),
        encoding="utf-8")
    summary = webui._screening_manifest_summary(str(out_new))
    assert summary["drop_reasons"] == {"twin_r3": 2, "proper_r2": 1,
                                       "other": 2}
    out_legacy = tmp_path / "legacy"
    out_legacy.mkdir()
    (out_legacy / "screened.manifest.json").write_text(json.dumps({
        "kept_total": 1, "dropped_total": 5, "per_lemma": []}),
        encoding="utf-8")
    legacy = webui._screening_manifest_summary(str(out_legacy))
    assert "drop_reasons" not in legacy
    assert webui._screening_manifest_summary(str(tmp_path / "missing")) is None
