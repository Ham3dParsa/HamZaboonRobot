"""T-RUN-E: single rotation helper over the net leg policy, hermetic.

Keyless, no network, no clock, no W: drive. run_leg.plan() resolves the
walk every R6 leg repeats (ordered providers, per-provider models, ring,
target, key_var) read-only over factory.precard.net policy. Legs keep
prompt + validate + telemetry; this file pins only the helper contract.
"""
from factory.precard import net as NET
from factory.precard import run_leg


class _Ring:
    def __init__(self, name):
        self.name = name
        self.idx = 0


def test_plan_single_paid_provider_uses_chain():
    ring = _Ring("base")
    base, steps = run_leg.plan("sense_judge", "google", None, None, ring, "K")
    assert base == "google"
    assert [s["provider"] for s in steps] == ["google"]
    step = steps[0]
    assert step["models"] == NET.leg_chain("google", "sense_judge")
    assert step["ring"] is ring
    assert step["target"] == NET.target_for("google")
    assert step["key_var"] == "K"


def test_plan_empty_provider_yields_empty_walk():
    # Faithful to the inline legs: falsy provider produced an empty
    # walk (net policy maps it to no provider), never a default walk.
    ring = _Ring("base")
    base, steps = run_leg.plan("topic_label", "", None, None, ring, "K")
    assert base == "avalai"
    assert steps == []
    base, steps = run_leg.plan("sense_judge", None, None, None, ring, "K")
    assert steps == []


def test_plan_normalizes_mixed_case_provider():
    ring = _Ring("base")
    base, steps = run_leg.plan("sense_judge", "Google", None, None, ring, "K")
    assert base == "google"
    assert [s["provider"] for s in steps] == ["google"]


def test_plan_explicit_models_win_only_on_base(monkeypatch):
    monkeypatch.setattr(NET, "FREE_PROVIDERS", frozenset({"avalai"}))
    base_ring = _Ring("base")
    other_ring = _Ring("other")
    rings = {"avalai": base_ring, "google": other_ring}
    base, steps = run_leg.plan(
        "sense_judge", "avalai", ["m1"], rings, base_ring, "K")
    assert [s["provider"] for s in steps] == ["avalai", "google"]
    assert steps[0]["models"] == ["m1"]
    assert steps[0]["ring"] is base_ring
    assert steps[0]["key_var"] == "K"
    assert steps[1]["models"] == NET.leg_chain("google", "sense_judge")
    assert steps[1]["ring"] is other_ring
    assert steps[1]["key_var"] == ""


def test_plan_skips_provider_without_ring(monkeypatch):
    monkeypatch.setattr(NET, "FREE_PROVIDERS", frozenset({"avalai"}))
    base_ring = _Ring("base")
    base, steps = run_leg.plan(
        "topic_vectors", "avalai", None, {"avalai": base_ring},
        base_ring, "K")
    assert [s["provider"] for s in steps] == ["avalai"]


def test_plan_unknown_leg_raises():
    ring = _Ring("base")
    try:
        run_leg.plan("bogus", "avalai", None, None, ring, "K")
    except ValueError:
        return
    raise AssertionError("unknown leg must raise via net policy")


def test_cooldown_continues_only_before_last():
    ordered = ["avalai", "google"]
    assert run_leg.cooldown_continues(ordered, 0) is True
    assert run_leg.cooldown_continues(ordered, 1) is False
    assert run_leg.cooldown_continues(["avalai"], 0) is False
