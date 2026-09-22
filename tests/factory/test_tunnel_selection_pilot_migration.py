"""T7 — pilot migration onto the tunnel-selection seam (hermetic).

Locked scope (phase-05): the pilot card paths — ``call_responses`` (the
single Zen POST choke point behind ``generate_card`` and the main()
content/grammar/sense review defaults) — become thin select/prove/
remember callers. Judging/content logic, batch and concurrency
semantics, and the cloud registry stay exactly as they are (forbidden
zone). The old direct (non-seam) urllib path is deleted in this same
ticket.

All doubles are injected fakes: no network, no keys, no disk. Secrets
appear as names only, never values.
"""

from __future__ import annotations

import inspect
import json
import os
import urllib.error

import pytest

from factory.pipeline import card_pilot

VALID_CARD = {
    "word": "resilient",
    "phonetic": "IPA: /rɪˈzɪl.jənt/",
    "fa_meaning": "تاب‌آور",
    "fa_explanation": "کسی که پس از سختی به حالت عادی برمی‌گردد.",
    "synonyms": ["tough", "hardy"],
    "antonyms": ["fragile"],
    "examples": ["She is a resilient student studying daily here.",
                 "Resilient trees grow strong after every storm."],
    "example_translations": ["او دانش‌آموز تاب‌آوری است که هر روز در اینجا درس می‌خواند.",
                             "درختان تاب‌آور پس از هر طوفان قوی رشد می‌کنند."],
    "grammar_tip": "صفت است و معمولا با be می‌آید.",
}


class _RecordingSelector:
    """Fake seam: records select/prove/remember, drives the adapter."""

    def __init__(self, provider, adapter, exit_id="zen-exit",
                 verdict_proof=None):
        self.provider = provider
        self.adapter = adapter
        self.exit_id = exit_id
        self.calls = []
        self._proof = verdict_proof

    def select(self, provider):
        from factory.net.tunnel_selection import Selection

        self.calls.append(("select", provider))
        return Selection(exit_id=self.exit_id, lease=None,
                         whitelisted=False, served_from="subscription")

    def prove(self, provider, exits):
        from factory.net.tunnel_selection import Proof

        self.calls.append(("prove", provider, list(exits)))
        for exit_id in exits:
            self.adapter.probe(exit_id)
        if self._proof is not None:
            return self._proof
        return Proof(clean=list(exits), blocked=[], unknown=[])

    def remember(self, provider, exit_id, latency_ms):
        self.calls.append(("remember", provider, exit_id, latency_ms))


def _selector_fn_factory(seen, **kwargs):
    def _selector_fn(provider, adapter):
        seen["provider"] = provider
        seen["adapter"] = adapter
        sel = _RecordingSelector(provider, adapter, **kwargs)
        seen["selector"] = sel
        return sel

    return _selector_fn


def test_pilot_provider_calls_cross_seam(monkeypatch):
    """call_responses crosses the full trio; the POST runs behind prove."""
    from factory.net.tunnel_selection import KeyedProviderProbe

    posts = []

    def _fake_post(api_key, body, timeout):
        posts.append((body, timeout))
        assert api_key == "k-zen"  # value rides the leaf only, never the seam
        return json.dumps({"ok": True, "text": "PICK run#0"})

    monkeypatch.setattr(card_pilot, "_pilot_post_once", _fake_post)
    seen = {}
    text = card_pilot.call_responses(
        "k-zen", "m-model", "SYS", "USER",
        selector_fn=_selector_fn_factory(seen))
    assert text == json.dumps({"ok": True, "text": "PICK run#0"})
    assert len(posts) == 1  # one POST, no retry inflation
    assert seen["provider"] == "zen"  # pilot provider namespace
    adapter = seen["adapter"]
    assert isinstance(adapter, KeyedProviderProbe)
    assert adapter.key_name == "OPENCODE_ZEN_API_KEY"  # key NAME only
    sel = seen["selector"]
    kinds = [c[0] for c in sel.calls]
    assert kinds == ["select", "prove", "remember"]  # full trio, in order
    assert sel.calls[0] == ("select", "zen")
    assert sel.calls[1] == ("prove", "zen", ["zen-exit"])
    provider, exit_id, latency_ms = sel.calls[2][1:]
    assert provider == "zen"
    assert exit_id == "zen-exit"
    assert isinstance(latency_ms, float)


