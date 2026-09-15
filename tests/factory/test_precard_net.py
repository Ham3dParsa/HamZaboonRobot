"""P0 net core: hermetic tests for factory/precard/net.py + seam guards.

Keyless, no network, no clock, no W: drive, no real .env reads: servers
and clocks are fakes, transports are injected, env maps and dotenv
files are explicit temp files. Key values are sentinels that must never
surface in messages (asserted).
"""

import io
import os
import sys
import urllib.error

import pytest

from factory.core import llm_json as LJ
from factory.precard import net as NET
from factory.precard import transport as T

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "tools", "egress"))
import supervisor as SUP  # noqa: E402  (probe mapping lives there)


def _http(code, body=b""):
    return urllib.error.HTTPError("http://x", code, "reason", {},
                                  io.BytesIO(body) if body else None)


def _servers():
    return [{"scheme": "vless", "host": "h1", "port": 1, "id": "s1"},
            {"scheme": "vless", "host": "h2", "port": 2, "id": "s2"}]


def _cfg(**kw):
    now = [1000.0]
    base = {"servers": _servers(), "clock": lambda: now[0],
            "sleeper": lambda s: None, "cooldown_s": 300.0}
    base.update(kw)
    cfg = NET.NetConfig(**base)
    cfg._now = now  # test handle to advance the fake clock
    return cfg


# --- TARGETS single ownership ---

def test_targets_shape_and_single_owner():
    assert set(NET.TARGETS) == {"direct", "zen", "google",
                                "openrouter", "avalai"}
    assert NET.TARGETS["direct"] == {"provider": None, "tunnel": False,
                                     "probe": None}
    assert NET.TARGETS["openrouter"] == {"provider": "openrouter",
                                         "tunnel": True, "probe": None}
    assert NET.TARGETS["avalai"] == {"provider": "avalai",
                                     "tunnel": False, "probe": None}
    assert NET.TARGETS["zen"]["provider"] == "zen"
    assert NET.TARGETS["zen"]["tunnel"] is True
    assert NET.TARGETS["google"]["provider"] == "google"
    # Moved from supervisor: the supervisor re-exports this same dict
    # and only attaches its live probes (probe identity is asserted in
    # tests/test_egress.py, which owns the supervisor side).
    assert SUP.TARGETS is NET.TARGETS


def test_keyring_single_owner():
    import factory.lexicon.phrase_judge as PJ
    assert PJ.KeyRing is T.KeyRing
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path(PJ.__file__).read_text(
        encoding="utf-8"))
    defs = [n.name for n in tree.body
            if isinstance(n, ast.ClassDef)]
    assert "KeyRing" not in defs


# --- resolve_key / require_key order ---

def test_resolve_key_flag_beats_env_beats_file(tmp_path):
    dotenv = tmp_path / "factory.env"
    dotenv.write_text("PROBE_KEY=file-v\n", encoding="utf-8")
    assert NET.resolve_key("PROBE_KEY", explicit="flag-v",
                           env_map={"PROBE_KEY": "env-v"},
                           file_paths=(str(dotenv),)) == "flag-v"
    assert NET.resolve_key("PROBE_KEY", env_map={"PROBE_KEY": "env-v"},
                           file_paths=(str(dotenv),)) == "env-v"
    assert NET.resolve_key("PROBE_KEY", env_map={},
                           file_paths=(str(dotenv),)) == "file-v"
    assert NET.resolve_key("PROBE_KEY", env_map={},
                           file_paths=()) == ""


def test_require_key_loud_stop_names_var_and_file_never_values(tmp_path):
    dotenv = tmp_path / "factory.env"
    dotenv.write_text("PROBE_KEY=file-v\n", encoding="utf-8")
    assert NET.require_key("PROBE_KEY", env_map={},
                           file_paths=(str(dotenv),),
                           flag="--probe-key",
                           file_label="factory/.env") == "file-v"
    with pytest.raises(NET.MissingKeyError) as exc:
        NET.require_key("PROBE_KEY", env_map={},
                        file_paths=(str(tmp_path / "empty.env"),),
                        flag="--probe-key", file_label="factory/.env")
    msg = str(exc.value)
    assert "PROBE_KEY" in msg and "--probe-key" in msg
    assert "factory/.env" in msg and "file-v" not in msg


