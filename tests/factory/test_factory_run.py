"""Network-run-ux phase 01 (R1-R4): hermetic tests for factory/run.py.

Keyless, no network, no subprocess, no W: drive: env maps are explicit
dicts, supervisor health/spawn and the pipeline main are injected fakes.
A test fails if any network/subprocess call escapes (sentinels raise).
"""

import os
import sys

import pytest

from factory.precard import transport as T
from factory import run as RUN


def _ns(**kw):
    base = {"preset": None, "llm_provider": None, "stage_provider": None,
            "precard_model": None, "judge_model": None, "stage_model": None,
            "sample": None, "out": None, "progress_dir": None, "limit": None,
            "sleep_secs": None, "cooldown_secs": None,
            "max_429_strikes": None, "egress_mode": None, "sup_url": None,
            "sup_token": None, "sup_port": None, "no_sup_spawn": None,
            "probe_top_n": None, "cache": None, "dry_run": None,
            "yes": None, "quiet": None, "json_log": None, "no_color": None,
            "list_models": False}
    base.update(kw)
    return type("NS", (), base)()


def _no_network(url, token):
    raise AssertionError("network touched in a hermetic test")


def _no_spawn(*args, **kwargs):
    raise AssertionError("spawn touched in a hermetic test")


def _no_pipeline(argv):
    raise AssertionError("pipeline touched in a hermetic test")


# --- R2 preset expansion ---

def test_preset_table_values():
    assert RUN.expand_preset("avalai") == {
        "llm_provider": "avalai", "egress_mode": "direct",
        "precard_model": T.AVALAI_PRECARD_MODEL}
    assert RUN.expand_preset("google") == {
        "llm_provider": "google", "egress_mode": "tunnel",
        "precard_model": T.GOOGLE_PRECARD_MODEL}
    assert RUN.expand_preset("zen") == {
        "llm_provider": "zen", "egress_mode": "direct",
        "precard_model": ""}
    with pytest.raises(SystemExit):
        RUN.expand_preset("openrouter")


def test_preset_case_insensitive():
    assert RUN.expand_preset("AvalAI")["llm_provider"] == "avalai"


# --- R3 precedence matrix: CLI > env > preset > code ---

def test_precedence_code_default():
    cfg, sources = RUN.resolve_config(_ns(), {})
    assert cfg["llm_provider"] == "zen" and sources["llm_provider"] == "preset"
    assert cfg["preset"] == "zen"
    assert cfg["egress_mode"] == "direct"


def test_precedence_preset_beats_code():
    cfg, sources = RUN.resolve_config(_ns(preset="google"), {})
    assert cfg["llm_provider"] == "google"
    assert sources["llm_provider"] == "preset"
    assert cfg["egress_mode"] == "tunnel"
    assert cfg["precard_model"] == T.GOOGLE_PRECARD_MODEL


def test_precedence_env_beats_preset():
    env = {"FACTORY_PRESET": "google",
           "FACTORY_LLM_PROVIDER": "avalai"}
    cfg, sources = RUN.resolve_config(_ns(), env)
    assert cfg["preset"] == "google" and sources["preset"] == "env"
    assert cfg["llm_provider"] == "avalai"
    assert sources["llm_provider"] == "env"


def test_precedence_cli_beats_env():
    env = {"FACTORY_LLM_PROVIDER": "avalai",
           "FACTORY_LIMIT": "20", "FACTORY_SAMPLE": "env-sample.json"}
    cfg, sources = RUN.resolve_config(
        _ns(preset="google", llm_provider="zen", limit=5), env)
    assert cfg["llm_provider"] == "zen" and sources["llm_provider"] == "cli"
    assert cfg["limit"] == 5 and sources["limit"] == "cli"
    assert cfg["sample"] == "env-sample.json"
    assert sources["sample"] == "env"


