"""Wave 0 / T1 — hermetic seam tests for factory.net.tunnel_selection.

All doubles are injected fakes: no network, no keys, no disk beyond tmp_path.
"""

import inspect

import pytest


def _make_fakes(tmp_path):
    from factory.net.tunnel_selection import ProviderProbe, SubscriptionSource

    class FakeSubs(SubscriptionSource):
        def __init__(self):
            self.refresh_calls = 0

        def refresh(self):
            self.refresh_calls += 1
            return []

    class FakeProbe(ProviderProbe):
        def __init__(self, verdict="clean"):
            self.probe_calls = 0
            self.verdict = verdict

        def probe(self, exit_id):
            self.probe_calls += 1
            return self.verdict

    class FakeStore:
        def __init__(self):
            self.reads = 0
            self.writes = 0

        def read(self, provider):
            self.reads += 1
            return []

        def write(self, provider, rows):
            self.writes += 1

    return FakeSubs(), FakeProbe(), FakeStore()


def test_seam_select_prove_remember_importable():
    from factory.net import tunnel_selection as ts
    from factory.net.tunnel_selection import (
        NoTunnelExit,
        Proof,
        ProviderProbe,
        Selection,
        SubscriptionSource,
        TunnelSelector,
    )

    assert callable(TunnelSelector)
    for name in ("select", "prove", "remember"):
        assert callable(getattr(TunnelSelector, name)), name
    assert issubclass(NoTunnelExit, Exception)
    assert issubclass(SubscriptionSource, object)
    assert issubclass(ProviderProbe, object)
    sig = inspect.signature(TunnelSelector.__init__)
    assert sig.parameters["batch"].default == 5
    assert sig.parameters["keep"].default == 5
    assert "subs" in sig.parameters and "probes" in sig.parameters
    assert "store" in sig.parameters and "clock" in sig.parameters
    # re-exported at package root
    import factory.net as net

    assert net.TunnelSelector is TunnelSelector
    assert net.Selection is Selection and net.Proof is Proof


def test_ctor_touches_no_io(tmp_path):
    from factory.net.tunnel_selection import TunnelSelector

    subs, probe, store = _make_fakes(tmp_path)
    sel = TunnelSelector(
        subs=subs, probes={"google": probe}, store=store, clock=lambda: 0.0
    )
    assert subs.refresh_calls == 0
    assert probe.probe_calls == 0
    assert store.reads == 0 and store.writes == 0
    assert list(tmp_path.iterdir()) == []


def test_select_prove_remember_with_injected_fakes(tmp_path):
    from factory.net.tunnel_selection import NoTunnelExit, TunnelSelector

    subs, probe, store = _make_fakes(tmp_path)
    sel = TunnelSelector(
        subs=subs, probes={"google": probe}, store=store, clock=lambda: 0.0
    )
    with pytest.raises(NoTunnelExit):
        sel.select("google")
    proof = sel.prove("google", ["e1", "e2"])
    assert proof.clean == ["e1", "e2"] and proof.blocked == [] and proof.unknown == []
    assert probe.probe_calls == 2  # T3 batch loop: priority order, early stop at keep
    assert store.writes == 0  # prove writes nothing (T3); select only reads
    sel.remember("google", "e1", 12.5)  # T2 stabilize: upsert through the store
    assert store.writes == 1
    sel.remember("google", "", 0)  # empty never touches the store
    assert store.writes == 1


def test_batch_keep_overridable(tmp_path):
    from factory.net.tunnel_selection import TunnelSelector

    subs, probe, store = _make_fakes(tmp_path)
    sel = TunnelSelector(
        subs=subs,
        probes={"google": probe},
        store=store,
        clock=lambda: 0.0,
        batch=2,
        keep=3,
    )
    assert sel.batch == 2 and sel.keep == 3


def test_deletion_justifies_seam(tmp_path):
    """R3 justification: two real probe shapes behind one ProviderProbe seam.

    If the ProviderProbe adapter is removed, this test breaks at import —
    keyless Google and keyed probes would lock into one body instead.
    """

    from factory.net.tunnel_selection import ProviderProbe, TunnelSelector

    class KeylessGoogleProbe(ProviderProbe):
        def probe(self, exit_id):
            return "clean"

    class KeyedSecondProbe(ProviderProbe):
        def __init__(self, key_name):
            self.key_name = key_name  # name only, never the value

        def probe(self, exit_id):
            return "clean"

    subs, _, store = _make_fakes(tmp_path)
    for probe in (KeylessGoogleProbe(), KeyedSecondProbe(key_name="PROBE_KEY")):
        assert isinstance(probe, ProviderProbe)
        sel = TunnelSelector(
            subs=subs, probes={"p": probe}, store=store, clock=lambda: 0.0
        )
        proof = sel.prove("p", ["e1"])
        assert hasattr(proof, "clean")
        assert hasattr(proof, "blocked") and hasattr(proof, "unknown")