# --- lease_for / report_lease with fake servers + clock ---

def test_lease_direct_and_unknown_target():
    cfg = _cfg()
    lease = NET.lease_for(cfg, "direct")
    assert lease["mode"] == "direct" and lease["provider"] is None
    bad = NET.lease_for(cfg, "bogus")
    assert bad["error"] == "park" and "bogus" in bad["message"]


def test_lease_tunnel_picks_first_and_cools_on_429():
    cfg = _cfg()
    first = NET.lease_for(cfg, "zen")
    assert (first["mode"], first["server_id"],
            first["provider"]) == ("tunnel", "s1", "zen")
    assert NET.report_lease(cfg, first["lease_id"],
                            "http429") == {"action": "switch"}
    second = NET.lease_for(cfg, "zen")
    assert second["server_id"] == "s2"  # s1 cooling for zen
    # A google lease still takes s1: cooldowns are per (server, provider).
    google = NET.lease_for(cfg, "google")
    assert google["server_id"] == "s1"
    # Cooling expires with the fake clock.
    cfg._now[0] += 301.0
    assert NET.lease_for(cfg, "zen")["server_id"] == "s1"


def test_lease_parks_when_everything_cools():
    cfg = _cfg()
    for target in ("zen", "zen"):
        lease = NET.lease_for(cfg, target)
        NET.report_lease(cfg, lease["lease_id"], "http429")
    parked = NET.lease_for(cfg, "zen")
    assert parked["error"] == "park"


def test_report_unknown_lease_auth_and_junk_provider():
    cfg = _cfg()
    assert NET.report_lease(cfg, "nope", "ok") == {
        "action": "unknown-lease"}
    lease = NET.lease_for(cfg, "zen")
    # Junk provider strings never mint cooldown keys.
    assert NET.report_lease(cfg, lease["lease_id"], "http429",
                            provider="junk-string") == {"action": "keep"}
    assert not NET.is_cool(cfg, lease["server_id"], "junk-string")
    assert NET.report_lease(cfg, lease["lease_id"],
                            "ok") == {"action": "keep"}
    assert NET.report_lease(cfg, lease["lease_id"],
                            "auth_err") == {"action": "reauth"}
    assert NET.report_lease(cfg, lease["lease_id"],
                            "ok") == {"action": "unknown-lease"}


# --- call_leg rotation / stops ---

def test_call_leg_rotates_on_429_to_next_key():
    cfg = _cfg(keys={"zen": ["k1-sentinel", "k2-sentinel"]})
    seen = []
    sleeps = []

    def fake(api_key, model, text):
        seen.append(api_key)
        if api_key == "k1-sentinel":
            raise _http(429)
        return "done"

    out = NET.call_leg(cfg, "zen", "prompt", transport=fake,
                       model="m", sleep_fn=sleeps.append, state={})
    assert out == ("done", None)
    assert seen == ["k1-sentinel", "k2-sentinel"]
    assert sleeps == [T.ROTATE_PAUSE]


def test_call_leg_all_keys_429_raises_after_every_key():
    cfg = _cfg(keys={"zen": ["k1", "k2"]})
    seen = []

    def fake(api_key, model, text):
        seen.append(api_key)
        raise _http(429)

    with pytest.raises(T.RateLimited):
        NET.call_leg(cfg, "zen", "prompt", transport=fake, model="m",
                     sleep_fn=lambda s: None, state={})
    assert seen == ["k1", "k2"]