def test_explicit_zero_stays_cli():
    """--sleep-secs 0 disables pacing: 0 is a value, not 'unset'."""
    cfg, sources = RUN.resolve_config(_ns(sleep_secs=0.0, limit=0), {})
    assert cfg["sleep_secs"] == 0.0 and sources["sleep_secs"] == "cli"
    assert cfg["limit"] == 0 and sources["limit"] == "cli"


def test_env_list_and_bool_parsing():
    env = {"FACTORY_STAGE_PROVIDER": "sense_judge=avalai, topic_label=zen",
           "FACTORY_QUIET": "yes", "EGRESS_NO_SUP_SPAWN": "1"}
    cfg, sources = RUN.resolve_config(_ns(), env)
    assert cfg["stage_provider"] == ["sense_judge=avalai",
                                     "topic_label=zen"]
    assert sources["stage_provider"] == "env"
    assert cfg["quiet"] is True and sources["quiet"] == "env"
    assert cfg["no_sup_spawn"] is True


def test_every_flag_has_env_mirror():
    ns = RUN.parse_args([])
    for dest in RUN.FLAG_ENVS:
        assert hasattr(ns, dest), "flag --%s missing" % dest


def test_help_prints_precedence_and_mirrors(capsys):
    with pytest.raises(SystemExit) as exc:
        RUN.parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "CLI flag > env var > preset > code" in out
    assert "FACTORY_LLM_PROVIDER" in out
    assert "EGRESS_SUP_URL" in out
    assert "avalai (direct, no VPN)" in out


# --- --list-models: no network, no writes ---

def test_list_models_output(capsys):
    code = RUN.run(["--list-models"], env_map={},
                   health_fn=_no_network, spawn_fn=_no_spawn,
                   pipeline_main_fn=_no_pipeline)
    assert code == 0
    out = capsys.readouterr().out
    assert T.AVALAI_PRECARD_MODEL in out
    assert T.GOOGLE_PRECARD_MODEL in out


def test_list_models_prints_per_entry_cost_labels(capsys):
    """P2 (R3): every table entry prints with its cost label."""
    from factory.precard import net as NET
    code = RUN.run(["--list-models"], env_map={},
                   health_fn=_no_network, spawn_fn=_no_spawn,
                   pipeline_main_fn=_no_pipeline)
    assert code == 0
    out = capsys.readouterr().out
    assert "(free)" in out and "(paid)" in out
    for (provider, leg), entries in NET.LEG_FALLBACKS.items():
        assert "%s/%s:" % (provider, leg) in out
        for model, cost in entries:
            assert "%s (%s)" % (model, cost) in out


# --- --dry-run: no network, no writes ---

def test_dry_run_no_network_no_write(tmp_path, capsys):
    sample = tmp_path / "sample.json"
    sample.write_text('[{"kind": "word", "text": "abandon"}]',
                      encoding="utf-8")
    out = tmp_path / "never" / "precard.jsonl"
    prog = tmp_path / "prog"
    # The pipeline is stubbed here (the next test covers the real
    # pipeline dry-run): health/spawn sentinels raise on any touch.
    seen = {}

    def _pipeline(argv):
        seen["argv"] = argv
        assert "--dry-run" in argv
        return 0

    code = RUN.run(["--preset", "avalai", "--dry-run",
                    "--sample", str(sample),
                    "--out", str(out),
                    "--progress-dir", str(prog),
                    "--limit", "5"],
                   env_map={}, health_fn=_no_network, spawn_fn=_no_spawn,
                   pipeline_main_fn=_pipeline,
                   sleep_fn=lambda s: None)
    assert code == 0
    assert not out.exists()
    assert not prog.exists()
    assert "--llm-provider" in seen["argv"]
    assert "avalai" in seen["argv"]
    stdout = capsys.readouterr().out
    assert "no network, no writes" in stdout


