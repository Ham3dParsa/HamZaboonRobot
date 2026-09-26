"""کنسول کارخانه داده — linker-line local WebUI.

Thin adapter (no engine logic here): the CLI + engine stay the system of
record. Every UI run spawns the exact receipt command shown on screen
(linking flow: ``python -m factory.linking.cli link``), so any run
replays identically from a terminal.

Usage:
    python factory/webui/server.py [--host <ip>] [--port 5561]
    Open http://127.0.0.1:5561 on this machine, or http://<lan-ip>:5561
    from a tablet on the LAN (plain start binds all interfaces, so it
    is LAN-visible with no flags; set HAMZABAN_WEBUI_HOST or pass
    --host to override, e.g. --host 127.0.0.1 for loopback-only).

Screens (four): compose a run, watch a run live, compare a run against
gold labels, and a full guide. Safety: key VALUES never appear in pages,
logs, or streams (names + booleans only); custom runs (sample without gold
sense ids, or any run on an operator-defined custom provider profile)
carry a non-comparable watermark.

Operator data (never code) lives next to runs:
    runs/               dated parents ``YYYY-MM-DD/<UTC-timestamp>_<id>``
    presets/            versioned named presets (plain JSON, one file each)
    provider_profiles/  operator-defined custom provider profiles (plain JSON)
    operator_keys.json  pasted provider keys, encrypted via
                        ``services/db/key_crypto.py`` (fail-closed, names only)
"""

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import argparse
import datetime
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import uuid

from flask import Flask, jsonify, request, send_from_directory

from factory.precard import provider_registry
from factory.precard.accounting import source_item_key

app = Flask(__name__, static_folder=None)

HOST = "127.0.0.1"
PORT = 5561

#: Plain-start bind: all interfaces (loopback and LAN both work, so a
#: plain start is LAN-visible with no flags).
ALL_INTERFACES = "0.0.0.0"

HOST_ENV_VAR = "HAMZABAN_WEBUI_HOST"
PORT_ENV_VAR = "HAMZABAN_WEBUI_PORT"


def _detect_lan_ipv4():
    """Machine LAN IPv4 for tablet access ("" when undetectable).

    Local-only, zero traffic: a UDP connect() against a public address
    never transmits — it only selects the outbound interface whose
    address we read back. Fallback is the platform address list.
    Loopback and link-local are excluded; "" means the caller binds
    loopback instead. No I/O beyond sockets, no secret values.
    """
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            hit = sock.getsockname()[0]
        finally:
            sock.close()
        if hit and not str(hit).startswith("127.") \
                and str(hit) != "0.0.0.0":
            return str(hit)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ip = (info[4] or [None])[0] if len(info) > 4 else None
            text = str(ip or "")
            if text and not text.startswith("127.") \
                    and not text.startswith("169.254."):
                return text
    except OSError:
        pass
    return ""


def _default_host():
    """All interfaces unless HAMZABAN_WEBUI_HOST names another one.

    Precedence: explicit HAMZABAN_WEBUI_HOST, else all-interfaces
    (loopback and LAN both work, so plain start is LAN-visible with
    no flags). An explicit --host flag still overrides this default
    at the argparse layer (e.g. 127.0.0.1 for loopback-only).
    ``_detect_lan_ipv4`` stays for the boot-receipt LAN note only —
    it no longer selects the bind address.
    """
    explicit = (os.environ.get(HOST_ENV_VAR) or "").strip()
    if explicit:
        return explicit
    return ALL_INTERFACES


def _default_port():
    """Standard port unless HAMZABAN_WEBUI_PORT holds an integer."""
    raw = (os.environ.get(PORT_ENV_VAR) or "").strip()
    if not raw:
        return PORT
    try:
        return int(raw)
    except (TypeError, ValueError):
        return PORT


def parse_server_args(argv=None):
    """CLI flags for serving the console (tablet access included).

    ``--host`` defaults to HAMZABAN_WEBUI_HOST else all-interfaces
    (0.0.0.0 — loopback and LAN both work); pass --host 127.0.0.1
    for loopback-only. ``--port`` (int) defaults to
    HAMZABAN_WEBUI_PORT else 5561.
    Hermetic: no I/O, no behavior change to any route.
    """
    parser = argparse.ArgumentParser(
        description="HamZaban linker-line local WebUI console.")
    parser.add_argument("--host", default=_default_host(),
                        help="interface to bind (default: %s else %s; "
                        "pass 127.0.0.1 for loopback-only)"
                        % (HOST_ENV_VAR, ALL_INTERFACES))
    parser.add_argument("--port", type=int, default=_default_port(),
                        help="port to bind (default: %s else %d)"
                        % (PORT_ENV_VAR, PORT))
    return parser.parse_args(argv)
RUNS_DIR = os.path.join(SCRIPT_DIR, "runs")
REGISTRY_PATH = os.path.join(SCRIPT_DIR, "runs.json")
PRESETS_DIR = os.path.join(SCRIPT_DIR, "presets")
PROFILES_DIR = os.path.join(SCRIPT_DIR, "provider_profiles")
OPERATOR_KEYS_PATH = os.path.join(SCRIPT_DIR, "operator_keys.json")
KEY_VAR_MAP_PATH = os.path.join(SCRIPT_DIR, "provider_key_vars.json")
MASTER_VAR = "AI_MASTER_KEY"

#: Supervisor bearer variable (name only — the value is pasted once in the
#: providers panel, stored encrypted in the operator store, and never
#: displayed, logged, or returned).
SUPERVISOR_TOKEN_VAR = "EGRESS_SUP_TOKEN"

FACTORY_ENV_PATH = os.path.abspath(
    os.path.join(PROJECT_ROOT, "factory", ".env"))

RESUME_MODES = ("on", "off", "plan")
NON_COMPARABLE_WATERMARK = "CUSTOM — NON-COMPARABLE"

# Re-entrant: request handlers call _poll_proc() while already holding this
# lock (a plain Lock deadlocked the server as soon as any run exited).
_lock = threading.RLock()
_procs = {}

_RUN_NAME_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}_[0-9a-f]{12}$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KEY_VAR_RX = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_PRESET_NAME_RX = re.compile(r"^[^/\\]{1,64}$")


# ─── Pure adapter helpers (engine owns all domain logic) ─────────────

