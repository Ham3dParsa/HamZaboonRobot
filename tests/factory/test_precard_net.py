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


# --- P2 LEG_FALLBACKS single table (R5/R6, hermetic) ---

def test_p2_table_keys_shape_and_costs():
    legs = ("inflection_review", "sense_judge", "topic_vectors",
            "topic_label")
    assert set(NET.LEG_FALLBACKS) == {
        (provider, leg)
        for provider in ("zen", "avalai", "google") for leg in legs}
    for (provider, leg), entries in NET.LEG_FALLBACKS.items():
        assert entries, "empty chain for %r" % ((provider, leg),)
        for entry_model, cost in entries:
            assert isinstance(entry_model, str) and entry_model
            assert cost in ("free", "paid"), cost
    # Frozen literals (not derived from the module): the zen
    # judge/inflection legs keep the historic Muse-only pair while
    # vectors/label keep the full five. A silent reorder/rename of
    # JUDGE_MODELS must fail here, not slide through.
    frozen_pair = ["muse-spark-1.3-contributor-free",
                   "muse-spark-1.2-contributor-free"]
    frozen_five = frozen_pair + ["ling-3.0-flash-fin-free",
                                 "mimo-v2.5-free",
                                 "nemotron-3.5-lightning-free"]
    assert NET.JUDGE_MODELS == frozen_five
    assert [m for m, _ in NET.LEG_FALLBACKS[
        ("zen", "sense_judge")]] == frozen_pair
    assert [m for m, _ in NET.LEG_FALLBACKS[
        ("zen", "inflection_review")]] == frozen_pair
    assert [m for m, _ in NET.LEG_FALLBACKS[
        ("zen", "topic_vectors")]] == frozen_five
    assert [m for m, _ in NET.LEG_FALLBACKS[
        ("zen", "topic_label")]] == frozen_five
    assert all(cost == "free" for _, cost in NET.LEG_FALLBACKS[
        ("zen", "sense_judge")])
    # AvalAI/Google legs are single paid defaults.
    assert NET.LEG_FALLBACKS[("avalai", "sense_judge")] == (
        (T.AVALAI_PRECARD_MODEL, "paid"),)
    assert NET.LEG_FALLBACKS[("google", "sense_judge")] == (
        (T.GOOGLE_PRECARD_MODEL, "paid"),)
    assert NET.leg_chain("avalai", "topic_label") == [
        T.AVALAI_PRECARD_MODEL]
    assert NET.leg_chain("google", "topic_vectors") == [
        T.GOOGLE_PRECARD_MODEL]
    assert NET.leg_chain("bogus", "sense_judge") == []


def test_p2_consts_moved_single_owner_legs_hold_zero_lists():
    """JUDGE_MODELS + precard/avalai/google consts live in net; the
    legs import them (same objects, no twin defs, no list literals)."""
    import ast
    import pathlib
    from factory.precard import judge as J
    assert J.JUDGE_MODELS is NET.JUDGE_MODELS
    assert T.AVALAI_PRECARD_MODEL is NET.AVALAI_PRECARD_MODEL
    assert T.AVALAI_CHAT_URL is NET.AVALAI_CHAT_URL
    assert T.GOOGLE_PRECARD_MODEL is NET.GOOGLE_PRECARD_MODEL
    assert T.GOOGLE_MODELS_URL is NET.GOOGLE_MODELS_URL
    moved = {"JUDGE_MODELS", "V15_MODELS", "TOPUP_MODELS",
             "INFLECTION_REVIEW_MODELS", "AVALAI_PRECARD_MODEL",
             "AVALAI_CHAT_URL", "GOOGLE_PRECARD_MODEL",
             "GOOGLE_MODELS_URL"}
    for name in ("judge.py", "topics.py"):
        tree = ast.parse(pathlib.Path(
            NET.__file__).parent.joinpath(name).read_text(
                encoding="utf-8"))
        defined = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                for target in targets:
                    if isinstance(target, ast.Name):
                        defined.add(target.id)
        assert not (defined & moved), \
            "%s still defines %s" % (name, defined & moved)


def test_p2_switch_policy_and_target_routing():
    assert NET.may_auto_switch("zen") is True
    assert NET.may_auto_switch("avalai") is False
    assert NET.may_auto_switch("google") is False
    assert NET.target_for("zen") == "zen"
    assert NET.target_for("avalai") == "avalai"
    assert NET.target_for("google") == "google"
    assert NET.target_for("bogus") == "zen"