def test_dry_run_real_pipeline_writes_nothing(tmp_path, capsys):
    """End-to-end dry-run through the real pipeline: plan prints, the
    out file is never created, no supervisor is touched."""
    from factory.precard.pipeline import main as real_pipeline
    sample = tmp_path / "sample.json"
    sample.write_text('[{"kind": "word", "text": "abandon"}]',
                      encoding="utf-8")
    out = tmp_path / "precard.jsonl"
    prog = tmp_path / "prog"
    code = RUN.run(["--preset", "zen", "--dry-run",
                    "--sample", str(sample), "--out", str(out),
                    "--progress-dir", str(prog)],
                   env_map={}, health_fn=_no_network, spawn_fn=_no_spawn,
                   pipeline_main_fn=real_pipeline,
                   sleep_fn=lambda s: None)
    assert code == 0
    assert not out.exists()
    assert not (tmp_path / "run_events.jsonl").exists()


# --- R4 spawn refusal ---

def test_no_sup_spawn_refuses_without_spawning(capsys):
    def _down(url, token):
        return None

    code = RUN.run(["--preset", "google", "--no-sup-spawn",
                    "--sup-url", "http://127.0.0.1:9"],
                   env_map={}, health_fn=_down, spawn_fn=_no_spawn,
                   pipeline_main_fn=_no_pipeline,
                   sleep_fn=lambda s: None)
    assert code == 2
    err = capsys.readouterr().err
    assert "--sup-spawn" in err


def test_tunnel_healthy_proceeds_without_spawn(capsys):
    def _healthy(url, token):
        assert url == "http://127.0.0.1:18789"
        return {"ok": True, "servers": 3, "leases": 1, "healthy": True}

    seen = {}

    def _pipeline(argv):
        seen["argv"] = argv
        return 0

    code = RUN.run(["--preset", "google"], env_map={},
                   health_fn=_healthy, spawn_fn=_no_spawn,
                   pipeline_main_fn=_pipeline,
                   sleep_fn=lambda s: None)
    assert code == 0
    out = capsys.readouterr().out
    assert "healthy" in out


def test_tunnel_spawn_prints_pid_port(capsys):
    def _down(url, token):
        return None

    def _spawn(port, token, health_fn, sleep_fn, **kwargs):
        assert port == 18791
        return 4242, 18791

    seen = {}

    def _pipeline(argv):
        seen["argv"] = argv
        return 7

    code = RUN.run(["--preset", "google", "--sup-port", "18791"],
                   env_map={}, health_fn=_down, spawn_fn=_spawn,
                   pipeline_main_fn=_pipeline,
                   sleep_fn=lambda s: None)
    assert code == 7  # pipeline code passes through
    out = capsys.readouterr().out
    assert "pid=4242" in out and "port=18791" in out


def test_tunnel_spawn_failure_returns_2(capsys):
    def _down(url, token):
        return None

    def _fail(port, token, health_fn, sleep_fn, **kwargs):
        raise RuntimeError("never healthy (5s budget)")

    code = RUN.run(["--preset", "google"], env_map={},
                   health_fn=_down, spawn_fn=_fail,
                   pipeline_main_fn=_no_pipeline,
                   sleep_fn=lambda s: None)
    assert code == 2
    assert "unavailable" in capsys.readouterr().err


def test_direct_preset_skips_supervisor(capsys):
    seen = {}

    def _pipeline(argv):
        seen["argv"] = argv
        return 0

    code = RUN.run(["--preset", "avalai"], env_map={},
                   health_fn=_no_network, spawn_fn=_no_spawn,
                   pipeline_main_fn=_pipeline,
                   sleep_fn=lambda s: None)
    assert code == 0
    assert "skipped" in capsys.readouterr().out


# --- token hygiene + forwarding ---

