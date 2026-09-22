"""T3 — prove batch-5/keep-5 loop + two-adapter proof (hermetic).

All doubles are injected fakes: no network, no keys, no disk beyond tmp_path.
Consumes the locked T1 seam (TunnelSelector ctor + prove signature) read-only.

Locked rules under test:
- batch/keep arrive as injected defaults (default 5) with override.
- at most `batch` probes per batch, in priority (input) order.
- early stop once `keep` clean is met (even mid-batch) — no second batch.
- transport errors map to unknown, never blocked.
- prove writes nothing to any cache (no store writes, no subs refresh).
- exactly two adapters (SubscriptionSource, ProviderProbe) via injection.
"""

import pytest

from factory.net.tunnel_selection import (
    NoTunnelExit,
    ProviderProbe,
    SubscriptionSource,
    TunnelSelector,
)


class FakeSubs(SubscriptionSource):
    def __init__(self):
        self.refresh_calls = 0

    def refresh(self):
        self.refresh_calls += 1
        return []


class FakeStore:
    """Counting store double. T2 owns the real store; T3 must not write it."""

    def __init__(self):
        self.reads = 0
        self.writes = 0

    def read(self, provider):
        self.reads += 1
        return []

    def write(self, provider, rows):
        self.writes += 1


class ScriptProbe(ProviderProbe):
    """Verdict per exit_id; names in `raise_on` simulate transport errors."""

    def __init__(self, verdicts=None, raise_on=()):
        self.verdicts = dict(verdicts or {})
        self.raise_on = set(raise_on)
        self.probe_calls = 0
        self.probed_ids = []

    def probe(self, exit_id):
        self.probe_calls += 1
        self.probed_ids.append(exit_id)
        if exit_id in self.raise_on:
            raise TimeoutError("simulated transport timeout for %r" % (exit_id,))
        return self.verdicts.get(exit_id, "clean")


def _selector(probe, batch=5, keep=5):
    subs = FakeSubs()
    store = FakeStore()
    sel = TunnelSelector(
        subs=subs,
        probes={"google": probe},
        store=store,
        clock=lambda: 0.0,
        batch=batch,
        keep=keep,
    )
    return sel, subs, store


def test_prove_batches_max_five_with_early_stop_at_keep():
    """12 clean exits, defaults batch=5/keep=5: exactly 5 probes, keep 5."""
    probe = ScriptProbe()
    sel, _, _ = _selector(probe)
    exits = ["e%02d" % i for i in range(12)]
    proof = sel.prove("google", exits)
    assert probe.probe_calls == 5  # 6-wide batch would fail here
    assert proof.clean == exits[:5]  # priority order kept
    assert len(proof.clean) == 5  # 6 stabilized would fail here
    assert proof.blocked == [] and proof.unknown == []


def test_prove_no_second_batch_once_keep_met():
    """keep=3/batch=5 all-clean: stop mid-first-batch, never a 2nd batch."""
    probe = ScriptProbe()
    sel, _, _ = _selector(probe, batch=5, keep=3)
    exits = ["e%02d" % i for i in range(10)]
    proof = sel.prove("google", exits)
    assert proof.clean == exits[:3]
    assert probe.probe_calls == 3
    assert probe.probed_ids == exits[:3]


def test_prove_batch_keep_override_drives_batches():
    """batch=2/keep=3 all-clean: 2-wide batches, stop after 3 clean."""
    probe = ScriptProbe()
    sel, _, _ = _selector(probe, batch=2, keep=3)
    exits = ["eA", "eB", "eC", "eD", "eE"]
    proof = sel.prove("google", exits)
    assert proof.clean == ["eA", "eB", "eC"]
    assert probe.probe_calls == 3
    assert probe.probed_ids == ["eA", "eB", "eC"]


def test_transport_timeout_is_unknown_not_blocked():
    """TimeoutError on one exit lands in unknown; blocked stays empty."""
    probe = ScriptProbe(
        verdicts={"e1": "clean", "e2": "blocked"}, raise_on={"e3"}
    )
    sel, _, _ = _selector(probe)
    proof = sel.prove("google", ["e1", "e2", "e3"])
    assert proof.clean == ["e1"]
    assert proof.blocked == ["e2"]
    assert proof.unknown == ["e3"]  # transport error is unknown, never blocked


def test_two_adapters_same_prove_scenario():
    """R3 justification: keyless Google + keyed probe, one scenario, both green."""

    class KeylessGoogleProbe(ProviderProbe):
        def probe(self, exit_id):
            return "clean"

    class KeyedSecondProbe(ProviderProbe):
        def __init__(self, key_name):
            self.key_name = key_name  # name only, never the value

        def probe(self, exit_id):
            return "clean"

    subs = FakeSubs()
    store = FakeStore()
    exits = ["e1", "e2"]
    for probe in (KeylessGoogleProbe(), KeyedSecondProbe(key_name="PROBE_KEY")):
        assert isinstance(probe, ProviderProbe)
        sel = TunnelSelector(
            subs=subs,
            probes={"p": probe},
            store=store,
            clock=lambda: 0.0,
        )
        proof = sel.prove("p", exits)
        assert proof.clean == exits
        assert proof.blocked == [] and proof.unknown == []


def test_prove_writes_no_cache(tmp_path):
    """prove touches no store writes and triggers no subscription refresh."""
    probe = ScriptProbe()
    sel, subs, store = _selector(probe)
    proof = sel.prove("google", ["e1", "e2", "e3"])
    assert proof.clean == ["e1", "e2", "e3"]
    assert store.writes == 0
    assert subs.refresh_calls == 0
    assert list(tmp_path.iterdir()) == []


def test_prove_unknown_provider_raises_no_tunnel():
    """No registered probe for the provider: honest park, never invent exits."""
    probe = ScriptProbe()
    sel, _, _ = _selector(probe)
    with pytest.raises(NoTunnelExit):
        sel.prove("groq", ["e1"])


@pytest.mark.skip(reason="gated live: needs flag + network; hermetic CI skips")
def test_live_prove_gated_skipped_without_flag():
    """Live prove stub: runs only with an explicit live flag (never in CI)."""
    raise AssertionError("live prove must stay gated")