def test_call_leg_401_stops_after_one_attempt_naming_var_and_file():
    cfg = _cfg(keys={"zen": ["zz-secret-1", "zz-secret-2"]})
    seen = []

    def fake(api_key, model, text):
        seen.append(api_key)
        raise _http(401)

    with pytest.raises(T.AuthError) as exc:
        NET.call_leg(cfg, "zen", "prompt", transport=fake, model="m",
                     sleep_fn=lambda s: None, state={})
    assert seen == ["zz-secret-1"]  # no further attempts
    msg = str(exc.value)
    assert "401" in msg and "OPENCODE_ZEN_API_KEY" in msg
    assert "factory/.env" in msg
    assert "zz-secret-1" not in msg and "zz-secret-2" not in msg


def test_call_leg_missing_keys_stops_loud_without_calling():
    cfg = _cfg()
    seen = []

    def fake(api_key, model, text):  # pragma: no cover (never called)
        seen.append(api_key)
        return "x"

    with pytest.raises(NET.MissingKeyError) as exc:
        NET.call_leg(cfg, "zen", "prompt", transport=fake, model="m")
    assert seen == [] and "OPENCODE_ZEN_API_KEY" in str(exc.value)


def test_call_leg_unknown_leg_is_programmer_error():
    cfg = _cfg()
    with pytest.raises(ValueError):
        NET.call_leg(cfg, "bogus", "prompt", transport=lambda *a: "x",
                     model="m")


# --- transport classify routing (zero behavior change pins) ---

def test_wrapper_rotates_on_bare_429_and_google_quota_body():
    state = {}
    ring = T.KeyRing(["k1", "k2"])
    calls = []

    def fake(api_key, model, text):
        calls.append(api_key)
        raise _http(429)

    with pytest.raises(T.RateLimited):
        T._call_with_rotation(fake, ring, "m", "t", lambda s: None,
                              state, "lbl")
    assert calls == ["k1", "k2"]
    # Google project-quota body classifies COOLDOWN_SWITCH, and the
    # precard transport must NOT rotate same-project keys on it
    # (llm_json taxonomy: cool down + switch provider). It raises
    # ProviderCooldown after exactly one attempt; the subclass keeps
    # every existing ``except RateLimited`` flush+stop handler safe.
    assert LJ.classify(429, "RESOURCE_EXHAUSTED: quota",
                       "google") == LJ.COOLDOWN_SWITCH
    ring2 = T.KeyRing(["k1", "k2"])
    calls2 = []
    backoffs = {"backoffs": []}

    def fake_q(api_key, model, text):
        calls2.append(api_key)
        raise _http(429, b"RESOURCE_EXHAUSTED: quota exceeded")

    with pytest.raises(T.ProviderCooldown) as excinfo:
        T._call_with_rotation(fake_q, ring2, "m", "t",
                              lambda s: None, backoffs, "lbl",
                              provider="google")
    assert calls2 == ["k1"]  # single attempt, no rotation
    assert isinstance(excinfo.value, T.RateLimited)
    assert "google" in str(excinfo.value)
    assert backoffs["backoffs"] and backoffs["backoffs"][-1][
        "outcome"] == "cooldown_switch"


def test_wrapper_abort_is_loud_auth_error_and_500_propagates():
    ring = T.KeyRing(["k1", "k2"])
    with pytest.raises(T.AuthError):
        T._call_with_rotation(lambda *a: (_ for _ in ()).throw(_http(
            401)), ring, "m", "t", lambda s: None, {}, "lbl")
    with pytest.raises(urllib.error.HTTPError):
        T._call_with_rotation(lambda *a: (_ for _ in ()).throw(_http(
            500)), T.KeyRing(["k1"]), "m", "t", lambda s: None, {},
            "lbl")


def test_rotating_transport_routes_through_classify():
    ring = T.KeyRing(["k1"])
    wrap = T._rotating_llm_transport(
        lambda *a: (_ for _ in ()).throw(_http(403)), lambda s: None,
        {}, ring)
    with pytest.raises(T.AuthError):
        wrap("ignored", "m", "t")