def test_sup_token_never_printed(capsys):
    def _healthy(url, token):
        assert token == "s3cr3t"
        return {"ok": True, "servers": 1, "leases": 0, "healthy": True}

    code = RUN.run(["--preset", "google", "--sup-token", "s3cr3t"],
                   env_map={}, health_fn=_healthy, spawn_fn=_no_spawn,
                   pipeline_main_fn=lambda argv: 0,
                   sleep_fn=lambda s: None)
    assert code == 0
    captured = capsys.readouterr()
    assert "s3cr3t" not in captured.out
    assert "s3cr3t" not in captured.err


def test_env_sup_token_used_and_masked(capsys):
    seen = {}

    def _healthy(url, token):
        seen["token"] = token
        return {"ok": True, "servers": 1, "leases": 0, "healthy": True}

    code = RUN.run(["--preset", "google"],
                   env_map={"EGRESS_SUP_TOKEN": "envtok"},
                   health_fn=_healthy, spawn_fn=_no_spawn,
                   pipeline_main_fn=lambda argv: 0,
                   sleep_fn=lambda s: None)
    assert code == 0
    assert seen["token"] == "envtok"
    assert "envtok" not in capsys.readouterr().out


def test_sup_url_defaults_from_port():
    cfg, sources = RUN.resolve_config(_ns(sup_port=18888), {})
    assert cfg["sup_url"] == "http://127.0.0.1:18888"


def test_pipeline_argv_forwarding():
    cfg, _ = RUN.resolve_config(
        _ns(preset="avalai", limit=5, quiet=True, json_log=True,
            stage_provider=["sense_judge=avalai"],
            precard_model="glm-5.3-flash", judge_model="j1",
            stage_model=["sense_judge=j1"]),
        {})
    argv = RUN.build_pipeline_argv(cfg)
    for flag in ("--sample", "--out", "--progress-dir", "--limit", "5",
                 "--sleep-secs", "--llm-provider", "avalai",
                 "--stage-provider", "sense_judge=avalai",
                 "--precard-model", "glm-5.3-flash",
                 "--judge-model", "j1",
                 "--stage-model", "sense_judge=j1",
                 "--quiet", "--json-log"):
        assert flag in argv


def test_validation_rejects_nonsense():
    with pytest.raises(SystemExit):
        RUN.resolve_config(_ns(limit=-1), {})
    with pytest.raises(SystemExit):
        RUN.resolve_config(_ns(sup_port=99999), {})
    with pytest.raises(SystemExit):
        RUN.resolve_config(_ns(preset="nope"), {})


def test_code_defaults_track_owners():
    """run.py cites (not moves) owner constants: drift fails here."""
    _egress = os.path.join(RUN.REPO_ROOT, "tools", "egress")
    sys.path.insert(0, _egress)
    try:
        import supervisor as SUP
        assert RUN.SUP_DEFAULT_PORT == SUP.DEFAULT_PORT
        assert RUN.SUP_DEFAULT_PROBE_TOP_N == SUP.PROBE_TOP_N
        assert RUN.SUP_DEFAULT_COOLDOWN_SECS == SUP.COOLDOWN_S
    finally:
        sys.path.remove(_egress)
    from factory.precard.pipeline import DEFAULT_OUT, DEFAULT_SAMPLE, SLEEP
    cfg, _ = RUN.resolve_config(_ns(), {})
    assert cfg["sample"] == DEFAULT_SAMPLE
    assert cfg["out"] == DEFAULT_OUT
    assert cfg["sleep_secs"] == SLEEP


def test_no_key_flags():
    """LLM API keys must never become CLI flags (R-keys rule)."""
    src = open(RUN.__file__, encoding="utf-8").read()
    for var in ("AVALAI_API_KEY", "GOOGLE_AI_API_KEY",
                "OPENCODE_ZEN_API_KEY", "OPENROUTER_API_KEY"):
        assert var not in src


# --- reviewer fixes: fail-fast env parsing (exit 2, names the var) ---

