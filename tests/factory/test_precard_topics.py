"""Identity T3: topics live in the new home on the 16-head registry.

The live world is 16 heads (Society, Work & Careers, ...), not the 13
of the v14 era. The guard rewired here returns only live names (this
fixes the live invalid-label bug); a membership test pins it.
"""

from factory.precard import topics


def test_registry_is_live_16():
    assert len(topics.LABELS) == 16
    assert "Society" in topics.LABELS
    assert "Work & Careers" in topics.LABELS
    assert "Society & Culture" not in topics.LABELS
    assert "Work & Education" not in topics.LABELS


def test_gender_never_animals():
    assert topics.topic_post_guard(
        "gender", "the biological sex of a person",
        "Animals & Living Beings") == "Health & Body"
    assert topics.topic_post_guard(
        "gender", "the socially constructed roles of men and women",
        "Animals & Living Beings") == "Society"


def test_functional_concepts_use_live_names():
    assert topics.topic_post_guard(
        "call", "a telephone conversation",
        "Other / Abstract") == "Science & Technology"
    assert topics.topic_post_guard(
        "call", "to shout loudly", "Other / Abstract") == "Society"
    assert topics.topic_post_guard(
        "working", "paid employment",
        "Other / Abstract") == "Work & Careers"
    assert topics.topic_post_guard(
        "spectacle", "a public performance",
        "Other / Abstract") == "Society"
    assert topics.topic_post_guard(
        "accrue", "to accumulate money",
        "Other / Abstract") == "Business & Economy"
    assert topics.topic_post_guard(
        "evelate".replace("evel", "elev"), "to lift something up",
        "Other / Abstract") == "Daily Life & Home"


def test_guard_output_always_in_registry():
    probes = [("gender", "male roles", "Animals & Living Beings"),
              ("call", "phone call", "Other / Abstract"),
              ("about", "on the subject of", "Other / Abstract"),
              ("apple", "a round fruit", "Food & Drink"),
              ("", "", ""),
              (None, None, None)]
    for text, gloss, label in probes:
        assert topics.topic_post_guard(text, gloss, label) in (
            topics.LABELS + [None, ""])


def test_pseudo_records_cover_all_picks():
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    judge_map = {"w:call": {"sense_id": "call#1",
                            "gloss": "to shout loudly",
                            "picks": [
                                {"sense_id": "call#1",
                                 "gloss": "to shout loudly"},
                                {"sense_id": "call#0",
                                 "gloss": "a telephone conversation"}]}}
    recs = topics.vectors_pseudo_records(batch, judge_map, {})
    sids = [s["sense_id"] for r in recs for s in r["ranked_senses"]]
    assert sorted(sids) == ["call#0", "call#1"]


def test_fallback_row_shape():
    row = topics.label_fallback_result({"s#0": [{"label": "X"}]}, "s#0")
    assert row["label"] == "Other / Abstract"
    assert row["topic_path"] == "fallback"