def test_p2_switch_plan_order_and_paid_stop():
    """R6 provider order lives in one helper: free legs try self then
    the rest of SWITCH_ORDER that own the step; paid legs try only
    themselves (a cooldown stops for a resume)."""
    assert NET.switch_plan("zen", "sense_judge") == [
        "zen", "google", "avalai"]
    assert NET.switch_plan("google", "sense_judge") == ["google"]
    assert NET.switch_plan("avalai", "topic_label") == ["avalai"]
    assert NET.switch_plan("zen", "topic_vectors") == [
        "zen", "google", "avalai"]


def test_p2_switch_plan_unknown_step_is_programmer_error():
    cfg = _cfg(keys={"zen": ["k1"]})
    with pytest.raises(ValueError):
        NET.switch_plan("zen", "bogus")


def test_p2_leg_free_cooldown_switches_provider_with_own_keys():
    """R6 in the production path (finding A+B): a free leg cooled on
    zen continues on google's chain, and the google attempt presents
    GOOGLE's key — never zen's. z2 is skipped (same-project rotation
    is forbidden on a cooldown)."""
    from factory.precard import judge as J
    z1 = NET.JUDGE_MODELS[0]
    gmodel = T.GOOGLE_PRECARD_MODEL
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = {"w:call": {"candidates": [
        {"sense_id": "call#0", "gloss": "a telephone conversation"}]}}
    seen = []

    def fake(api_key, model, text):
        seen.append((api_key, model))
        if model in NET.leg_chain("zen", "sense_judge"):
            raise T.ProviderCooldown("project blocked")
        return ('{"results": [{"key": "w:call", '
                '"picks": ["call#0"]}]}'), None

    zen_ring = T.KeyRing(["zk1", "zk2"])
    tele, tried = [], []
    out = J.judge_batch(batch, amap, "zk1", fake, lambda s: None, {},
                        telemetry=tele, tele_batch=1, provider="zen",
                        ring=zen_ring,
                        rings={"zen": zen_ring,
                               "google": T.KeyRing(["gk1"])},
                        tried=tried)
    assert out["w:call"]["sense_id"] == "call#0"
    assert out["w:call"]["model"] == gmodel
    assert seen == [("zk1", z1), ("gk1", gmodel)]
    assert tried == [z1, gmodel]
    assert [(r["model"], r["provider"], r["outcome"]) for r in tele] == [
        (z1, "zen", "error"), (gmodel, "google", "ok")]


def test_p2_leg_paid_cooldown_stops_no_switch():
    """Paid legs never auto-switch in the production path either:
    google project quota stops after one attempt for a resume."""
    from factory.precard import judge as J
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = {"w:call": {"candidates": [
        {"sense_id": "call#0", "gloss": "a telephone conversation"}]}}
    seen = []

    def fake(api_key, model, text):
        seen.append((api_key, model))
        raise T.ProviderCooldown("project blocked")

    with pytest.raises(T.ProviderCooldown):
        J.judge_batch(batch, amap, "gk1", fake, lambda s: None, {},
                      provider="google",
                      ring=T.KeyRing(["gk1"]),
                      rings={"google": T.KeyRing(["gk1"])})
    assert seen == [("gk1", T.GOOGLE_PRECARD_MODEL)]  # no rotation/switch


def test_p2_inflection_review_429_rotates_keys():
    """Finding C: inflection attempts route through net.call_leg, so a
    429 rotates to the next key on the SAME model (the old raw
    transport call never rotated)."""
    from factory.precard import judge as J
    m1 = NET.JUDGE_MODELS[0]
    items = [{"key": "k1", "text": "w", "gloss": "g"}]
    seen = []
    calls = {"n": 0}

    def fake(api_key, model, *texts):
        seen.append((api_key, model))
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http(429)
        return ('{"results": [{"key": "k1", "keep": true, '
                '"reason": "ok"}]}'), None

    out = J.inflection_review(items, fake, "k",
                              ring=T.KeyRing(["k1", "k2"]),
                              sleep_fn=lambda s: None, state={})
    assert out["k1"] == {"keep": True, "reason": "ok", "model": m1,
                         "uncertain": False}
    assert seen == [("k1", m1), ("k2", m1)]