def test_env_garbage_fails_fast(capsys):
    with pytest.raises(SystemExit) as exc:
        RUN.resolve_config(_ns(), {"FACTORY_LIMIT": "abc"})
    assert exc.value.code == 2
    assert "FACTORY_LIMIT" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        RUN.resolve_config(_ns(), {"FACTORY_SLEEP_SECS": "not_a_number"})
    assert exc.value.code == 2
    assert "FACTORY_SLEEP_SECS" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        RUN.resolve_config(_ns(), {"FACTORY_DRY_RUN": "tru"})
    assert exc.value.code == 2
    assert "FACTORY_DRY_RUN" in capsys.readouterr().err


def test_env_list_empty_entry_fails_fast(capsys):
    with pytest.raises(SystemExit) as exc:
        RUN.resolve_config(
            _ns(), {"FACTORY_STAGE_PROVIDER":
                    "sense_judge=avalai,,topic_label=zen"})
    assert exc.value.code == 2
    assert "FACTORY_STAGE_PROVIDER" in capsys.readouterr().err


# --- reviewer fixes: self-documenting flags ---

def test_no_color_and_sup_token_help(capsys):
    with pytest.raises(SystemExit):
        RUN.parse_args(["--help"])
    out = capsys.readouterr().out
    assert "ANSI" in out  # --no-color finally has help text
    assert "process list" in out  # --sup-token warns argv is visible


# --- reviewer fixes: usage errors exit 2 with a message ---

def test_usage_errors_exit_2(capsys):
    with pytest.raises(SystemExit) as exc:
        RUN.expand_preset("nope")
    assert exc.value.code == 2
    assert "unknown preset" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        RUN.resolve_config(_ns(limit=-1), {})
    assert exc.value.code == 2
    assert "--limit" in capsys.readouterr().err


# --- reviewer fixes: supervisor auth vs down + child reap ---

def test_supervisor_auth_error_skips_spawn():
    def _auth(url, token):
        return {"auth_error": "HTTP 401 from %s/v1/health "
                              "(check EGRESS_SUP_TOKEN)" % url}

    result = RUN.ensure_supervisor(
        {"egress_mode": "tunnel", "sup_url": "http://127.0.0.1:18789",
         "sup_token": "wrong", "sup_port": 18789, "no_sup_spawn": False},
        health_fn=_auth, spawn_fn=_no_spawn,
        sleep_fn=lambda s: None)
    assert result["action"] == "failed"
    assert "auth" in result["reason"].lower()


def test_sup_http_health_maps_401_to_auth_error(monkeypatch):
    import urllib.error as urlerror

    def _raise_401(req, timeout=None):
        raise urlerror.HTTPError(req.full_url, 401, "Unauthorized",
                                 {}, None)

    monkeypatch.setattr(RUN.urllib.request, "urlopen", _raise_401)
    payload = RUN._sup_http_health("http://127.0.0.1:18789", "wrong")
    assert "401" in payload["auth_error"]
    assert "EGRESS_SUP_TOKEN" in payload["auth_error"]

    def _raise_500(req, timeout=None):
        raise urlerror.HTTPError(req.full_url, 500, "Server Error",
                                 {}, None)

    monkeypatch.setattr(RUN.urllib.request, "urlopen", _raise_500)
    assert RUN._sup_http_health("http://127.0.0.1:18789", "tok") is None


def test_spawn_timeout_reaps_child(monkeypatch):
    import subprocess as _subprocess

    class _StubProc:
        pid = 4242
        returncode = None

        def __init__(self):
            self.calls = []

        def poll(self):
            return None

        def terminate(self):
            self.calls.append("terminate")

        def kill(self):
            self.calls.append("kill")

        def wait(self, timeout=None):
            self.calls.append("wait")
            raise _subprocess.TimeoutExpired("supervisor", timeout)

    stub = _StubProc()
    monkeypatch.setattr(RUN.subprocess, "Popen",
                        lambda *a, **k: stub)
    with pytest.raises(RuntimeError):
        RUN._spawn_supervisor(18799, "", lambda u, t: None,
                              sleep_fn=lambda s: None, timeout=0)
    assert stub.calls == ["terminate", "wait", "kill", "wait"]


