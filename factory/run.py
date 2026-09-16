"""One-command factory runs (network-run-ux phase 01: R1-R4). Thin entry.

Composes three seams, moves no logic (wiring only):

- supervisor client: ``/v1/health`` check + auto-spawn of
  ``tools/egress/supervisor.py`` for tunnel presets (shape owned by
  ``factory.precard.net.supervisor_health``; spawn target owned by the
  supervisor's own ``--port`` CLI).
- home probe table: ``factory.precard.net.TARGETS`` decides direct vs
  tunnel; ``PROVIDER_KEY_VARS`` names missing-key errors (never values).
- line runner: ``factory.precard.pipeline.main`` does the real work.

Precedence everywhere: CLI flag > env var > preset > code default,
printed by ``--help``. API keys are never flags, never printed, never
logged (``--sup-token`` only carries the loopback supervisor bearer,
and even it prints as set/unset only).

Usage:
    python -m factory.run --preset avalai --limit 20 --dry-run
    python -m factory.run --preset google --sample S --out O --progress-dir P
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import time
import urllib.request

FACTORY_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(FACTORY_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from factory.precard.pipeline import (  # noqa: E402 (path bootstrap above)
    DEFAULT_OUT,
    DEFAULT_PROGRESS_DIR,
    DEFAULT_SAMPLE,
    SLEEP,
    main as pipeline_main,
)
from factory.precard.net import (  # noqa: E402
    AVALAI_CHAT_URL,
    AVALAI_PRECARD_MODEL,
    CLEAN_CACHE_TTL_S,
    GOOGLE_PRECARD_MODEL,
    LEG_FALLBACKS,
    LEGS,
    direct_probe_event,
    format_cache_line,
)

# Code defaults whose owners live elsewhere (cited, not moved):
# supervisor DEFAULT_PORT/COOLDOWN_S/PROBE_TOP_N in tools/egress/supervisor.py.
SUP_DEFAULT_PORT = 18789
SUP_DEFAULT_COOLDOWN_SECS = 300.0
SUP_DEFAULT_PROBE_TOP_N = 20
DEFAULT_MAX_429_STRIKES = 3  # README runbook: three consecutive 429s stop.

SUPERVISOR_SCRIPT = os.path.join(REPO_ROOT, "tools", "egress",
                                 "supervisor.py")
HEALTH_TIMEOUT_S = 5.0
SPAWN_POLL_S = 0.5
SPAWN_TIMEOUT_S = 20.0
SPAWN_REAP_TIMEOUT_S = 5.0

# R2 presets: avalai is domestic-direct (no VPN, no supervisor);
# google rides the tunnel (supervisor auto-spawn); zen is the default.
PRESETS = {
    "zen": {"llm_provider": "zen", "egress_mode": "direct",
            "precard_model": ""},
    "avalai": {"llm_provider": "avalai", "egress_mode": "direct",
               "precard_model": AVALAI_PRECARD_MODEL},
    "google": {"llm_provider": "google", "egress_mode": "tunnel",
               "precard_model": GOOGLE_PRECARD_MODEL},
}

# Flag dest -> env mirror (every flag has one; printed in --help).
FLAG_ENVS = {
    "preset": "FACTORY_PRESET",
    "llm_provider": "FACTORY_LLM_PROVIDER",
    "stage_provider": "FACTORY_STAGE_PROVIDER",
    "precard_model": "FACTORY_PRECARD_MODEL",
    "judge_model": "FACTORY_JUDGE_MODEL",
    "stage_model": "FACTORY_STAGE_MODEL",
    "sample": "FACTORY_SAMPLE",
    "out": "FACTORY_OUT",
    "progress_dir": "FACTORY_PROGRESS_DIR",
    "limit": "FACTORY_LIMIT",
    "sleep_secs": "FACTORY_SLEEP_SECS",
    "cooldown_secs": "FACTORY_COOLDOWN_SECS",
    "max_429_strikes": "FACTORY_MAX_429_STRIKES",
    "egress_mode": "EGRESS_MODE",
    "sup_url": "EGRESS_SUP_URL",
    "sup_token": "EGRESS_SUP_TOKEN",
    "sup_port": "EGRESS_SUP_PORT",
    "no_sup_spawn": "EGRESS_NO_SUP_SPAWN",
    "probe_top_n": "EGRESS_PROBE_TOP_N",
    "cache": "FACTORY_CACHE",
    "clean_ttl": "EGRESS_CLEAN_TTL",
    "direct_probe": "AVALAI_DIRECT_FIRST",
    "dry_run": "FACTORY_DRY_RUN",
    "yes": "FACTORY_YES",
    "quiet": "FACTORY_QUIET",
    "json_log": "FACTORY_JSON_LOG",
    "no_color": "FACTORY_NO_COLOR",
}

_MISSING = object()
_TRUE_WORDS = {"1", "true", "yes", "on"}
_FALSE_WORDS = {"0", "false", "no", "off"}


def _env_raw(env_map, var):
    try:
        return (env_map.get(var, "") or "").strip()
    except AttributeError:
        return ""


def _env_str(env_map, var):
    return _env_raw(env_map, var) or None


def _fail(msg):
    """Usage error: message to stderr, exit 2 (matches run() refusal).

    Single owner of the exit-2 convention so ``expand_preset``,
    ``_validate`` and the typed ``_env_*`` parsers agree: scripts can
    distinguish usage errors (2) from pipeline failures.
    """
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def _bad_env(var, raw, want):
    """Fail-fast on a set-but-unparseable env value (exit 2, names var).

    Silent fallback to the code default once inverted real behavior
    (``FACTORY_DRY_RUN=tru`` ran a real run), so every typed parser
    below rejects garbage instead of returning None.
    """
    _fail("factory/run: bad %s=%r (want %s)" % (var, raw, want))


def _env_bool(env_map, var):
    raw = _env_raw(env_map, var).lower()
    if not raw:
        return None
    if raw in _TRUE_WORDS:
        return True
    if raw in _FALSE_WORDS:
        return False
    return _bad_env(var, _env_raw(env_map, var),
                    "one of: %s" % ", ".join(sorted(
                        _TRUE_WORDS | _FALSE_WORDS)))


def _env_int(env_map, var):
    raw = _env_raw(env_map, var)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return _bad_env(var, raw, "an integer")


def _env_float(env_map, var):
    raw = _env_raw(env_map, var)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return _bad_env(var, raw, "a number")


def _env_list(env_map, var):
    raw = _env_raw(env_map, var)
    if not raw:
        return None
    parts = raw.split(",")
    if any(not p.strip() for p in parts):
        return _bad_env(var, raw, "comma-separated entries, no empties")
    return [p.strip() for p in parts]


def _cli_present(value):
    """True when the CLI actually set the flag.

    Numbers count even when 0 (``--sleep-secs 0`` disables pacing and
    must not fall through to the default); strings/lists count only
    when non-empty; None (argparse unset default) never counts.
    """
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return bool(value)
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _pick(cli_value, env_value, preset_value, default):
    """R3 precedence: CLI > env > preset > code. Returns (value, source)."""
    if _cli_present(cli_value):
        return cli_value, "cli"
    if env_value is not None:
        return env_value, "env"
    if preset_value is not None:
        return preset_value, "preset"
    return default, "code"


def expand_preset(name):
    """Preset table row (copy); unknown names raise SystemExit(2)."""
    try:
        return dict(PRESETS[str(name or "").strip().lower()])
    except KeyError:
        _fail("factory/run: unknown preset %r (want one of: %s)"
              % (name, ", ".join(sorted(PRESETS))))


def parse_args(argv=None):
    """CLI for the thin entry (every flag defaults to unset: env/preset
    fill in under R3; ``--help`` prints the precedence + env mirrors)."""
    ap = argparse.ArgumentParser(
        prog="factory.run",
        description="One-command factory precard runs (R1-R4). "
                    "Thin wiring over supervisor + home probe table + "
                    "factory.precard.pipeline.",
        epilog="Precedence: CLI flag > env var > preset > code default. "
               "Env mirrors: " + ", ".join(
                   "--%s=%s" % (d.replace("_", "-"), v)
                   for d, v in sorted(FLAG_ENVS.items()))
               + ". Presets: avalai (direct, no VPN) / google (tunnel, "
                 "auto-spawns the supervisor) / zen (default). "
                 "API keys are never flags and never printed: LLM keys "
                 "come from factory/.env; --sup-token only carries the "
                 "loopback supervisor bearer and prints as set/unset. "
                  "--cache/--cooldown-secs/--max-429-strikes/--yes are "
                  "accepted and shown in the plan; PR-C wires --cache/ "
                  "--clean-ttl/--direct-probe behavior through the net "
                  "clean-cache home (this phase resolves them).")
    ap.add_argument("--preset", default=None,
                    choices=tuple(sorted(PRESETS)),
                    help="run preset (default: zen)")
    ap.add_argument("--llm-provider", default=None,
                    choices=("zen", "avalai", "google"),
                    help="ALL precard LLM legs (overrides the preset)")
    ap.add_argument("--stage-provider", action="append", default=None,
                    metavar="STAGE=PROVIDER",
                    help="per-leg provider override, repeatable "
                         "(comma-separated STAGE=PROVIDER in "
                         "FACTORY_STAGE_PROVIDER)")
    ap.add_argument("--precard-model", default=None,
                    help="model for all precard legs (default: preset "
                         "default; ignored on the zen path)")
    ap.add_argument("--judge-model", default=None,
                    help="judge model id (default: provider default)")
    ap.add_argument("--stage-model", action="append", default=None,
                    metavar="STAGE=MODEL",
                    help="per-leg model override, repeatable "
                         "(comma-separated in FACTORY_STAGE_MODEL)")
    ap.add_argument("--sample", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--progress-dir", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep-secs", type=float, default=None)
    ap.add_argument("--cooldown-secs", type=float, default=None,
                    help="reserved for PR-B/C (resolved + shown only)")
    ap.add_argument("--max-429-strikes", type=int, default=None,
                    help="reserved for PR-B/C (resolved + shown only)")
    ap.add_argument("--egress-mode", default=None,
                    choices=("direct", "tunnel"),
                    help="direct skips the supervisor; tunnel ensures it "
                         "(default: preset)")
    ap.add_argument("--sup-url", default=None,
                    help="supervisor base URL (default: "
                         "http://127.0.0.1:<sup-port>)")
    ap.add_argument("--sup-token", default=None,
                    help="supervisor bearer (env EGRESS_SUP_TOKEN "
                         "preferred: argv is visible in process lists on "
                         "multi-user hosts; never printed)")
    ap.add_argument("--sup-port", type=int, default=None)
    ap.add_argument("--sup-spawn", dest="no_sup_spawn",
                    action="store_false", default=None,
                    help="allow auto-spawning the supervisor (default; "
                         "negates --no-sup-spawn; CLI beats env "
                         "EGRESS_NO_SUP_SPAWN either way)")
    ap.add_argument("--no-sup-spawn", dest="no_sup_spawn",
                    action="store_true", default=None,
                    help="refuse to spawn the supervisor (exit 2 when it "
                         "is down instead; negates --sup-spawn)")
    ap.add_argument("--probe-top-n", type=int, default=None,
                    help="whitelist top-N (resolved + shown; PR-B owns "
                         "the probe call)")
    ap.add_argument("--cache", default=None,
                    help="clean-cache path (default: beside the pool; "
                         "forwarded to auto-spawned supervisors via "
                         "EGRESS_CLEAN_CACHE_PATH; a running supervisor "
                         "keeps its own file)")
    ap.add_argument("--clean-ttl", type=float, default=None,
                    help="clean-cache freshness seconds (default: 86400; "
                         "env EGRESS_CLEAN_TTL)")
    ap.add_argument("--direct-probe", dest="direct_probe",
                    action="store_true", default=None,
                    help="AvalAI leaseless first: one direct ping, no "
                         "lease on success, lease fallback with "
                         "telemetry on failure (negates "
                         "--no-direct-probe)")
    ap.add_argument("--no-direct-probe", dest="direct_probe",
                    action="store_false", default=None,
                    help="force the lease path even when "
                         "AVALAI_DIRECT_FIRST is set (negates "
                         "--direct-probe)")
    ap.add_argument("--dry-run", action="store_true", default=None,
                    help="print the plan, run the pipeline dry-run: no "
                         "network, no writes, supervisor untouched "
                         "(negates --no-dry-run)")
    ap.add_argument("--no-dry-run", dest="dry_run",
                    action="store_false", default=None,
                    help="force a real run even when FACTORY_DRY_RUN is "
                         "set (negates --dry-run)")
    ap.add_argument("--yes", action="store_true", default=None,
                    help="accepted for forward-compat (PR-D resume "
                         "confirms); no prompts exist in this phase "
                         "(negates --no-yes)")
    ap.add_argument("--no-yes", dest="yes",
                    action="store_false", default=None,
                    help="force asking even when FACTORY_YES is set "
                         "(negates --yes)")
    ap.add_argument("--quiet", action="store_true", default=None,
                    help="less output (negates --no-quiet)")
    ap.add_argument("--no-quiet", dest="quiet",
                    action="store_false", default=None,
                    help="force full output even when FACTORY_QUIET is "
                         "set (negates --quiet)")
    ap.add_argument("--json-log", action="store_true", default=None,
                    help="also emit the machine event stream "
                         "(negates --no-json-log)")
    ap.add_argument("--no-json-log", dest="json_log",
                    action="store_false", default=None,
                    help="suppress the event stream even when "
                         "FACTORY_JSON_LOG is set (negates --json-log)")
    ap.add_argument("--color", dest="no_color",
                    action="store_false", default=None,
                    help="force ANSI colors even when FACTORY_NO_COLOR "
                         "is set (negates --no-color)")
    ap.add_argument("--no-color", action="store_true", default=None,
                    help="disable ANSI colors (negates --color)")
    ap.add_argument("--list-models", action="store_true",
                    help="print known precard models and exit "
                         "(no network, no writes)")
    return ap.parse_args(argv)


def resolve_config(ns, env_map=None):
    """Resolve every option under R3. Returns (config, sources).

    ``env_map`` defaults to ``os.environ`` (tests inject a dict).
    ``sources[key]`` is one of cli/env/preset/code. The supervisor
    token value stays in ``config`` but must never be printed.
    """
    env = os.environ if env_map is None else env_map
    preset_name, _ = _pick(getattr(ns, "preset", None),
                            _env_str(env, "FACTORY_PRESET"),
                            None, "zen")
    preset = expand_preset(preset_name)
    cfg, sources = {}, {}

    def _set(key, cli, env_val, preset_val, default):
        value, source = _pick(cli, env_val, preset_val, default)
        cfg[key] = value
        sources[key] = source

    _set("preset", getattr(ns, "preset", None),
         _env_str(env, "FACTORY_PRESET"), None, "zen")
    _set("llm_provider", getattr(ns, "llm_provider", None),
         _env_str(env, "FACTORY_LLM_PROVIDER"),
         preset["llm_provider"], "zen")
    _set("stage_provider", getattr(ns, "stage_provider", None),
         _env_list(env, "FACTORY_STAGE_PROVIDER"), None, [])
    _set("precard_model", getattr(ns, "precard_model", None),
         _env_str(env, "FACTORY_PRECARD_MODEL"),
         preset["precard_model"] or None, "")
    _set("judge_model", getattr(ns, "judge_model", None),
         _env_str(env, "FACTORY_JUDGE_MODEL"), None, "")
    _set("stage_model", getattr(ns, "stage_model", None),
         _env_list(env, "FACTORY_STAGE_MODEL"), None, [])
    _set("sample", getattr(ns, "sample", None),
         _env_str(env, "FACTORY_SAMPLE"), None, DEFAULT_SAMPLE)
    _set("out", getattr(ns, "out", None),
         _env_str(env, "FACTORY_OUT"), None, DEFAULT_OUT)
    _set("progress_dir", getattr(ns, "progress_dir", None),
         _env_str(env, "FACTORY_PROGRESS_DIR"), None,
         DEFAULT_PROGRESS_DIR)
    _set("limit", getattr(ns, "limit", None),
         _env_int(env, "FACTORY_LIMIT"), None, 0)
    _set("sleep_secs", getattr(ns, "sleep_secs", None),
         _env_float(env, "FACTORY_SLEEP_SECS"), None, SLEEP)
    _set("cooldown_secs", getattr(ns, "cooldown_secs", None),
         _env_float(env, "FACTORY_COOLDOWN_SECS"), None,
         SUP_DEFAULT_COOLDOWN_SECS)
    _set("max_429_strikes", getattr(ns, "max_429_strikes", None),
         _env_int(env, "FACTORY_MAX_429_STRIKES"), None,
         DEFAULT_MAX_429_STRIKES)
    _set("egress_mode", getattr(ns, "egress_mode", None),
         _env_str(env, "EGRESS_MODE"),
         preset["egress_mode"], "direct")
    _set("sup_port", getattr(ns, "sup_port", None),
         _env_int(env, "EGRESS_SUP_PORT"), None, SUP_DEFAULT_PORT)
    _set("sup_token", getattr(ns, "sup_token", None),
         _env_str(env, "EGRESS_SUP_TOKEN"), None, "")
    _set("no_sup_spawn", getattr(ns, "no_sup_spawn", None),
         _env_bool(env, "EGRESS_NO_SUP_SPAWN"), None, False)
    _set("probe_top_n", getattr(ns, "probe_top_n", None),
         _env_int(env, "EGRESS_PROBE_TOP_N"), None,
         SUP_DEFAULT_PROBE_TOP_N)
    _set("cache", getattr(ns, "cache", None),
         _env_str(env, "FACTORY_CACHE"), None, "")
    _set("clean_ttl", getattr(ns, "clean_ttl", None),
         _env_float(env, "EGRESS_CLEAN_TTL"), None,
         CLEAN_CACHE_TTL_S)
    _set("direct_probe", getattr(ns, "direct_probe", None),
         _env_bool(env, "AVALAI_DIRECT_FIRST"), None, False)
    _set("dry_run", getattr(ns, "dry_run", None),
         _env_bool(env, "FACTORY_DRY_RUN"), None, False)
    _set("yes", getattr(ns, "yes", None),
         _env_bool(env, "FACTORY_YES"), None, False)
    _set("quiet", getattr(ns, "quiet", None),
         _env_bool(env, "FACTORY_QUIET"), None, False)
    _set("json_log", getattr(ns, "json_log", None),
         _env_bool(env, "FACTORY_JSON_LOG"), None, False)
    _set("no_color", getattr(ns, "no_color", None),
         _env_bool(env, "FACTORY_NO_COLOR"), None, False)

    # sup-url defaults to the resolved port (explicit url wins).
    url_cli = getattr(ns, "sup_url", None)
    url_env = _env_str(env, "EGRESS_SUP_URL")
    if _cli_present(url_cli):
        cfg["sup_url"], sources["sup_url"] = url_cli.strip(), "cli"
    elif url_env is not None:
        cfg["sup_url"], sources["sup_url"] = url_env, "env"
    else:
        cfg["sup_url"] = "http://127.0.0.1:%d" % cfg["sup_port"]
        sources["sup_url"] = ("sup-port(%s)" % sources["sup_port"]
                              if sources["sup_port"] != "code" else "code")

    _validate(cfg)
    return cfg, sources


def _validate(cfg):
    """Fail-fast on nonsense (exit 2, names not values)."""
    if cfg["egress_mode"] not in ("direct", "tunnel"):
        _fail("factory/run: bad EGRESS_MODE %r "
              "(want direct|tunnel)" % cfg["egress_mode"])
    if cfg["llm_provider"] not in ("zen", "avalai", "google"):
        _fail("factory/run: bad provider %r"
              % cfg["llm_provider"])
    if (cfg["limit"] or 0) < 0:
        _fail("factory/run: --limit must be >= 0")
    if cfg["sleep_secs"] < 0:
        _fail("factory/run: --sleep-secs must be >= 0")
    if cfg["cooldown_secs"] <= 0:
        _fail("factory/run: --cooldown-secs must be > 0")
    if not 1 <= cfg["sup_port"] <= 65535:
        _fail("factory/run: --sup-port must be 1..65535")
    if (cfg["max_429_strikes"] or 0) < 1:
        _fail("factory/run: --max-429-strikes must be >= 1")
    if (cfg["probe_top_n"] or 0) < 0:
        _fail("factory/run: --probe-top-n must be >= 0")
    try:
        _ttl = float(cfg["clean_ttl"])
    except (TypeError, ValueError):
        _ttl = 0.0
    if not math.isfinite(_ttl) or _ttl <= 0:
        _fail("factory/run: --clean-ttl must be > 0")


def _sup_http_health(url, token, timeout=HEALTH_TIMEOUT_S):
    """GET <url>/v1/health (loopback contract owned by the supervisor;
    shape owned by net.supervisor_health). Returns the payload dict,
    ``{"auth_error": ...}`` on HTTP 401/403 (wrong EGRESS_SUP_TOKEN),
    or None when the supervisor is down/unreachable."""
    import json as _json
    import urllib.error as _urlerror
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/health",
        headers={"Authorization": "Bearer " + (token or "")})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = _json.load(resp)
    except _urlerror.HTTPError as exc:
        if exc.code in (401, 403):
            return {"auth_error":
                    "HTTP %s from %s/v1/health (check EGRESS_SUP_TOKEN)"
                    % (exc.code, url.rstrip("/"))}
        return None
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _sup_is_healthy(payload):
    """True iff the health payload reports a usable pool (R4 hook:
    ``healthy`` iff servers are pooled; ``ok`` keeps the legacy shape)."""
    if not isinstance(payload, dict):
        return False
    if "healthy" in payload:
        return bool(payload["healthy"])
    return bool(payload.get("ok"))


def _spawn_supervisor(port, token, health_fn, sleep_fn=time.sleep,
                      timeout=SPAWN_TIMEOUT_S, clean_ttl=None,
                      cache_path=None):
    """Spawn ``tools/egress/supervisor.py --port`` and wait for health.

    Returns (pid, port) once the health check passes first (R4); raises
    RuntimeError when the supervisor never becomes healthy. The bearer
    travels in the child's environment only (never argv, never logs).
    ``clean_ttl``/``cache_path`` forward the resolved --clean-ttl/
    --cache into the child's env (EGRESS_CLEAN_TTL/
    EGRESS_CLEAN_CACHE_PATH) so the supervisor's cache-first lease
    path honors the CLI for auto-spawned supervisors; a running
    supervisor keeps whatever env it started with.
    """
    env = dict(os.environ)
    if token:
        env["EGRESS_SUP_TOKEN"] = token
    if clean_ttl is not None:
        env["EGRESS_CLEAN_TTL"] = str(clean_ttl)
    if cache_path:
        env["EGRESS_CLEAN_CACHE_PATH"] = str(cache_path)
    try:
        proc = subprocess.Popen(
            [sys.executable, SUPERVISOR_SCRIPT, "--port", str(port)],
            env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise RuntimeError("supervisor spawn failed: %s" % exc)
    url = "http://127.0.0.1:%d" % port
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                "supervisor exited (code %s) before health-check passed"
                % proc.returncode)
        if _sup_is_healthy(health_fn(url, token)):
            return proc.pid, port
        sleep_fn(SPAWN_POLL_S)
    try:
        proc.terminate()
    except OSError:
        pass
    # Reap the child so a SIGTERM-ignoring supervisor cannot linger as
    # a zombie holding the port; escalate to kill on a bounded wait.
    try:
        proc.wait(timeout=SPAWN_REAP_TIMEOUT_S)
    except Exception:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=SPAWN_REAP_TIMEOUT_S)
        except Exception:
            pass
    raise RuntimeError("supervisor on 127.0.0.1:%d never became healthy "
                       "(%ds budget)" % (port, timeout))


def ensure_supervisor(cfg, health_fn=None, spawn_fn=None,
                      sleep_fn=time.sleep):
    """R4: health-check first, auto-spawn on tunnel, refuse on
    --no-sup-spawn. Returns a small result dict (never raises for
    refusal/failure; SystemExit stays with the caller).

    ``health_fn(url, token)`` and ``spawn_fn(port, token, health_fn,
    sleep_fn, clean_ttl, cache_path)`` are injectable (hermetic tests);
    defaults are live. ``clean_ttl``/``cache_path`` carry the resolved
    --clean-ttl/--cache to the spawned child (see _spawn_supervisor).
    """
    if cfg["egress_mode"] != "tunnel":
        return {"action": "skip", "reason": "direct mode needs no VPN"}
    health = health_fn or _sup_http_health
    spawn = spawn_fn or _spawn_supervisor
    payload = health(cfg["sup_url"], cfg["sup_token"])
    if isinstance(payload, dict) and payload.get("auth_error"):
        return {"action": "failed",
                "reason": "supervisor auth error: %s (not a spawn "
                          "problem)" % payload["auth_error"]}
    if _sup_is_healthy(payload):
        return {"action": "ok", "sup_url": cfg["sup_url"],
                "servers": (payload or {}).get("servers", "?"),
                "leases": (payload or {}).get("leases", "?")}
    if cfg["no_sup_spawn"]:
        return {"action": "refused",
                "reason": "--no-sup-spawn set and no healthy supervisor "
                          "at %s" % cfg["sup_url"]}
    try:
        pid, port = spawn(cfg["sup_port"], cfg["sup_token"], health,
                          sleep_fn, clean_ttl=cfg.get("clean_ttl"),
                          cache_path=(cfg.get("cache") or None))
    except RuntimeError as exc:
        return {"action": "failed", "reason": str(exc)}
    return {"action": "spawned", "pid": pid, "port": port}


def build_pipeline_argv(cfg):
    """Forward the pipeline-owned subset to precard.pipeline.main."""
    argv = ["--sample", cfg["sample"], "--out", cfg["out"],
            "--progress-dir", cfg["progress_dir"],
            "--limit", str(cfg["limit"] or 0),
            "--sleep-secs", str(cfg["sleep_secs"]),
            "--llm-provider", cfg["llm_provider"]]
    for entry in cfg["stage_provider"] or []:
        argv += ["--stage-provider", entry]
    if cfg["precard_model"]:
        argv += ["--precard-model", cfg["precard_model"]]
    if cfg["judge_model"]:
        argv += ["--judge-model", cfg["judge_model"]]
    for entry in cfg["stage_model"] or []:
        argv += ["--stage-model", entry]
    if cfg["quiet"]:
        argv += ["--quiet"]
    if cfg["json_log"]:
        argv += ["--json-log"]
    if cfg["dry_run"]:
        argv += ["--dry-run"]
    return argv


def print_plan(cfg, sources):
    """Resolved plan to stdout (token prints as set/unset only)."""
    print("factory/run plan (precedence: cli > env > preset > code):")
    rows = [("preset", cfg["preset"]),
            ("llm-provider", cfg["llm_provider"]),
            ("precard-model", cfg["precard_model"] or "(provider default)"),
            ("judge-model", cfg["judge_model"] or "(provider default)"),
            ("stage-provider",
             ",".join(cfg["stage_provider"] or []) or "-"),
            ("stage-model", ",".join(cfg["stage_model"] or []) or "-"),
            ("egress", "%s via %s" % (cfg["egress_mode"],
                                      cfg["sup_url"]
                                      if cfg["egress_mode"] == "tunnel"
                                      else "no VPN")),
            ("sup-token",
             "set (%s)" % sources["sup_token"]
             if cfg["sup_token"] else "unset"),
            ("sample", cfg["sample"]),
            ("out", cfg["out"]),
            ("progress-dir", cfg["progress_dir"]),
            ("limit", str(cfg["limit"] or 0)),
            ("sleep-secs", str(cfg["sleep_secs"])),
            ("cooldown-secs", str(cfg["cooldown_secs"])),
            ("max-429-strikes", str(cfg["max_429_strikes"])),
            ("probe-top-n", str(cfg["probe_top_n"])),
            ("cache", cfg["cache"] or "(default: beside the pool)"),
            ("clean-ttl", str(cfg["clean_ttl"])),
            ("direct-probe", str(bool(cfg["direct_probe"]))),
            ("dry-run", str(bool(cfg["dry_run"]))),
            ("quiet", str(bool(cfg["quiet"]))),
            ("json-log", str(bool(cfg["json_log"]))),
            ("sup-spawn", str(not cfg["no_sup_spawn"])),
            ("color", str(not cfg["no_color"]))]
    _DEST = {"sup-spawn": "no_sup_spawn", "color": "no_color"}
    for key, shown in rows:
        if key == "egress":
            dest = "egress_mode"
        else:
            dest = _DEST.get(key, key.replace("-", "_"))
        src = sources.get(dest, "?")
        print("  %-14s %s (%s)" % (key + ":", shown, src))


def print_cache_line(hit, server_id="", provider=""):
    """CACHE HIT/MISS console line (thin over the net home's text)."""
    print(format_cache_line(hit, server_id, provider))


def direct_probe_telemetry(ok, provider="avalai"):
    """R8 telemetry event for the leaseless direct-first path (thin
    over the net home: hit takes no lease, miss falls back to one)."""
    return direct_probe_event(ok, provider)


def _load_supervisor_tcp_ping():
    """tcp_ping callable owned by tools/egress/supervisor.py.

    PR-0 probe seam: used as-is, never redefined here. Single shared
    import (plain ``import supervisor`` with tools/egress on sys.path):
    the file must execute exactly once per process, because it binds
    its probe functions into the shared net.TARGETS table — a second
    exec under another module name would rebind another copy's
    functions and break probe identity. Import only: no network, no
    keys, no spawn.
    """
    mod = sys.modules.get("supervisor")
    if mod is None:
        import pathlib as _pathlib
        _dir = str(_pathlib.Path(SUPERVISOR_SCRIPT).resolve().parent)
        if _dir not in sys.path:
            sys.path.insert(0, _dir)
        import supervisor as mod
    return mod.tcp_ping


def _avalai_direct_probe(ping_fn=None):
    """One TCP handshake to the AvalAI API host:443 (R8 default).

    No keys, no lease, no model call: reachability only. Returns
    truthy ms on success, None when unreachable. ``ping_fn(host,
    port)`` is injectable (hermetic tests); default is the
    supervisor's tcp_ping. Never raises for probe failures
    (unreachable is the fallback, not an error).
    """
    from urllib.parse import urlparse
    try:
        host = urlparse(AVALAI_CHAT_URL).hostname or "api.avalai.ir"
    except Exception:  # noqa: BLE001 (URL is a const; keep a host)
        host = "api.avalai.ir"
    ping = ping_fn or _load_supervisor_tcp_ping()
    try:
        return ping(host, 443)
    except Exception:  # noqa: BLE001 (probe failure = lease fallback)
        return None


def maybe_direct_first(cfg, direct_probe_fn=None):
    """R8 AvalAI direct-first gate: the production branch on
    cfg["direct_probe"].

    Returns the telemetry event dict, or None when the gate is
    inactive (flag off or non-avalai provider: zero behavior change).
    Active: one direct reachability probe (injectable; the default is
    a TCP handshake to the AvalAI API host — no keys, no lease). Hit
    prints CACHE HIT (server=direct: no lease, no full probe) with a
    direct-ok event; miss prints CACHE MISS with a lease-fallback
    event and the caller continues the normal (lease-taking) path.
    Probe failures fall back, never raise: unreachable IS the miss.

    Probe-only framing: run() mints no per-run leases itself (leases
    live in the supervisor tunnel path / external wrappers), so the
    gate cannot bypass anything — it proves reachability and labels
    it. ``lease_taken`` is mode-aware: outside tunnel mode no lease
    path exists, so a miss continues direct and never mints a lease
    (the generic True would be false there); tunnel-mode bypass of
    downstream leases is deferred.
    """
    if not cfg.get("direct_probe") \
            or cfg.get("llm_provider") != "avalai":
        return None
    probe = direct_probe_fn or _avalai_direct_probe
    try:
        ok = bool(probe())
    except Exception:  # noqa: BLE001 (probe failure = lease fallback)
        ok = False
    event = direct_probe_telemetry(ok, "avalai")
    if cfg.get("egress_mode") != "tunnel":
        event["lease_taken"] = False
    if ok:
        print_cache_line(True, "direct", "avalai")
    else:
        print_cache_line(False, "", "avalai")
    print("direct-probe: %s (lease_taken=%s)"
          % (event["outcome"], event["lease_taken"]))
    return event


def print_models():
    """--list-models: known precard models + cost labels.

    No network, no writes. Every entry comes from the net table
    (R3/R5): (provider, leg) -> model (cost). Costs are "free" (zen
    chain) or "paid" (avalai/google legs).
    """
    print("precard models:")
    print("  avalai default: %s (paid)" % AVALAI_PRECARD_MODEL)
    print("  google default: %s (paid)" % GOOGLE_PRECARD_MODEL)
    print("  zen: chain models (free)")
    for leg in LEGS:
        for provider in ("zen", "avalai", "google"):
            entries = LEG_FALLBACKS.get((provider, leg), ())
            if not entries:
                continue
            print("    %s/%s: %s" % (
                provider, leg,
                ", ".join("%s (%s)" % (model, cost)
                          for model, cost in entries)))


def run(argv=None, env_map=None, health_fn=None, spawn_fn=None,
        pipeline_main_fn=None, sleep_fn=time.sleep,
        direct_probe_fn=None):
    """Orchestrate: parse -> resolve -> plan -> egress ensure -> pipeline.

    Returns the process exit code (pipeline SystemExit propagates, same
    as calling the pipeline directly). ``health_fn``/``spawn_fn``/
    ``pipeline_main_fn`` inject fakes (hermetic tests); ``env_map``
    replaces ``os.environ``. ``direct_probe_fn`` injects the R8 AvalAI
    reachability probe (None uses the TCP default; never called unless
    --direct-probe/AVALAI_DIRECT_FIRST is set on an avalai run outside
    --dry-run).
    """
    ns = parse_args(argv)
    if ns.list_models:
        print_models()
        return 0
    cfg, sources = resolve_config(ns, env_map)
    print_plan(cfg, sources)
    if cfg["dry_run"]:
        # No network, no writes, supervisor untouched: the pipeline
        # dry-run only reads the sample + progress JSONs.
        print("dry-run: no network, no writes, supervisor untouched")
        pipe = pipeline_main_fn or pipeline_main
        return pipe(build_pipeline_argv(cfg))
    # R8 direct-first: leaseless AvalAI attempt with telemetry; a miss
    # falls back to the normal path below (the run continues either
    # way — the gate only adds the probe + lines, never a refusal).
    maybe_direct_first(cfg, direct_probe_fn=direct_probe_fn)
    result = ensure_supervisor(cfg, health_fn=health_fn,
                               spawn_fn=spawn_fn, sleep_fn=sleep_fn)
    action = result.get("action")
    if action == "spawned":
        # R4: pid + port go to stdout after the health-check passed.
        print("supervisor spawned: pid=%s port=%s (health-check passed)"
              % (result["pid"], result["port"]))
    elif action == "ok":
        print("supervisor: healthy at %s (servers=%s leases=%s)"
              % (result.get("sup_url"), result.get("servers"),
                 result.get("leases")))
    elif action == "skip":
        print("supervisor: skipped (%s)" % result.get("reason"))
    elif action == "refused":
        print("factory/run: refusing to run: %s "
              "(pass --sup-spawn to auto-spawn)" % result.get("reason"),
              file=sys.stderr)
        return 2
    else:
        print("factory/run: supervisor unavailable: %s"
              % result.get("reason"), file=sys.stderr)
        return 2
    pipe = pipeline_main_fn or pipeline_main
    return pipe(build_pipeline_argv(cfg))


def main(argv=None):
    """Real entry (``python -m factory.run``)."""
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