def test_rotating_transport_cooldown_switch_no_rotation():
    """The S4 wrapper maps the same llm_json COOLDOWN_SWITCH row as
    _call_with_rotation: Google RESOURCE_EXHAUSTED raises
    ProviderCooldown after exactly one attempt (no same-project key
    rotation); the RateLimited subclass keeps flush+stop handlers safe."""
    assert LJ.classify(429, "RESOURCE_EXHAUSTED: quota",
                       "google") == LJ.COOLDOWN_SWITCH
    ring = T.KeyRing(["k1", "k2"])
    calls = []
    backoffs = {"backoffs": []}

    def fake(api_key, model, text):
        calls.append(api_key)
        raise _http(429, b"RESOURCE_EXHAUSTED: quota exceeded")

    wrap = T._rotating_llm_transport(fake, lambda s: None, backoffs,
                                     ring, provider="google")
    with pytest.raises(T.ProviderCooldown) as excinfo:
        wrap("ignored", "m", "t")
    assert calls == ["k1"]  # single attempt, no rotation
    assert isinstance(excinfo.value, T.RateLimited)
    assert "google" in str(excinfo.value)
    assert backoffs["backoffs"] and backoffs["backoffs"][-1][
        "outcome"] == "cooldown_switch"


def test_pipeline_env_loader_single_owner():
    """load_factory_env/KEYS live in factory.core.env_loader; the precard
    pipeline imports them (no twin def or tuple there)."""
    import ast
    import pathlib
    path = pathlib.Path(os.path.dirname(__file__), "..", "..",
                        "factory", "precard", "pipeline.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        assert not (isinstance(node, (ast.FunctionDef,
                                      ast.AsyncFunctionDef,
                                      ast.ClassDef))
                    and node.name == "load_factory_env"), \
            "pipeline.py must not redefine load_factory_env"
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            assert not any(isinstance(t, ast.Name) and t.id == "KEYS"
                           for t in targets), \
                "pipeline.py must not redefine KEYS"
    imports = [n for n in tree.body
               if isinstance(n, ast.ImportFrom)
               and n.module == "factory.core.env_loader"]
    names = [a.name for n in imports for a in n.names]
    assert "load_factory_env" in names
    from factory.core import env_loader as EL
    from factory.precard import pipeline as PI
    assert PI.load_factory_env is EL.load_factory_env


# --- supervisor probe key mapping ---

def test_probe_key_order_and_no_zen_alias(tmp_path, monkeypatch):
    """probe_key order is os.environ -> factory/.env; the removed
    ZEN_API_KEY alias is never consulted. Injection is via os.environ
    only — keys never ride CLI args or caller-built dicts."""
    factory_env = tmp_path / "factory.env"
    factory_env.write_text("OPENCODE_ZEN_API_KEY=file-v\n", encoding="utf-8")
    real = SUP.FACTORY_DOTENV
    SUP.FACTORY_DOTENV = factory_env
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY", raising=False)
    monkeypatch.delenv("ZEN_API_KEY", raising=False)
    try:
        monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "env-v")
        assert SUP.probe_key("OPENCODE_ZEN_API_KEY") == "env-v"
        monkeypatch.delenv("OPENCODE_ZEN_API_KEY")
        assert SUP.probe_key("OPENCODE_ZEN_API_KEY") == "file-v"
        # The removed ZEN_API_KEY alias is never consulted.
        monkeypatch.setenv("ZEN_API_KEY", "alias-v")
        assert SUP.probe_key("OPENCODE_ZEN_API_KEY") == "file-v"
        assert SUP.probe_key("OPENCODE_ZEN_API_KEY") != "alias-v"
    finally:
        SUP.FACTORY_DOTENV = real


def test_probe_key_never_returns_none_and_google_egress_last(
        tmp_path, monkeypatch):
    egress_env = tmp_path / "egress.env"
    egress_env.write_text("GOOGLE_AI_API_KEY=egress-v\n",
                          encoding="utf-8")
    real = SUP.FACTORY_DOTENV
    SUP.FACTORY_DOTENV = tmp_path / "missing.env"
    monkeypatch.delenv("GOOGLE_AI_API_KEY", raising=False)
    try:
        got = SUP.probe_key("GOOGLE_AI_API_KEY",
                            extra_files=(str(egress_env),))
        assert got == "egress-v"
        assert SUP.probe_key("GOOGLE_AI_API_KEY") == ""
    finally:
        SUP.FACTORY_DOTENV = real


