"""T-RUN-E: single rotation helper over the lease policy, hermetic.

Keyless, no network, no clock, no W: drive. leg_walk.resolve_leg_walk() resolves the
walk every R6 leg repeats (ordered providers, per-provider models, ring,
target, key_var) read-only over factory.precard.provider_lease_policy policy. Legs keep
prompt + validate + telemetry; this file pins only the helper contract.
"""
from factory.precard import provider_lease_policy as NET
from factory.precard import leg_walk


class _Ring:
    def __init__(self, name):
        self.name = name
        self.idx = 0


def test_resolve_leg_walk_single_paid_provider_uses_chain():
    ring = _Ring("base")
    base, steps = leg_walk.resolve_leg_walk("sense_judge", "google", None, None, ring, "K")
    assert base == "google"
    assert [s["provider"] for s in steps] == ["google"]
    step = steps[0]
    assert step["models"] == NET.leg_chain("google", "sense_judge")
    assert step["ring"] is ring
    assert step["target"] == NET.target_for("google")
    assert step["key_var"] == "K"


def test_resolve_leg_walk_empty_provider_yields_empty_walk():
    # Faithful to the inline legs: falsy provider produced an empty
    # walk (net policy maps it to no provider), never a default walk.
    ring = _Ring("base")
    base, steps = leg_walk.resolve_leg_walk("topic_label", "", None, None, ring, "K")
    assert base == "avalai"
    assert steps == []
    base, steps = leg_walk.resolve_leg_walk("sense_judge", None, None, None, ring, "K")
    assert steps == []


def test_resolve_leg_walk_normalizes_mixed_case_provider():
    ring = _Ring("base")
    base, steps = leg_walk.resolve_leg_walk("sense_judge", "Google", None, None, ring, "K")
    assert base == "google"
    assert [s["provider"] for s in steps] == ["google"]


def test_resolve_leg_walk_explicit_models_win_only_on_base(monkeypatch):
    monkeypatch.setattr(NET, "FREE_PROVIDERS", frozenset({"avalai"}))
    base_ring = _Ring("base")
    other_ring = _Ring("other")
    rings = {"avalai": base_ring, "google": other_ring}
    base, steps = leg_walk.resolve_leg_walk(
        "sense_judge", "avalai", ["m1"], rings, base_ring, "K")
    assert [s["provider"] for s in steps] == ["avalai", "google"]
    assert steps[0]["models"] == ["m1"]
    assert steps[0]["ring"] is base_ring
    assert steps[0]["key_var"] == "K"
    assert steps[1]["models"] == NET.leg_chain("google", "sense_judge")
    assert steps[1]["ring"] is other_ring
    assert steps[1]["key_var"] == ""


def test_resolve_leg_walk_skips_provider_without_ring(monkeypatch):
    monkeypatch.setattr(NET, "FREE_PROVIDERS", frozenset({"avalai"}))
    base_ring = _Ring("base")
    base, steps = leg_walk.resolve_leg_walk(
        "topic_vectors", "avalai", None, {"avalai": base_ring},
        base_ring, "K")
    assert [s["provider"] for s in steps] == ["avalai"]


def test_resolve_leg_walk_unknown_leg_raises():
    ring = _Ring("base")
    try:
        leg_walk.resolve_leg_walk("bogus", "avalai", None, None, ring, "K")
    except ValueError:
        return
    raise AssertionError("unknown leg must raise via net policy")


def test_cooldown_continues_only_before_last():
    ordered = ["avalai", "google"]
    assert leg_walk.cooldown_continues(ordered, 0) is True
    assert leg_walk.cooldown_continues(ordered, 1) is False
    assert leg_walk.cooldown_continues(["avalai"], 0) is False