def _custom_profile_names():
    """Operator-defined provider profile names (data, never the code registry)."""
    try:
        names = []
        for entry in sorted(os.listdir(PROFILES_DIR)):
            if not entry.endswith(".json"):
                continue
            try:
                rec = json.load(open(os.path.join(PROFILES_DIR, entry),
                                     encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("name"):
                names.append(str(rec["name"]))
        return names
    except OSError:
        return []


def _is_known_provider(provider):
    return (provider in provider_registry.provider_names()
            or provider in _custom_profile_names())


def _is_custom_profile(provider):
    return provider in _custom_profile_names()


def build_cli_argv(fields):
    """argv list for ``python -m factory.precard`` from compose fields.

    Fail-closed: unknown provider, bad limit, bad concurrency, or bad
    resume mode raises ValueError and no command is built. Empty optional
    fields mean "engine default" (never re-stated here).

    Operator custom profiles (data files under provider_profiles/) are
    accepted as provider names so the run is recorded and stamped; the
    engine's own preflight gate still rejects names outside its code
    registry fail-closed, and the run log shows why.
    """
    provider = str((fields or {}).get("provider") or "").strip()
    if not _is_known_provider(provider):
        raise ValueError("unknown provider: %r" % provider)
    try:
        limit = int((fields or {}).get("limit", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer >= 0")
    if limit < 0:
        raise ValueError("limit must be >= 0")
    raw_conc = (fields or {}).get("concurrency", 0)
    try:
        concurrency = int(raw_conc or 0)
    except (TypeError, ValueError):
        raise ValueError("concurrency must be an integer 1..10 or empty")
    if concurrency < 0 or concurrency > 10:
        raise ValueError("concurrency must be an integer 1..10 or empty")
    if concurrency == 0:
        concurrency = 0
    resume = str((fields or {}).get("resume", "on") or "on").strip()
    if resume not in RESUME_MODES:
        raise ValueError("resume must be one of %s" % ("/".join(RESUME_MODES),))
    argv = [sys.executable, "-m", "factory.precard",
            "--llm-provider", provider, "--json-log"]
    model = str((fields or {}).get("model") or "").strip()
    if model:
        argv += ["--precard-model", model]
    sample = str((fields or {}).get("sample") or "").strip()
    if sample:
        argv += ["--sample", sample]
    out = str((fields or {}).get("out") or "").strip()
    if out:
        argv += ["--out", out]
    progress_dir = str((fields or {}).get("progress_dir") or "").strip()
    if progress_dir:
        argv += ["--progress-dir", progress_dir]
    if limit:
        argv += ["--limit", str(limit)]
    if concurrency:
        argv += ["--concurrency", str(concurrency)]
    if resume == "off":
        argv += ["--no-resume"]
    elif resume == "plan":
        argv += ["--resume"]
    return argv


def cli_equivalent(argv):
    """Exact command-line string for identical replay (display only)."""
    return shlex.join(["python" if a == sys.executable else a for a in argv])


def build_linking_cli_argv(fields):
    """argv list for the linking line's own command (display only).

    ``python -m factory.linking.cli link --words <input> --out <output>``
    from the spare run-form fields. Fail-closed: empty words/out raise
    ValueError (the CLI declares both ``required=True`` — omitting them
    would spawn a command guaranteed to exit 2). Provider/model ride
    the run record, not this offline command — stated, never faked.
    """
    argv = [sys.executable, "-m", "factory.linking.cli", "link"]
    words = str((fields or {}).get("sample") or "").strip()
    if not words:
        raise ValueError(
            "فایل ورودی انتخاب نشده است (فهرست واژه لازم است).")
    argv += ["--words", words]
    out = str((fields or {}).get("out") or "").strip()
    if not out:
        raise ValueError("مسیر خروجی انتخاب نشده است.")
    argv += ["--out", out]
    return argv


def linking_cli_equivalent(argv):
    """Exact linking command-line string (display only)."""
    return shlex.join(["python" if a == sys.executable else a for a in argv])


#: Domain router: flow name -> its own runner (builder + shower).
#: The run-creation route executes exactly the receipt command built
#: here — linking flow never touches the precard runner. A future
#: precard flow reuses its own entry without touching the router.
FLOW_RUNNERS = {
    "linking": {"build": build_linking_cli_argv,
                "show": linking_cli_equivalent},
    "precard": {"build": build_cli_argv, "show": cli_equivalent},
}


def build_run_command(flow, fields):
    """(argv, shown) for one flow via the domain router.

    Fail-closed: unknown flow raises ValueError and nothing is built.
    Provider/model ride the run record, not the linking argv (the
    linking runner takes only what it accepts — no flags invented).
    """
    name = str(flow or "linking").strip() or "linking"
    runner = FLOW_RUNNERS.get(name)
    if runner is None:
        raise ValueError("unknown flow: %r" % flow)
    argv = runner["build"](fields)
    return argv, runner["show"](argv)


def _factory_env_value(var):
    """One value from the gitignored factory env file ("" when absent).

    Reads the file directly (never prints or logs values); the caller
    only tests for emptiness or forwards the value in-memory.
    """
    try:
        with open(FACTORY_ENV_PATH, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == var:
                    return v.strip().strip("'\"")
    except OSError:
        pass
    return ""


def _load_factory_master_into_process():
    """Make the persisted master key visible to the crypto seam.

    The crypto helper reads the master from process config at call
    time; after a restart the shell may not carry it, so the gitignored
    factory file value (when present) is mirrored into the process
    environment and the process config. Names only in logs — the value
    is never printed, returned, or logged.
    """
    if os.environ.get(MASTER_VAR):
        try:
            import config as _cfg
            if not getattr(_cfg, MASTER_VAR, ""):
                setattr(_cfg, MASTER_VAR, os.environ[MASTER_VAR])
        except Exception:
            pass
        return True
    hit = _factory_env_value(MASTER_VAR)
    if not hit:
        return False
    os.environ[MASTER_VAR] = hit
    try:
        import config as _cfg
        setattr(_cfg, MASTER_VAR, hit)
    except Exception:
        pass
    return True


_load_factory_master_into_process()


def master_status():
    """Secure-storage readiness: NAME + boolean only, never the value."""
    _load_factory_master_into_process()
    try:
        from services.db import key_crypto
        capable = key_crypto._fernet() is not None
    except Exception:
        capable = False
    return {"var": MASTER_VAR, "configured": bool(capable)}


def ensure_factory_master_key(confirmed=False):
    """Generate-and-store the master key on first use (operator-confirmed).

    When no master resolves anywhere, generates a fresh Fernet key and
    appends it to the gitignored factory env file (created when
    missing), then mirrors it into the process. Requires confirmed=True
    (the operator pressed the button); the value is never displayed,
    returned, or logged — names only out. (ok, error, created)
    """
    if master_status().get("configured"):
        return True, "", False
    if not confirmed:
        return False, ("secure storage is not active yet "
                       "(confirm once to generate it)"), False
    try:
        from cryptography.fernet import Fernet
        fresh = Fernet.generate_key().decode()
    except Exception:
        return False, "cannot generate a key on this machine", False
    try:
        os.makedirs(os.path.dirname(FACTORY_ENV_PATH), exist_ok=True)
        with open(FACTORY_ENV_PATH, "a", encoding="utf-8") as handle:
            handle.write("%s=%s\n" % (MASTER_VAR, fresh))
        try:
            os.chmod(FACTORY_ENV_PATH, 0o600)
        except OSError:
            pass
    except OSError as exc:
        return False, "cannot write the factory env file: %s" % exc, False
    os.environ[MASTER_VAR] = fresh
    try:
        import config as _cfg
        setattr(_cfg, MASTER_VAR, fresh)
    except Exception:
        pass
    # Names only in every surface: never echo the value back.
    app.logger.info("factory master key generated for %s", MASTER_VAR)
    return True, "", True


def _key_var_mapping():
    """Operator's per-provider key-variable mapping (NAMES only)."""
    try:
        data = json.load(open(KEY_VAR_MAP_PATH, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_key_var_mapping(mapping):
    tmp = KEY_VAR_MAP_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(mapping, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, KEY_VAR_MAP_PATH)


def _resolve_any(vars_):
    """True when any key var resolves via env or the factory file.

    Unified loader order: process env first, then the gitignored
    factory env file. Names in, boolean out — values never read here.
    """
    try:
        from factory.precard.provider_lease_policy import (
            resolve_key as _resolve,
        )
    except Exception:
        _resolve = None
    for var in vars_ or ():
        if not var:
            continue
        if os.environ.get(var):
            return True
        if _resolve is not None:
            try:
                if _resolve(var):
                    return True
            except Exception:
                continue
    return False


def _operator_key_values():
    """{key_var: plaintext} of operator-stored keys (in-memory only).

    Decrypts via the repo's key_crypto seam; fail-closed (undecryptable
    entries resolve to "" and are skipped). Values are only ever used for
    log scrubbing — never returned, logged, or displayed.
    """
    try:
        from services.db import key_crypto
    except Exception:
        return {}
    try:
        stored = json.load(open(OPERATOR_KEYS_PATH, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    if isinstance(stored, dict):
        for var, token in stored.items():
            try:
                plain = key_crypto.decrypt_secret(token or "")
            except Exception:
                plain = ""
            if plain:
                out[str(var)] = plain
    return out


def key_presence(clean_fn=None):
    """Provider key status: NAMES + booleans only, values never read.

    A registry provider counts as ready when its effective key var
    (operator mapping or registry refs) resolves via the unified loader
    (process env, then the gitignored factory env file) OR an
    operator-pasted key for the same var name decrypts (fail-closed).
    Tunnel-route Google rows additionally carry ``clean_exit``: the
    fresh whitelisted exit head ("" when no verified exit exists —
    the compose routing line notes it when present).

    The whitelist head arrives via ``clean_fn`` (tests pass fakes —
    never the real cache file); the default is the T5 linker adapter
    (``google_clean.fresh_clean_exits``), resolved at call time.
    """
    stored = _operator_key_values()
    try:
        from factory.linking import google_clean as _gc
        clean = clean_fn if clean_fn is not None else _gc.fresh_clean_exits
        _clean_head = (clean() or [""])[0] or ""
    except Exception:
        _clean_head = ""
    rows = []
    for name in provider_registry.provider_names():
        try:
            refs = list(provider_registry.key_ref_for(name, "G1")
                        + provider_registry.key_ref_for(name, "G2"))
        except Exception:
            refs = []
        effective = _provider_key_var(name)
        ordered = []
        for var in ([effective] if effective else []) + refs:
            if var and var not in ordered:
                ordered.append(var)
        ready = _resolve_any(ordered) or any(
            v in stored for v in ordered)
        route, route_reason = route_for_provider(name)
        rows.append({
            "name": name,
            "key_vars": ordered,
            "key_var": effective,
            "has_key": bool(ready),
            "route": route,
            "route_reason": route_reason,
            "clean_exit": (_clean_head if route == "leased"
                           and name == "google" else ""),
        })
    return rows


def operator_key_names():
    """Names of operator-stored keys (names only, never values)."""
    try:
        stored = json.load(open(OPERATOR_KEYS_PATH, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(stored, dict):
        return []
    return sorted(str(k) for k in stored.keys())


_SECRET_RX = re.compile(
    r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*\S+")


def scrub_secrets(text, extra_values=None):
    """Redact secret-looking material from log/stream text (best-effort).

    ``extra_values`` is a pre-decrypted secret set for the hot path
    (one decrypt per run, reused per log line). When None (cold paths,
    tests, back-compat callers) values decrypt on demand. Names only
    everywhere — values never logged, returned, or displayed.
    """
    if not text:
        return text
    out = _SECRET_RX.sub(lambda m: m.group(1) + "=***", text)
    for var in list(os.environ):
        upper = var.upper()
        if "KEY" in upper or "TOKEN" in upper or "SECRET" in upper:
            val = os.environ.get(var) or ""
            if len(val) >= 8 and val in out:
                out = out.replace(val, "***")
    try:
        if extra_values is None:
            vals = _operator_key_values().values()
        else:
            vals = extra_values
        for val in vals:
            if len(val or "") >= 8 and val in out:
                out = out.replace(val, "***")
    except Exception:
        pass
    return out


def parse_run_events(text):
    """Tolerant JSONL parse of run_events.jsonl content (skips bad lines)."""
    events = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            events.append(rec)
    return events


def run_rows_by_key(out_path):
    """{key: sense_id} from a precard.jsonl result file (skips bad lines)."""
    return {k: v.get("sense_id", "")
            for k, v in run_rows_full_by_key(out_path).items()}


def run_rows_full_by_key(out_path):
    """{key: full-row-dict} from a precard.jsonl result file.

    Keeps the human-readable fields the benchmark screen shows first
    (text/kind/pos/en_def gloss); later duplicate keys win, bad lines
    are skipped. Pure reader — no engine logic.
    """
    rows = {}
    try:
        handle = open(out_path, encoding="utf-8")
    except OSError:
        return rows
    with handle:
        for line in handle:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("key"):
                rows[rec["key"]] = rec
    return rows


def sample_rows_full_by_key(sample_path):
    """{key: full-row-dict} from a linking words input file (word list)."""
    rows = {}
    try:
        data = json.load(open(sample_path, encoding="utf-8"))
    except (OSError, ValueError):
        return rows
    if not isinstance(data, list):
        return rows
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            key = source_item_key(row)
        except (KeyError, TypeError):
            continue
        rows[key] = row
    return rows


def gold_rows_by_key(sample_path):
    """{key: sense_id} gold from a linking words input file (word list)."""
    gold = {}
    try:
        data = json.load(open(sample_path, encoding="utf-8"))
    except (OSError, ValueError):
        return gold
    if not isinstance(data, list):
        return gold
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            key = source_item_key(row)
        except (KeyError, TypeError):
            continue
        gold[key] = row.get("sense_id", "") or ""
    return gold


def validate_sample_file(sample_path):
    """Pre-launch words-input check: (ok, error_fa, info).

    ok True -> info {"rows": n, "gold": m}. ok False -> error_fa names the
    exact problem in plain Persian: missing file, unreadable/corrupt JSON,
    bad top-level shape, empty list, or the first bad row (not a dict,
    missing kind/text, bad kind value).

    Polymorphic: whole-file JSON that fails to parse falls back to the
    linking line-based word list (the ``read_wordlist`` rule — ``{``
    lines parse as objects extracting text/lemma, other lines read
    directly as words), so plain text files and screening JSONL outputs
    validate with gold 0 instead of failing as corrupt JSON. A
    line-based read with zero words keeps the original JSON error.
    """
    path = str(sample_path or "").strip()
    if not path:
        return False, "فایل ورودی انتخاب نشده است (فهرست واژه لازم است).", {}
    if not os.path.isfile(path):
        return False, "فایل ورودی پیدا نشد: %s" % path, {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError:
        return False, "فایل ورودی خوانا نیست (JSON خراب است): %s" % path, {}
    except ValueError:
        from factory.linking import cli as _link_cli
        try:
            words = _link_cli.read_wordlist(path)
        except (OSError, ValueError):
            words = []
        if words:
            return True, "", {"rows": len(words), "gold": 0}
        return False, "فایل ورودی خوانا نیست (JSON خراب است): %s" % path, {}
    if not isinstance(data, list):
        return False, ("شکل فایل ورودی درست نیست: فهرست واژه (آرایه) لازم است، "
                       "اما این فایل %s است." % type(data).__name__), {}
    if not data:
        return False, "فایل ورودی خالی است (هیچ ردیفی ندارد).", {}
    gold = 0
    for idx, row in enumerate(data):
        if not isinstance(row, dict):
            return False, ("ردیف %d فایل ورودی یک شیء نیست (نوع: %s)."
                           % (idx + 1, type(row).__name__)), {}
        kind = row.get("kind")
        text = row.get("text")
        if kind not in ("word", "phrase"):
            return False, ("ردیف %d فایل ورودی فیلد kind درستی ندارد "
                           "(باید word یا phrase باشد)." % (idx + 1)), {}
        if not isinstance(text, str) or not text.strip():
            return False, ("ردیف %d فایل ورودی فیلد text ندارد "
                           "(متن خالی است)." % (idx + 1)), {}
        if row.get("sense_id"):
            gold += 1
    return True, "", {"rows": len(data), "gold": gold}


def _parent_of_run(run_name):
    date = (run_name.split("T")[0] if "T" in run_name else "")
    return date if _DATE_RX.match(date or "") else "undated"


def resolve_run_paths(fields, run_name):
    """Resolved (out, progress_dir, rundir) for a run before launch.

    Empty out/progress_dir mean "inside this run's own folder" (never
    re-stated to the engine as a default — the adapter fills them in).
    """
    rundir = os.path.join(RUNS_DIR, _parent_of_run(run_name), run_name)
    out = str((fields or {}).get("out") or "").strip() or os.path.join(
        rundir, "precard.jsonl")
    progress_dir = str((fields or {}).get("progress_dir") or "").strip() or os.path.join(
        rundir, "progress")
    return out, progress_dir, rundir


def score_against_gold(run_rows, gold_rows):
    """Accuracy over joined keys; mismatches listed (pure, no I/O)."""
    joined = sorted(set(run_rows) & set(gold_rows))
    mismatches = []
    matched = 0
    for key in joined:
        want, got = gold_rows[key], run_rows.get(key, "")
        if got == want:
            matched += 1
        else:
            mismatches.append({"key": key, "gold": want, "predicted": got})
    total = len(joined)
    return {
        "total": total,
        "matched": matched,
        "mismatched": len(mismatches),
        "accuracy": (matched / total) if total else 0.0,
        "mismatches": mismatches,
    }


def comparability(gold_rows, run_rows, profile=None):
    """(comparable, reason): custom runs carry the non-comparable watermark.

    A run is comparable iff its gold sample joins the run output on >=1
    key WITH a gold sense_id — and it is NOT on an operator custom
    profile (custom profiles are always non-comparable). Anything else is
    custom and must not be scored.
    """
    if profile:
        return False, (
            "%s: custom provider profile %r is never scored "
            "(operator data — scoring refused)" % (NON_COMPARABLE_WATERMARK,
                                                   profile))
    joined = set(run_rows) & set(gold_rows)
    gold_joined = [k for k in joined if gold_rows.get(k)]
    if not gold_joined:
        return False, (
            "%s: sample carries no gold sense ids for this run's keys "
            "(custom sample — scoring refused)" % NON_COMPARABLE_WATERMARK)
    return True, "پیوند طلا روی %d کلید" % len(gold_joined)


def judge_preset_schema():
    """Judge knob schema mirroring the bot's own preset wording.

    Field names/defaults come from the single owner
    (services.ai.preset_fields); labels + help wording come from the
    bot admin wizard (handlers.admin_ai_wizard FIELD_LABELS/help —
    read-only, never copied). Rate caps (max_rpm/max_tpm/
    max_daily_req), pacing (max_concurrency), timeout
    (timeout_seconds) are display facts (the precard engine takes
    pacing/timeout through its own run knobs, not per-judge keys —
    stated, never faked). Temperature is LOCKED: the engine
    transports pin 0.0 for determinism, so the field shows locked
    with the reason instead of a fake control.
    """
    try:
        from services.ai import preset_fields as _pf
    except Exception:
        _pf = None
    try:
        from handlers import admin_ai_wizard as _wiz
        _labels = dict(getattr(_wiz, "FIELD_LABELS", {}) or {})
        _help = dict(getattr(_wiz, "_FIELD_HELP", {}) or {})
    except Exception:
        _labels, _help = {}, {}

    def _meta(field, fallback_label, fallback_help):
        default = None
        if _pf is not None:
            try:
                default = _pf.write_default(field)
            except Exception:
                default = None
        return {
            "field": field,
            "label": _labels.get(field, fallback_label),
            "help": _help.get(field, fallback_help),
            "default": default,
        }

    schema = {
        "rate_caps": [
            _meta("max_rpm", "RPM Limit",
                  "بیشترین تعداد درخواست در هر دقیقه. "
                  "صفر = بدون محدودیت."),
            _meta("max_tpm", "Max TPM",
                  "بیشترین تعداد توکن ورودی و خروجی در هر دقیقه. "
                  "صفر = بدون محدودیت."),
            _meta("max_daily_req", "Max Daily Requests",
                  "سقف تعداد درخواست به این پریست در هر روز. "
                  "صفر = بدون محدودیت."),
        ],
        "pacing": [
            _meta("max_concurrency", "Concurrency",
                  "تعداد درخواست‌هایی که هم‌زمان به این "
                  "سرویس‌دهنده فرستاده می‌شود."),
        ],
        "timeout": [
            _meta("timeout_seconds", "Timeout (s)",
                  "مدت زمان انتظار برای پاسخ از سرویس‌دهنده "
                  "(به ثانیه)."),
        ],
        "temperature": {
            "field": "temperature",
            "label": _labels.get("temperature", "Temperature"),
            "supported": False,
            "locked": True,
            "fixed": 0.0,
            "reason": ("locked: the engine transports pin temperature "
                       "0.0 for determinism — no knob exists, so none "
                       "is shown as control"),
        },
    }
    return schema


def provider_model_list(provider, timeout=30, *, lease_fn=None,
                         target_fn=None, clean_fn=None, verify_fn=None,
                         remember_fn=None, report_fn=None, tunneled=None,
                         env_map=None, file_paths=None,
                         registry_fn=None, wake_fn=None, health_fn=None):
    """Server-side per-provider model list (key-gated, never faked).

    Resolves the provider key server-side (env/file/operator store —
    values in-memory only, never returned/logged/stored in the
    browser) and fetches the provider's own list endpoint: leased
    (tunnel-route) providers via models:list through OUR leased
    supervisor proxy (direct egress dies with geo-block/sanctions
    403); direct-route OpenAI-compatible rows via {base}/models with
    bearer auth. Returns
    (models_or_None, error_or_None): models is [exact ids]; error is
    an attributed plain line (provider + kind + http, never values).
    An empty real list is returned as ([], None) — never invented.

    Universal auto-wake: a leased-route provider with no supervisor
    token wakes the shared supervisor from the factory domain path in
    the background (``wake_fn`` injects the wake leg — tests pass
    fakes, never a process) and retries; the caller sees a friendly
    wait line, never a raw error. Route-based, never Google-only.

    The lease/report/remember legs arrive via the tunnel seam
    (``lease_fn``/``report_fn``/``remember_fn`` inject them — tests
    pass fakes, never the network or the real cache file); the
    key-gated list fetch itself stays here (composition fact for the
    model-picker screen, values in-memory only).
    """
    import urllib.request as _url

    name = str(provider or "").strip()
    if name not in provider_registry.provider_names():
        return None, "unknown provider: %s" % name
    try:
        row = provider_registry.resolve_provider(name) or {}
    except Exception:
        row = {}
    # Key-gated: resolve server-side only (names out, values in-memory).
    try:
        from factory.precard.provider_lease_policy import (
            resolve_key as _resolve)
    except Exception:
        _resolve = None
    stored = _operator_key_values()
    var_order = []
    try:
        eff = _provider_key_var(name)
        refs = list(provider_registry.key_ref_for(name, "G1")
                    + provider_registry.key_ref_for(name, "G2"))
        for var in ([eff] if eff else []) + refs:
            if var and var not in var_order:
                var_order.append(var)
    except Exception:
        var_order = []
    key_value = ""
    for var in var_order:
        if _resolve is not None:
            try:
                hit = _resolve(var)
            except Exception:
                hit = ""
            if hit:
                key_value = hit
                break
        if not key_value and var in stored:
            key_value = stored[var]
            break
    if not key_value:
        return None, ("no key resolves for %s (%s) — paste the key in "
                      "the providers panel first"
                      % (name, "+".join(var_order) or "no key refs"))
    protocol = str(row.get("protocol") or "")
    route, _route_reason = route_for_provider(
        name, registry_fn=registry_fn, tunneled=tunneled,
        env_map=env_map, file_paths=file_paths)
    if route == "leased":
        lease, lease_error = lease_tunnel_for_run(
            name, lease_fn=lease_fn, target_fn=target_fn,
            clean_fn=clean_fn, verify_fn=verify_fn, tunneled=tunneled,
            env_map=env_map, file_paths=file_paths,
            wake_fn=wake_fn, health_fn=health_fn)
        if lease_error:
            return None, ("%s models:list refused: %s"
                          % (name, lease_error))
        proxy_url = str((lease or {}).get("proxy_url") or "")
        opener = _url.build_opener(_url.ProxyHandler(
            {"http": proxy_url, "https": proxy_url})) if proxy_url \
            else _url.build_opener()
        if protocol == "gemini_rest" or name == "google":
            endpoint = ("https://generativelanguage.googleapis.com/"
                        "v1beta/models?pageSize=200")
            headers = {"x-goog-api-key": key_value}
            ids_of = _google_model_ids
        else:
            base = str(row.get("base_url") or "")
            endpoint = _openai_models_endpoint(base)
            if not endpoint:
                return None, ("%s has no listable base address "
                               "(no /models endpoint)" % name)
            headers = {"Authorization": "Bearer " + key_value}
            ids_of = _openai_model_ids
        req = _url.Request(endpoint, headers=headers)
        try:
            import time as _time
            _start = _time.monotonic()
            with opener.open(req, timeout=timeout) as resp:
                data = json.load(resp)
            _latency_ms = int((_time.monotonic() - _start) * 1000)
        except Exception as exc:
            _report_lease_outcome(lease, name, exc, report_fn=report_fn)
            return None, _attributed_error(name, exc)
        _report_lease_outcome(lease, name, None, report_fn=report_fn)
        # Proven exit: a successful list through OUR lease is a clean
        # signal for ANY leased-route provider — warm its own
        # provider-scoped clean cache so the next lease prefers it
        # (supervisor cache-first, no restart; namespaces never leak
        # across providers). Best-effort, ours only.
        try:
            from factory.linking import google_clean as _gc_m
            remember = (remember_fn if remember_fn is not None
                        else _gc_m.remember_success)
            _sid = str((lease or {}).get("server_id") or "")
            if _sid:
                remember(_sid, name, _latency_ms)
        except Exception:
            pass
        return ids_of(data), None
    base = str(row.get("base_url") or "")
    endpoint = _openai_models_endpoint(base)
    if not endpoint:
        return None, ("%s has no listable base address "
                      "(no /models endpoint)" % name)
    req = _url.Request(endpoint, headers={
        "Authorization": "Bearer " + key_value})
    try:
        with _url.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as exc:
        return None, _attributed_error(name, exc)
    return _openai_model_ids(data), None


def _report_lease_outcome(lease, provider, exc, report_fn=None):
    """Report OUR list-fetch lease outcome (best-effort, never raises).

    Success reports "ok" and a 429 reports "http429" (OUR server cools
    for the provider) behind the probe report seam (``report_fn``
    injects the client — tests pass fakes, never the network); any
    other failure reports nothing (exit codes alone prove no network
    health — same rule as run_with_lease.py).
    """
    try:
        lease_id = str((lease or {}).get("lease_id") or "")
    except Exception:
        return
    if not lease_id:
        return
    if exc is None:
        report_run_lease(lease_id, provider, True, report_fn=report_fn)
        return
    import urllib.error as _httperr
    if isinstance(exc, _httperr.HTTPError) and exc.code == 429:
        if report_fn is None and not _supervisor_token():
            return
        try:
            from factory.linking import probe_providers as _pp
            _pp.report_outcome(lease_id, "http429",
                               provider=str(provider or ""),
                               report_fn=report_fn)
        except Exception:
            pass


def _attributed_error(provider, exc):
    """Attributed fetch error line (provider + kind + http; never values)."""
    import urllib.error as _httperr
    if isinstance(exc, _httperr.HTTPError):
        return ("%s models fetch failed: http-%d (provider-side; "
                "check the key and retry)" % (provider, exc.code))
    if isinstance(exc, _httperr.URLError):
        reason = str(getattr(exc, "reason", "") or "")
        if "timed out" in reason.lower():
            return ("%s models fetch timed out (network; retry)"
                    % provider)
        return ("%s models fetch failed: url-error (network; retry)"
                % provider)
    if isinstance(exc, TimeoutError):
        return ("%s models fetch timed out (network; retry)" % provider)
    return ("%s models fetch failed: %s" % (provider,
                                            type(exc).__name__))


def _google_model_ids(data):
    """Exact model ids from a models:list payload (never invented)."""
    ids = []
    try:
        entries = (data or {}).get("models") or []
    except AttributeError:
        entries = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("name") or "")
        short = raw.split("/")[-1].strip() if raw else ""
        if short and short not in ids:
            ids.append(short)
        if len(ids) >= 200:
            break
    return ids


def _openai_models_endpoint(base_url):
    """{base}/models for an OpenAI-compatible chat base ("" when unknown)."""
    base = str(base_url or "").strip().rstrip("/")
    if not base or not base.startswith("http"):
        return ""
    if base.endswith("/chat/completions"):
        return base[: -len("/chat/completions")] + "/models"
    if base.endswith("/v1"):
        return base + "/models"
    return base.rstrip("/") + "/models"


def _openai_model_ids(data):
    """Exact model ids from an OpenAI /models payload (never invented)."""
    ids = []
    try:
        entries = (data or {}).get("data") or []
    except AttributeError:
        entries = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        mid = str(entry.get("id") or "").strip()
        if mid and mid not in ids:
            ids.append(mid)
        if len(ids) >= 200:
            break
    return ids


# ─── Engine facts (honest surface: only what the engine exposes) ───

def engine_info():
    """Facts the precard engine actually exposes (nothing invented).

    The WebUI renders exactly this: provider names come straight from
    the engine registry (Kilo is NOT ready engine-side, so it never
    appears here); ready model names are the engine's own documented
    defaults plus its documented comparison example — the engine
    exposes NO model list endpoint, NO temperature knob (transports
    pin temperature 0.0 for determinism), and NO judge-batch knob
    (JUDGE_BATCH fixed). Callers must surface the gaps, never fake them.
    """
    try:
        from factory.precard import provider_lease_policy as _lease
        avalai_model = _lease.AVALAI_PRECARD_MODEL
        google_model = _lease.GOOGLE_PRECARD_MODEL
    except Exception:
        avalai_model, google_model = "", ""
    try:
        from factory.precard.judge import (
            JUDGE_BATCH as _jb, INFLECTION_REVIEW_BATCH as _rb)
        judge_batch, review_batch = int(_jb), int(_rb)
    except Exception:
        judge_batch, review_batch = 12, 16
    try:
        from factory.precard import pipeline as _pipe
        sample_default = _pipe.DEFAULT_SAMPLE
        sleep_default = float(_pipe.SLEEP)
    except Exception:
        sample_default, sleep_default = "", 2.5
    return {
        # Exactly the engine registry — nothing more (no Kilo: not ready).
        "providers": provider_registry.provider_names(),
        "model_list": None,  # engine exposes no model list endpoint
        "default_models": {
            "avalai": avalai_model,
            "google": google_model,
            # Documented --precard-model help example (a known id to
            # copy, NOT a registry list — the engine has no list).
            "comparison_example": "deepseek-v4-flash",
        },
        "sample_default": sample_default,
        # No CLI knob: transports hard-pin temperature 0.0 (determinism).
        "temperature": {"supported": False, "fixed": 0.0},
        # Fixed batch sizes: no CLI knobs.
        "judge_batch": judge_batch,
        "inflection_review_batch": review_batch,
        # Engine pacing knob (exists, but the compose form does not
        # expose it — stated here so the UI can say so honestly).
        "sleep_secs_default": sleep_default,
        "sleep_secs_exposed": False,
        # Compose-form batching knob (async cloud-judge path only).
        "concurrency": {"min": 1, "max": 10, "default": 8,
                        "async_path_only": True},
        # Leased-vs-direct routing per provider (precard TARGETS mirror:
        # Google defaults leased — geo-block 403 direct). Shown on the
        # compose routing line BEFORE launch. Google rows additionally
        # carry clean_exit (fresh whitelisted exit head, "" when none
        # verified) so the line can note the preferred exit.
        "routing": {name: {"route": route_for_provider(name)[0],
                           "reason": route_for_provider(name)[1],
                           "clean_exit": _routing_clean_exit(name)}
                    for name in provider_registry.provider_names()},
        "google_tunnel_reason": GOOGLE_TUNNEL_REASON,
        # Judge knob schema mirroring the bot's own preset fields
        # (labels + help wording from the admin wizard, defaults from
        # the canonical preset schema; temperature locked — pinned).
        "judge_schema": judge_preset_schema(),
        "rate_limit_note": (
            "429 rotates to the next key on the same model; a "
            "ROTATE-exhausted model steps down to the next chain model; "
            "a fully-exhausted chain STOPS loud (progress flushed, "
            "resume safe). 401/403 aborts loud. Details in run.log."),
    }


def _routing_clean_exit(provider, clean_fn=None):
    """Fresh whitelisted exit head for leased Google ("" otherwise).

    The head arrives via ``clean_fn`` (tests pass fakes — never the
    real cache file); the default is the T5 linker adapter
    (``google_clean.fresh_clean_exits``), resolved at call time.
    """
    try:
        route, _reason = route_for_provider(provider)
    except Exception:
        return ""
    if route != "leased" or str(provider or "").strip() != "google":
        return ""
    try:
        from factory.linking import google_clean as _gc_e
        clean = clean_fn if clean_fn is not None else _gc_e.fresh_clean_exits
        return (clean() or [""])[0] or ""
    except Exception:
        return ""


# ─── Server-side file browser (localhost console only) ────────────

_FILE_LIST_LIMIT = 500


def _browse_roots():
    """Operator starting points: bundled samples, this console's runs, drives."""
    roots = []
    try:
        from factory.precard import pipeline as _pipe
        pilot = os.path.dirname(_pipe.DEFAULT_SAMPLE)
        roots.append({"path": pilot, "label": "bundled samples (pilot)"})
    except Exception:
        pass
    roots.append({"path": RUNS_DIR, "label": "this console runs"})
    try:
        home = os.path.expanduser("~")
        if home and os.path.isdir(home):
            roots.append({"path": home, "label": "home"})
    except Exception:
        pass
    for drive in ("C:\\", "D:\\", "W:\\"):
        if os.path.isdir(drive) and not any(
                r["path"] == drive for r in roots):
            roots.append({"path": drive, "label": "drive %s" % drive})
    seen, out = set(), []
    for root in roots:
        # Only existing dirs (a moved/deleted data folder drops out
        # instead of opening a dead dialog).
        if root["path"] not in seen and os.path.isdir(root["path"]):
            seen.add(root["path"])
            out.append(root)
    return out


def _list_dir(absdir):
    """(ok, error, payload) listing of one absolute directory.

    Names + dir flags + sizes only — file contents are never read here
    (sample validation stays the separate /api/sample/validate path).
    """
    want = os.path.abspath(str(absdir or ""))
    if not want or not os.path.isdir(want):
        return False, "not a directory: %s" % absdir, {}
    try:
        entries = sorted(os.listdir(want))
    except OSError as exc:
        return False, "cannot list: %s" % exc, {}
    dirs, files = [], []
    for name in entries[:_FILE_LIST_LIMIT]:
        full = os.path.join(want, name)
        try:
            if os.path.isdir(full):
                dirs.append({"name": name, "is_dir": True})
            elif os.path.isfile(full):
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = -1
                files.append({"name": name, "is_dir": False,
                              "size": size})
        except OSError:
            continue
    parent = os.path.dirname(want.rstrip(os.sep)) or None
    return True, "", {"dir": want, "parent": parent,
                      "entries": dirs + files,
                      "truncated": len(entries) > _FILE_LIST_LIMIT}


# ─── Dated run layout (human-sortable, newest last) ──────────────────

def run_name_for(created_iso, run_id):
    """``YYYY-MM-DDTHH-MM-SS_<id>`` (UTC, filesystem-safe, sortable)."""
    try:
        stamp = datetime.datetime.fromisoformat(created_iso)
    except (TypeError, ValueError):
        stamp = datetime.datetime.now(datetime.timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    base = stamp.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    return "%s_%s" % (base, run_id)


def _migrate_record(rec):
    """Rewrite one old-layout record to the dated layout (moves dir).

    Returns True when the record changed. Missing on-disk dirs are
    rewritten without a move (no orphans, never crashes).
    """
    rundir = rec.get("dir") or ""
    base = os.path.basename(rundir.rstrip(os.sep))
    if _RUN_NAME_RX.match(base or ""):
        return False
    run_id = rec.get("id") or base or uuid.uuid4().hex[:12]
    created = rec.get("created") or ""
    run_name = run_name_for(created, run_id)
    parent = _parent_of_run(run_name)
    new_dir = os.path.join(RUNS_DIR, parent, run_name)
    old_dir = rundir
    if old_dir and old_dir != new_dir and os.path.isdir(old_dir):
        try:
            os.makedirs(os.path.dirname(new_dir), exist_ok=True)
            if not os.path.exists(new_dir):
                shutil.move(old_dir, new_dir)
        except OSError:
            return False
    for key in ("out", "progress_dir"):
        val = rec.get(key) or ""
        if old_dir and val.startswith(old_dir):
            rec[key] = new_dir + val[len(old_dir):]
    cli = rec.get("cli") or ""
    if old_dir and old_dir in cli:
        rec["cli"] = cli.replace(old_dir, new_dir)
    rec["dir"] = new_dir
    rec["run_name"] = run_name
    return True


def _sort_records(records):
    records.sort(key=lambda r: (r.get("created") or "", r.get("id") or ""))


# ─── Run registry (adapter state; engine state stays in out/progress) ──

def _load_registry():
    try:
        data = json.load(open(REGISTRY_PATH, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save_registry(records):
    tmp = REGISTRY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, REGISTRY_PATH)


def _load_registry_migrated():
    """Load + migrate old flat-layout receipts to dated layout (saves once)."""
    records = _load_registry()
    changed = False
    for rec in records:
        try:
            if _migrate_record(rec):
                changed = True
        except Exception:
            continue
    _sort_records(records)
    order_changed = ([r.get("id") for r in _load_registry()]
                     != [r.get("id") for r in records])
    if changed or order_changed:
        try:
            _save_registry(records)
        except OSError:
            pass
    return records


def _find_record(records, run_id):
    for rec in records:
        if rec.get("id") == run_id:
            return rec
    return None


def _events_path(record):
    out = record.get("out") or ""
    base = os.path.dirname(out) if out else record.get("dir", "")
    return os.path.join(base, "run_events.jsonl")


def _poll_proc(run_id):
    proc = _procs.get(run_id)
    if proc is None:
        return None
    code = proc.poll()
    if code is not None:
        with _lock:
            _procs.pop(run_id, None)
    return code


#: Durable stop marker written into a run record by the cancel endpoint.
OPERATOR_STOP_MESSAGE = "operator-stopped by console cancel"

#: Grace between the terminate signal and the force-kill fallback.
CANCEL_GRACE_SECONDS = 5.0


def _proc_pid(proc):
    """Live pid of a child handle (None when unknown)."""
    try:
        pid = proc.pid
    except Exception:
        return None
    return pid if isinstance(pid, int) else None


def _pid_alive(pid):
    """True when a pid still names a live process (best-effort)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True
    return True


#: Start-time skew absorbed when comparing the stored fingerprint
#: against the live process (float epoch seconds round-trip exactly
#: through JSON; 1s absorbs read skew while a PID reuse hours later
#: still mismatches loudly).
_FINGERPRINT_TIME_TOLERANCE = 1.0


def _pid_identity(pid):
    """(create_time_or_None, cmdline_str) for a live pid (never raises).

    Read-only identity probe for the restarted-server cancel path:
    process start time plus full command line via psutil (portable —
    no /proc parsing). (None, "") means unverifiable (no such
    process, access denied, or psutil unavailable) — the caller must
    refuse to signal, never guess. Values stay in-memory only.
    """
    try:
        import psutil as _psutil
    except ImportError:
        return None, ""
    try:
        handle = _psutil.Process(int(pid))
    except Exception:
        return None, ""
    try:
        started = float(handle.create_time())
    except Exception:
        started = None
    try:
        cmdline = " ".join(handle.cmdline())
    except Exception:
        cmdline = ""
    return started, cmdline or ""


def _verify_bare_pid_identity(pid, rec):
    """(ok, error_or_None): does pid still name THIS run's child?

    The restarted-server path lost the live handle, so a bare pid
    alone proves nothing (PID reuse could name an unrelated
    process). The stored fingerprint (start time + command-line
    marker, persisted at spawn) must both agree with the live
    process; any mismatch — or any unverifiable state (pre-fix
    record without a fingerprint, unreadable process table) —
    refuses with an unknown-target error and nothing is signalled.
    """
    stored_time = rec.get("pid_create_time")
    marker = rec.get("pid_marker") or ""
    if stored_time is None or not marker:
        return False, ("refusing to signal: pid %s has no child "
                       "identity on record (unknown target — "
                       "nothing signalled)" % (pid,))
    try:
        live_time, live_cmd = _pid_identity(pid)
    except Exception:
        return False, ("refusing to signal: pid %s identity "
                       "unverifiable (unknown target — nothing "
                       "signalled)" % (pid,))
    if live_time is None or not live_cmd:
        return False, ("refusing to signal: pid %s identity "
                       "unverifiable (unknown target — nothing "
                       "signalled)" % (pid,))
    try:
        drift = abs(float(live_time) - float(stored_time))
    except (TypeError, ValueError):
        return False, ("refusing to signal: pid %s identity "
                       "unverifiable (unknown target — nothing "
                       "signalled)" % (pid,))
    if drift > _FINGERPRINT_TIME_TOLERANCE:
        return False, ("refusing to signal: pid %s identity mismatch "
                       "(unknown target — possible PID reuse, nothing "
                       "signalled)" % (pid,))
    if str(marker) not in live_cmd:
        return False, ("refusing to signal: pid %s identity mismatch "
                       "(unknown target — possible PID reuse, nothing "
                       "signalled)" % (pid,))
    return True, None


def _terminate_child(proc, pid, grace_seconds=CANCEL_GRACE_SECONDS,
                     verify=None):
    """Stop one child by pid only: terminate signal, force-kill if needed.

    The live handle is preferred (identity-checked by the caller); a
    bare pid covers the restarted-server case (handle lost, record pid
    kept). Never signals anything but the given child — no blanket
    kills. Returns (exit_code_or_None, force_note).

    Stale-handle guard: a live handle that already exited (``poll()``
    non-None) is never signalled — the exit code returns with an
    already-finished note. Bare-pid identity is re-verified through
    ``verify`` (``verify(pid) -> (ok, error)``) immediately before
    each kill call, closing the lock-to-signal gap: a pid reused
    between the registry lock and the signal refuses with an
    identity-lost note and nothing is signalled.
    """
    import signal
    import time as _time

    if proc is not None:
        try:
            _early = proc.poll()
        except Exception:
            _early = None
        if _early is not None:
            return _early, " (already finished)"
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            return proc.wait(timeout=grace_seconds), ""
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            return proc.wait(timeout=grace_seconds), " (force-killed)"
        except Exception:
            return None, " (force-killed)"
    if pid is None:
        return None, ""
    if verify is not None:
        try:
            _ok, _err = verify(pid)
        except Exception:
            return None, " (identity lost — nothing signalled)"
        if not _ok:
            return None, " (identity lost — nothing signalled)"
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return None, " (already gone)"
    except Exception as exc:
        return None, " (signal failed: %s)" % type(exc).__name__
    deadline = _time.monotonic() + grace_seconds
    while _time.monotonic() < deadline:
        if not _pid_alive(pid):
            return None, ""
        _time.sleep(0.2)
    if verify is not None:
        try:
            _ok, _err = verify(pid)
        except Exception:
            return None, " (identity lost — nothing signalled)"
        if not _ok:
            return None, " (identity lost — nothing signalled)"
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass
    return None, " (force-killed)"


#: Already-finished error marker: cancel arriving after a natural
#: zero-exit returns this shape (409) so the console shows finished
#: as finished, never as cancelled. The literal token
#: ``already_finished`` rides the message so API clients can match
#: it with either spelling ("already finished" / "already_finished").
def _already_finished_error(code):
    return ("run already finished (already_finished, exit %s) — "
            "nothing to stop" % (code,))


def cancel_run(run_id, grace_seconds=CANCEL_GRACE_SECONDS):
    """Cancel a running run: stop its child, mark failed/operator-stopped.

    Pid-targeted only: when both the live handle pid and the recorded
    pid are known they must match, or nothing is signalled; with
    neither known the cancel is refused (never a blanket kill). After
    a server restart the live handle is gone, so a bare recorded pid
    is signalled only when its stored child fingerprint (start time
    + command-line marker) still matches the live process — any
    mismatch or unverifiable state refuses with 409 (unknown target).
    A natural finish during the grace window (zero exit, or a record
    that already left "running") returns the already-finished 409
    shape (never 200 cancelled). Returns
    (record_or_None, error_or_None, http_status).
    """
    with _lock:
        records = _load_registry_migrated()
        rec = _find_record(records, run_id)
        if rec is None:
            return None, "unknown run", 404
        if rec.get("status") != "running":
            return rec, ("run is not running (status: %s)"
                         % rec.get("status")), 409
        proc = _procs.get(run_id)
        pid = rec.get("pid")
        live_pid = _proc_pid(proc) if proc is not None else None
        if (proc is not None and pid is not None
                and live_pid is not None and live_pid != pid):
            return rec, ("refusing to signal: live pid %d != "
                         "recorded pid %s" % (live_pid, pid)), 409
        if proc is None and pid is None:
            return rec, ("no live handle and no recorded pid — "
                         "cannot target the child safely"), 409
        if proc is None and pid is not None:
            verified, verify_error = _verify_bare_pid_identity(pid, rec)
            if not verified:
                return rec, verify_error, 409
            _fp_time, _fp_marker = (rec.get("pid_create_time"),
                                    rec.get("pid_marker"))
        else:
            _fp_time, _fp_marker = None, None
        target_pid = live_pid if live_pid is not None else pid

    def _reverify(_pid, _t=_fp_time, _m=_fp_marker):
        return _verify_bare_pid_identity(
            _pid, {"pid_create_time": _t, "pid_marker": _m})

    _code, _note = _terminate_child(
        proc, pid, grace_seconds=grace_seconds,
        verify=(_reverify if proc is None and pid is not None else None))
    if _note == " (identity lost — nothing signalled)":
        with _lock:
            records = _load_registry_migrated()
            rec = _find_record(records, run_id)
            if rec is None:
                return None, "unknown run", 404
        return rec, ("refusing to signal: pid %s identity mismatch "
                     "(unknown target — possible PID reuse, nothing "
                     "signalled)" % (pid,)), 409
    with _lock:
        records = _load_registry_migrated()
        rec = _find_record(records, run_id)
        if rec is None:
            return None, "unknown run", 404
        if rec.get("status") != "running":
            return rec, _already_finished_error(rec.get("exit_code")), 409
        final = _poll_proc(run_id)
        code = final if final is not None else _code
        if _note == " (already finished)" or code == 0:
            rec["status"] = "done" if code == 0 else "failed"
            rec["exit_code"] = code
            _save_registry(records)
            return rec, _already_finished_error(code), 409
        if rec.get("status") == "running":
            rec["status"] = "failed"
            rec["exit_code"] = code
            rec["stop_reason"] = "%s (pid %s)%s" % (
                OPERATOR_STOP_MESSAGE, target_pid, _note)
            _save_registry(records)
        return rec, None, 200


# ─── Presets + custom profiles (operator data, plain JSON files) ─────

def _read_json_file(path):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data


def _safe_filename(name):
    """Filesystem-safe stem for preset/profile names (no separators).

    Allows ASCII word chars plus the Persian block (U+0600-U+06FF),
    space, dot, underscore, hyphen. ``/`` and ``\\`` always map to
    ``_`` so ``..\\\\..\\\\x`` can never escape the data dir (the
    ``.json`` suffix is appended by callers, so ``..`` alone is also
    inert — it still lands inside the dir as ``....json``-style).

    ASCII names that need no sanitization keep an exact 1:1 mapping
    (``witness-benchmark`` stays ``witness-benchmark``). Anything
    else (non-ASCII, sanitized, or empty) gets a short sha1 suffix of
    the full original name, so two distinct display names never share
    one file (e.g. two 3-letter Persian names no longer both land on
    ``___.json``). Deterministic: same name always maps to same file.
    """
    raw = str(name or "").strip()
    base = re.sub(r"[^A-Za-z0-9_.\-\u0600-\u06FF ]", "_",
                  raw).strip()
    if not base or base in (".", ".."):
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        return "n-%s" % digest
    try:
        raw.encode("ascii")
        ascii_only = True
    except UnicodeEncodeError:
        ascii_only = False
    if ascii_only and base == raw[:64]:
        return base[:64]
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    keep = 64 - 9
    stem = base[:keep].rstrip()
    if not stem or stem in (".", ".."):
        return "n-%s" % digest
    return "%s-%s" % (stem, digest)


PRESET_KINDS = ("run", "judge")

#: Ready whole-run preset (speed + accuracy): small limit for speed, the
#: engine-default gold sample for accuracy. Seeded only when missing —
#: an operator edit is never overwritten.
WITNESS_PRESET_NAME = "witness-benchmark"
WITNESS_PRESET_FIELDS = {
    "provider": "avalai",
    "model": "",
    "sample": "",
    "limit": 30,
    "concurrency": 8,
    "out": "",
    "progress_dir": "",
    "resume": "on",
}


def _preset_version_number(rec):
    """int version for preset dedup (operator junk versions read as 0)."""
    try:
        return int((rec or {}).get("version") or 0)
    except (TypeError, ValueError):
        return 0


def list_presets(kind=None):
    """All stored presets (old records without a kind read as "run").

    Load-time dedup by (kind, display name) (stale twin files, e.g. the
    hyphen/underscore witness-benchmark pair, collapse to one: highest
    version wins, ties keep the first file in sorted order).
    """
    by_key = {}
    try:
        entries = sorted(os.listdir(PRESETS_DIR))
    except OSError:
        return []
    for entry in entries:
        if not entry.endswith(".json"):
            continue
        rec = _read_json_file(os.path.join(PRESETS_DIR, entry))
        if isinstance(rec, dict) and rec.get("name"):
            rec.setdefault("kind", "run")
            if kind is not None and rec.get("kind") != kind:
                continue
            name = rec.get("name")
            key = (rec.get("kind"),
                   name if isinstance(name, str) else str(name))
            prev = by_key.get(key)
            if prev is None or _preset_version_number(rec) > \
                    _preset_version_number(prev):
                by_key[key] = rec
    out = sorted(by_key.values(), key=lambda r: str(r.get("name") or ""))
    return out


def _ensure_witness_preset():
    """Seed the ready witness-benchmark run preset once (never overwrite)."""
    try:
        if get_preset(WITNESS_PRESET_NAME) is not None:
            return
        fields = dict(WITNESS_PRESET_FIELDS)
        fields["name"] = WITNESS_PRESET_NAME
        fields["kind"] = "run"
        fields["ready"] = True
        save_preset(fields)
    except (OSError, ValueError):
        pass


def get_preset(name):
    safe = _safe_filename(name)
    if not safe or safe != str(name or "").strip():
        alt = _read_json_file(os.path.join(PRESETS_DIR, safe + ".json"))
        if isinstance(alt, dict) and alt.get("name") == name:
            return alt
        # fall through to scan for exact display-name match
        for rec in list_presets():
            if rec.get("name") == name:
                return rec
        return None
    rec = _read_json_file(os.path.join(PRESETS_DIR, safe + ".json"))
    return rec if isinstance(rec, dict) else None


def save_preset(fields):
    """Save a versioned preset; returns the stored record (version bumped).

    Two kinds: "run" (the whole compose form) and "judge" (judge knobs
    only: provider/model/concurrency — plugs into the compose form).
    Old records without a kind read back as "run".
    """
    name = str((fields or {}).get("name") or "").strip()
    if not name or not _PRESET_NAME_RX.match(name):
        raise ValueError("preset name must be 1..64 chars without / or \\")
    safe = _safe_filename(name)
    if not safe:
        raise ValueError("preset name must be 1..64 chars without / or \\")
    kind = str((fields or {}).get("kind") or "run").strip()
    if kind not in PRESET_KINDS:
        raise ValueError("preset kind must be one of %s" % "/".join(
            PRESET_KINDS))
    provider = str((fields or {}).get("provider") or "").strip()
    if not _is_known_provider(provider):
        raise ValueError("unknown provider: %r" % provider)
    try:
        limit = int((fields or {}).get("limit", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer >= 0")
    if limit < 0:
        raise ValueError("limit must be >= 0")
    try:
        concurrency = int((fields or {}).get("concurrency", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError("concurrency must be an integer 1..10 or empty")
    if concurrency < 0 or concurrency > 10:
        raise ValueError("concurrency must be an integer 1..10 or empty")
    resume = str((fields or {}).get("resume", "on") or "on").strip()
    if resume not in RESUME_MODES:
        raise ValueError("resume must be one of %s" % ("/".join(RESUME_MODES),))
    os.makedirs(PRESETS_DIR, exist_ok=True)
    prev = get_preset(name)
    version = int((prev or {}).get("version") or 0) + 1
    rec = {
        "name": name,
        "version": version,
        "kind": kind,
        "provider": provider,
        "model": str((fields or {}).get("model") or "").strip(),
        "sample": str((fields or {}).get("sample") or "").strip(),
        "limit": limit,
        "concurrency": concurrency,
        "out": str((fields or {}).get("out") or "").strip(),
        "progress_dir": str((fields or {}).get("progress_dir")
                            or "").strip(),
        "resume": resume,
        "updated": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
    }
    if (fields or {}).get("ready") is True or (
            prev or {}).get("ready") is True:
        rec["ready"] = True
    tmp = os.path.join(PRESETS_DIR, safe + ".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(rec, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(PRESETS_DIR, safe + ".json"))
    return rec


def delete_preset(name):
    safe = _safe_filename(name)
    path = os.path.join(PRESETS_DIR, safe + ".json")
    rec = get_preset(name)
    if rec is None or not os.path.isfile(path):
        # exact-name scan fallback (unicode names map 1:1, so this is rare)
        for cand in list_presets():
            if cand.get("name") == name:
                path = os.path.join(PRESETS_DIR,
                                    _safe_filename(cand["name"]) + ".json")
                rec = cand
                break
    if rec is None:
        return False
    try:
        os.remove(path)
    except OSError:
        return False
    return True


def list_profiles():
    out = []
    try:
        entries = sorted(os.listdir(PROFILES_DIR))
    except OSError:
        return out
    for entry in entries:
        if not entry.endswith(".json"):
            continue
        rec = _read_json_file(os.path.join(PROFILES_DIR, entry))
        if isinstance(rec, dict) and rec.get("name"):
            out.append(rec)
    out.sort(key=lambda r: str(r.get("name") or ""))
    return out


def get_profile(name):
    for rec in list_profiles():
        if rec.get("name") == name:
            return rec
    return None


def _key_var_for_custom_name(name):
    """Derived key reference for a custom profile name (no manual typing).

    ``mine`` -> ``MINE_API_KEY``; anything else is uppercased, non
    alphanumerics become ``_``, and ``_API_KEY`` is appended unless
    already present. Names only — values never derived here.
    """
    stem = re.sub(r"[^A-Z0-9]+", "_", str(name or "").strip().upper())
    stem = stem.strip("_")
    if not stem:
        return ""
    if not stem[0].isalpha():
        stem = "P_" + stem
    if not stem.endswith("_API_KEY"):
        stem = stem + "_API_KEY"
    return stem[:64]


def _provider_key_var(provider):
    """Effective key variable for a built-in provider (name only).

    The operator mapping (provider card) wins; otherwise the first
    registry ref (convention group slot, then legacy fallbacks).
    """
    try:
        mapped = _key_var_mapping().get(str(provider or "").strip())
    except Exception:
        mapped = ""
    if mapped and _KEY_VAR_RX.match(str(mapped).strip().upper()):
        return str(mapped).strip().upper()
    try:
        refs = provider_registry.key_ref_for(provider)
    except Exception:
        return ""
    return str(refs[0]) if refs else ""


def _store_operator_key(var, value):
    """Encrypt + persist one operator key; (ok, error_fa_or_en).

    Shared by the per-provider endpoint and the legacy generic endpoint.
    Fail-closed: no master key (or empty value) stores nothing.
    The plaintext value is never logged or returned — names only out.
    """
    var = str(var or "").strip().upper()
    value = str(value or "")
    if not _KEY_VAR_RX.match(var or ""):
        return False, "key reference name must look like SOME_API_KEY"
    if not value:
        return False, "key value is empty (nothing stored)"
    try:
        from services.db import key_crypto
        stored = key_crypto.encrypt_for_storage(value)
    except Exception:
        stored = ""
    if not stored:
        return False, ("cannot store the key: secure storage is not "
                       "active on this machine (activate it once from "
                       "the providers panel, then retry — fail-closed; "
                       "nothing was saved)")
    with _lock:
        try:
            current = json.load(open(OPERATOR_KEYS_PATH, encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        current[var] = stored
        tmp = OPERATOR_KEYS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, OPERATOR_KEYS_PATH)
        try:
            os.chmod(OPERATOR_KEYS_PATH, 0o600)
        except OSError:
            pass
    # Names only in every surface: never echo the value back, never log it.
    app.logger.info("operator key stored for %s", var)
    return True, ""


def _remove_operator_key(var):
    """Delete one stored operator key; True when something was removed."""
    var = str(var or "").strip().upper()
    with _lock:
        try:
            current = json.load(open(OPERATOR_KEYS_PATH, encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        if not isinstance(current, dict) or var not in current:
            return False
        del current[var]
        tmp = OPERATOR_KEYS_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(current, handle, ensure_ascii=False, indent=1)
            os.replace(tmp, OPERATOR_KEYS_PATH)
            try:
                os.chmod(OPERATOR_KEYS_PATH, 0o600)
            except OSError:
                pass
        except OSError:
            return False
    return True


def save_profile(fields):
    """Save an operator provider profile (data only — never the code registry).

    The key reference is auto-derived from the name (``mine`` ->
    ``MINE_API_KEY``) so the operator never types it; an explicit
    ``key_var`` in fields is still honored so old stored records and old
    callers keep working.
    """
    name = str((fields or {}).get("name") or "").strip()
    if not name or not _PRESET_NAME_RX.match(name):
        raise ValueError("profile name must be 1..64 chars without / or \\")
    if name in provider_registry.provider_names():
        raise ValueError("profile name %r is a code-registry provider "
                         "(pick another name)" % name)
    base_url = str((fields or {}).get("base_url") or "").strip()
    if not base_url:
        raise ValueError("base address is required")
    key_var = str((fields or {}).get("key_var") or "").strip().upper()
    if not key_var:
        key_var = _key_var_for_custom_name(name)
    if not _KEY_VAR_RX.match(key_var or ""):
        raise ValueError("key reference name must look like SOME_API_KEY")
    safe = _safe_filename(name)
    os.makedirs(PROFILES_DIR, exist_ok=True)
    rec = {
        "name": name,
        "base_url": base_url,
        "key_var": key_var,
        "model": str((fields or {}).get("model") or "").strip(),
        "updated": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
    }
    tmp = os.path.join(PROFILES_DIR, safe + ".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(rec, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(PROFILES_DIR, safe + ".json"))
    return rec


def delete_profile(name):
    rec = get_profile(name)
    if rec is None:
        return False
    path = os.path.join(PROFILES_DIR, _safe_filename(name) + ".json")
    if not os.path.isfile(path):
        return False
    try:
        os.remove(path)
    except OSError:
        return False
    return True


def custom_provider_rows():
    """Custom profiles for display: names + key-var NAMES + booleans only."""
    stored = _operator_key_values()
    rows = []
    for rec in list_profiles():
        var = rec.get("key_var") or ""
        rows.append({
            "name": rec.get("name"),
            "base_url": rec.get("base_url"),
            "model": rec.get("model"),
            "key_vars": [var] if var else [],
            "key_var": var,
            "has_key": bool(_resolve_any([var]) if var else False)
            or bool(var and var in stored),
        })
    return rows


def rate_state():
    """Honest per-provider throttling facts (names + booleans + knobs).

    Audit surface only — no throttling behavior lives here. Per
    provider: effective key var, group-slot booleans (G1/G2 resolve via
    the unified loader or operator storage), populated-group count,
    lease routing (direct vs tunnel), and the engine pacing knobs that
    actually exist (inter-batch sleep default, 429-rotation pause,
    compose concurrency default). Values never appear.
    """
    try:
        from factory.precard import provider_lease_policy as _lease
        lease_targets = dict(_lease.TARGETS)
        lease_target_for = _lease.target_for
    except Exception:
        lease_targets = {}
        lease_target_for = None
    try:
        from factory.precard import pipeline as _pipe
        sleep_default = float(_pipe.SLEEP)
    except Exception:
        sleep_default = 2.5
    try:
        from factory.core.llm_json import cooldown_for as _cooldown_for
        rotate_pause = float(_cooldown_for("generic"))
    except Exception:
        rotate_pause = 5.0
    stored = _operator_key_values()
    rows = []
    for presence in key_presence():
        name = presence.get("name")
        try:
            row = provider_registry.resolve_provider(name) or {}
        except Exception:
            row = {}
        groups = {}
        for group in ("G1", "G2"):
            try:
                refs = provider_registry.key_ref_for(name, group)
            except Exception:
                refs = []
            groups[group] = bool(
                _resolve_any(refs)
                or any(v in stored for v in refs))
        route = str(row.get("route") or "")
        if not route:
            try:
                target = (lease_target_for(name)
                          if lease_target_for is not None else "")
                spec = (lease_targets.get(target) or {})
                route = ("direct" if not spec.get("tunnel")
                         else "tunnel")
            except Exception:
                route = ""
        try:
            from factory.precard.provider_lease_policy import (
                is_tunneled as _tun)
            row_default = (route == "tunnel")
            route = ("tunnel" if _tun(name, row_tunnel=row_default)
                     else "direct")
        except Exception:
            pass
        rows.append({
            "name": name,
            "key_var": presence.get("key_var"),
            "has_key": presence.get("has_key"),
            "groups": groups,
            "groups_count": sum(1 for v in groups.values() if v),
            "route": route,
            "pacing": {
                "sleep_secs_default": sleep_default,
                "rotate_pause_secs": rotate_pause,
                "concurrency_default": 8,
                "rpm_limiter": False,
            },
            "lease_note": (
                "WebUI leases a supervisor tunnel for tunnel-route "
                "providers (Google: geo-block 403 direct) before spawn "
                "— proxy + lease identity ride the child env only; "
                "429 rotates keys on the same model, exhaustion stops "
                "loud with progress flushed."),
        })
    return rows


# ─── Egress routing (leased vs direct — precard line mirrored) ───

#: Single owner is the probe module (T4): this name is an alias, never
#: a rival literal — one reason string for every surface (probe lines,
#: compose routing line, engine facts).
from factory.linking import probe_providers as _probe_reasons
GOOGLE_TUNNEL_REASON = _probe_reasons.GOOGLE_TUNNEL_REASON

#: Domestic hosts bypass the tunnel proxy (same rule as
#: tools/egress/run_with_lease.py — child env only, never the parent).
_NO_PROXY_DOMESTIC = "api.avalai.ir,localhost,127.0.0.1"


def route_for_provider(provider, registry_fn=None, tunneled=None,
                       env_map=None, file_paths=None):
    """(route, reason): "leased" for tunnel providers, else "direct".

    Thin composition over the probe seam: the flag-first decision
    arrives via ``probe_providers.route_for`` (``registry_fn`` injects
    the row reader, ``tunneled``/``env_map``/``file_paths`` inject the
    flag — tests pass fakes; the default resolves live through the
    engine registry + EGRESS_TUNNEL_PROVIDERS flag) and the one-line
    reason via ``probe_providers.route_reason`` (names only — never
    values). Operator custom profiles have no registry route — they
    read "direct" honestly (no lease exists for names outside the
    engine registry); that guard is operator-data composition, not
    tunnel logic, so it stays here.
    """
    name = str(provider or "").strip()
    if _is_custom_profile(name):
        return ("direct",
                "%s is an operator custom profile — no engine tunnel "
                "route exists, runs direct" % name)
    from factory.linking import probe_providers as _pp
    route = _pp.route_for(name, registry_fn=registry_fn,
                          tunneled=tunneled, env_map=env_map,
                          file_paths=file_paths)
    return (route, _pp.route_reason(name, route))


#: Exact operator command that starts the shared egress supervisor
#: (loopback lease service, tools/egress/supervisor.py). Shown verbatim
#: in every supervisor-down error — names only, never secret values.
SUPERVISOR_START_CMD = "python tools/egress/supervisor.py"


def _factory_supervisor_script():
    """Factory-domain supervisor entry (single source, never a copy).

    The path is owned by ``factory.run`` (SUPERVISOR_SCRIPT); this
    adapter only reads it so the wake path and the CLI can never drift
    into rival literals.
    """
    try:
        from factory import run as _frun
        return str(getattr(_frun, "SUPERVISOR_SCRIPT", "") or "")
    except Exception:
        return ""


def _factory_supervisor_port():
    """Loopback port for a woken supervisor (URL first, factory default).

    The resolved supervisor URL wins when it names a loopback port;
    otherwise the factory default (factory.run.SUP_DEFAULT_PORT).
    """
    try:
        from urllib.parse import urlsplit as _split
        port = _split(_supervisor_url()).port
        if port:
            return int(port)
    except Exception:
        pass
    try:
        from factory import run as _frun
        return int(getattr(_frun, "SUP_DEFAULT_PORT", 18789))
    except Exception:
        return 18789


def _wake_supervisor_background(port=None, spawn_fn=None, health_fn=None,
                                timeout=5.0):
    """Background wake of the shared supervisor (best-effort, never raises).

    Health-first: a healthy supervisor is returned as-is (never
    restarted, never re-spawned). Otherwise the factory-domain entry
    (``factory.run.SUPERVISOR_SCRIPT``) is launched detached in the
    background — bearer rides the child env only, never argv/logs —
    and health is re-polled on a bounded budget. Others' leases are
    never touched (no lease/report call exists on this path).
    ``spawn_fn``/``health_fn`` inject the spawn + health legs (tests
    pass fakes, never a real process). Returns True when a healthy
    supervisor answers after the attempt.
    """
    health = health_fn or supervisor_health_snapshot
    try:
        ok, _ = health()
    except Exception:
        ok = False
    if ok:
        return True
    script = _factory_supervisor_script()
    if not script or not os.path.isfile(script):
        return False
    target = int(port or _factory_supervisor_port())
    try:
        if spawn_fn is not None:
            spawn_fn(target)
        else:
            env = dict(os.environ)
            tok = _supervisor_token()
            if tok:
                env["EGRESS_SUP_TOKEN"] = tok
            subprocess.Popen(
                [sys.executable, script, "--port", str(target)],
                env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True)
    except Exception:
        return False
    import time as _time
    try:
        budget = max(0.5, float(timeout or 0))
    except (TypeError, ValueError):
        budget = 5.0
    deadline = _time.monotonic() + budget
    while _time.monotonic() < deadline:
        try:
            ok, _ = health()
        except Exception:
            ok = False
        if ok:
            return True
        _time.sleep(0.5)
    return False


def _ensure_supervisor_for_leased(provider, *, wake_fn=None, health_fn=None,
                                  tunneled=None, env_map=None,
                                  file_paths=None):
    """Universal auto-wake gate for leased-route providers (never raw).

    Route-based, never provider-named: any provider whose flag-driven
    route is "leased" rides this gate (Google-only gates are banned).
    Direct-route providers return ready without touching the
    supervisor. Otherwise the token is checked; when missing, the
    supervisor is woken in the background from the factory domain path
    and the token re-resolved (a child cannot change the parent
    environment, so the retry re-reads the shared temp file the
    supervisor workflow leaves behind), then the request retries — the
    caller sees a friendly wait line, never a raw error. ``wake_fn`` injects
    the wake leg (() -> bool; tests pass fakes, never a process).
    Returns (ready_bool, error_or_None).
    """
    route, _reason = route_for_provider(
        provider, tunneled=tunneled, env_map=env_map,
        file_paths=file_paths)
    if route != "leased":
        return True, None
    if _supervisor_token():
        _touch_supervisor_active()
        return True, None
    if wake_fn is not None:
        try:
            woke = wake_fn()
        except Exception:
            woke = False
    else:
        woke = _wake_supervisor_background(health_fn=health_fn)
    if woke and _supervisor_token():
        _touch_supervisor_active()
        return True, None
    if woke:
        return False, ("supervisor is starting in the background "
                       "(EGRESS_SUP_TOKEN) — retry this request in a few "
                       "seconds; manual start: %s" % SUPERVISOR_START_CMD)
    return False, ("no supervisor token resolves (EGRESS_SUP_TOKEN) "
                   "— the shared supervisor was woken in the background: "
                   "%s (nothing else touched)" % SUPERVISOR_START_CMD)


#: Idle-sleep minutes — PARKED (owner number pending, never invented).
#: ``None`` means "no owner value yet": the idle path stays inert until
#: the owner configures a real number (env override below or a future
#: literal). Tests assert this parked default and drive the idle verdict
#: with injected minutes instead of any real duration.
IDLE_SLEEP_MINUTES = None

#: Owner-configured idle-minutes override (name only; value never logged).
SUPERVISOR_IDLE_MINUTES_ENV_VAR = "HAMZABAN_SUPERVISOR_IDLE_MINUTES"

#: Last supervisor activity (monotonic seconds, in-memory only). Touched
#: by the wake/lease legs so the sleep endpoint can tell idle from busy.
_SUPERVISOR_LAST_ACTIVE_TS = None


def _configured_idle_minutes(default=IDLE_SLEEP_MINUTES):
    """Owner-configured idle minutes (env override else parked default).

    Returns an int/float when the owner configured a positive number,
    else the parked default (``None`` — never invented). Names only out;
    unparseable values fall back to the parked default.
    """
    raw = (os.environ.get(SUPERVISOR_IDLE_MINUTES_ENV_VAR) or "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    if val <= 0:
        return default
    return val


def _touch_supervisor_active(now=None):
    """Record supervisor activity (in-memory timestamp, never I/O)."""
    global _SUPERVISOR_LAST_ACTIVE_TS
    try:
        import time as _time
        _SUPERVISOR_LAST_ACTIVE_TS = (
            float(now) if now is not None else _time.monotonic())
    except (TypeError, ValueError):
        pass


def supervisor_idle_due(last_seen_ts, now_ts, minutes=IDLE_SLEEP_MINUTES,
                        active_leases=0):
    """True when an idle supervisor may sleep (pure, no I/O).

    Honors the injected ``minutes`` (owner-configured value at the call
    site); the parked default (``None``) never sleeps. Any active lease
    blocks sleep — others' leases are never disturbed. Unknown
    timestamps never sleep (honest fallback, never a guess).
    """
    try:
        if int(active_leases or 0) > 0:
            return False
    except (TypeError, ValueError):
        return False
    if minutes is None:
        return False
    try:
        span = float(minutes)
    except (TypeError, ValueError):
        return False
    if span <= 0:
        return False
    try:
        idle_secs = float(now_ts) - float(last_seen_ts)
    except (TypeError, ValueError):
        return False
    return idle_secs >= span * 60.0


def supervisor_lifecycle_state(healthy=None, configured=None,
                               active_leases=0, idle_minutes=None):
    """State-surface facts: names + booleans only, never values."""
    if configured is None:
        configured = bool(_supervisor_token())
    if idle_minutes is None:
        idle_minutes = _configured_idle_minutes()
    return {"var": SUPERVISOR_TOKEN_VAR,
            "configured": bool(configured),
            "healthy": bool(healthy) if healthy is not None else False,
            "active_leases": int(active_leases or 0),
            "idle_minutes": idle_minutes,
            "idle_parked": idle_minutes is None}


def request_supervisor_sleep(*, stop_fn=None, last_seen_ts=None,
                             now_ts=None, active_leases=0, minutes=None):
    """Best-effort idle sleep (never disturbs others' leases).

    Sleeps only when the idle clock is due AND no lease is active;
    otherwise returns (False, reason). ``stop_fn`` injects the stop leg
    (tests pass fakes, never a process); the default has no stop hook
    configured, so it honestly reports not-slept instead of guessing.
    Never raises, never touches lease/report state.
    """
    if minutes is None:
        minutes = _configured_idle_minutes()
    if minutes is None:
        return False, "idle minutes parked (owner number pending)"
    try:
        import time as _time
        now = float(now_ts) if now_ts is not None else _time.monotonic()
    except (TypeError, ValueError):
        return False, "unknown clock (sleep refused)"
    if last_seen_ts is None:
        last_seen_ts = _SUPERVISOR_LAST_ACTIVE_TS
    if last_seen_ts is None:
        return False, "no activity timestamp yet (sleep refused)"
    if not supervisor_idle_due(last_seen_ts, now, minutes=minutes,
                               active_leases=active_leases):
        try:
            if int(active_leases or 0) > 0:
                return False, "leases active (sleep refused)"
        except (TypeError, ValueError):
            pass
        return False, "not idle yet (sleep refused)"
    if stop_fn is None:
        return False, "no stop hook configured (sleep refused)"
    try:
        stopped = stop_fn()
    except Exception:
        return False, "stop hook failed (sleep refused)"
    return bool(stopped), ("" if stopped else "stop hook declined")


def _supervisor_token():
    """Supervisor bearer (in-memory only, never logged or returned).

    Resolution order: process env, then the PRIMARY factory environment
    file (``_factory_env_value``: ``factory/.env``), then the shared
    supervisor-issued temp file (a woken child cannot change the parent
    environment, so the parent re-reads the token the supervisor
    workflow left on disk), then the shared egress loader
    (``tools.egress.supervisor.load_env``: the canonical
    tools/egress/.env, then the factory/.env fallback), then the
    file-anchored lease-policy resolver, then the encrypted operator
    store (pasted once in the providers panel, decrypted fail-closed).
    Branch location plays no role: every lookup path is anchored at
    the module file (``__file__``) or the shared temp directory,
    never at the checkout directory or cwd.
    """
    hit = os.environ.get(SUPERVISOR_TOKEN_VAR, "")
    if hit:
        return hit
    hit = _factory_env_value(SUPERVISOR_TOKEN_VAR)
    if hit:
        return hit
    hit = _read_supervisor_token_file()
    if hit:
        return hit
    try:
        from tools.egress import supervisor as _sup
        data = _sup.load_env() or {}
        tok = str(data.get(SUPERVISOR_TOKEN_VAR, "") or "").strip()
        if tok:
            return tok
    except Exception:
        pass
    try:
        from factory.precard.provider_lease_policy import (
            resolve_key as _resolve)
        hit = _resolve(SUPERVISOR_TOKEN_VAR) or ""
        if hit:
            return hit
    except Exception:
        pass
    try:
        stored = _operator_key_values()
        hit = stored.get(SUPERVISOR_TOKEN_VAR, "")
        if hit:
            return hit
    except Exception:
        pass
    return ""


#: Shared-temp-file name holding the supervisor-issued bearer the
#: parent re-reads (a child process cannot change the parent
#: environment). Written by whoever starts the supervisor with a token
#: (operator workflow, mode 0600); read here, never logged/returned.
SUP_TOKEN_FILENAME = "hamzaban-egress-sup-token"


def _supervisor_token_file():
    """Absolute path of the shared supervisor-token file (temp dir)."""
    try:
        base = tempfile.gettempdir()
    except Exception:
        return ""
    if not base:
        return ""
    return os.path.join(base, SUP_TOKEN_FILENAME)


_SUP_TOKEN_FILE_RX = re.compile(r"^[A-Za-z0-9_\-]{8,512}$")


def _read_supervisor_token_file(path=None):
    """Bearer from the shared temp file ("" when absent/invalid).

    Single-line, charset-guarded read — values stay in-memory only,
    never logged, returned only to in-process callers. A missing file
    is the normal supervisor-down state, never an error.
    """
    target = path or _supervisor_token_file()
    if not target:
        return ""
    try:
        with open(target, encoding="utf-8") as handle:
            raw = handle.read(4096)
    except (OSError, ValueError):
        return ""
    line = (raw or "").strip().splitlines()
    token = line[0].strip() if line else ""
    if not token or not _SUP_TOKEN_FILE_RX.match(token):
        return ""
    return token


def _refresh_egress_client_auth():
    """Place the resolved bearer on the loopback lease legs (best-effort).

    ``tools.egress.client`` binds SUP_TOKEN/SUP_URL at import time, so
    a token that resolved after import (shared temp file, supervisor
    workflow) would never reach the tunneled provider requests
    (lease/health/report for every leased route — google and any
    future leased row alike). Refreshing the module attributes from
    the resolved values keeps those legs on the active token without
    touching any file outside this adapter. Names only out — the
    value is assigned in-memory, never logged or returned.
    """
    try:
        from tools.egress import client as _client
    except Exception:
        return
    try:
        token = _supervisor_token()
    except Exception:
        token = ""
    try:
        url = _supervisor_url()
    except Exception:
        url = ""
    try:
        if token:
            _client.SUP_TOKEN = token
        if url:
            _client.SUP_URL = url
    except Exception:
        pass


def _supervisor_url():
    """Supervisor base URL through the same unified path (never copied).

    Same anchoring rule as :func:`_supervisor_token`: env first, then
    the shared egress loader, else the loopback default.
    """
    hit = (os.environ.get("EGRESS_SUP_URL", "") or "").strip()
    if hit:
        return hit
    try:
        from tools.egress import supervisor as _sup
        data = _sup.load_env() or {}
        url = str(data.get("EGRESS_SUP_URL", "") or "").strip()
        if url:
            return url
    except Exception:
        pass
    try:
        from factory.precard.provider_lease_policy import (
            resolve_key as _resolve)
        hit = (_resolve("EGRESS_SUP_URL")
               or os.environ.get("EGRESS_SUP_URL", ""))
    except Exception:
        hit = os.environ.get("EGRESS_SUP_URL", "")
    return (hit or "").strip() or "http://127.0.0.1:18789"


def supervisor_health_snapshot(timeout=10):
    """Read-only supervisor health (never spawns, never leases).

    Returns (ok, payload-or-error): payload is the /v1/health dict
    (servers/leases/healthy counts); error is a plain operator line.
    Values never leave — counts and booleans only.
    """
    import urllib.request as _url

    token = _supervisor_token()
    if not token:
        return False, ("no supervisor token resolves "
                       "(EGRESS_SUP_TOKEN) — start the shared "
                       "supervisor first: %s (nothing spawned)"
                       % SUPERVISOR_START_CMD)
    _refresh_egress_client_auth()
    try:
        req = _url.Request(
            _supervisor_url().rstrip("/") + "/v1/health",
            headers={"Authorization": "Bearer " + token})
        with _url.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as exc:
        return False, ("supervisor unreachable at %s (%s) — "
                       "shared infrastructure untouched, nothing "
                       "spawned; start it with: %s"
                       % (_supervisor_url(), type(exc).__name__,
                          SUPERVISOR_START_CMD))
    if not isinstance(data, dict):
        return False, "supervisor health unreadable (bad shape)"
    return True, {"servers": data.get("servers"),
                  "leases": data.get("leases"),
                  "healthy": bool(data.get("healthy"))}


def lease_tunnel_for_run(provider, *, lease_fn=None, target_fn=None,
                           clean_fn=None, verify_fn=None, tunneled=None,
                           env_map=None, file_paths=None, wake_fn=None,
                           health_fn=None):
    """Lease a clean tunnel for one WebUI run (auto-wake, fail-closed).

    Thin composition over the probe lease seam: a tunnel-route provider
    leases from the CURRENT supervisor health state via
    ``probe_providers.lease_tunnel`` (``lease_fn``/``target_fn`` inject
    it — tests pass fakes, never the network). Universal auto-wake:
    when no supervisor token resolves, the shared supervisor is woken
    in the background from the factory domain path
    (``wake_fn`` injects the wake leg — tests pass fakes, never a
    process) and the request retries without a raw error; a still-down
    supervisor is a friendly wait line (never a traceback, never an
    auto-spawn storm — one background wake, shared infrastructure and
    others' leases undisturbed). Route-based, never Google-only.
    Returns (lease_dict_or_None, error_or_None).

    Google leases additionally carry the whitelist verdict
    (``clean``/``clean_note``/``clean_exit`` annotations on OUR lease
    dict only): the leased exit is compared against the fresh
    verified-exit whitelist (``clean_fn``, default the T5 linker
    adapter), then keyless-verified through OUR proxy (``verify_fn``,
    default ``google_clean.verify_and_remember`` — one unbilled call,
    no key sent) and remembered when clean so the next lease prefers
    it. Verification never blocks a launch and never touches others'
    leases.
    """
    route, _reason = route_for_provider(
        provider, tunneled=tunneled, env_map=env_map,
        file_paths=file_paths)
    if route != "leased":
        return None, None
    ready, wake_error = _ensure_supervisor_for_leased(
        provider, wake_fn=wake_fn, health_fn=health_fn,
        tunneled=tunneled, env_map=env_map, file_paths=file_paths)
    if not ready:
        return None, wake_error
    token = _supervisor_token()
    if not token:
        return None, ("no supervisor token resolves (EGRESS_SUP_TOKEN) "
                      "— start the shared supervisor first: %s "
                      "(nothing spawned)" % SUPERVISOR_START_CMD)
    _refresh_egress_client_auth()
    try:
        from factory.linking import probe_providers as _pp
        lease = _pp.lease_tunnel(provider, lease_fn=lease_fn,
                                 target_fn=target_fn)
    except Exception as exc:
        return None, ("supervisor lease failed (%s) — shared "
                      "infrastructure untouched, nothing spawned"
                      % type(exc).__name__)
    if not isinstance(lease, dict) or lease.get("error"):
        msg = ""
        try:
            msg = str((lease or {}).get("message") or "")
        except Exception:
            msg = ""
        return None, ("supervisor refused the lease%s — pick a direct "
                      "provider or retry later"
                      % (": %s" % msg if msg else ""))
    try:
        from factory.linking import google_clean as _gc
        from factory.precard.provider_lease_policy import (
            norm_provider as _norm_p)
        if _norm_p(provider) == "google":
            clean = (clean_fn if clean_fn is not None
                     else _gc.fresh_clean_exits)
            head = (clean() or [""])[0] or ""
            sid = str((lease or {}).get("server_id") or "")
            lease["clean_exit"] = head
            lease["clean"] = bool(sid and head and sid == head)
            lease["clean_note"] = _gc.clean_note(
                sid, [head] if head else [])
            verify = (verify_fn if verify_fn is not None
                      else _gc.verify_and_remember)
            verify(
                str((lease or {}).get("proxy_url") or ""), sid,
                provider="google", timeout=10)
    except Exception:
        pass
    return lease, None


def report_run_lease(lease_id, provider, ok, report_fn=None):
    """Best-effort terminal report for OUR run lease only (never others').

    Thin composition over the probe report seam: ok True -> "ok";
    False -> "unknown" (keeps the lease, cools nothing — exit codes
    alone cannot prove network health, same rule as run_with_lease.py).
    ``report_fn`` injects the client (tests pass fakes, never the
    network). Never raises, never fails a run.
    """
    if not lease_id:
        return
    if report_fn is None and not _supervisor_token():
        return
    try:
        from factory.linking import probe_providers as _pp
        _pp.report_outcome(lease_id, "ok" if ok else "unknown",
                           provider=str(provider or ""),
                           report_fn=report_fn)
    except Exception:
        pass


def _child_env_with_lease(child_env, lease):
    """Export OUR lease proxy into the child env only (parent untouched).

    Same rule as run_with_lease.py: HTTPS_PROXY/HTTP_PROXY (+ NO_PROXY
    domestic) plus EGRESS_LEASE_ID/SERVER_ID identity (ids only,
    secret-free) so provider-aware children report terminal outcomes
    back. Returns the patched dict.
    """
    proxy = str((lease or {}).get("proxy_url") or "")
    if proxy:
        child_env["HTTPS_PROXY"] = proxy
        child_env["HTTP_PROXY"] = proxy
        prev_no = child_env.get("NO_PROXY", "")
        domestic = [h for h in _NO_PROXY_DOMESTIC.split(",") if h]
        if prev_no:
            domestic = prev_no.split(",") + domestic
        child_env["NO_PROXY"] = ",".join(dict.fromkeys(
            h.strip() for h in domestic if h.strip()))
    if (lease or {}).get("lease_id"):
        child_env["EGRESS_LEASE_ID"] = lease["lease_id"]
    if (lease or {}).get("server_id"):
        child_env["EGRESS_SERVER_ID"] = lease["server_id"]
    return child_env


# ─── Index ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(SCRIPT_DIR, "index.html")


# ─── API ─────────────────────────────────────────────────────────────

@app.route("/api/providers")
def api_providers():
    return jsonify({"providers": key_presence(),
                    "custom": custom_provider_rows(),
                    "master": master_status()})


@app.route("/api/rate_state", methods=["GET"])
def api_rate_state():
    """Honest per-provider throttling facts (audit surface, read-only)."""
    return jsonify({"providers": rate_state()})


@app.route("/api/egress/health", methods=["GET"])
def api_egress_health():
    """Read-only supervisor health (never spawns, never leases).

    Counts + booleans only — values never leave. Unhealthy means
    tunnel-route (Google) runs refuse loud until the shared
    supervisor is back; direct providers are unaffected.
    """
    ok, payload = supervisor_health_snapshot()
    if not ok:
        return jsonify({"healthy": False, "error": payload}), 503
    return jsonify({"healthy": bool(payload.get("healthy")),
                    "servers": payload.get("servers"),
                    "leases": payload.get("leases")})


@app.route("/api/providers/<name>/route", methods=["GET"])
def api_provider_route(name):
    """Leased-vs-direct routing for one provider (pre-launch facts)."""
    provider = str(name or "").strip()
    if (provider not in provider_registry.provider_names()
            and not _is_custom_profile(provider)):
        return jsonify({"error": "unknown provider: %s" % provider}), 404
    route, reason = route_for_provider(provider)
    return jsonify({"provider": provider, "route": route,
                    "reason": reason,
                    "clean_exit": _routing_clean_exit(provider)})


@app.route("/api/providers/<name>/models", methods=["GET"])
def api_provider_models(name):
    """Server-side per-provider model list (key-gated, never faked).

    The key resolves server-side only (env/file/operator store —
    values in-memory, never returned, logged, or stored in the
    browser). Tunnel-route providers list through a leased
    supervisor proxy (route-based — direct egress dies with
    geo-block/sanctions 403).
    Errors are attributed (provider + kind + http). An exact-id
    manual entry stays available client-side as fallback.
    """
    provider = str(name or "").strip()
    models, error = provider_model_list(provider)
    if error is not None:
        status = 400 if error.startswith("no key resolves") else 502
        if error.startswith("unknown provider"):
            status = 404
        return jsonify({"provider": provider, "models": [],
                        "error": error}), status
    return jsonify({"provider": provider, "models": models or [],
                    "count": len(models or [])})


@app.route("/api/master/status", methods=["GET"])
def api_master_status():
    return jsonify(master_status())


@app.route("/api/master/ensure", methods=["POST"])
def api_master_ensure():
    """Operator-confirmed first-use activation of secure key storage.

    Body {"confirm": true} generates and stores the master key in the
    gitignored factory env file (never displayed). Anything else is a
    plain 400 — nothing is generated without confirmation.
    """
    fields = request.get_json(force=True, silent=True) or {}
    if fields.get("confirm") is not True:
        return jsonify({"error": "confirmation required "
                                 "(send {\"confirm\": true})"}), 400
    ok, error, created = ensure_factory_master_key(confirmed=True)
    if not ok:
        return jsonify({"error": error}), 500
    return jsonify({"master": master_status(), "created": bool(created)})


def supervisor_token_status():
    """Supervisor-token readiness: NAME + boolean only, never the value."""
    return {"var": SUPERVISOR_TOKEN_VAR,
            "configured": bool(_supervisor_token())}


@app.route("/api/supervisor/status", methods=["GET"])
def api_supervisor_status():
    """Names-only supervisor-token readiness (never the value)."""
    return jsonify(supervisor_token_status())


@app.route("/api/supervisor/token", methods=["POST"])
def api_supervisor_token_save():
    """Paste the supervisor bearer ONCE (encrypted store, never returned).

    Body {"key_value": "<bearer>"} stores encrypted via the existing
    operator-key path (``_store_operator_key`` → ``key_crypto``,
    fail-closed). The value is shown one time — in the operator's own
    input before submit — then never returned, logged, or displayed:
    every read after this is names + booleans only.
    """
    fields = request.get_json(force=True, silent=True) or {}
    value = str((fields or {}).get("key_value")
                or (fields or {}).get("key") or "")
    ok, error = _store_operator_key(SUPERVISOR_TOKEN_VAR, value)
    if not ok:
        if "empty" in error or "reference name" in error:
            return jsonify({"error": error}), 400
        return jsonify({"error": error}), 500
    return jsonify({"stored": SUPERVISOR_TOKEN_VAR})


@app.route("/api/supervisor/token", methods=["DELETE"])
def api_supervisor_token_delete():
    """Delete the pasted supervisor bearer (names only out)."""
    if not _remove_operator_key(SUPERVISOR_TOKEN_VAR):
        return jsonify(
            {"error": "key not found: %s" % SUPERVISOR_TOKEN_VAR}), 404
    return jsonify({"deleted": SUPERVISOR_TOKEN_VAR})


@app.route("/api/supervisor/wake", methods=["POST"])
def api_supervisor_wake():
    """Wake-on-demand: background wake, never a restart of healthy.

    Health-first (read-only): a healthy supervisor returns woken True
    without spawning. Otherwise one background wake from the factory
    domain path; bearer rides the child env only. Names + booleans
    only — values never leave. Never touches others' leases.
    """
    try:
        ok, payload = supervisor_health_snapshot()
    except Exception:
        ok, payload = False, "health check failed"
    if ok:
        _touch_supervisor_active()
        return jsonify({"woken": True, "already_healthy": True,
                        "var": SUPERVISOR_TOKEN_VAR,
                        "health": payload if isinstance(payload, dict)
                        else {}})
    woke = _wake_supervisor_background()
    if woke:
        _touch_supervisor_active()
        return jsonify({"woken": True, "already_healthy": False,
                        "var": SUPERVISOR_TOKEN_VAR,
                        "note": ("supervisor is starting in the background "
                                 "(EGRESS_SUP_TOKEN) — retry in a few "
                                 "seconds")})
    return jsonify({"woken": False, "already_healthy": False,
                    "var": SUPERVISOR_TOKEN_VAR,
                    "error": payload if isinstance(payload, str)
                    else "wake refused"}), 503


@app.route("/api/supervisor/sleep", methods=["POST"])
def api_supervisor_sleep():
    """Idle sleep: sleeps only when idle-due with zero active leases.

    Parked idle minutes (owner number pending) honestly refuse with
    slept False — never invented. Others' leases are never disturbed
    (no lease/report call exists on this path). Names + booleans only.
    """
    minutes = _configured_idle_minutes()
    if minutes is None:
        return jsonify({"slept": False, "var": SUPERVISOR_TOKEN_VAR,
                        "reason": "idle minutes parked "
                        "(owner number pending)"})
    try:
        ok, payload = supervisor_health_snapshot()
    except Exception:
        ok, payload = False, "health check failed"
    if not ok:
        return jsonify({"slept": False, "var": SUPERVISOR_TOKEN_VAR,
                        "reason": payload if isinstance(payload, str)
                        else "supervisor not running"})
    try:
        leases = int((payload or {}).get("leases") or 0) \
            if isinstance(payload, dict) else 0
    except (TypeError, ValueError):
        leases = 0
    import time as _time
    slept, reason = request_supervisor_sleep(
        last_seen_ts=_SUPERVISOR_LAST_ACTIVE_TS, now_ts=_time.monotonic(),
        active_leases=leases, minutes=minutes)
    status = 200 if slept else 409
    body = {"slept": bool(slept), "var": SUPERVISOR_TOKEN_VAR,
            "idle_minutes": minutes, "active_leases": leases}
    if reason:
        body["reason"] = reason
    return jsonify(body), status


@app.route("/api/providers/<name>/key_var", methods=["GET"])
def api_provider_key_var_get(name):
    provider = str(name or "").strip()
    if provider not in provider_registry.provider_names():
        return jsonify({"error": "unknown provider: %s" % provider}), 404
    return jsonify({"provider": provider,
                    "key_var": _provider_key_var(provider)})


@app.route("/api/providers/<name>/key_var", methods=["PUT"])
def api_provider_key_var_put(name):
    """Map a provider to its key variable name (persisted, names only).

    Built-ins persist to provider_key_vars.json; custom profiles update
    their profile record. The value is never accepted or returned here.
    """
    provider = str(name or "").strip()
    fields = request.get_json(force=True, silent=True) or {}
    var = str((fields or {}).get("key_var") or "").strip().upper()
    if not _KEY_VAR_RX.match(var or ""):
        return jsonify({"error": "key reference name must look like "
                                 "SOME_API_KEY"}), 400
    if _is_custom_profile(provider):
        rec = get_profile(provider)
        if rec is None:
            return jsonify({"error": "profile not found: %s"
                                     % provider}), 404
        rec["key_var"] = var
        try:
            save_profile(rec)
        except (ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"provider": provider, "key_var": var})
    if provider not in provider_registry.provider_names():
        return jsonify({"error": "unknown provider: %s" % provider}), 404
    try:
        mapping = _key_var_mapping()
        mapping[provider] = var
        _save_key_var_mapping(mapping)
    except OSError as exc:
        return jsonify({"error": "save failed: %s" % exc}), 500
    return jsonify({"provider": provider, "key_var": var})


@app.route("/api/sample/validate", methods=["GET"])
def api_sample_validate():
    ok, error, info = validate_sample_file(request.args.get("path") or "")
    body = {"ok": ok}
    if ok:
        body.update(info)
    else:
        body["error"] = error
    return jsonify(body)


@app.route("/api/paths", methods=["GET"])
def api_paths():
    """Echo resolved input/output paths before launch (no run created)."""
    sample = (request.args.get("sample") or "").strip()
    out = (request.args.get("out") or "").strip()
    progress_dir = (request.args.get("progress_dir") or "").strip()
    created = datetime.datetime.now(datetime.timezone.utc).isoformat()
    preview_name = run_name_for(created, "preview")
    parent = _parent_of_run(preview_name)
    rundir = os.path.join(RUNS_DIR, parent, preview_name)
    resolved_out = out or os.path.join(rundir, "precard.jsonl")
    resolved_progress = progress_dir or os.path.join(rundir, "progress")
    body = {
        "sample": sample,
        "out": resolved_out,
        "progress_dir": resolved_progress,
        "run_dir": rundir,
        "run_dir_note": ("dated parent + date-time-first run name; "
                         "the short hash replaces 'preview' at launch"),
    }
    if sample:
        ok, error, info = validate_sample_file(sample)
        body["sample_ok"] = ok
        if ok:
            body.update(info)
        else:
            body["sample_error"] = error
    return jsonify(body)


@app.route("/api/runs", methods=["GET"])
def api_runs():
    records = _load_registry_migrated()
    with _lock:
        for rec in records:
            code = _poll_proc(rec.get("id", ""))
            if code is not None and rec.get("status") == "running":
                rec["status"] = "done" if code == 0 else "failed"
                rec["exit_code"] = code
        if any(r.get("status") in ("done", "failed") for r in records):
            _save_registry(records)
    return jsonify({"runs": [
        {k: r.get(k) for k in (
            "id", "run_name", "created", "flow", "provider", "model",
            "route", "lease", "egress", "egress_clean", "sample",
            "limit", "concurrency", "out", "progress_dir", "resume", "cli",
            "status", "exit_code", "pid", "stop_reason",
            "has_gold", "watermark", "preset",
            "preset_version", "profile")}
        for r in records
    ]})


@app.route("/api/runs", methods=["POST"])
def api_create_run():
    fields = request.get_json(force=True, silent=True) or {}
    flow = str((fields or {}).get("flow") or "linking").strip() or "linking"
    if flow == "linking" and not _is_known_provider(
            str((fields or {}).get("provider") or "").strip()):
        return jsonify({"error": "unknown provider: %r" % str(
            (fields or {}).get("provider") or "")}), 400
    try:
        argv, _shown = build_run_command(flow, fields)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    sample = str(fields.get("sample") or "").strip()
    if sample:
        ok, error, _info = validate_sample_file(sample)
        if not ok:
            return jsonify({"error": error}), 400
    preset_stamp = None
    preset_version = None
    preset_name = str(fields.get("preset") or fields.get("job_template")
                      or fields.get("template") or "").strip()
    if preset_name:
        prec = get_preset(preset_name)
        if prec is None:
            return jsonify(
                {"error": "preset not found: %s" % preset_name}), 400
        preset_stamp = prec.get("name")
        preset_version = prec.get("version")
    provider = str(fields.get("provider") or "")
    is_custom = _is_custom_profile(provider)
    run_id = uuid.uuid4().hex[:12]
    created = datetime.datetime.now(datetime.timezone.utc).isoformat()
    run_name = run_name_for(created, run_id)
    parent = _parent_of_run(run_name)
    rundir = os.path.join(RUNS_DIR, parent, run_name)
    os.makedirs(rundir, exist_ok=True)
    # Leased-vs-direct routing resolved BEFORE launch (precard TARGETS
    # mirror): tunnel-route providers lease a clean supervisor tunnel
    # (Google: geo-block 403 direct) — no spawn on failure, loud 502.
    # Linking runs offline (local word list in, local TSV out), so they
    # never lease, never resolve keys, and always read "direct".
    if flow == "linking":
        run_route = "direct"
        run_route_reason = ("linking runs offline "
                            "(local word list in, local TSV out)")
    else:
        run_route, run_route_reason = route_for_provider(provider)
    run_lease_short = None
    run_lease_id = ""
    run_egress_clean = None
    if flow == "linking":
        _lease, run_egress = None, "direct"
    elif run_route == "leased" and not is_custom:
        _lease, _lease_error = lease_tunnel_for_run(provider)
        if _lease_error:
            return jsonify({"error": _lease_error}), 502
        run_lease_id = str((_lease or {}).get("lease_id") or "")
        run_lease_short = (run_lease_id[:8] if run_lease_id else None)
        run_egress = str((_lease or {}).get("server_id")
                         or (_lease or {}).get("egress_ip") or "")
        run_egress_clean = (None if (_lease or {}).get("clean") is None
                            else bool((_lease or {}).get("clean")))
    else:
        _lease, run_egress = None, "direct"
    out = str(fields.get("out") or "").strip() or os.path.join(
        rundir, "precard.jsonl")
    progress_dir = str(fields.get("progress_dir") or "").strip() or os.path.join(
        rundir, "progress")
    # Receipt-equals-execution: linking flow spawns exactly the
    # receipt argv (no fills, never the precard runner); precard flow
    # keeps its own out/progress-dir fills via its own runner.
    if flow == "precard":
        final_argv = list(argv)
        if not str((fields or {}).get("out") or "").strip():
            final_argv += ["--out", out]
        if not str((fields or {}).get("progress_dir") or "").strip():
            final_argv += ["--progress-dir", progress_dir]
        cli_text = FLOW_RUNNERS["precard"]["show"](final_argv)
    else:
        final_argv = list(argv)
        cli_text = FLOW_RUNNERS["linking"]["show"](final_argv)
    has_gold = False
    if sample:
        try:
            gold = gold_rows_by_key(sample)
            has_gold = any(bool(v) for v in gold.values())
        except Exception:
            has_gold = False
    watermark = None
    if is_custom:
        watermark = ("%s: custom provider profile %r "
                     "(operator data — scoring refused)"
                     % (NON_COMPARABLE_WATERMARK, provider))
    elif not has_gold:
        watermark = NON_COMPARABLE_WATERMARK
    try:
        concurrency_val = int(fields.get("concurrency") or 0)
    except (TypeError, ValueError):
        concurrency_val = 0
    try:
        limit_val = int(fields.get("limit") or 0)
    except (TypeError, ValueError):
        limit_val = 0
    record = {
        "id": run_id,
        "run_name": run_name,
        "created": created,
        "flow": flow,
        "provider": provider,
        "model": str(fields.get("model") or ""),
        "route": run_route,
        "route_reason": run_route_reason,
        "lease": run_lease_short,
        "egress": run_egress,
        "egress_clean": run_egress_clean,
        "sample": sample,
        "limit": limit_val,
        "concurrency": concurrency_val,
        "out": out,
        "progress_dir": progress_dir,
        "resume": str(fields.get("resume") or "on"),
        "cli": cli_text,
        "dir": rundir,
        "status": "running",
        "exit_code": None,
        "pid": None,
        "stop_reason": None,
        "has_gold": bool(has_gold),
        "watermark": watermark,
        "preset": preset_stamp,
        "preset_version": preset_version,
        "profile": provider if is_custom else None,
    }
    log_path = os.path.join(rundir, "run.log")
    log_handle = open(log_path, "w", encoding="utf-8")
    # Unified key resolution for the child: operator-pasted keys fill
    # the gaps the environment + factory file leave (in-memory only;
    # the pump scrubs them from the log). Values never touch disk here.
    # Decrypted ONCE per run and reused (hot-path scrubber gets the
    # frozen set — no per-line file IO or Fernet work).
    child_env = dict(os.environ)
    if flow == "linking":
        # Offline child takes no secrets: keys stay out of its env.
        _op_keys = {}
    else:
        try:
            _op_keys = _operator_key_values()
        except Exception:
            _op_keys = {}
    try:
        for _var, _val in _op_keys.items():
            if _val and not child_env.get(_var):
                child_env[_var] = _val
    except Exception:
        pass
    try:
        _run_secret_values = tuple(
            v for v in _op_keys.values() if len(v or "") >= 8)
    except Exception:
        _run_secret_values = ()
    if _lease:
        # OUR lease proxy rides the child env only (parent untouched);
        # shared supervisor + others' leases undisturbed.
        _child_env_with_lease(child_env, _lease)
    try:
        proc = subprocess.Popen(
            final_argv, cwd=PROJECT_ROOT, env=child_env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        log_handle.close()
        return jsonify({"error": "spawn failed: %s" % exc}), 500
    # Durable child identity for pid-targeted cancel (fake spawns in
    # tests carry no pid — None then, cancel refuses without a target).
    # The fingerprint (process start time + command-line marker) lets
    # the restarted-server bare-pid path prove the pid still names
    # THIS child before signalling (PID reuse refuses as unknown
    # target). The marker is the resolved output path: it rides the
    # child argv (--out) for both flows, so it appears in the live
    # command line. Best-effort here (None/"" when unreadable) —
    # verification is fail-closed, so an incomplete fingerprint can
    # only refuse a later bare-pid cancel, never mis-signal.
    record["pid"] = _proc_pid(proc)
    try:
        _fp_time, _ = _pid_identity(record["pid"]) \
            if record["pid"] is not None else (None, "")
    except Exception:
        _fp_time = None
    record["pid_create_time"] = _fp_time
    record["pid_marker"] = out

    def _pump(_secrets=_run_secret_values):
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                log_handle.write(scrub_secrets(line, extra_values=_secrets))
                log_handle.flush()
        finally:
            try:
                log_handle.close()
            except OSError:
                pass
            try:
                code = proc.wait()
            except Exception:
                code = None
            # Terminal report for OUR lease only (ok on 0, unknown
            # otherwise — exit codes alone prove no network health).
            # Best-effort: never fails anything, cools nothing extra.
            try:
                if run_lease_id:
                    report_run_lease(run_lease_id, provider,
                                     ok=(code == 0))
            except Exception:
                pass

    with _lock:
        _procs[run_id] = proc
    threading.Thread(target=_pump, daemon=True).start()
    with _lock:
        records = _load_registry_migrated()
        records.append(record)
        _sort_records(records)
        _save_registry(records)
    return jsonify({"run": record}), 201


@app.route("/api/runs/<run_id>", methods=["GET"])
def api_run(run_id):
    with _lock:
        records = _load_registry_migrated()
        rec = _find_record(records, run_id)
        if rec is None:
            return jsonify({"error": "unknown run"}), 404
        code = _poll_proc(run_id)
        if code is not None and rec.get("status") == "running":
            rec["status"] = "done" if code == 0 else "failed"
            rec["exit_code"] = code
            _save_registry(records)
        return jsonify({"run": rec})


@app.route("/api/runs/<run_id>/cancel", methods=["POST"])
def api_cancel_run(run_id):
    """Stop a running child by pid only; terminal state failed/operator-stopped.

    Unknown runs 404; runs that already left "running" 409 with the
    record; a pid-identity mismatch or a missing target refuses
    without signalling (never a blanket kill).
    """
    rec, error, status = cancel_run(
        run_id, grace_seconds=CANCEL_GRACE_SECONDS)
    if rec is None:
        return jsonify({"error": error}), status
    if error is not None:
        body = {"run": rec, "error": error}
        if "already_finished" in str(error or ""):
            body["already_finished"] = True
        return jsonify(body), status
    return jsonify({"run": rec}), 200


@app.route("/api/runs/<run_id>/events", methods=["GET"])
def api_events(run_id):
    with _lock:
        records = _load_registry_migrated()
        rec = _find_record(records, run_id)
        if rec is None:
            return jsonify({"error": "unknown run"}), 404
        code = _poll_proc(run_id)
        if code is not None and rec.get("status") == "running":
            rec["status"] = "done" if code == 0 else "failed"
            rec["exit_code"] = code
            _save_registry(records)
    try:
        offset = int(request.args.get("offset", 0) or 0)
    except ValueError:
        offset = 0
    try:
        text = open(_events_path(rec), encoding="utf-8").read()
    except OSError:
        text = ""
    events = parse_run_events(text)
    for rec_event in events:
        for field in ("api_key", "apikey", "token", "secret"):
            rec_event.pop(field, None)
    status = rec.get("status")
    if status == "running" and code is not None:
        status = "done" if code == 0 else "failed"
    return jsonify({
        "events": events[max(offset, 0):],
        "total": len(events),
        "status": status,
        "exit_code": code if code is not None else rec.get("exit_code"),
        "cli": rec.get("cli", ""),
    })


@app.route("/api/runs/<run_id>/compare", methods=["GET"])
def api_compare(run_id):
    with _lock:
        rec = _find_record(_load_registry_migrated(), run_id)
        if rec is None:
            return jsonify({"error": "unknown run"}), 404
    profile = rec.get("profile")
    if profile:
        _ok, reason = comparability({}, {}, profile=profile)
        return jsonify({
            "comparable": False,
            "watermark": NON_COMPARABLE_WATERMARK,
            "reason": reason,
            "profile": profile,
            "cli": rec.get("cli", ""),
        })
    gold_path = request.args.get("gold") or rec.get("sample") or ""
    if not gold_path:
        return jsonify({
            "comparable": False,
            "watermark": NON_COMPARABLE_WATERMARK,
            "reason": "%s: run has no sample file (nothing to join gold on)"
                      % NON_COMPARABLE_WATERMARK,
            "cli": rec.get("cli", ""),
        })
    gold = gold_rows_by_key(gold_path)
    run_rows = run_rows_by_key(rec.get("out") or "")
    comparable, reason = comparability(gold, run_rows)
    if not comparable:
        return jsonify({
            "comparable": False,
            "watermark": NON_COMPARABLE_WATERMARK,
            "reason": reason,
            "cli": rec.get("cli", ""),
        })
    result = score_against_gold(run_rows, gold)
    joined_keys = sorted(set(run_rows) & set(gold))
    sample_full = sample_rows_full_by_key(gold_path)
    run_full = run_rows_full_by_key(rec.get("out") or "")


    def _gloss(row):
        for field in ("en_def", "gloss", "definition"):
            val = (row or {}).get(field) or ""
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""


    result.update({
        "comparable": True,
        "watermark": None,
        "reason": reason,
        "gold": gold_path,
        "cli": rec.get("cli", ""),
        # Full join table (additive): every joined key with its match flag,
        # so the benchmark screen can filter/sort/search/page over matched
        # rows too — not just the mismatches list above. Human-readable
        # source first (lemma + kind/pos + gloss); technical identifiers
        # (w:key, sense ids) ride along for the secondary small text.
        "rows": [{
            "key": key,
            "text": str((sample_full.get(key) or run_full.get(key)
                         or {}).get("text") or ""),
            "kind": str((sample_full.get(key) or run_full.get(key)
                         or {}).get("kind") or ""),
            "pos": str((sample_full.get(key) or run_full.get(key)
                        or {}).get("pos") or ""),
            "pool_level": str((sample_full.get(key) or run_full.get(key)
                               or {}).get("pool_level") or ""),
            "source_gloss": _gloss(sample_full.get(key))
            or _gloss(run_full.get(key)),
            "gold": gold.get(key, ""),
            "gold_gloss": _gloss(sample_full.get(key)),
            "predicted": run_rows.get(key, ""),
            "predicted_gloss": _gloss(run_full.get(key)),
            "match": run_rows.get(key, "") == gold.get(key, ""),
        } for key in joined_keys],
    })
    return jsonify(result)


# ─── Presets API (versioned, operator data) ──────────────────────────
# Engineering name: "job template" (قالب کاری). The /api/presets routes
# stay as the canonical store; /api/job_templates are thin aliases over
# the same records so old receipts and scripts keep replaying.

def _preset_payload():
    _ensure_witness_preset()
    runs = list_presets(kind="run")
    return {"job_templates": runs, "presets": runs}


def _save_preset_route(fields, force_kind=None):
    if force_kind is not None:
        fields = dict(fields or {})
        fields["kind"] = force_kind
    try:
        rec = save_preset(fields)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"error": "save failed: %s" % exc}), 500
    if rec.get("kind") == "judge":
        return jsonify({"judge_preset": rec, "preset": rec}), 200
    return jsonify({"preset": rec, "job_template": rec}), 200


@app.route("/api/engine_info", methods=["GET"])
def api_engine_info():
    """Honest engine facts (providers/models/knobs) — gaps stated, never faked."""
    return jsonify(engine_info())


@app.route("/api/files/roots", methods=["GET"])
def api_files_roots():
    return jsonify({"roots": _browse_roots()})


@app.route("/api/files/list", methods=["GET"])
def api_files_list():
    if not (request.args.get("dir") or "").strip():
        return jsonify({"error": "dir is required"}), 400
    ok, error, payload = _list_dir(request.args.get("dir") or "")
    if not ok:
        return jsonify({"error": error}), 400
    return jsonify(payload)


@app.route("/api/presets", methods=["GET"])
def api_presets():
    _ensure_witness_preset()
    kind = (request.args.get("kind") or "").strip() or None
    if kind is not None and kind not in PRESET_KINDS:
        return jsonify({"error": "kind must be one of %s" % "/".join(
            PRESET_KINDS)}), 400
    return jsonify({"presets": list_presets(kind=kind)})


@app.route("/api/job_templates", methods=["GET"])
def api_job_templates():
    return jsonify(_preset_payload())


@app.route("/api/judge_presets", methods=["GET"])
def api_judge_presets():
    return jsonify({"judge_presets": list_presets(kind="judge"),
                    "presets": list_presets(kind="judge")})


@app.route("/api/presets", methods=["POST"])
def api_preset_save():
    fields = request.get_json(force=True, silent=True) or {}
    return _save_preset_route(fields)


@app.route("/api/job_templates", methods=["POST"])
def api_job_template_save():
    fields = request.get_json(force=True, silent=True) or {}
    return _save_preset_route(fields, force_kind="run")


@app.route("/api/judge_presets", methods=["POST"])
def api_judge_preset_save():
    fields = request.get_json(force=True, silent=True) or {}
    return _save_preset_route(fields, force_kind="judge")


@app.route("/api/presets/<name>", methods=["DELETE"])
def api_preset_delete(name):
    if not delete_preset(name):
        return jsonify({"error": "preset not found: %s" % name}), 404
    return jsonify({"deleted": name})


@app.route("/api/job_templates/<name>", methods=["DELETE"])
def api_job_template_delete(name):
    if not delete_preset(name):
        return jsonify({"error": "job template not found: %s" % name}), 404
    return jsonify({"deleted": name})


@app.route("/api/judge_presets/<name>", methods=["DELETE"])
def api_judge_preset_delete(name):
    if not delete_preset(name):
        return jsonify({"error": "judge preset not found: %s" % name}), 404
    return jsonify({"deleted": name})


# ─── Custom provider profiles API (operator data) ────────────────────

@app.route("/api/custom_providers", methods=["GET"])
def api_profiles():
    return jsonify({"custom": custom_provider_rows()})


@app.route("/api/custom_providers", methods=["POST"])
def api_profile_save():
    fields = request.get_json(force=True, silent=True) or {}
    # Unified creation form: the operator pastes a key VALUE in the same
    # form; the key reference is auto-derived from the name server-side.
    # A legacy explicit ``key_var`` is still honored (old records callers).
    key_value = str((fields or {}).get("key_value")
                    or (fields or {}).get("key") or "")
    if key_value and not str((fields or {}).get("key_var") or "").strip():
        fields = dict(fields or {})
        fields["key_var"] = _key_var_for_custom_name(
            str(fields.get("name") or ""))
    try:
        rec = save_profile(fields)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"error": "save failed: %s" % exc}), 500
    if key_value:
        ok, error = _store_operator_key(rec.get("key_var") or "", key_value)
        if not ok:
            return jsonify({"error": error}), 500 if "master key" in error else 400
    return jsonify({"profile": rec}), 200


@app.route("/api/custom_providers/<name>", methods=["DELETE"])
def api_profile_delete(name):
    if not delete_profile(name):
        return jsonify({"error": "profile not found: %s" % name}), 404
    return jsonify({"deleted": name})


# ─── Operator keys API (encrypted at rest, names only out) ───────────
# Provider entities own keys now: per-provider endpoints are canonical.
# The generic /api/keys routes stay as thin wrappers over the same
# shared helpers so old receipts and scripts keep replaying.

@app.route("/api/providers/<name>/key", methods=["POST"])
def api_provider_key_save(name):
    """Save the key for a named built-in provider (first key var)."""
    provider = str(name or "").strip()
    if provider not in provider_registry.provider_names():
        return jsonify({"error": "unknown provider: %s" % provider}), 404
    fields = request.get_json(force=True, silent=True) or {}
    value = str((fields or {}).get("key_value")
                or (fields or {}).get("key") or "")
    var = _provider_key_var(provider)
    if not var:
        return jsonify({"error": "no key reference for: %s" % provider}), 500
    ok, error = _store_operator_key(var, value)
    if not ok:
        if "empty" in error or "reference name" in error:
            return jsonify({"error": error}), 400
        return jsonify({"error": error}), 500
    return jsonify({"stored": provider})


@app.route("/api/providers/<name>/key", methods=["DELETE"])
def api_provider_key_delete(name):
    """Delete the stored key for a named built-in provider."""
    provider = str(name or "").strip()
    if provider not in provider_registry.provider_names():
        return jsonify({"error": "unknown provider: %s" % provider}), 404
    var = _provider_key_var(provider)
    if not var or not _remove_operator_key(var):
        return jsonify({"error": "key not found for: %s" % provider}), 404
    return jsonify({"deleted": provider})


@app.route("/api/keys", methods=["GET"])
def api_keys():
    return jsonify({"keys": [{"key_var": v, "configured": True}
                             for v in operator_key_names()]})


@app.route("/api/keys", methods=["POST"])
def api_key_save():
    fields = request.get_json(force=True, silent=True) or {}
    var = str((fields or {}).get("key_var") or "").strip().upper()
    value = str((fields or {}).get("key_value") or "")
    ok, error = _store_operator_key(var, value)
    if not ok:
        if "empty" in error or "reference name" in error:
            return jsonify({"error": error}), 400
        return jsonify({"error": error}), 500
    return jsonify({"stored": var})


@app.route("/api/keys/<var>", methods=["DELETE"])
def api_key_delete(var):
    var = str(var or "").strip().upper()
    if not _remove_operator_key(var):
        return jsonify({"error": "key not found: %s" % var}), 404
    return jsonify({"deleted": var})


# ─── Screened browser + human labels (Steps 4-6, thin readers) ──────
# Read-only browser over the Step-2 screened export; append-only label
# store. Screening (factory.precard.prune) and scoring
# (factory.linking.linker arbitrate/signals) are never called and never
# modified — the candidates feed below only uses the linker's thin
# pure index accessors (cli.read_table + build_link_index/lookup_link)
# and the viewer's pure wordnet readers (resolver + parse_wn_parts +
# sensekey locator). Scoring, screening, evidence, and ranking code
# stay untouched. Join discipline: every row shows identifier + gloss
# together, never bare row numbers. Localhost only (HOST is 127.0.0.1,
# fixed).

DEFAULT_SCREENED_PATH = (
    "W:/hamzaban_data_factory/proof-linker/screened/screened.jsonl")
LABELS_PATH = os.path.join(SCRIPT_DIR, "labels.jsonl")

SCREENED_LIMIT = 500

#: Frozen vendor link table (shipped repo file — read-only via the
#: linker's own thin index accessors; never scored or rewritten here).
DEFAULT_LINK_TABLE = os.path.join(PROJECT_ROOT, "factory", "linking",
                                  "table.tsv")

#: REAL run candidate file (a linking run's own shortlist output, e.g.
#: run20 ``candidates_run20.json`` — read-only, never re-ranked here).
DEFAULT_CANDIDATES_RUN = (
    "W:/hamzaban_data_factory/proof-linker/run20/candidates_run20.json")

#: Human-review lists (both read-only, both honest-empty when absent):
#: the escalation-queue sink owned by ``factory/linking/human_queue.py``
#: plus one witness-label list (gold shape: list of ``{kid, ...}``).
DEFAULT_HUMAN_QUEUE = (
    "W:/hamzaban_data_factory/proof-linker/human_escalation_queue.jsonl")
DEFAULT_WITNESS_LABELS = (
    "W:/hamzaban_data_factory/proof-linker/gold/calibration_gold_26.json")

#: Every console input/output path resolves through configuration:
#: explicit query param, else these env vars, else the good default
#: above — no step path or main path is ever hardcoded in the logic.
SCREENED_ENV_VAR = "HAMZABAN_SCREENED_PATH"
LINK_TABLE_ENV_VAR = "HAMZABAN_LINK_TABLE"
CANDIDATES_RUN_ENV_VAR = "HAMZABAN_CANDIDATES_RUN"
HUMAN_QUEUE_ENV_VAR = "HAMZABAN_HUMAN_QUEUE"
WITNESS_LABELS_ENV_VAR = "HAMZABAN_WITNESS_LABELS"


def _configured_path(explicit, env_var, default):
    """Resolve one console path: explicit arg, else env, else default."""
    hit = str(explicit or "").strip()
    if hit:
        return hit
    hit = (os.environ.get(env_var) or "").strip()
    if hit:
        return hit
    return default


def screened_id_map(screened_path):
    """Map SHORT queue ids (``sense.sense_id``, e.g. ``run#5``) to FULL
    kaikki ids (``sense.id``, e.g. ``en-run-en-verb-tL7-sssU``).

    Pure reader over the screened export: skips bad lines and rows
    without both forms. Missing file -> ``{}`` (no join, never an
    invented mapping).
    """
    mapping = {}
    try:
        handle = open(screened_path, encoding="utf-8")
    except OSError:
        return mapping
    with handle:
        for line in handle:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            sense = rec.get("sense")
            if not isinstance(sense, dict):
                continue
            short = sense.get("sense_id")
            full = sense.get("id")
            if isinstance(short, str) and short.strip() \
                    and isinstance(full, str) and full.strip():
                mapping.setdefault(short.strip(), full.strip())
    return mapping


def _sense_gloss(sense):
    """First non-empty gloss of a kept sense dict ("" when none)."""
    if not isinstance(sense, dict):
        return ""
    for cand in sense.get("glosses") or []:
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    gloss = sense.get("gloss")
    return gloss.strip() if isinstance(gloss, str) and gloss.strip() else ""


def _sense_example(sense):
    """First example sentence of a kept sense dict ("" when none)."""
    if not isinstance(sense, dict):
        return ""
    for item in sense.get("examples") or []:
        text = item.get("text") if isinstance(item, dict) else item
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def screened_rows(screened_path):
    """[{lemma, sense_id, gloss, example}] from a screened.jsonl export.

    Pure reader: skips bad lines and rows without a sense_id. The
    sense dict itself is never re-screened or re-ranked here.
    """
    rows = []
    try:
        handle = open(screened_path, encoding="utf-8")
    except OSError:
        return rows
    with handle:
        for line in handle:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            sense = rec.get("sense")
            if not isinstance(sense, dict):
                continue
            sid = sense.get("sense_id")
            if not (isinstance(sid, str) and sid.strip()):
                continue
            rows.append({
                "lemma": str(rec.get("lemma") or ""),
                "sense_id": sid.strip(),
                "gloss": _sense_gloss(sense),
                "example": _sense_example(sense),
            })
    return rows


def _label_watermark(rec):
    """Non-gold strata are custom judgments: watermark, never scored."""
    if str((rec or {}).get("stratum") or "") != "gold":
        return ("%s: custom stratum %r is an operator judgment, "
                "not a gold label (never scored)" % (
                    NON_COMPARABLE_WATERMARK,
                    str((rec or {}).get("stratum") or "")))
    return None


@app.route("/api/screened", methods=["GET"])
def api_screened():
    """Read-only list of screened source senses (identifier + gloss)."""
    path = _configured_path(request.args.get("path"), SCREENED_ENV_VAR,
                            DEFAULT_SCREENED_PATH)
    query = (request.args.get("q") or "").strip().lower()
    rows = screened_rows(path)
    if query:
        rows = [r for r in rows
                if query in r["sense_id"].lower()
                or query in r["gloss"].lower()
                or query in r["lemma"].lower()]
    total = len(rows)
    return jsonify({"path": path, "total": total,
                    "rows": rows[:SCREENED_LIMIT],
                    "truncated": total > SCREENED_LIMIT})


def _candidates_limit():
    """Review-queue candidate cap from the linker owner (12 on fallback).

    Reads ``SHORTLIST_CAP`` at call time (lazy: the linker core is
    never imported at server startup); the literal is a fallback only,
    never a second registry.
    """
    try:
        from factory.linking import linker as _linker
        return int(_linker.SHORTLIST_CAP)
    except Exception:
        return 12


def _wordnet_live_fields(sensekey):
    """(synset_name, example) for one sensekey, best-effort ("" when absent).

    Read-only over the same ``synset_from_sense_key`` seam the viewer
    resolver uses (the engine exposes no example/synset-name reader, so
    this thin read lives here, in the adapter — never in the core).
    Missing NLTK/wordnet data fails soft to ("", ""): honest empty,
    never invented.
    """
    try:
        from nltk.corpus import wordnet as _wn
        syn = _wn.synset_from_sense_key(sensekey or "")
    except Exception:
        return "", ""
    if syn is None:
        return "", ""
    try:
        name = _wn.synset_from_sense_key(sensekey or "").name() or ""
    except Exception:
        name = ""
    try:
        examples = syn.examples() or []
        first = examples[0] if examples else ""
        example = first if isinstance(first, str) else ""
    except Exception:
        example = ""
    return name, example


def _read_run_candidates(run_path):
    """Normalized candidates from a REAL run file (read-only, order kept).

    The run file maps FULL kaikki ids to ``{top3: [{sensekey, gloss,
    lemmas, examples, fires, jaccard}]}`` (run20 ``candidates_run20.json``
    shape). Each entry becomes one adapter row (verbatim run data — no
    wordnet lookups, no re-ranking, nothing invented). Missing or
    unreadable file -> ``{}`` (honest empty, never fabricated).
    """
    try:
        with open(run_path, encoding="utf-8") as handle:
            blob = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(blob, dict):
        return {}
    try:
        from factory.linking import viewer as _viewer
    except Exception:
        _viewer = None
    out = {}
    for kid, rec in blob.items():
        if not isinstance(kid, str) or not kid.strip():
            continue
        if not isinstance(rec, dict):
            continue
        entries = rec.get("top3")
        if not isinstance(entries, list):
            continue
        rows = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            skey = entry.get("sensekey")
            if not (isinstance(skey, str) and skey.strip()):
                continue
            skey = skey.strip()
            lemmas = entry.get("lemmas")
            synonyms = [s for s in (lemmas or [])
                        if isinstance(s, str) and s.strip()]
            examples = entry.get("examples")
            example = ""
            for item in (examples or []):
                text = item.get("text") if isinstance(item, dict) else item
                if isinstance(text, str) and text.strip():
                    example = text.strip()
                    break
            fires = [f for f in (entry.get("fires") or [])
                     if isinstance(f, str) and f.strip()]
            try:
                jac = float(entry.get("jaccard"))
                jac_text = "j=%.4g" % jac
            except (TypeError, ValueError):
                jac_text = ""
            evidence = "+".join(fires)
            if jac_text:
                evidence = (evidence + " · " + jac_text).strip(" ·")
            try:
                locator = _viewer._parse_sensekey_locator(skey) \
                    if _viewer is not None else ""
            except Exception:
                locator = ""
            gloss = entry.get("gloss")
            rows.append({
                "sensekey": skey,
                "synset": "",
                "synset_locator": locator,
                "gloss": gloss if isinstance(gloss, str) else "",
                "synonyms": synonyms,
                "example": example,
                "method": "run:top3",
                "evidence": evidence,
            })
        out[kid.strip()] = rows
    return out


def review_flags_for_sense(full_id, short_id, queue_path, witness_path):
    """Human-review flags for one sense (read-only join, never invented).

    The queue sink is read through the owner's own
    ``human_queue.load_queue_deduped`` (records match on either key
    form); the witness list accepts gold/witness shapes (a list of
    ``{kid, ...}`` or ``{"rows": [...]}`` with a verdict-ish key and an
    optional winner sensekey). Missing files -> empty flags.
    """
    flags = {"in_review": False, "review_reason": "",
             "witness_verdict": "", "witness_pick": ""}
    keys = {k for k in (full_id, short_id)
            if isinstance(k, str) and k.strip()}
    try:
        from factory.linking import human_queue as _hq
        queue_rows = _hq.load_queue_deduped(queue_path)
    except Exception:
        queue_rows = []
    for rec in (queue_rows or []):
        if not isinstance(rec, dict):
            continue
        hit = ""
        entry = rec.get("source_entry")
        if isinstance(entry, dict):
            for key in ("sense_id", "id"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip() in keys:
                    hit = value.strip()
                    break
        if not hit:
            for key in ("sense_id", "id", "kid"):
                value = rec.get(key)
                if isinstance(value, str) and value.strip() in keys:
                    hit = value.strip()
                    break
        if hit:
            flags["in_review"] = True
            reason = rec.get("escalation_reason")
            if isinstance(reason, str) and reason.strip():
                flags["review_reason"] = reason.strip()
            break
    try:
        with open(witness_path, encoding="utf-8") as handle:
            blob = json.load(handle)
    except (OSError, ValueError):
        blob = None
    entries = blob.get("rows") if isinstance(blob, dict) else blob
    for entry in (entries or []):
        if not isinstance(entry, dict):
            continue
        kid = entry.get("kid")
        if not (isinstance(kid, str) and kid.strip() in keys):
            continue
        for key in ("gemini_verdict", "verdict", "class", "baseline"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                flags["witness_verdict"] = value.strip()
                break
        for key in ("winner_sensekey", "table_winner_sensekey",
                    "target_synset"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                flags["witness_pick"] = value.strip()
                break
        break
    return flags


def _resolve_full_sense_id(kid, run_keys, table_index, screened_path):
    """Resolve any queue identifier to its FULL kaikki id ("" = no join).

    Direct hits (already-full ids present in the run file or vendor
    table) pass through with no map read. Otherwise the SHORT screened
    id resolves through the screened export's ``sense.id`` map. A
    short-form id (``lemma#N``) absent from the map is unresolvable
    (no-join); anything else is taken as a full-form id that simply
    has no rows anywhere (no-data).
    """
    if kid in run_keys or kid in table_index:
        return kid
    mapping = screened_id_map(screened_path)
    if kid in mapping:
        return mapping[kid]
    if "#" in kid:
        return ""
    return kid


def candidates_for_sense(sense_id, table_path=None, resolver=None,
                         run_path=None, queue_path=None, witness_path=None,
                         screened_path=None):
    """WordNet candidates for one sense id (read-only, no scoring).

    Join order (nothing ever lost): REAL run rows first (file order),
    then vendor-table rows for sensekeys not already seen (index
    order), each annotated with read-only human-review flags
    (``in_review`` / ``review_reason`` / ``witness_pick``). Every path
    resolves through configuration (explicit arg, else ``HAMZABAN_*``
    env, else the good default) — no literals. The queue's SHORT id
    resolves to the FULL kaikki id through the screened map; full ids
    pass through. ``[]`` is always honest (no join, or joined but no
    rows) — rows are never fabricated.
    """
    kid = str(sense_id or "").strip()
    if not kid:
        return []
    from factory.linking import build_link_index, lookup_link
    from factory.linking import cli as _link_cli
    from factory.linking import viewer as _viewer

    table = _configured_path(table_path, LINK_TABLE_ENV_VAR,
                             DEFAULT_LINK_TABLE)
    run = _configured_path(run_path, CANDIDATES_RUN_ENV_VAR,
                           DEFAULT_CANDIDATES_RUN)
    queue = _configured_path(queue_path, HUMAN_QUEUE_ENV_VAR,
                             DEFAULT_HUMAN_QUEUE)
    witness = _configured_path(witness_path, WITNESS_LABELS_ENV_VAR,
                               DEFAULT_WITNESS_LABELS)
    screened = _configured_path(screened_path, SCREENED_ENV_VAR,
                                DEFAULT_SCREENED_PATH)
    _header, rows = _link_cli.read_table(table)
    index = build_link_index(rows or [])
    run_rows = _read_run_candidates(run)
    full = _resolve_full_sense_id(kid, set(run_rows), index, screened)
    if not full:
        return []
    flags = review_flags_for_sense(full, kid, queue, witness)
    pick = flags.get("witness_pick") or ""
    out = []
    seen = set()
    for row in (run_rows.get(full) or []):
        skey = row.get("sensekey") or ""
        if skey in seen:
            continue
        seen.add(skey)
        out.append({**row, "in_review": flags["in_review"],
                    "review_reason": flags["review_reason"],
                    "witness_pick": bool(pick) and skey == pick})
    if resolver is None:
        try:
            resolver = _viewer._default_wordnet_resolver()
        except Exception:
            resolver = None
    hits = lookup_link(index, full) or []
    for row in hits[:_candidates_limit()]:
        if not isinstance(row, dict):
            continue
        skey = str(row.get("wordnet_sensekey") or "")
        if not skey or skey in seen:
            continue
        seen.add(skey)
        try:
            raw = _viewer._resolve_wordnet_def(skey, resolver)
        except Exception:
            raw = ""
        try:
            gloss, synonyms, _packed_eg = _viewer.parse_wn_parts(raw or "")
        except Exception:
            gloss, synonyms = "", []
        try:
            locator = _viewer._parse_sensekey_locator(skey)
        except Exception:
            locator = ""
        synset_name, example = _wordnet_live_fields(skey)
        if not example and isinstance(_packed_eg, str):
            example = _packed_eg
        out.append({
            "sensekey": skey,
            "synset": synset_name or locator,
            "synset_locator": locator,
            "gloss": gloss,
            "synonyms": list(synonyms or []),
            "example": example,
            "method": str(row.get("method") or ""),
            "evidence": str(row.get("evidence") or ""),
            "in_review": flags["in_review"],
            "review_reason": flags["review_reason"],
            "witness_pick": bool(pick) and skey == pick,
        })
    return out


def candidate_feed_for(sense_id, table_path=None, resolver=None,
                       run_path=None, queue_path=None, witness_path=None,
                       screened_path=None):
    """Feed envelope for ``GET /api/candidates`` (pure join, no I/O here
    beyond the readers above).

    ``cause`` names the empty state: ``joined`` (rows found),
    ``no-join`` (the id resolved to no kaikki identity), ``no-data``
    (joined identity, rows nowhere). ``full_id`` is the resolved
    identity ("" on no-join); ``witness_verdict`` rides at the sense
    level so the page need not scan rows.
    """
    kid = str(sense_id or "").strip()
    if not kid:
        return {"sense_id": "", "full_id": "", "total": 0,
                "candidates": [], "cause": "no-join",
                "witness_verdict": ""}
    from factory.linking import build_link_index
    from factory.linking import cli as _link_cli

    table = _configured_path(table_path, LINK_TABLE_ENV_VAR,
                             DEFAULT_LINK_TABLE)
    run = _configured_path(run_path, CANDIDATES_RUN_ENV_VAR,
                           DEFAULT_CANDIDATES_RUN)
    queue = _configured_path(queue_path, HUMAN_QUEUE_ENV_VAR,
                             DEFAULT_HUMAN_QUEUE)
    witness = _configured_path(witness_path, WITNESS_LABELS_ENV_VAR,
                               DEFAULT_WITNESS_LABELS)
    screened = _configured_path(screened_path, SCREENED_ENV_VAR,
                                DEFAULT_SCREENED_PATH)
    try:
        _header, rows = _link_cli.read_table(table)
    except OSError:
        raise
    index = build_link_index(rows or [])
    run_rows = _read_run_candidates(run)
    full = _resolve_full_sense_id(kid, set(run_rows), index, screened)
    if not full:
        return {"sense_id": kid, "full_id": "", "total": 0,
                "candidates": [], "cause": "no-join",
                "witness_verdict": ""}
    cands = candidates_for_sense(kid, table, resolver, run, queue,
                                 witness, screened)
    flags = review_flags_for_sense(full, kid, queue, witness)
    return {"sense_id": kid, "full_id": full, "total": len(cands),
            "candidates": cands,
            "cause": "joined" if cands else "no-data",
            "witness_verdict": flags.get("witness_verdict") or ""}


@app.route("/api/candidates", methods=["GET"])
def api_candidates():
    """Read-only WordNet candidate feed for one review-queue sense.

    ``GET /api/candidates?sense_id=<queue-sense-id>`` -> ``{"sense_id",
    "full_id", "total", "candidates", "cause", "witness_verdict"}``.
    The queue id may be SHORT (``run#5`` — resolved to the FULL kaikki
    id through the screened map) or FULL (passes through). Rows join
    REAL run shortlists first, then vendor-table rows, each annotated
    with read-only human-review flags. Every path is configurable
    (query param, else ``HAMZABAN_*`` env, else the good default).
    400 when the sense identifier is missing; 500 when the vendor table
    is unreadable; 200 with an (honest, possibly empty) list otherwise.
    """
    sense_id = (request.args.get("sense_id") or "").strip()
    if not sense_id:
        return jsonify({"error": "sense_id is required"}), 400
    try:
        feed = candidate_feed_for(
            sense_id,
            request.args.get("table"),
            run_path=request.args.get("run"),
            queue_path=request.args.get("queue"),
            witness_path=request.args.get("witness"),
            screened_path=request.args.get("screened"))
    except OSError as exc:
        return jsonify({"error": "cannot read link table: %s" % exc}), 500
    return jsonify(feed)


@app.route("/api/labels", methods=["GET"])
def api_labels():
    """Read the human-annotation store (newest last, names only)."""
    store = (request.args.get("store") or "").strip() or LABELS_PATH
    try:
        from factory.webui import labels as _labels
    except ImportError as exc:
        return jsonify({"error": "label store unavailable: %s" % exc}), 500
    return jsonify({"store": store,
                    "labels": _labels.load_labels(store)})


@app.route("/api/labels", methods=["POST"])
def api_label_save():
    """Save one operator judgment (append-only, enum-validated)."""
    from factory.webui import labels as _labels

    fields = request.get_json(force=True, silent=True) or {}
    store = str((fields or {}).get("store") or "").strip() or LABELS_PATH
    try:
        rec = _labels.save_label(fields, store)
    except _labels.LabelError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "label": rec,
        "store": store,
        "replay": _labels.replay_reference(rec),
        "watermark": _label_watermark(rec),
    }), 201


def build_boot_lines(host, port, pid, lan):
    """Boot receipt lines proving the exact bind (pure, no I/O).

    First line always reproduces the bound host/port/pid exactly.
    A plain all-interfaces start appends a LAN-visibility note (which
    address to open from a tablet vs loopback on this machine); an
    explicit override reproduces exactly with no note. Names only,
    no secrets.
    """
    lines = ["webui boot host=%s port=%s pid=%s" % (host, port, pid)]
    if str(host or "").strip() in (ALL_INTERFACES, "::"):
        if lan:
            lines.append(
                "webui net lan=%s note=plain start is LAN-visible: "
                "open http://%s:%s from tablet, "
                "http://127.0.0.1:%s on this machine"
                % (lan, lan, port, port))
        else:
            lines.append(
                "webui net lan=unavailable note=plain start binds all "
                "interfaces but no LAN address detected: open "
                "http://127.0.0.1:%s on this machine" % (port,))
    return lines


if __name__ == "__main__":
    _args = parse_server_args()
    os.chdir(PROJECT_ROOT)
    os.makedirs(RUNS_DIR, exist_ok=True)
    # Boot receipt: proves the exact host/port the process bound
    # (operators match this line against the -BindHost/-Port they
    # passed to server_ctl.ps1; names only, no secrets).
    for _line in build_boot_lines(
            _args.host, _args.port, os.getpid(), _detect_lan_ipv4()):
        print(_line, flush=True)
    app.run(host=_args.host, port=_args.port)