# --- Boolean pairs: CLI beats env in both directions ---

def test_no_quiet_beats_env_quiet():
    """FACTORY_QUIET=yes silenced, but --no-quiet forces full output."""
    ns = RUN.parse_args(["--no-quiet"])
    cfg, sources = RUN.resolve_config(ns, {"FACTORY_QUIET": "yes"})
    assert cfg["quiet"] is False and sources["quiet"] == "cli"


def test_quiet_beats_unset_env():
    ns = RUN.parse_args(["--quiet"])
    cfg, sources = RUN.resolve_config(ns, {})
    assert cfg["quiet"] is True and sources["quiet"] == "cli"


def test_sup_spawn_beats_env_refusal():
    """EGRESS_NO_SUP_SPAWN=1 refuses, but --sup-spawn re-allows."""
    ns = RUN.parse_args(["--sup-spawn"])
    cfg, sources = RUN.resolve_config(ns, {"EGRESS_NO_SUP_SPAWN": "1"})
    assert cfg["no_sup_spawn"] is False
    assert sources["no_sup_spawn"] == "cli"


def test_no_dry_run_beats_env_dry_run():
    ns = RUN.parse_args(["--no-dry-run"])
    cfg, sources = RUN.resolve_config(ns, {"FACTORY_DRY_RUN": "yes"})
    assert cfg["dry_run"] is False and sources["dry_run"] == "cli"


def test_color_pair_beats_env():
    ns = RUN.parse_args(["--color"])
    cfg, sources = RUN.resolve_config(ns, {"FACTORY_NO_COLOR": "yes"})
    assert cfg["no_color"] is False and sources["no_color"] == "cli"
    ns2 = RUN.parse_args(["--no-color"])
    cfg2, _ = RUN.resolve_config(ns2, {})
    assert cfg2["no_color"] is True


def test_help_shows_boolean_pairs(capsys):
    with pytest.raises(SystemExit) as exc:
        RUN.parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for pair in ("--dry-run", "--no-dry-run", "--yes", "--no-yes",
                 "--quiet", "--no-quiet", "--sup-spawn", "--no-sup-spawn",
                 "--color", "--no-color", "--json-log", "--no-json-log"):
        assert pair in out, "help missing %s" % pair


# --- R8 direct-first gate (phase 03 W1): the flag changes behavior ---

def _raising_probe():
    raise AssertionError("direct probe touched in a hermetic test")


def test_direct_probe_default_loader_returns_supervisor_ping():
    """The default probe is the supervisor's tcp_ping (PR-0 seam
    reused as a callable, never redefined): import-only, no network."""
    ping = RUN._load_supervisor_tcp_ping()
    assert callable(ping) and ping.__name__ == "tcp_ping"


def test_direct_probe_loader_returns_single_shared_instance():
    """The loader never double-executes supervisor.py: its tcp_ping
    is the same object as a plain import's (probe identity holds in
    both import orders)."""
    _egress = os.path.join(RUN.REPO_ROOT, "tools", "egress")
    sys.path.insert(0, _egress)
    try:
        import supervisor as SUP
        assert RUN._load_supervisor_tcp_ping() is SUP.tcp_ping
    finally:
        sys.path.remove(_egress)


def test_direct_probe_hit_prints_cache_hit_and_continues(capsys):
    """Flag on + avalai + reachable: probe runs once, CACHE HIT +
    direct-ok lines print, the run continues to the pipeline."""
    calls = []

    def _probe():
        calls.append(True)
        return 12

    seen = {}

    def _pipeline(argv):
        seen["argv"] = argv
        return 0

    code = RUN.run(["--preset", "avalai", "--direct-probe"],
                   env_map={}, health_fn=_no_network,
                   spawn_fn=_no_spawn, pipeline_main_fn=_pipeline,
                   sleep_fn=lambda s: None, direct_probe_fn=_probe)
    assert code == 0
    assert calls == [True]
    out = capsys.readouterr().out
    assert "CACHE HIT" in out and "direct" in out
    assert "direct-ok" in out and "lease_taken=False" in out
    assert seen["argv"]  # normal path continued


