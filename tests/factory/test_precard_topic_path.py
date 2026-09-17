"""topic_path promotion (D-go-rev): s4 leg metadata rides top-level.

_build_precard_row carries sub_label.topic_path (cache/llm/unlabelled,
plus the retired leg1/fallback values from older progress states)
and sub_label.topic_guarded onto every emitted row — primaries and
fanned-out secondaries alike. The v16b-exact fossil is gone: the default
method tag is topics.TOPIC_METHOD ("live16").
"""

from factory.precard import pipeline as new_pipeline
from factory.precard.topics import TOPIC_METHOD, label_batch

_VALID_PATHS = ("leg1", "cache", "llm", "fallback", "unlabelled")


def _row(sub_label):
    return new_pipeline._build_precard_row(
        {"kind": "word", "text": "apple"}, "w:apple",
        {"sense_id": "apple#0"}, {}, sub_label,
        [{"label": "Food & Drink", "weight": 1.0}],
        {}, {}, {}, {}, {}, 0, 1)


def test_topic_path_promoted_primary():
    row = _row({"method": TOPIC_METHOD, "topic_path": "llm"})
    assert row["topic_path"] == "llm"
    assert row["topic_guarded"] is False
    assert row["topic_method"] == TOPIC_METHOD
    # stage_calls keeps the nested copy the viewer chip reads.
    assert row["stage_calls"]["s4_path"] == "llm"


def test_topic_path_promoted_guarded_secondary():
    row = _row({"method": TOPIC_METHOD, "topic_path": "leg1",
                "topic_guarded": True})
    assert row["topic_path"] == "leg1"
    assert row["topic_guarded"] is True


def test_topic_path_fail_closed_and_no_fossil():
    row = _row({})
    assert row["topic_path"] == ""
    assert row["topic_guarded"] is False
    assert row["topic_method"] == TOPIC_METHOD == "live16"
    blob = str(row)
    assert "v16b-exact" not in blob
    assert row["topic_path"] in ("",) + _VALID_PATHS


def test_none_topic_path_fail_closed():
    """Reviewer finding (Kilo WARNING + OC warnings): an explicit None
    path normalizes to "" in both the top-level field and s4_path."""
    row = _row({"method": TOPIC_METHOD, "topic_path": None})
    assert row["topic_path"] == ""
    assert row["stage_calls"]["s4_path"] == ""


def test_guarded_secondary_flag_survives_extra_fold():
    """End-to-end s4 secondary path: label_batch -> extra -> pipeline
    promotion. R3 locked: transport=None leaves every sense UNLABELLED
    (never Other); the fold still collects one secondary per extra pick
    and the pipeline promotion honors the folded row."""
    batch = [{"kind": "word", "text": "call"}]
    picks = {"w:call": {"picks": [
        {"sense_id": "call#0", "gloss": "to cry out"},
        {"sense_id": "call#2", "gloss": "to telephone someone"}]}}
    out = label_batch(batch, picks, None, "test-key", None,
                      lambda s: None, {}, None, {})
    primary = out["w:call"]
    assert primary["label"] is None
    assert primary["topic_path"] == "unlabelled"
    assert primary.get("topic_guarded", False) is False
    assert len(primary["extra"]) == 1
    secondary = primary["extra"][0]
    assert secondary["label"] is None
    assert secondary["topic_path"] == "unlabelled"
    # And the pipeline promotion honors the folded path.
    promoted = _row(secondary)
    assert promoted["topic_path"] == "unlabelled"
    assert promoted["stage_calls"]["s4_path"] == "unlabelled"