def test_p2_judge_batch_steps_down_on_429():
    """Leg level: model-1 429 (all keys) settles on model 2; tried
    records both; telemetry keeps the per-model error + ok rows."""
    from factory.precard import judge as J
    m1, m2 = NET.JUDGE_MODELS[0], NET.JUDGE_MODELS[1]
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = {"w:call": {"candidates": [
        {"sense_id": "call#0", "gloss": "a telephone conversation"}]}}
    seen = []

    def fake(api_key, model, text):
        seen.append((api_key, model))
        if model == m1:
            raise _http(429)
        return ('{"results": [{"key": "w:call", '
                '"picks": ["call#0"]}]}'), None

    tele, tried = [], []
    out = J.judge_batch(batch, amap, "k", fake, lambda s: None, {},
                        telemetry=tele, tele_batch=1,
                        ring=T.KeyRing(["k1", "k2"]), tried=tried)
    assert out["w:call"]["sense_id"] == "call#0"
    assert out["w:call"]["model"] == m2
    assert tried == [m1, m2]
    assert [r["model"] for r in tele] == [m1, m2]


def test_p2_judge_batch_401_single_attempt():
    from factory.precard import judge as J
    seen = []

    def fake(api_key, model, text):
        seen.append((api_key, model))
        raise _http(401)

    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = {"w:call": {"candidates": [
        {"sense_id": "call#0", "gloss": "a telephone conversation"}]}}
    with pytest.raises(LJ.AuthError):
        J.judge_batch(batch, amap, "k", fake, lambda s: None, {},
                      ring=T.KeyRing(["k1", "k2"]))
    assert len(seen) == 1  # STOP, no second call


def test_p2_judge_batch_chain_exhaustion_raises():
    from factory.precard import judge as J
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = {"w:call": {"candidates": [
        {"sense_id": "call#0", "gloss": "a telephone conversation"}]}}

    def fake(api_key, model, text):
        raise _http(429)

    with pytest.raises(T.RateLimited):
        J.judge_batch(batch, amap, "k", fake, lambda s: None, {},
                      ring=T.KeyRing(["k1"]))
    # A validation failure (not ROTATE) still fails closed to the s1
    # pick instead of stepping down or raising.
    out = J.judge_batch(
        batch, amap, "k", lambda *a: ("not json", None),
        lambda s: None, {}, ring=T.KeyRing(["k1"]))
    assert out["w:call"]["model"] == "s1-fallback"


def test_p2_vectors_batch_steps_down_on_429():
    """Vectors leg: model-1 429 settles on model 2 with tried recorded."""
    from factory.precard import topics as TOP
    m1, m2 = NET.JUDGE_MODELS[0], NET.JUDGE_MODELS[1]
    lab = TOP.V15_ID2LABEL[1]
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    jmap = {"w:call": {"sense_id": "call#0", "gloss": "a call"}}
    amap = {"w:call": {"candidates": [
        {"sense_id": "call#0", "gloss": "a call"}]}}
    seen = []

    def fake(api_key, model, text):
        seen.append((api_key, model))
        if model == m1:
            raise _http(429)
        return ('{"results": [{"lemma": "call", "vectors": ['
                '{"sense_id": "call#0", "vector": [{"topic_id": 1, '
                '"topic_label": "%s", "weight": 1.0}]}]}]}' % lab), None

    tried = []
    out = TOP.vectors_batch(batch, jmap, amap, "k", fake,
                            lambda s: None, {}, ring=T.KeyRing(
                                ["k1", "k2"]), tried=tried)
    assert out["call#0"]["model"] == m2
    assert tried == [m1, m2]


def test_p2_inflection_review_default_chain_from_table():
    """Inflection leg defaults to the table pair: garbage on model 1
    steps down to model 2 (2 attempts each); tried records both."""
    from factory.precard import judge as J
    m1, m2 = NET.JUDGE_MODELS[0], NET.JUDGE_MODELS[1]
    items = [{"key": "k1", "text": "w", "gloss": "g"}]
    seen = []

    def fake(api_key, model, *texts):
        seen.append(model)
        if model == m1:
            return "not json", None
        return ('{"results": [{"key": "k1", "keep": true, '
                '"reason": "ok"}]}'), None

    tried = []
    out = J.inflection_review(items, fake, "k", tried=tried)
    assert out["k1"] == {"keep": True, "reason": "ok", "model": m2,
                         "uncertain": False}
    assert tried == [m1, m2]
    assert seen == [m1, m1, m2]


# --- PR-C clean-cache + direct-first (R7/R8, hermetic) ---

def _cache_entry(sid, provider="zen", age_s=0, ms=50, now=1000.0):
    return {"server_id": sid, "provider": provider,
            "last_ok_ts": now - age_s, "latency_ms": ms}