def test_direct_probe_off_never_probes(capsys):
    """Flag off: the probe is never touched, no CACHE lines print."""
    code = RUN.run(["--preset", "avalai"], env_map={},
                   health_fn=_no_network, spawn_fn=_no_spawn,
                   pipeline_main_fn=lambda argv: 0,
                   sleep_fn=lambda s: None,
                   direct_probe_fn=_raising_probe)
    assert code == 0
    out = capsys.readouterr().out
    assert "CACHE HIT" not in out and "CACHE MISS" not in out
    assert "direct-ok" not in out and "lease-fallback" not in out


def test_direct_probe_miss_falls_back_to_normal_path(capsys):
    """Unreachable direct in direct mode: CACHE MISS + lease-fallback
    print, but lease_taken=False — no lease path exists outside
    tunnel mode, so the run just continues direct (fallback, never
    a refusal)."""
    seen = {}

    def _pipeline(argv):
        seen["argv"] = argv
        return 0

    code = RUN.run(["--preset", "avalai", "--direct-probe"],
                   env_map={}, health_fn=_no_network,
                   spawn_fn=_no_spawn, pipeline_main_fn=_pipeline,
                   sleep_fn=lambda s: None,
                   direct_probe_fn=lambda: None)
    assert code == 0
    out = capsys.readouterr().out
    assert "CACHE MISS" in out
    assert "lease-fallback" in out and "lease_taken=False" in out
    assert seen["argv"]


def test_direct_probe_miss_tunnel_mode_claims_lease(capsys):
    """Tunnel override + miss: a lease path exists, so the generic
    lease-fallback/lease_taken=True claim stands."""
    def _healthy(url, token):
        return {"ok": True, "servers": 1, "leases": 0, "healthy": True}

    code = RUN.run(["--preset", "avalai", "--egress-mode", "tunnel",
                    "--direct-probe"],
                   env_map={}, health_fn=_healthy, spawn_fn=_no_spawn,
                   pipeline_main_fn=lambda argv: 0,
                   sleep_fn=lambda s: None,
                   direct_probe_fn=lambda: None)
    assert code == 0
    out = capsys.readouterr().out
    assert "lease-fallback" in out and "lease_taken=True" in out


def test_direct_probe_env_flag_enables_gate(capsys):
    """AVALAI_DIRECT_FIRST=1 enables the gate without the CLI flag."""
    calls = []

    def _probe():
        calls.append(True)
        return 5

    code = RUN.run(["--preset", "avalai"],
                   env_map={"AVALAI_DIRECT_FIRST": "1"},
                   health_fn=_no_network, spawn_fn=_no_spawn,
                   pipeline_main_fn=lambda argv: 0,
                   sleep_fn=lambda s: None,
                   direct_probe_fn=_probe)
    assert code == 0
    assert calls == [True]
    assert "CACHE HIT" in capsys.readouterr().out


def test_direct_probe_skipped_off_provider():
    """Flag on but non-avalai provider: gate inactive, probe untouched
    (tunnel path proceeds via the supervisor as before)."""
    def _healthy(url, token):
        return {"ok": True, "servers": 1, "leases": 0, "healthy": True}

    code = RUN.run(["--preset", "google", "--direct-probe"],
                   env_map={}, health_fn=_healthy, spawn_fn=_no_spawn,
                   pipeline_main_fn=lambda argv: 0,
                   sleep_fn=lambda s: None,
                   direct_probe_fn=_raising_probe)
    assert code == 0


