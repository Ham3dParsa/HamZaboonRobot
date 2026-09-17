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


def test_unlabelled_row_shape():
    """R3 locked: LLM failure leaves the row UNLABELLED (never Other)."""
    row = topics.label_unlabelled_result({"s#0": [{"label": "X"}]}, "s#0")
    assert row["label"] is None
    assert row["topic_path"] == "unlabelled"
    assert row["method"] == topics.TOPIC_METHOD
    assert row["vector"] == [{"label": "X"}]
    empty = topics.label_unlabelled_result(None, "s#9")
    assert empty["label"] is None
    assert empty["topic_path"] == "unlabelled"
    assert empty["vector"] == []


def test_r3_leg1_gone():
    """R3 locked: no deterministic leg1 path (no import, no lookup)."""
    import inspect
    assert not hasattr(topics, "evp_fallback_label")
    assert not hasattr(topics, "_label_leg1_lookup")
    assert not hasattr(topics, "MIGRATE_DEFAULT")
    assert not hasattr(topics, "label_fallback_result")
    assert "lookup" not in inspect.signature(topics.label_batch).parameters


def test_r3_llm_failure_yields_unlabelled():
    """R3 locked: transport=None (or a failed LLM leg) never emits Other."""
    batch = [{"kind": "word", "text": "apple", "pool_level": "A1"}]
    picks = {"w:apple": {"sense_id": "apple#9", "gloss": "a thing"}}
    out = topics.label_batch(
        batch, picks, None, "k", None, lambda s: None, {}, "/none", {})
    assert out["w:apple"]["label"] is None
    assert out["w:apple"]["topic_path"] == "unlabelled"
    assert out["w:apple"]["method"] == topics.TOPIC_METHOD


def test_r3_s3_prompt_has_visual_rule():
    """R3 locked: the s3 vectors prompt carries the visual/tangible rule."""
    assert "pink" in topics.V15_USER_TMPL
    assert "Arts & Culture" in topics.V15_USER_TMPL


def test_topup_tiebreak_distinguishes_leisure_from_sport():
    """Q5 locked: the TOPUP tie-break family carries the leisure/sport
    line (same style as the R3 color/shape rules)."""
    assert "casual leisure" in topics.TOPUP_USER_TMPL
    assert "Competitive sports" in topics.TOPUP_USER_TMPL
    prompt = topics._label_prompt(
        [{"key": "w:tennis", "text": "tennis",
          "gloss": "a game played with rackets",
          "sense_id": "tennis#0"}])
    assert "casual leisure" in prompt
    assert "Sports & Leisure" in prompt


def test_r3_pink_like_resolves_via_llm():
    """R3 locked: a pink-like sense resolves via the LLM path (transport)."""
    import json
    from factory.precard.transport import KeyRing

    batch = [{"kind": "word", "text": "pink", "pool_level": "A1"}]
    picks = {"w:pink": {"sense_id": "pink#0",
                        "gloss": "a pale reddish color"}}

    def fake_transport(api_key, model, user_text):
        assert "pink" in user_text
        return json.dumps({"results": [{
            "lemma": "pink", "senses": [{
                "sense_id": "pink#0", "topic_id": 8,
                "topic_label": "Arts & Culture", "confidence": 0.9,
                "vector": [
                    {"topic_id": 8,
                     "topic_label": "Arts & Culture",
                     "weight": 0.60},
                    {"topic_id": 1,
                     "topic_label": "Daily Life & Home",
                     "weight": 0.40}]}]}]})

    out = topics.label_batch(
        batch, picks, None, "k", fake_transport, lambda s: None,
        {"done": {}, "failed": [], "backoffs": []}, None, {},
        ring=KeyRing(["k"]))
    row = out["w:pink"]
    assert row["label"] == "Arts & Culture"
    assert row["topic_path"] == "llm"
    assert row["vector"][0]["label"] == "Arts & Culture"