def test_probe_key_honors_exported_env_when_no_map_given(
        tmp_path, monkeypatch):
    """Regression: the google probe call site must not pass the egress
    file dict as env_map — an exported GOOGLE_AI_API_KEY has to win
    over dotenv files (old behavior: os.environ.get)."""
    factory_env = tmp_path / "factory.env"
    factory_env.write_text("GOOGLE_AI_API_KEY=file-v\n", encoding="utf-8")
    egress_env = tmp_path / "egress.env"
    egress_env.write_text("GOOGLE_AI_API_KEY=egress-v\n",
                          encoding="utf-8")
    real = SUP.FACTORY_DOTENV
    SUP.FACTORY_DOTENV = factory_env
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "exported-v")
    try:
        assert SUP.probe_key(
            "GOOGLE_AI_API_KEY", "",
            extra_files=(str(egress_env),)) == "exported-v"
    finally:
        SUP.FACTORY_DOTENV = real
    monkeypatch.delenv("GOOGLE_AI_API_KEY")
    SUP.FACTORY_DOTENV = factory_env
    try:
        assert SUP.probe_key(
            "GOOGLE_AI_API_KEY", "",
            extra_files=(str(egress_env),)) == "file-v"
    finally:
        SUP.FACTORY_DOTENV = real


def test_supervisor_helpers_are_net_single_owner():
    """norm/target/known helpers live in factory.precard.net; the
    supervisor only re-exports them (same objects, no twin defs)."""
    assert SUP.norm_target is NET.norm_target
    assert SUP.norm_provider is NET.norm_provider
    assert SUP.target_spec is NET.target_spec
    assert SUP.known_provider is NET.known_provider


# --- reviewer P0: single AuthError class + threaded auth context ---

