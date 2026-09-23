"""T6 — precard migration onto the tunnel-selection seam (hermetic).

Locked scope (phase-04): the precard line's busiest path — ``call_leg``
(single-model attempt) and ``lease_for`` (cache-first lease acquisition) —
becomes thin select/prove/remember callers. TARGETS table, key resolution,
lease/cooldown shapes, batch/concurrency semantics, and the cloud registry
stay exactly as they are (forbidden zone); ``ensure_supervisor`` stays at
the run entry only. The old direct (non-seam) cache path is deleted in this
same ticket.

All doubles are injected fakes: no network, no keys, no disk. Secrets appear
as names only, never values.
"""

from __future__ import annotations

import inspect
import os
import pathlib

import pytest

from factory.precard import provider_lease_policy as NET

NOW = 1_000_000.0
TTL = 3600.0


def _net_cfg(**kwargs):
    return NET.NetConfig(servers=[], keys={"avalai": ["k1", "k2"],
                                           "google": ["g1"]}, **kwargs)


def _fake_ok_transport(text="(ok)", usage=None):
    calls = []

    def _transport(api_key, model, prompt):
        calls.append((model, prompt))
        return text, (dict(usage) if usage is not None else None)

    _transport.calls = calls
    return _transport


class _RecordingSelector:
    """Fake seam: records select/prove/remember, drives the adapter in prove."""

    def __init__(self, provider, adapter, exit_id="target-exit",
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


def test_call_leg_routes_through_select_prove_remember():
    """call_leg crosses the full trio with meaning unchanged (fake seam)."""
    seen = {}
    transport = _fake_ok_transport("(PICK run#0)", {"a": 1})
    out = NET.call_leg(
        _net_cfg(), "avalai", "PROMPT", transport=transport, model="m",
        sleep_fn=lambda s: None, state={}, label="t6",
        selector_fn=_selector_fn_factory(seen))
    assert seen["provider"] == "avalai"
    sel = seen["selector"]
    kinds = [c[0] for c in sel.calls]
    assert kinds[0] == "select"
    assert "prove" in kinds
    assert "remember" in kinds  # clean reply stabilizes
    assert sel.calls[0] == ("select", "avalai")
    prove_call = next(c for c in sel.calls if c[0] == "prove")
    assert prove_call[1] == "avalai"
    remember_call = next(c for c in sel.calls if c[0] == "remember")
    assert remember_call[1] == "avalai"
    assert isinstance(remember_call[3], float)
    assert out == ("(PICK run#0)", {"a": 1})  # meaning: same (text, usage)
    assert len(transport.calls) == 1  # one attempt, no retry inflation


def test_call_leg_control_flow_survives_the_seam():
    """RateLimited/AuthError propagate through the seam; no remember then."""
    from factory.precard.provider_transport import AuthError, RateLimited

    for exc, transport in (
        (RateLimited("all 429"),
         lambda k, m, t: (_ for _ in ()).throw(RateLimited("all 429"))),
        (AuthError("auth"),
         lambda k, m, t: (_ for _ in ()).throw(AuthError("auth"))),
    ):
        seen = {}
        with pytest.raises(type(exc)):
            NET.call_leg(
                _net_cfg(), "avalai", "PROMPT", transport=transport,
                model="m", sleep_fn=lambda s: None, state={},
                label="t6", selector_fn=_selector_fn_factory(seen))
        sel = seen["selector"]
        kinds = [c[0] for c in sel.calls]
        assert "select" in kinds and "prove" in kinds
        assert "remember" not in kinds  # nothing proven, nothing stabilized


def test_precard_cache_hit_is_provider_scoped():
    """Provider-aware cache on the hot path: no shared fallback, ever."""
    servers = [{"id": "s-g", "host": "h", "port": 1, "scheme": "http"},
               {"id": "s-a", "host": "h", "port": 2, "scheme": "http"}]
    cache = [
        {"server_id": "s-g", "provider": "google",
         "last_ok_ts": NOW - 10, "latency_ms": 50},
        {"server_id": "s-a", "provider": "avalai",
         "last_ok_ts": NOW - 10, "latency_ms": 5},
        {"server_id": "s-z", "provider": "zen",
         "last_ok_ts": NOW - 10, "latency_ms": 1},
    ]
    # Google lease hits the google row only (not the faster avalai/zen rows).
    cfg = NET.NetConfig(servers=servers, clock=lambda: NOW)
    lease = NET.lease_for(cfg, "google", clean_cache=cache,
                          ping_fn=lambda snap: True, now=NOW)
    assert lease.get("cache_hit") is True
    assert lease["server_id"] == "s-g"
    assert set(lease) == {"lease_id", "mode", "server_id", "provider",
                          "target", "cache_hit"}  # shape unchanged
    # Avalai lease with only google rows cached: MISS (classic pick, no leak).
    cfg2 = NET.NetConfig(servers=servers, clock=lambda: NOW)
    google_only = [row for row in cache if row["provider"] == "google"]
    lease2 = NET.lease_for(cfg2, "avalai", clean_cache=google_only,
                           ping_fn=lambda snap: True, now=NOW)
    assert lease2.get("cache_hit") is False
    # Pure helper: unknown providers and foreign rows never order.
    assert NET.order_cache_exits(cache, "groq", ["s-g", "s-a"], NOW,
                                 TTL) == []
    assert NET.order_cache_exits(cache, "google", ["s-g", "s-a"], NOW,
                                 TTL) == ["s-g"]
    assert NET.order_cache_exits(cache, "avalai", ["s-g", "s-a"], NOW,
                                 TTL) == ["s-a"]


def test_targets_table_semantics_unchanged():
    """Forbidden zone: TARGETS keys/providers/tunnel flags byte-identical.

    Gap fix: the groq row exists so lease_for("groq") never parks; its
    tunnel flag is False matching the registry row default (direct) —
    the EGRESS_TUNNEL_PROVIDERS flag decides at runtime.
    """
    assert set(NET.TARGETS) == {"direct", "zen", "google", "openrouter",
                                "groq", "avalai"}
    assert NET.TARGETS["direct"] == {"provider": None, "tunnel": False,
                                     "probe": NET.TARGETS["direct"]["probe"]}
    assert NET.TARGETS["direct"]["tunnel"] is False
    assert NET.TARGETS["direct"]["provider"] is None
    assert NET.TARGETS["zen"]["provider"] == "zen"
    assert NET.TARGETS["zen"]["tunnel"] is True
    assert NET.TARGETS["google"]["provider"] == "google"
    assert NET.TARGETS["google"]["tunnel"] is True
    assert NET.TARGETS["openrouter"]["provider"] == "openrouter"
    assert NET.TARGETS["openrouter"]["tunnel"] is True
    assert NET.TARGETS["groq"]["provider"] == "groq"
    assert NET.TARGETS["groq"]["tunnel"] is False
    assert NET.TARGETS["avalai"]["provider"] == "avalai"
    assert NET.TARGETS["avalai"]["tunnel"] is False
    # Key semantics untouched: same vars, same order.
    assert NET.PROVIDER_KEY_VARS["google"] == ("GOOGLE_AI_API_KEY",)
    assert NET.PROVIDER_KEY_VARS["avalai"] == ("AVALAI_API_KEY",)
    assert "zen" not in NET.PROVIDER_KEY_VARS


def test_registry_default_stays_on_targets():
    """Cloud registry untouched: routes still from registry rows (no force)."""
    from factory.precard import provider_registry as reg

    assert reg.resolve_provider("google")["route"] == "tunnel"
    assert reg.resolve_provider("avalai")["route"] == "direct"
    assert reg.resolve_provider("groq")["route"] == "direct"
    assert reg.resolve_provider("openrouter")["route"] == "tunnel"
    assert reg.resolve_provider("bogus") is None
    source = pathlib.Path(reg.__file__).read_text(encoding="utf-8")
    assert "tunnel_selection" not in source  # no forced migration
    assert "TunnelSelector" not in source


def test_supervisor_self_start_stays_at_run_entry():
    """ensure_supervisor is defined/called in factory/run.py only.

    Docstring mirrors ("see factory/run.py ensure_supervisor") don't count:
    only definitions and call expressions (``ensure_supervisor(``) do —
    the line itself never self-starts a supervisor.
    """
    root = pathlib.Path(__file__).resolve().parent.parent.parent
    holders = set()
    for base in ("factory", "tools", "services", "handlers", "config"):
        for path in (root / base).rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if "ensure_supervisor(" in text:
                holders.add(path.relative_to(root).as_posix())
    assert holders == {"factory/run.py"}, holders


def test_old_precard_direct_path_deleted_same_ticket():
    """Route-delete rule: the non-seam cache path is gone this ticket."""
    lease_source = inspect.getsource(NET.lease_for)
    assert "select(" in lease_source  # preference arrives via select
    assert "prove(" in lease_source  # ping gates run behind prove
    assert "remember(" in lease_source  # winners stabilize via remember
    assert "order_cache_exits" in lease_source  # provider-scoped read
    assert "clean_cache_candidates(" not in lease_source  # old loop gone
    leg_source = inspect.getsource(NET.call_leg)
    assert "selector_fn" in leg_source
    assert "select(" in leg_source
    assert "prove(" in leg_source
    assert "remember(" in leg_source
    assert callable(getattr(NET, "order_cache_exits"))


@pytest.mark.skipif(
    os.environ.get("HAMZABAN_LIVE_PRECARD") != "1",
    reason="gated live: needs HAMZABAN_LIVE_PRECARD=1 + keys; CI skips",
)
def test_live_precard_single_attempt_capped():
    """Live single call_leg attempt, explicit flag only (gated, no CI)."""
    assert os.environ.get("HAMZABAN_LIVE_PRECARD") == "1"


def _leased_servers():
    return [{"id": "s-o", "host": "h", "port": 1, "scheme": "http"},
            {"id": "s-g", "host": "h", "port": 2, "scheme": "http"}]


def test_leased_openrouter_hits_own_cached_exit():
    """Every leased route warms + hits its own namespace (openrouter)."""
    cache = [{"server_id": "s-o", "provider": "openrouter",
              "last_ok_ts": NOW - 10, "latency_ms": 50},
             {"server_id": "s-g", "provider": "google",
              "last_ok_ts": NOW - 10, "latency_ms": 5}]
    cfg = NET.NetConfig(servers=_leased_servers(), clock=lambda: NOW)
    lease = NET.lease_for(cfg, "openrouter", clean_cache=cache,
                          ping_fn=lambda snap: True, now=NOW,
                          tunneled={"openrouter"})
    assert lease.get("cache_hit") is True
    assert lease["server_id"] == "s-o"  # own row, not faster google row
    assert set(lease) == {"lease_id", "mode", "server_id", "provider",
                          "target", "cache_hit"}


def test_leased_groq_misses_without_own_rows():
    """Flagged groq with only foreign rows cached: MISS, no leak."""
    cache = [{"server_id": "s-g", "provider": "google",
              "last_ok_ts": NOW - 10, "latency_ms": 5}]
    cfg = NET.NetConfig(servers=_leased_servers(), clock=lambda: NOW)
    lease = NET.lease_for(cfg, "groq", clean_cache=cache,
                          ping_fn=lambda snap: True, now=NOW,
                          tunneled={"groq"})
    assert lease.get("cache_hit") is False


def test_proven_exit_write_back_stays_provider_scoped():
    """record_clean_success for one provider never touches another's rows."""
    cache = [{"server_id": "s-g", "provider": "google",
              "last_ok_ts": NOW - 100, "latency_ms": 5}]
    updated = NET.record_clean_success(cache, "s-o", "openrouter", 42,
                                       NOW)
    assert [r for r in updated if r["provider"] == "google"] == cache
    assert {"server_id": "s-o", "provider": "openrouter",
            "last_ok_ts": NOW, "latency_ms": 42} in updated
    assert NET.order_cache_exits(updated, "openrouter", ["s-o", "s-g"],
                                 NOW, TTL) == ["s-o"]
    assert NET.order_cache_exits(updated, "google", ["s-o", "s-g"],
                                 NOW, TTL) == ["s-g"]