def test_pilot_control_flow_survives_the_seam(monkeypatch):
    """HTTP/auth failures propagate unchanged; nothing stabilizes then."""
    boom = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)

    def _fake_post(api_key, body, timeout):
        raise boom

    monkeypatch.setattr(card_pilot, "_pilot_post_once", _fake_post)
    seen = {}
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        card_pilot.call_responses(
            "k-zen", "m-model", "SYS", "USER",
            selector_fn=_selector_fn_factory(seen))
    assert exc_info.value is boom  # same object: generate_card maps 401 loud
    sel = seen["selector"]
    kinds = [c[0] for c in sel.calls]
    assert "select" in kinds and "prove" in kinds
    assert "remember" not in kinds  # nothing proven, nothing stabilized


def test_pilot_judging_logic_unchanged():
    """Forbidden zone: fixture verdicts byte-identical (stub transport)."""
    item = {"kind": "word", "text": "resilient", "pool_level": "B2"}
    calls = {}

    def _ok(api_key, model, system, user):
        return json.dumps(VALID_CARD)

    rec = card_pilot.generate_card(item, "key", transport=_ok,
                                   model_calls=calls)
    assert rec["valid"] is True
    assert rec["model_used"] == card_pilot.MODELS[0]
    assert rec["card"]["word"] == "resilient"
    assert rec["card"]["fa_meaning"] == "تاب‌آور"
    assert rec["fa_dominant"] is True
    assert rec["headword_leaks"] == []
    assert rec["leaks"] == []
    assert rec["regen"] is False
    assert rec["reason"] == "" and rec["error"] == ""
    assert calls == {card_pilot.MODELS[0]: 1}  # one attempt, no inflation

    def _bad(api_key, model, system, user):
        return "this is not json at all {{{"

    bad = card_pilot.generate_card(
        {"kind": "word", "text": "xyz", "pool_level": "A1"},
        "key", transport=_bad, model_calls={})
    assert bad["valid"] is False
    assert bad["card"] is None
    assert bad["error"]  # recorded, never raised


def test_pilot_batch_five_respected(monkeypatch):
    """R5 on the pilot path: injected caps default 5, prove stays narrow."""
    params = inspect.signature(card_pilot.call_responses).parameters
    assert params["batch"].default == 5
    assert params["keep"].default == 5

    posts = []
    monkeypatch.setattr(
        card_pilot, "_pilot_post_once",
        lambda api_key, body, timeout: (posts.append(body), "TEXT")[1])
    seen = {}
    card_pilot.call_responses(
        "k-zen", "m-model", "SYS", "USER",
        selector_fn=_selector_fn_factory(seen))
    prove_call = next(c for c in seen["selector"].calls if c[0] == "prove")
    assert len(prove_call[2]) <= 5  # batch discipline: single-exit prove
    assert prove_call[2] == ["zen-exit"]

    # Default wiring carries the same caps into a real TunnelSelector.
    from factory.net.tunnel_selection import KeyedProviderProbe

    sel = card_pilot._default_pilot_selector(
        "zen", KeyedProviderProbe(key_name="K", check_fn=lambda e: "clean"),
        "zen-exit")
    assert sel.batch == 5
    assert sel.keep == 5
    assert sel.select("zen").exit_id == "zen-exit"  # served, no network


def test_old_pilot_direct_path_deleted_same_ticket():
    """Route-delete rule: the non-seam urllib path is gone this ticket."""
    source = inspect.getsource(card_pilot.call_responses)
    assert "select(" in source  # egress arrives via select
    assert "prove(" in source  # verdict arrives via prove
    assert "remember(" in source  # winners stabilize via remember
    assert "selector_fn" in source
    assert "_pilot_post_once" in source  # single POST leaf behind the seam
    assert "urllib.request.urlopen" not in source  # old inline POST gone
    assert "ZEN_BASE" not in source  # URL building lives in the leaf
    leaf = inspect.getsource(card_pilot._pilot_post_once)
    assert "urllib.request.urlopen" in leaf
    assert "ZEN_BASE" in leaf


@pytest.mark.skipif(
    os.environ.get("HAMZABAN_LIVE_PILOT") != "1",
    reason="gated live: needs HAMZABAN_LIVE_PILOT=1 + key; CI skips",
)
def test_live_pilot_single_probe_capped():
    """Live single pilot POST, explicit flag only (gated, no CI)."""
    assert os.environ.get("HAMZABAN_LIVE_PILOT") == "1"