def test_direct_probe_skipped_on_dry_run(capsys):
    """Dry-run stays network-free: the gate never probes even with the
    flag set (plan prints, stub pipeline sees --dry-run)."""
    seen = {}

    def _pipeline(argv):
        seen["argv"] = argv
        assert "--dry-run" in argv
        return 0

    code = RUN.run(["--preset", "avalai", "--dry-run", "--direct-probe"],
                   env_map={}, health_fn=_no_network,
                   spawn_fn=_no_spawn, pipeline_main_fn=_pipeline,
                   sleep_fn=lambda s: None,
                   direct_probe_fn=_raising_probe)
    assert code == 0
    assert "no network, no writes" in capsys.readouterr().out


def test_direct_probe_failure_falls_back(capsys):
    """A raising probe is a miss, not a crash (unreachable IS the
    fallback)."""
    def _boom():
        raise RuntimeError("boom")

    event = RUN.maybe_direct_first(
        {"direct_probe": True, "llm_provider": "avalai"},
        direct_probe_fn=_boom)
    assert event["outcome"] == "lease-fallback"
    assert "CACHE MISS" in capsys.readouterr().out


# --- spawn forwarding (phase 03 W1): --clean-ttl/--cache reach the
# auto-spawned supervisor's env, where the W2 lease path reads them ---

def test_spawn_forwards_clean_cache_config():
    """Resolved clean-ttl + explicit cache path arrive at spawn_fn."""
    seen = {}

    def _record(port, token, health_fn, sleep_fn, **kwargs):
        seen.update(kwargs)
        return 4242, 18789

    def _down(url, token):
        return None

    code = RUN.run(["--preset", "google", "--clean-ttl", "3600",
                    "--cache", "C:\\fakecache\\cc.json"],
                   env_map={}, health_fn=_down, spawn_fn=_record,
                   pipeline_main_fn=lambda argv: 0,
                   sleep_fn=lambda s: None)
    assert code == 0
    assert seen["clean_ttl"] == 3600.0
    assert seen["cache_path"] == "C:\\fakecache\\cc.json"


def test_spawn_defaults_keep_supervisor_default_cache():
    """No --cache: None forwarded (the supervisor keeps its
    beside-pool file); clean-ttl forwards the resolved default."""
    seen = {}

    def _record(port, token, health_fn, sleep_fn, **kwargs):
        seen.update(kwargs)
        return 4242, 18789

    def _down(url, token):
        return None

    code = RUN.run(["--preset", "google"], env_map={},
                   health_fn=_down, spawn_fn=_record,
                   pipeline_main_fn=lambda argv: 0,
                   sleep_fn=lambda s: None)
    assert code == 0
    assert seen["cache_path"] is None
    from factory.precard import net as NET
    assert seen["clean_ttl"] == NET.CLEAN_CACHE_TTL_S


def test_spawn_supervisor_sets_child_env(monkeypatch):
    """The live spawner exports the bearer + cache knobs to the child
    env only (never argv, never logs)."""
    captured = {}

    class _StubProc:
        pid = 4242

        def poll(self):
            return None

    def _popen(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env") or {}
        return _StubProc()

    monkeypatch.setattr(RUN.subprocess, "Popen", _popen)

    def _healthy(url, token):
        return {"ok": True, "servers": 1, "leases": 0, "healthy": True}

    pid, port = RUN._spawn_supervisor(
        18799, "tok", _healthy, lambda s: None,
        clean_ttl=60.0, cache_path="C:\\x\\cc.json")
    assert (pid, port) == (4242, 18799)
    env = captured["env"]
    assert env["EGRESS_SUP_TOKEN"] == "tok"
    assert env["EGRESS_CLEAN_TTL"] == "60.0"
    assert env["EGRESS_CLEAN_CACHE_PATH"] == "C:\\x\\cc.json"
    assert "tok" not in " ".join(captured["argv"])
