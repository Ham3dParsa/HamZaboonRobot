"""T-RUN-B: precard prompt registry (versioned, A/B pick, no wording edits).

- Byte-identical defaults: every registry default resolves to the exact
  pre-change bytes pinned in data/precard_prompts_v1.snapshot.json
  (captured 2026-09-18 before the move; any prompt byte-diff = FAIL).
- Variant pick: register_variant + select() reroutes resolution; reset()
  restores defaults.
- Legacy aliases (prompts.py / topics.py / judge.py names) stay identical
  to the registry defaults (pure re-export shims, zero behavior change).
"""

import hashlib
import json
import os

import pytest

from factory.precard import judge, prompt_registry as PR
from factory.precard import prompts
from factory.precard import topics

_HERE = os.path.dirname(os.path.abspath(__file__))
_SNAP = os.path.join(_HERE, "data", "precard_prompts_v1.snapshot.json")

# sha256 over the exact resolved bytes ("\n"-joined for head lists).
PINNED = {
    "topic_tiebreak": (
        "7e014aa912dff839ecd6bb26d2667a7f0cd0e842f0c96c1f4fbdc635e1c98a29"),
    "inflection_review_sys": (
        "504ce3032f2783eb8e1145168471036c0c0a2bf5da002a2400b80d541ee57469"),
    "v15_user_tmpl": (
        "aa52ebe0f79abfa0f06a7ce46933a2bf9c96336579180f7855e1764a2c41fce5"),
    "topup_user_tmpl": (
        "d5bd9be346703b99a5c3e11f6a7573a94394413936280371f79881bd6d0142b3"),
    "v16b_defs": (
        "c9a158c16d5d76cccc28d3a097dcf46cbf4982c230dfc26851913f20d84dfd3d"),
    "judge_head": (
        "30ecfc315e895a2841c971ad1c6a00213d16c33047d8b745f1930ce1bf6ed8f4"),
    "inflection_review_head": (
        "caa6c0d06041c87fa31ec3dcab657eedda091b265cc438012c271c29f68047a5"),
    "judge_prompt_fixture": (
        "17e215786de10947b9a7de4d8bdbde675d1460d493729dcd38c6f9b80d518707"),
    "inflection_prompt_fixture": (
        "9fe5eb3eb43a0f1f393c5000b0b11b2f8a3fbe521edab8771e5f084197933921"),
    "label_prompt_fixture": (
        "eddbde1f0ce574a64989264245ee9183d0b3b5ff8f937e0120c2ef1050789116"),
}