def test_c3_cache_hit_picks_cached_not_first_avail():
    """Fresh cached row wins behind one ping: s2 leased, s1 untouched."""
    cfg = _cfg()
    cache = [_cache_entry("s2", ms=10)]
    calls = []

    def _ping(server):
        calls.append(server["id"])
        return 10

    lease = NET.lease_for(cfg, "zen", clean_cache=cache,
                          ping_fn=_ping, now=1000.0)
    assert lease["server_id"] == "s2" and lease["cache_hit"] is True
    assert calls == ["s2"]  # one real-ping gate, no full scan


def test_c3_stale_entry_misses_without_ping():
    """Expired rows are a MISS: no ping, classic first-avail fallback."""
    cfg = _cfg()
    cache = [_cache_entry("s1", age_s=90000, ms=5)]
    calls = []

    def _ping(server):  # pragma: no cover (must never run)
        calls.append(server["id"])
        return 5

    lease = NET.lease_for(cfg, "zen", clean_cache=cache,
                          ping_fn=_ping, now=1000.0)
    assert lease["server_id"] == "s1" and lease["cache_hit"] is False
    assert calls == []


def test_c3_cooling_cached_row_skipped_for_next_fresh():
    """Cooling cached rows are skipped even when fresh (per-provider)."""
    cfg = _cfg()
    NET.cool(cfg, "s1", "zen")
    cache = [_cache_entry("s1", ms=5), _cache_entry("s2", ms=50)]
    calls = []

    def _ping(server):
        calls.append(server["id"])
        return 50

    lease = NET.lease_for(cfg, "zen", clean_cache=cache,
                          ping_fn=_ping, now=1000.0)
    assert lease["server_id"] == "s2" and lease["cache_hit"] is True
    assert calls == ["s2"]


def test_c3_ping_dead_falls_back_to_full_probe():
    """Ping-dead cached rows fall through to the first-avail pick."""
    cfg = _cfg()
    cache = [_cache_entry("s2", ms=10)]

    def _ping(server):
        return None

    lease = NET.lease_for(cfg, "zen", clean_cache=cache,
                          ping_fn=_ping, now=1000.0)
    assert lease["server_id"] == "s1" and lease["cache_hit"] is False


def test_c3_empty_probe_never_clobbers_cache(tmp_path):
    """save refuses empty (0, touches nothing); load tolerates
    missing/corrupt; only the four cache keys persist."""
    import json
    missing = tmp_path / "clean_cache.json"
    assert NET.save_clean_cache(str(missing), []) == 0
    assert not missing.exists()
    assert NET.load_clean_cache(str(missing)) == []
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert NET.load_clean_cache(str(corrupt)) == []
    dirty = [{"server_id": "s1", "provider": "zen",
              "last_ok_ts": 1000.0, "latency_ms": 12,
              "link": "vless://SECRET@h:1", "key": "SECRET-KEY"}]
    assert NET.save_clean_cache(str(missing), dirty) == 1
    payload = json.loads(missing.read_text(encoding="utf-8"))
    assert set(payload["entries"][0]) == {
        "server_id", "provider", "last_ok_ts", "latency_ms"}
    assert "SECRET" not in missing.read_text(encoding="utf-8")
    assert NET.load_clean_cache(str(missing)) == [
        {"server_id": "s1", "provider": "zen",
         "last_ok_ts": 1000.0, "latency_ms": 12}]


def test_c3_writeback_upserts_and_roundtrips(tmp_path):
    """record_clean_success upserts (fresh ts, moves to end); the file
    round-trips through the single writer."""
    rows = NET.record_clean_success(
        [_cache_entry("s1", ms=90)], "s2", "zen", 12, 2000.0)
    assert rows[-1] == {"server_id": "s2", "provider": "zen",
                        "last_ok_ts": 2000.0, "latency_ms": 12}
    rows2 = NET.record_clean_success(rows, "s1", "zen", 7, 2000.0)
    assert rows2[-1]["server_id"] == "s1"
    assert len(rows2) == 2  # upsert, not duplicate
    path = str(tmp_path / "clean_cache.json")
    assert NET.save_clean_cache(path, rows2) == 2
    assert [e["server_id"] for e in NET.load_clean_cache(path)] == [
        "s2", "s1"]


def test_c3_direct_ok_takes_zero_lease():
    """R8: direct ping ok => leaseless (no lease minted) + telemetry."""
    cfg = _cfg()
    before = len(cfg._leases)
    event = NET.direct_probe_event(True, "avalai")
    assert event == {"event": "direct-probe", "provider": "avalai",
                     "outcome": "direct-ok", "lease_taken": False}
    assert len(cfg._leases) == before  # caller mints nothing on ok


