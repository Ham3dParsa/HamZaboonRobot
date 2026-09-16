"""T0-v1 sampler: quotas, tag-policy flags, deterministic selection."""

import json

from factory.precard import sampler
from factory.precard.anchor import OBSOLETE_TAGS, VULGAR_TAGS


def _row(key, level="B1", method="pool-fallback", tags=None,
         examples=None, zipf=5.0):
    row = {"key": key, "sense_cefr": level,
           "sense_cefr_method": method, "zipf": zipf}
    if tags is not None:
        row["tags"] = tags
    if examples is not None:
        row["dataset_examples"] = examples
    return row


def test_media_profile_keeps_slang_drops_obsolete():
    drop = sampler.resolve_drop_tags("media")
    assert drop == frozenset(OBSOLETE_TAGS)
    rows = [_row("w:a", tags=["slang"]),
            _row("w:b", tags=["obsolete"]),
            _row("w:c")]
    selected, summary = sampler.sample(
        rows, quotas={"B1": 10}, drop_tags=drop)
    assert {r["key"] for r in selected} == {"w:a", "w:c"}
    assert summary["drops"] == {"tag:obsolete": 1}


def test_clean_profile_drops_vulgar_and_slang():
    drop = sampler.resolve_drop_tags("clean")
    assert set(VULGAR_TAGS) <= set(drop)
    assert {"slang", "colloquial"} <= set(drop)
    rows = [_row("w:a", tags=["slang"]), _row("w:b", tags=["vulgar"]),
            _row("w:c")]
    selected, _ = sampler.sample(rows, quotas={"B1": 10},
                                 drop_tags=drop)
    assert [r["key"] for r in selected] == ["w:c"]


def test_explicit_flags_beat_profile():
    drop = sampler.resolve_drop_tags("clean", include=("slang",))
    assert "slang" not in drop
    drop = sampler.resolve_drop_tags("media", exclude=("slang",))
    assert "slang" in drop
    rows = [_row("w:a", tags=["slang"])]
    selected, _ = sampler.sample(rows, quotas={"B1": 10},
                                 drop_tags=drop)
    assert selected == []


def test_missing_tags_pass_through():
    selected, _ = sampler.sample(
        [_row("w:a")], quotas={"B1": 5},
        drop_tags=frozenset(OBSOLETE_TAGS))
    assert [r["key"] for r in selected] == ["w:a"]


def test_score_order_and_quota():
    rows = [_row("w:low", method="pool-fallback"),
            _row("w:high", method="wn-single"),
            _row("w:mid", method="pool-fallback",
                 examples=["She runs."])]
    selected, summary = sampler.sample(rows, quotas={"B1": 2},
                                       drop_tags=frozenset())
    assert [r["key"] for r in selected] == ["w:high", "w:mid"]
    assert summary["per_level"]["B1"]["shortfall"] == 0
    assert summary["per_level"]["B1"]["reservoir_need"] == 4  # ceil(2/.58)


def test_unknown_level_capped_by_other_quota():
    rows = [_row("w:x", level=""), _row("w:y", level="Z9")]
    selected, summary = sampler.sample(rows, quotas={"B1": 5},
                                       drop_tags=frozenset(),
                                       other_quota=1)
    assert len(selected) == 1
    assert summary["per_level"]["OTHER"]["selected"] == 1


def test_cli_end_to_end(tmp_path):
    rows = [_row("w:k%d" % i, tags=["obsolete"] if i == 0 else [])
            for i in range(4)]
    src = tmp_path / "rows.jsonl"
    src.write_text("\n".join(json.dumps(r) for r in rows),
                   encoding="utf-8")
    out = tmp_path / "out.jsonl"
    rc = sampler.main(["--rows", str(src), "--out", str(out),
                       "--mix", "0,0,2,0,0,0", "--profile", "media"])
    assert rc == 0
    kept = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines()]
    assert len(kept) == 2
    assert all("obsolete" not in (r.get("tags") or []) for r in kept)


def test_reviewer_findings_casefold_nan_empty_quotas():
    """Reviewer findings (OC warnings): uncasefolded drop_tags must not
    bypass the policy; NaN zipf sorts last; explicit {} quotas mean
    nothing selected (not full defaults)."""
    assert sampler.tag_drop_reason(["vulgar"],
                                   frozenset({"VULGAR"})) == "vulgar"
    assert sampler.score_row({"zipf": float("nan")}) < \
        sampler.score_row({"zipf": 0.0, "sense_cefr_method": "wn-single"})
    selected, summary = sampler.sample(
        [_row("w:a")], quotas={}, survival={},
        drop_tags=frozenset())
    assert selected == []
    assert summary["per_level"]["B1"]["quota"] == 0


def test_cli_malformed_jsonl_exits_2(tmp_path):
    """Reviewer finding (Kilo WARNING): bad input line -> usage error
    naming file + line, not a traceback."""
    import pytest

    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"key": "w:a"}\nNOT JSON\n', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        sampler.main(["--rows", str(bad),
                      "--out", str(tmp_path / "o.jsonl"),
                      "--mix", "0,0,1,0,0,0"])
    assert exc.value.code == 2