def _sha(blob):
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _snap():
    with open(_SNAP, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(autouse=True)
def _clean_registry():
    PR.reset()
    try:
        yield
    finally:
        PR.reset()
        os.environ.pop("FACTORY_PROMPT_VARIANT", None)


def test_version_tag():
    assert PR.PROMPTS_VERSION == "v1"
    for name in PR.PROMPT_NAMES:
        assert PR.prompt_version(name) == "v1"


def test_defaults_match_snapshot_bytes():
    snap = _snap()
    assert PR.get_prompt("topic_tiebreak") == snap["topic_tiebreak"]
    assert PR.get_prompt("inflection_review_sys") == \
        snap["inflection_review_sys"]
    assert PR.get_prompt("v15_user_tmpl") == snap["v15_user_tmpl"]
    assert PR.get_prompt("topup_user_tmpl") == snap["topup_user_tmpl"]
    assert PR.get_prompt("v16b_defs") == snap["v16b_defs"]
    assert list(PR.get_prompt_lines("judge_head")) == snap["judge_head"]
    assert list(PR.get_prompt_lines("inflection_review_head")) == \
        snap["inflection_review_head"]


def test_pinned_hashes():
    snap = _snap()
    for name, want in PINNED.items():
        blob = snap[name]
        if isinstance(blob, list):
            blob = "\n".join(blob)
        assert _sha(blob) == want, name


def test_registry_defaults_hash_to_pins():
    got = {
        "topic_tiebreak": PR.get_prompt("topic_tiebreak"),
        "inflection_review_sys": PR.get_prompt("inflection_review_sys"),
        "v15_user_tmpl": PR.get_prompt("v15_user_tmpl"),
        "topup_user_tmpl": PR.get_prompt("topup_user_tmpl"),
        "v16b_defs": PR.get_prompt("v16b_defs"),
        "judge_head": "\n".join(PR.get_prompt_lines("judge_head")),
        "inflection_review_head": "\n".join(
            PR.get_prompt_lines("inflection_review_head")),
    }
    for name, want in PINNED.items():
        if name in got:
            assert _sha(got[name]) == want, name


def test_builders_byte_identical_to_snapshot():
    snap = _snap()
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    anchor_map = {"w:call": {"candidates": [
        {"sense_id": "call#0", "gloss": "a telephone conversation",
         "tags": ["colloquial"]},
        {"sense_id": "call#1", "gloss": "to shout loudly", "tags": []}]}}
    assert judge.arbiter_prompt(batch, anchor_map) == \
        snap["judge_prompt_fixture"]
    assert judge._inflection_review_prompt(
        [{"key": "w:forcing", "text": "forcing",
          "gloss": "present participle of force"}]) == \
        snap["inflection_prompt_fixture"]
    assert topics._label_prompt(
        [{"key": "w:call", "text": "call", "sense_id": "call#0",
          "gloss": "a telephone conversation"}]) == \
        snap["label_prompt_fixture"]


def test_legacy_aliases_identical_to_registry():
    assert prompts.TOPIC_TIEBREAK == PR.get_prompt("topic_tiebreak")
    assert prompts.INFLECTION_REVIEW_SYS == \
        PR.get_prompt("inflection_review_sys")
    assert topics.V15_USER_TMPL == PR.get_prompt("v15_user_tmpl")
    assert topics.TOPUP_USER_TMPL == PR.get_prompt("topup_user_tmpl")
    assert topics.V16B_DEFS == PR.get_prompt("v16b_defs")


def test_variant_pick_and_reset():
    PR.register_variant("topic_tiebreak", "no-tiebreak", "PLAIN")
    assert PR.get_prompt("topic_tiebreak") != "PLAIN"
    PR.select("topic_tiebreak=no-tiebreak")
    assert PR.get_prompt("topic_tiebreak") == "PLAIN"
    assert PR.selected_variant("topic_tiebreak") == "no-tiebreak"
    PR.reset()
    assert PR.get_prompt("topic_tiebreak") != "PLAIN"
    assert PR.selected_variant("topic_tiebreak") == "default"


def test_variant_lines_pick():
    PR.register_variant("judge_head", "short",
                        ["SHORT HEAD", "Input follows:"])
    PR.select("judge_head=short")
    assert list(PR.get_prompt_lines("judge_head")) == [
        "SHORT HEAD", "Input follows:"]


def test_env_selects_variant():
    PR.register_variant("v15_user_tmpl", "alt", "ALT-TEMPLATE")
    os.environ["FACTORY_PROMPT_VARIANT"] = "v15_user_tmpl=alt"
    assert PR.get_prompt("v15_user_tmpl") == "ALT-TEMPLATE"


def test_unknown_name_fails_closed():
    with pytest.raises(KeyError):
        PR.get_prompt("no_such_prompt")
    with pytest.raises(KeyError):
        PR.select("no_such_prompt=x")
    with pytest.raises(KeyError):
        PR.register_variant("no_such_prompt", "x", "y")


def test_malformed_env_raises_fail_fast():
    """OC must-fix #765: a malformed FACTORY_PROMPT_VARIANT is never
    silently swallowed — _resolve/selected_variant let ValueError
    propagate (fail fast, env agrees with CLI select())."""
    os.environ["FACTORY_PROMPT_VARIANT"] = "bogus-chunk-no-equals"
    with pytest.raises(ValueError):
        PR.selected_variant("topic_tiebreak")
    with pytest.raises(ValueError):
        PR.get_prompt("topic_tiebreak")


def test_absent_and_empty_env_resolve_defaults():
    """Absent env (normal path) and empty env keep resolving v1."""
    os.environ.pop("FACTORY_PROMPT_VARIANT", None)
    assert PR.selected_variant("topic_tiebreak") == "default"
    assert PR.get_prompt("topic_tiebreak") == PR.TOPIC_TIEBREAK
    os.environ["FACTORY_PROMPT_VARIANT"] = ""
    assert PR.selected_variant("topic_tiebreak") == "default"
    assert PR.get_prompt("topic_tiebreak") == PR.TOPIC_TIEBREAK


def test_explicit_select_malformed_raises():
    """Explicit select() behavior unchanged: malformed chunks raise."""
    with pytest.raises(ValueError):
        PR.select("bogus-chunk-no-equals")