def test_c3_direct_fail_falls_back_to_lease_with_telemetry():
    """R8: direct ping fail => lease fallback (direct lease) + event."""
    cfg = _cfg()
    event = NET.direct_probe_event(False, "avalai")
    assert event["outcome"] == "lease-fallback"
    assert event["lease_taken"] is True
    lease = NET.lease_for(cfg, "avalai")
    assert lease["mode"] == "direct" and lease["cache_hit"] is False


def test_c3_cache_console_lines_and_run_printer(capsys):
    """Single-owner HIT/MISS text; the run entry only prints it."""
    from factory import run as RUN
    assert "CACHE HIT" in NET.format_cache_line(True, "s1", "zen")
    assert "s1" in NET.format_cache_line(True, "s1", "zen")
    assert "CACHE MISS" in NET.format_cache_line(False, "", "zen")
    RUN.print_cache_line(True, "s1", "zen")
    RUN.print_cache_line(False, "", "zen")
    out = capsys.readouterr().out
    assert "CACHE HIT" in out and "CACHE MISS" in out
    assert RUN.direct_probe_telemetry(True)["outcome"] == "direct-ok"
    assert RUN.direct_probe_telemetry(
        False)["lease_taken"] is True


def test_c3_supervisor_reexports_cache_home():
    """Supervisor holds zero cache logic: same objects + pool-side
    path; the write-back hook never raises and never clobbers."""
    import pathlib
    assert SUP.load_clean_cache is NET.load_clean_cache
    assert SUP.save_clean_cache is NET.save_clean_cache
    assert SUP.clean_cache_candidates is NET.clean_cache_candidates
    assert SUP.record_clean_success is NET.record_clean_success
    assert SUP.direct_probe_event is NET.direct_probe_event
    assert SUP.format_cache_line is NET.format_cache_line
    assert SUP.CLEAN_CACHE_PATH.name == "clean_cache.json"
    assert SUP.CLEAN_CACHE_PATH.parent == SUP.POOL_PATH.parent
    assert NET.default_clean_cache_path(str(SUP.POOL_PATH)) == str(
        SUP.CLEAN_CACHE_PATH)
    assert pathlib.Path(
        NET.default_clean_cache_path("/x/egress_pool.json")).name == \
        "clean_cache.json"


def test_c3_supervisor_writeback_hook(tmp_path):
    """note_clean_success writes back; empty/I-O-failed upkeep never
    raises and never creates a file (programming errors propagate)."""
    import json
    path = tmp_path / "clean_cache.json"
    SUP.note_clean_success("s1", "zen", 12, now=2000.0,
                           path=str(path))
    assert json.loads(path.read_text(encoding="utf-8"))[
        "entries"][-1]["server_id"] == "s1"
    ghost = tmp_path / "ghost.json"
    SUP.note_clean_success("", "zen", 12, now=2000.0,
                           path=str(ghost))
    assert not ghost.exists()


def test_c3_run_flags_clean_ttl_and_direct_probe():
    """R3: CLI > env > code for --clean-ttl/--direct-probe; bad ttl
    exits 2; keys never become flags."""
    from factory import run as RUN
    assert "clean_ttl" in RUN.FLAG_ENVS
    assert RUN.FLAG_ENVS["clean_ttl"] == "EGRESS_CLEAN_TTL"
    assert RUN.FLAG_ENVS["direct_probe"] == "AVALAI_DIRECT_FIRST"
    ns = RUN.parse_args([])
    assert hasattr(ns, "clean_ttl") and hasattr(ns, "direct_probe")
    cfg, sources = RUN.resolve_config(ns, {})
    assert cfg["clean_ttl"] == NET.CLEAN_CACHE_TTL_S
    assert cfg["direct_probe"] is False
    cfg2, sources2 = RUN.resolve_config(
        ns, {"EGRESS_CLEAN_TTL": "3600",
             "AVALAI_DIRECT_FIRST": "1"})
    assert cfg2["clean_ttl"] == 3600.0 and sources2["clean_ttl"] == "env"
    assert cfg2["direct_probe"] is True
    ns_cli = RUN.parse_args(["--clean-ttl", "60", "--direct-probe"])
    cfg3, _ = RUN.resolve_config(ns_cli, {"EGRESS_CLEAN_TTL": "3600"})
    assert cfg3["clean_ttl"] == 60.0
    assert cfg3["direct_probe"] is True
    import pytest as _pytest
    with _pytest.raises(SystemExit):
        RUN.resolve_config(ns, {"EGRESS_CLEAN_TTL": "0"})
    with _pytest.raises(SystemExit):
        RUN.resolve_config(ns, {"EGRESS_CLEAN_TTL": "abc"})
    src = open(RUN.__file__, encoding="utf-8").read()
    assert "AVALAI_API_KEY" not in src
    assert "CLEAN_CACHE_TTL_S" in src  # code default cited, not moved