def test_transport_auth_helpers_are_single_llm_json_class():
    """transport.AuthError/extract_json/raise_for_auth ARE the llm_json
    objects (no rival defs): a transport-raised auth abort is caught by
    a phrase_judge-style ``except llm_json.AuthError``."""
    import ast
    import pathlib
    assert T.AuthError is LJ.AuthError
    assert T.extract_json is LJ.extract_json
    assert T.raise_for_auth is LJ.raise_for_auth
    tree = ast.parse(pathlib.Path(T.__file__).read_text(
        encoding="utf-8"))
    defs = [n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    assert "AuthError" not in defs
    assert "extract_json" not in defs
    assert "raise_for_auth" not in defs
    try:
        raise T.AuthError("probe")
    except LJ.AuthError:
        caught = True
    else:  # pragma: no cover (identity makes this unreachable)
        caught = False
    assert caught


def test_abort_auth_names_threaded_file_label_never_values():
    ring = T.KeyRing(["zz-secret-1"])
    with pytest.raises(LJ.AuthError) as exc:
        T._call_with_rotation(lambda *a: (_ for _ in ()).throw(_http(
            401)), ring, "m", "t", lambda s: None, {}, "lbl",
            key_var="GOOGLE_AI_API_KEY",
            file_label="tools/egress/.env")
    msg = str(exc.value)
    assert "401" in msg and "GOOGLE_AI_API_KEY" in msg
    assert "tools/egress/.env" in msg
    assert "zz-secret-1" not in msg
    # Default direct callers keep the standard factory env label.
    with pytest.raises(LJ.AuthError) as exc2:
        T._abort_auth(_http(403))
    assert "factory/.env" in str(exc2.value)


def test_provider_kwarg_decides_google_cooldown_vs_zen_rotate():
    """The same Google project-quota body raises ProviderCooldown with
    provider="google" (no same-project rotation) but rotates to
    RateLimited on the zen default — i.e. the wired provider, not the
    default, decides the taxonomy outcome at each production site."""
    body = b"RESOURCE_EXHAUSTED: quota exceeded"

    def fake(api_key, model, text):
        raise _http(429, body)

    with pytest.raises(T.ProviderCooldown):
        T._call_with_rotation(fake, T.KeyRing(["k1", "k2"]), "m", "t",
                              lambda s: None, {}, "lbl",
                              provider="google",
                              key_var="GOOGLE_AI_API_KEY")
    seen = []

    def fake2(api_key, model, text):
        seen.append(api_key)
        raise _http(429, body)

    with pytest.raises(T.RateLimited):
        T._call_with_rotation(fake2, T.KeyRing(["k1", "k2"]), "m", "t",
                              lambda s: None, {}, "lbl")
    assert seen == ["k1", "k2"]  # zen default rotates, never cools down


def test_judge_batch_threads_provider_to_classify():
    """judge_batch(provider="google") surfaces ProviderCooldown for a
    Google project-quota body instead of burning the ring on rotation."""
    from factory.precard import judge as J

    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = {"w:call": {"candidates": [
        {"sense_id": "call#0", "gloss": "a telephone conversation"}]}}
    calls = []

    def fake(api_key, model, text):
        calls.append(api_key)
        raise _http(429, b"RESOURCE_EXHAUSTED: quota exceeded")

    with pytest.raises(T.ProviderCooldown):
        J.judge_batch(batch, amap, "k", fake, lambda s: None, {},
                      ring=T.KeyRing(["k1", "k2"]), provider="google",
                      key_var="GOOGLE_AI_API_KEY")
    assert calls == ["k1"]  # single attempt, no rotation


def test_file_label_threads_to_auth_errors():
    """file_label (default factory/.env) reaches the AuthError message
    through judge_batch and net.call_leg — an egress-fallback key
    names the file actually searched, values never surface."""
    from factory.precard import judge as J

    def fake401(api_key, model, text):
        raise _http(401)

    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = {"w:call": {"candidates": [
        {"sense_id": "call#0", "gloss": "a telephone conversation"}]}}
    with pytest.raises(LJ.AuthError) as exc:
        J.judge_batch(batch, amap, "zz-secret-9", fake401,
                      lambda s: None, {},
                      ring=T.KeyRing(["zz-secret-9"]),
                      provider="google",
                      key_var="GOOGLE_AI_API_KEY",
                      file_label="tools/egress/.env")
    msg = str(exc.value)
    assert "GOOGLE_AI_API_KEY" in msg
    assert "tools/egress/.env" in msg
    assert "zz-secret-9" not in msg
    cfg = _cfg(keys={"zen": ["zz-secret-1"]})
    with pytest.raises(LJ.AuthError) as exc2:
        NET.call_leg(cfg, "zen", "prompt", transport=fake401, model="m",
                     sleep_fn=lambda s: None, state={},
                     file_label="custom.env")
    assert "custom.env" in str(exc2.value)
    assert "zz-secret-1" not in str(exc2.value)
    with pytest.raises(NET.MissingKeyError) as exc3:
        NET.call_leg(_cfg(), "zen", "prompt",
                     transport=lambda *a: "x", model="m",
                     file_label="custom.env")
    assert "custom.env" in str(exc3.value)


# --- P1 whitelist home: hermetic (fake pairs/rows/files, no network) ---

def _pair(sid, ms):
    return (ms, {"scheme": "vless", "host": "h-" + sid, "port": 1,
                 "id": sid})


def test_p1_build_probe_rows_top_n_order_and_dead():
    rows = NET.build_probe_rows(
        [_pair("slow", 900), _pair("fast", 120),
         _pair("dead", NET.PROBE_DEAD_MS)], top_n=1)
    assert [r["id"] for r in rows] == ["fast", "slow", "dead"]
    assert rows[0]["latency_ms"] == 120
    assert rows[0]["zen_candidate"] is True
    assert rows[1]["zen_candidate"] is False  # alive but outside top-1
    assert rows[2] == {"host": "h-dead", "port": 1, "scheme": "vless",
                       "id": "dead", "latency_ms": None, "alive": False,
                       "zen_candidate": False}


def test_p1_order_pool_by_rank_alive_first_ghost_ignored():
    servers = [{"scheme": "vless", "host": "b", "port": 1, "id": "s1"},
               {"scheme": "vless", "host": "a", "port": 1, "id": "s2"},
               {"scheme": "vless", "host": "d", "port": 1, "id": "s3"}]
    ranked = [{"id": "s2", "alive": True},
              {"id": "ghost", "alive": True},
              {"id": "s1", "alive": False},
              "junk-row"]
    ordered = NET.order_pool_by_rank(servers, ranked)
    assert [s["id"] for s in ordered] == ["s2", "s1", "s3"]


def test_p1_order_google_first_keeps_rest_in_order():
    rows = [{"id": "a", "alive": True}, {"id": "b", "alive": True},
            {"id": "c", "alive": False}, {"id": "d", "alive": True}]
    assert [r["id"] for r in NET.order_google_first(rows, ["d", "b"])] == \
        ["b", "d", "a", "c"]
    # Kept supervisor behavior: a good id that is dead drops out.
    assert [r["id"] for r in NET.order_google_first(rows, ["c"])] == \
        ["a", "b", "d"]


def test_p1_should_save_whitelist_never_empty():
    assert NET.should_save_whitelist([]) is False
    assert NET.should_save_whitelist(None) is False
    assert NET.should_save_whitelist(
        [{"id": "a", "alive": False}]) is False
    assert NET.should_save_whitelist(
        [{"id": "a", "alive": False},
         {"id": "b", "alive": True}]) is True


def test_p1_write_pool_file_single_writer(tmp_path):
    import json
    missing = tmp_path / "pool.json"
    assert NET.write_pool_file(str(missing), []) == 0
    assert not missing.exists()  # empty probe touches nothing
    assert NET.write_pool_file(str(missing), [{"id": ""}]) == 0
    assert not missing.exists()
    servers = [{"scheme": "vless", "host": "h", "port": 1, "id": "s1",
                "link": "vless://SECRET-creds@h:1"}]
    assert NET.write_pool_file(str(missing), servers) == 1
    payload = json.loads(missing.read_text(encoding="utf-8"))
    assert set(payload) == {"saved_at", "servers"}
    assert payload["servers"] == [{"scheme": "vless", "host": "h",
                                   "port": 1, "id": "s1"}]
    assert "SECRET" not in missing.read_text(encoding="utf-8")


def test_p1_pool_save_delegates_and_never_overwrites_empty(tmp_path):
    pool = SUP.Pool()
    ghost = str(tmp_path / "ghost.json")
    pool.save_pool(ghost)  # empty pool: single writer refuses, no file
    assert not (tmp_path / "ghost.json").exists()
    pool.load([{"scheme": "vless", "host": "h", "port": 1, "id": "s1",
                "link": "vless://SECRET@h:1"}])
    path = str(tmp_path / "pool.json")
    pool.save_pool(path)
    import json
    payload = json.loads(
        (tmp_path / "pool.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in payload["servers"]] == ["s1"]
    assert "SECRET" not in (tmp_path / "pool.json").read_text(
        encoding="utf-8")
    pool2 = SUP.Pool()
    assert pool2.load_pool(path) == 1


def test_p1_pool_load_ranked_uses_home_order():
    pool = SUP.Pool()
    pool.load([
        {"scheme": "vless", "host": "slow", "port": 1, "id": "s1"},
        {"scheme": "vless", "host": "fast", "port": 1, "id": "s2"},
    ])
    pool.load_ranked([{"id": "s2", "alive": True},
                      {"id": "ghost", "alive": True}])
    assert [s["id"] for s in pool.servers] == ["s2", "s1"]


def test_p1_supervisor_health_healthy_flag():
    assert NET.supervisor_health([], {}) == {
        "ok": True, "servers": 0, "leases": 0, "healthy": False}
    got = NET.supervisor_health([{"id": "s1"}], {"l1": {}})
    assert got == {"ok": True, "servers": 1, "leases": 1,
                   "healthy": True}
    pool = SUP.Pool()
    assert pool.health()["healthy"] is False
    assert pool.health()["ok"] is True  # old shape preserved
    pool.load([{"scheme": "vless", "host": "h", "port": 1, "id": "s1"}])
    assert pool.health()["healthy"] is True


def test_p1_cooldown_parity_per_provider():
    """Retire parity: supervisor Pool and NetConfig isolate providers
    identically (zen-429 never cools google on the same server)."""
    cfg = _cfg()
    NET.cool(cfg, "s1", "zen")
    assert NET.is_cool(cfg, "s1", "zen") is True
    assert NET.is_cool(cfg, "s1", "google") is False
    pool = SUP.Pool()
    pool.cool("s1", "zen", seconds=60)
    assert pool.is_cool("s1", "zen") is True
    assert pool.is_cool("s1", "google") is False
    assert pool.is_cool("s1", "zen", now=10 ** 12) is False


def test_p1_build_probe_rows_skips_malformed():
    """Reviewer hardening: junk pairs never raise — only clean server
    dicts become rows, ranked as usual."""
    ranked = [_pair("fast", 120),
              "junk-row",
              ("not-a-pair",),
              (50, "not-a-dict"),
              (60, {"scheme": "vless", "host": "h", "port": 1}),  # no id
              (70, {"scheme": "vless", "host": "h", "id": "x"}),  # no port
              _pair("slow", 900)]
    rows = NET.build_probe_rows(ranked, top_n=5)
    assert [r["id"] for r in rows] == ["fast", "slow"]
    assert NET.build_probe_rows(None, top_n=1) == []


def test_p1_order_pool_by_rank_skips_malformed_servers():
    """Reviewer hardening: non-dict/id-less pool entries are dropped
    from the output instead of raising KeyError."""
    servers = [{"scheme": "vless", "host": "a", "port": 1, "id": "s1"},
               "junk-server",
               {"scheme": "vless", "host": "b", "port": 1},  # no id
               {"scheme": "vless", "host": "c", "port": 1, "id": "s2"}]
    ordered = NET.order_pool_by_rank(
        servers, [{"id": "s2", "alive": True}])
    assert [s["id"] for s in ordered] == ["s2", "s1"]


def test_p1_order_google_first_skips_malformed_rows():
    """Reviewer hardening: non-dict rows never raise; clean rows keep
    the moved google-first order."""
    rows = [{"id": "a", "alive": True}, "junk-row",
            {"id": "b", "alive": True}, {"id": "c", "alive": False}]
    assert [r["id"] for r in NET.order_google_first(rows, ["b"])] == \
        ["b", "a", "c"]


def test_p1_write_pool_file_atomic_keeps_old_on_failure(tmp_path):
    """Reviewer hardening: a failed write never truncates the good
    file (tmp + os.replace) and leaves no .tmp behind."""
    from unittest import mock
    path = tmp_path / "pool.json"
    servers = [{"scheme": "vless", "host": "h", "port": 1, "id": "s1"}]
    assert NET.write_pool_file(str(path), servers) == 1
    before = path.read_text(encoding="utf-8")
    assert not (tmp_path / "pool.json.tmp").exists()  # no tmp leftover
    with mock.patch.object(NET.json, "dump",
                           side_effect=OSError("boom")):
        with pytest.raises(OSError):
            NET.write_pool_file(str(path), servers)
    assert path.read_text(encoding="utf-8") == before  # old file intact
    assert not (tmp_path / "pool.json.tmp").exists()


def test_p1_supervisor_calls_home_functions():
    """Supervisor holds zero probe logic: the moved names are the home
    objects (same function, no twin defs)."""
    assert SUP.build_probe_rows is NET.build_probe_rows
    assert SUP.order_pool_by_rank is NET.order_pool_by_rank
    assert SUP.order_google_first is NET.order_google_first
    assert SUP.should_save_whitelist is NET.should_save_whitelist
    assert SUP.write_pool_file is NET.write_pool_file
    assert SUP.supervisor_health is NET.supervisor_health