# --- OC-bot blocking fixes (PR 717 re-review): ping outside the pool
# lock, finite TTL, symmetric write normalization, narrow write-back ---

def test_c3_ping_runs_outside_pool_lock():
    """W1: a second thread takes cfg._lock while ping_fn runs (a
    slow/hung ping must never serialize lease callers)."""
    import threading
    cfg = _cfg()
    cache = [_cache_entry("s2", ms=10)]
    entered = threading.Event()
    lock_free = []

    def _ping(server):
        entered.set()

        def _take():
            with cfg._lock:
                lock_free.append(True)

        worker = threading.Thread(target=_take, daemon=True)
        worker.start()
        worker.join(timeout=5.0)
        return 10

    lease = NET.lease_for(cfg, "zen", clean_cache=cache,
                          ping_fn=_ping, now=1000.0)
    assert entered.is_set()
    assert lease["server_id"] == "s2" and lease["cache_hit"] is True
    assert lock_free == [True]  # lock was free during the ping


def test_c3_ping_gets_snapshot_not_live_pool_row():
    """W1: ping_fn mutating its arg must not corrupt the pool."""
    cfg = _cfg()
    cache = [_cache_entry("s2", ms=10)]
    seen = []

    def _ping(server):
        seen.append(server)
        server["host"] = "MUTATED"
        return 10

    lease = NET.lease_for(cfg, "zen", clean_cache=cache,
                          ping_fn=_ping, now=1000.0)
    assert lease["server_id"] == "s2" and lease["cache_hit"] is True
    assert seen[0] is not cfg.servers[1]
    assert cfg.servers[1]["host"] == "h2"


def test_c3_nonfinite_ttl_falls_back_to_default():
    """W2: inf/nan/garbage/non-positive TTL never hangs the lib path:
    the default window applies and fresh rows still hit."""
    cfg = _cfg()
    cache = [_cache_entry("s2", ms=10)]
    for bad in ("inf", float("inf"), float("nan"), "nan",
                "garbage", 0, -5, object()):
        lease = NET.lease_for(cfg, "zen", clean_cache=cache,
                              clean_ttl=bad,
                              ping_fn=lambda s: 10, now=1000.0)
        assert lease["server_id"] == "s2" \
            and lease["cache_hit"] is True


def test_c3_nan_last_ok_row_is_stale():
    """W2: a NaN last_ok_ts row is stale (never fresh via NaN math)."""
    rows = NET.clean_cache_candidates(
        [{"server_id": "s1", "provider": "zen",
          "last_ok_ts": float("nan"), "latency_ms": 5}],
        "zen", 1000.0, 86400.0)
    assert rows == []


def test_c3_inf_ttl_uses_default_window():
    """W2: an inf TTL falls back to the default (fresh rows return)."""
    rows = NET.clean_cache_candidates(
        [_cache_entry("s1", age_s=1000)], "zen", 1000.0, float("inf"))
    assert [r["server_id"] for r in rows] == ["s1"]


def test_c3_run_rejects_nonfinite_clean_ttl():
    """W2: --clean-ttl/EGRESS_CLEAN_TTL inf/nan exits 2."""
    from factory import run as RUN
    import pytest as _pytest
    ns = RUN.parse_args([])
    for bad in ("inf", "nan"):
        with _pytest.raises(SystemExit):
            RUN.resolve_config(ns, {"EGRESS_CLEAN_TTL": bad})
    ns_cli = RUN.parse_args(["--clean-ttl", "inf"])
    with _pytest.raises(SystemExit):
        RUN.resolve_config(ns_cli, {})


def test_c3_save_normalizes_latency_like_load(tmp_path):
    """W3: the writer emits int/None latency (mirror load); junk
    latency becomes None instead of a non-serializable payload."""
    path = str(tmp_path / "clean_cache.json")
    rows = [{"server_id": "s1", "provider": "zen",
             "last_ok_ts": 1000.0, "latency_ms": "12"},
            {"server_id": "s2", "provider": "zen",
             "last_ok_ts": 1000.0, "latency_ms": object()},
            {"server_id": "s3", "provider": "zen",
             "last_ok_ts": float("nan"), "latency_ms": 12.9}]
    assert NET.save_clean_cache(path, rows) == 3
    loaded = NET.load_clean_cache(path)
    assert [e["latency_ms"] for e in loaded] == [12, None, 12]
    assert [e["last_ok_ts"] for e in loaded] == [1000.0, 1000.0, 0.0]


def test_c3_save_cleans_tmp_and_raises_on_unserializable(tmp_path):
    """W3: a failed write removes path.tmp and still raises."""
    import pytest as _pytest
    path = tmp_path / "clean_cache.json"
    rows = [{"server_id": {"unserializable", 1}, "provider": "zen",
             "last_ok_ts": 1000.0, "latency_ms": 5}]
    with _pytest.raises(TypeError):
        NET.save_clean_cache(str(path), rows)
    assert not path.exists()
    assert not (tmp_path / "clean_cache.json.tmp").exists()


def test_c3_writeback_best_effort_types(tmp_path, monkeypatch):
    """Unserializable payload (TypeError) is swallowed after tmp
    cleanup — the lease stands. Real programming errors
    (AttributeError) still surface."""
    import pytest as _pytest
    path = tmp_path / "clean_cache.json"
    SUP.note_clean_success(object(), "zen", 12, now=2000.0,
                           path=str(path))
    assert not path.exists()

    def _boom(p, entries):
        raise AttributeError("boom")

    monkeypatch.setattr(SUP, "save_clean_cache", _boom)
    with _pytest.raises(AttributeError):
        SUP.note_clean_success("s1", "zen", 12, now=2000.0,
                               path=str(path))


# --- Phase-03 W1/W2 production wiring: supervisor Pool.lease is the
# ONE production caller of the cache seam (load -> lease_for with
# tcp_ping + ttl -> note_clean_success), hermetic via a tmp cache
# file (env knob) + a fake ping. No network, no keys, no W: drive. ---

def _c4_link_pool():
    pool = SUP.Pool()
    pool.load([
        {"scheme": "vless", "host": "h1", "port": 1, "id": "s1",
         "link": "vless://u@h1:1"},
        {"scheme": "vless", "host": "h2", "port": 2, "id": "s2",
         "link": "vless://u@h2:2"},
    ])
    return pool


def _c4_cache_file(tmp_path, monkeypatch, rows):
    import json
    import time as _time
    path = tmp_path / "clean_cache.json"
    payload = {"saved_at": "test",
               "entries": [dict(r) for r in rows]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv(SUP.CLEAN_CACHE_PATH_VAR, str(path))
    monkeypatch.delenv(SUP.CLEAN_TTL_VAR, raising=False)
    return path


def _c4_fresh_row(server_id, provider="zen", age_s=10, ms=7):
    import time as _time
    return {"server_id": server_id, "provider": provider,
            "last_ok_ts": _time.time() - age_s, "latency_ms": ms}


def test_c3_supervisor_lease_cache_hit_skips_scan(
        tmp_path, monkeypatch, capsys):
    """W2: a fresh cached row + reachable ping mints that server
    (not first-avail), prints CACHE HIT, and writes back the
    measured latency."""
    import json
    path = _c4_cache_file(tmp_path, monkeypatch,
                          [_c4_fresh_row("s2", ms=7)])
    seen = []
    monkeypatch.setattr(
        SUP, "tcp_ping",
        lambda h, p, timeout=5.0: seen.append((h, p)) or (
            42 if h == "h2" else None))
    pool = _c4_link_pool()
    lease = pool.lease("zen")
    assert lease["mode"] == "tunnel" and lease["server_id"] == "s2"
    assert ("h2", 2) in seen and ("h1", 1) not in seen
    out = capsys.readouterr().out
    assert "CACHE HIT" in out and "s2" in out
    saved = json.loads(path.read_text(encoding="utf-8"))["entries"]
    back = [e for e in saved if e["server_id"] == "s2"]
    assert len(back) == 1 and back[0]["latency_ms"] == 42


def test_c3_supervisor_lease_miss_takes_first_avail(
        tmp_path, monkeypatch, capsys):
    """W2: no cache file -> classic first-avail pick, CACHE MISS
    line, and nothing is written back (lease is not success: the
    minted server was never probe-verified)."""
    import json
    path = tmp_path / "clean_cache.json"
    assert not path.exists()
    monkeypatch.setenv(SUP.CLEAN_CACHE_PATH_VAR, str(path))
    monkeypatch.delenv(SUP.CLEAN_TTL_VAR, raising=False)
    calls = []
    monkeypatch.setattr(
        SUP, "tcp_ping",
        lambda h, p, timeout=5.0: calls.append((h, p)) or 99)
    pool = _c4_link_pool()
    lease = pool.lease("zen")
    assert lease["server_id"] == "s1"  # first-avail, no ping needed
    assert calls == []
    assert "CACHE MISS" in capsys.readouterr().out
    assert not path.exists()


def test_c3_supervisor_lease_ping_budget_capped(
        tmp_path, monkeypatch, capsys):
    """W2 probe budget: 5 fresh rows but only the first 3 fastest are
    pinged with the 2s lease timeout; all dead -> classic first-avail
    pick, MISS, and the cache file is untouched."""
    pool = SUP.Pool()
    pool.load([{"scheme": "vless", "host": "h%d" % i, "port": i,
                "id": "s%d" % i, "link": "vless://u@h%d:%d" % (i, i)}
               for i in (1, 2, 3, 4, 5)])
    rows = [_c4_fresh_row("s%d" % i, ms=i) for i in (1, 2, 3, 4, 5)]
    path = _c4_cache_file(tmp_path, monkeypatch, rows)
    before = path.read_bytes()
    probed = []

    def _dead(h, p, timeout=5.0):
        probed.append((h, p, timeout))
        return None

    monkeypatch.setattr(SUP, "tcp_ping", _dead)
    lease = pool.lease("zen")
    assert lease["server_id"] == "s1"  # classic first-avail
    assert [h for h, _, _ in probed] == ["h1", "h2", "h3"]
    assert {t for _, _, t in probed} == {SUP.LEASE_PING_TIMEOUT_S}
    assert "CACHE MISS" in capsys.readouterr().out
    assert path.read_bytes() == before


def test_c3_supervisor_lease_cooled_mid_ping_falls_through(
        tmp_path, monkeypatch, capsys):
    """W1 lock discipline: a row cooled while its ping was in flight
    is never minted (re-checked under the lock) — the lease falls
    through to the classic pick."""
    path = _c4_cache_file(tmp_path, monkeypatch,
                          [_c4_fresh_row("s2", ms=7)])
    pool = _c4_link_pool()

    def _ping(h, p, timeout=5.0):
        pool.cool("s2", "zen")  # cooled mid-ping by a reporter
        return 30

    monkeypatch.setattr(SUP, "tcp_ping", _ping)
    lease = pool.lease("zen")
    assert lease["server_id"] == "s1"
    assert "CACHE MISS" in capsys.readouterr().out


def test_c3_supervisor_lease_audit_shape_unchanged(
        tmp_path, monkeypatch, capsys):
    """leases.jsonl behavior is untouched: the same event keys, no
    cache keys leak into the audit."""
    import json
    monkeypatch.setattr(SUP, "LEASES_PATH",
                        tmp_path / "leases.jsonl")
    monkeypatch.setenv(SUP.CLEAN_CACHE_PATH_VAR,
                       str(tmp_path / "no-cache.json"))
    monkeypatch.delenv(SUP.CLEAN_TTL_VAR, raising=False)
    monkeypatch.setattr(SUP, "tcp_ping",
                        lambda h, p, timeout=5.0: None)
    pool = _c4_link_pool()
    lease = pool.lease("zen")
    assert lease["server_id"] == "s1"
    lines = (tmp_path / "leases.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "lease" and rec["mode"] == "tunnel"
    assert rec["server"] == "s1" and rec["lease"] == \
        lease["lease_id"][:8]
    assert set(rec) == {"ts", "event", "lease", "mode", "server",
                        "provider", "target"}


def test_c3_supervisor_clean_env_knobs(tmp_path, monkeypatch):
    """EGRESS_CLEAN_TTL: finite-positive wins, garbage is the
    default; EGRESS_CLEAN_CACHE_PATH overrides the beside-pool file
    (empty falls back to it)."""
    monkeypatch.setenv(SUP.CLEAN_TTL_VAR, "60")
    assert SUP._clean_ttl_from_env() == 60.0
    for bad in ("0", "-5", "inf", "nan", "garbage", ""):
        monkeypatch.setenv(SUP.CLEAN_TTL_VAR, bad)
        assert SUP._clean_ttl_from_env() == NET.CLEAN_CACHE_TTL_S
    monkeypatch.delenv(SUP.CLEAN_TTL_VAR, raising=False)
    assert SUP._clean_ttl_from_env() == NET.CLEAN_CACHE_TTL_S
    monkeypatch.setenv(SUP.CLEAN_CACHE_PATH_VAR,
                       str(tmp_path / "custom.json"))
    assert SUP._clean_cache_path() == str(tmp_path / "custom.json")
    monkeypatch.setenv(SUP.CLEAN_CACHE_PATH_VAR, "   ")
    assert SUP._clean_cache_path() == str(SUP.CLEAN_CACHE_PATH)
