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
    Operator-only caution: the plain LAN-visible bind exposes
    key-accepting endpoints with no auth (trusted LAN only).

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
import time
import uuid

from flask import Flask, Response, jsonify, request, send_from_directory

from factory.precard import provider_registry
from factory.precard.accounting import source_item_key
from factory.core.env_loader import data_root
from factory.webui import batches as _batches
from factory.webui import batch_import as _batch_import
from factory.webui import batch_repair as _batch_repair
from factory.webui import gallery as _gallery

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
#: Shared operator store (outside git): presets, operator keys, and labels
#: live under the single-source data root. These are lazy helpers (not
#: module constants) because ``data_root()`` is lazy per call — binding
#: paths once at import would split reads/writes across roots when
#: ``HAMZABAN_DATA_ROOT`` changes later. Run history
#: (RUNS_DIR/REGISTRY_PATH) stays per-console by design.
def presets_dir():
    """Shared presets dir, re-resolved per call (never cached)."""
    return os.path.join(data_root(), "webui", "presets")


PROFILES_DIR = os.path.join(SCRIPT_DIR, "provider_profiles")


def operator_keys_path():
    """Shared operator-keys file, re-resolved per call (never cached)."""
    return os.path.join(data_root(), "webui", "operator_keys.json")
KEY_VAR_MAP_PATH = os.path.join(SCRIPT_DIR, "provider_key_vars.json")
MASTER_VAR = "AI_MASTER_KEY"

#: Supervisor bearer variable (name only — the value is pasted once in the
#: providers panel, stored encrypted in the operator store, and never
#: displayed, logged, or returned).
SUPERVISOR_TOKEN_VAR = "EGRESS_SUP_TOKEN"

FACTORY_ENV_PATH = os.path.abspath(
    os.path.join(PROJECT_ROOT, "factory", ".env"))

#: Owner-configured supervisor idle-minutes override (name only; value
#: never logged). Declared early: primary-path helpers below do not
#: depend on it, but the lifecycle surface does.
SUPERVISOR_IDLE_MINUTES_ENV_VAR = "HAMZABAN_SUPERVISOR_IDLE_MINUTES"

_PRIMARY_ROOT_CACHE = {"root": None}


def _primary_root():
    """Primary checkout root (read-only fallback for worktree runs).

    The console may serve from an isolated worktree whose own env
    files do not exist; the operator's secrets live in the primary
    checkout. A worktree ``.git`` file points at
    ``<primary>/.git/worktrees/<name>``; a plain checkout is its own
    primary. "" when unresolvable (current behavior, never a guess).
    Values are never read here — only the directory name.
    """
    if _PRIMARY_ROOT_CACHE["root"] is not None:
        return _PRIMARY_ROOT_CACHE["root"]
    root = ""
    try:
        checkout = os.path.abspath(PROJECT_ROOT)
        dotgit = os.path.join(checkout, ".git")
        if os.path.isdir(dotgit):
            root = checkout
        elif os.path.isfile(dotgit):
            try:
                with open(dotgit, encoding="utf-8") as handle:
                    first = (handle.read().strip().splitlines() or [""])[0]
            except (OSError, ValueError):
                first = ""
            if first.startswith("gitdir:"):
                gitdir = first.split(":", 1)[1].strip()
                if not os.path.isabs(gitdir):
                    gitdir = os.path.abspath(
                        os.path.join(checkout, gitdir))
                # <primary>/.git/worktrees/<name> -> <primary>
                primary = os.path.abspath(os.path.join(
                    gitdir, "..", "..", ".."))
                anchor = os.path.join(primary, ".git")
                if os.path.isdir(anchor) or os.path.isfile(anchor):
                    root = primary
    except (OSError, ValueError):
        root = ""
    _PRIMARY_ROOT_CACHE["root"] = root
    return root


def _extra_key_paths():
    """Key lookup files beyond the engine default (primary fallback).

    The engine default (this checkout's ``factory/.env``) stays first;
    the primary checkout's ``factory/.env`` + ``tools/egress/.env``
    follow read-only (never written, never logged). A plain-checkout
    run adds nothing (no duplicate reads). Always passed explicitly
    to the lease-policy resolver seam (hermetic tests keep mocking
    that seam — no direct file reads here).
    """
    try:
        from factory.precard.provider_lease_policy import (
            _default_factory_env as _default_env)
        default = _default_env()
    except Exception:
        default = ""
    paths = [default] if default else []
    root = _primary_root()
    if root and os.path.abspath(root) != os.path.abspath(PROJECT_ROOT):
        for cand in (os.path.join(root, "factory", ".env"),
                     os.path.join(root, "tools", "egress", ".env")):
            if os.path.isfile(cand) and cand not in paths:
                paths.append(cand)
    return [p for p in paths if p]

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

    The whole check+generate+append runs under ``_lock``: two racing
    confirmed calls must not both append (the loser would orphan keys
    encrypted under the other key). Re-entrant safe — callees take no
    other lock, and request handlers are synchronous.
    """
    with _lock:
        return _ensure_factory_master_key_locked(confirmed=confirmed)


def _ensure_factory_master_key_locked(confirmed=False):
    """ensure_factory_master_key body; caller must hold ``_lock``."""
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


def _resolve_any(vars_, file_paths=None):
    """True when any key var resolves via env or the env files.

    Unified loader order: process env first, then the dotenv files
    (this checkout's ``factory/.env`` plus the primary checkout's
    ``factory/.env`` + ``tools/egress/.env`` read-only fallback, so a
    worktree console sees the operator's primary keys with zero manual
    copies). Names in, boolean out — values never read here.
    ``file_paths`` injects the list (tests pass fakes — never files).
    """
    try:
        from factory.precard.provider_lease_policy import (
            resolve_key as _resolve,
        )
    except Exception:
        _resolve = None
    paths = list(file_paths) if file_paths is not None \
        else _extra_key_paths()
    for var in vars_ or ():
        if not var:
            continue
        if os.environ.get(var):
            return True
        if _resolve is not None:
            try:
                if _resolve(var, file_paths=paths):
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
        stored = _read_json_file(operator_keys_path())
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


def _read_json_file(path):
    """JSON dict from a file with closed handles ({} when unreadable)."""
    try:
        with open(str(path), encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _request_manifest_manager():
    """One manifest manager per request (single disk load, names only).

    Built through the registry seam (``fresh_manager``) so the
    registry test seam keeps working. The manager caches after its
    first load, so every registry call in the request shares one
    read. None when unconstructable (registry calls fall back to
    single fresh reads, as before).
    """
    try:
        return provider_registry.fresh_manager()
    except Exception:
        return None


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
    _mgr = _request_manifest_manager()
    for name in provider_registry.provider_names(_manager=_mgr):
        try:
            refs = provider_registry.ordered_key_vars(name, _manager=_mgr)
        except Exception:
            refs = []
        try:
            compat = list(provider_registry.key_ref_for(
                name, "G1", _manager=_mgr)
                + provider_registry.key_ref_for(name, "G2", _manager=_mgr))
        except Exception:
            compat = []
        merged = list(refs)
        for var in compat:
            if var and var not in merged:
                merged.append(var)
        refs = merged
        if not refs:
            refs = list(compat)
        effective = _provider_key_var(name, _manager=_mgr)
        ordered = []
        for var in ([effective] if effective else []) + refs:
            if var and var not in ordered:
                ordered.append(var)
        ready = _resolve_any(ordered) or any(
            v in stored for v in ordered)
        try:
            slot_count = int(provider_registry.key_count(name, _manager=_mgr))
        except Exception:
            slot_count = len(ordered)
        route, route_reason = route_for_provider(
            name,
            registry_fn=lambda n: provider_registry.resolve_provider(
                n, _manager=_mgr))
        rows.append({
            "name": name,
            "key_vars": ordered,
            "key_var": effective,
            "has_key": bool(ready),
            "key_count": int(slot_count),
            "active_keys": int(slot_count),
            "route": route,
            "route_reason": route_reason,
            "clean_exit": (_clean_head if route == "leased"
                           and name == "google" else ""),
        })
    return rows


def operator_key_names():
    """Names of operator-stored keys (names only, never values)."""
    try:
        stored = json.load(open(operator_keys_path(), encoding="utf-8"))
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


class _CycleFetchFailed(Exception):
    """Parked model-list fetch (no exception reached the transport)."""


def _http_code_of(exc):
    """HTTP status of a fetch failure (None when not HTTP)."""
    import urllib.error as _httperr
    if isinstance(exc, _httperr.HTTPError):
        try:
            return int(exc.code)
        except (TypeError, ValueError):
            return None
    return None


def _model_list_target(name, row, key_value):
    """(endpoint, headers, ids_of, error_or_None) for one provider.

    Pure composition over the provider row (data only — the key VALUE
    stays in-memory inside the returned headers, never logged or
    returned). Gemini-rest rows list via models:list; every other
    row lists via its OpenAI-compatible {base}/models.
    """
    protocol = str((row or {}).get("protocol") or "")
    try:
        from factory.precard.provider_manifest import (
            effective_trust as _trust)
        trusted = _trust(name, row)
    except Exception:
        trusted = False
    if protocol == "gemini_rest" or str(name or "") == "google":
        if not trusted:
            return None, None, None, (
                "%s is not trusted: stored keys are never sent until "
                "trust is confirmed in the providers panel" % name)
        return ("https://generativelanguage.googleapis.com/"
                "v1beta/models?pageSize=200",
                {"x-goog-api-key": key_value},
                _google_model_ids, None)
    base = str((row or {}).get("base_url") or "")
    endpoint = _openai_models_endpoint(base)
    if not endpoint:
        return None, None, None, ("%s has no listable base address "
                                  "(no /models endpoint)" % name)
    try:
        from factory.precard.provider_manifest import (
            base_host_allowed as _host_ok)
        host_ok = _host_ok(base)
    except Exception:
        host_ok = False
    if not host_ok:
        return None, None, None, ("%s base host is not allowed "
                                  "(loopback, localhost, or public "
                                  "IP/hostname only)" % name)
    if key_value and not trusted:
        return None, None, None, (
            "%s is not trusted: stored keys are never sent until "
            "trust is confirmed in the providers panel" % name)
    return endpoint, {"Authorization": "Bearer " + key_value}, \
        _openai_model_ids, None


def _cycle_store():
    """Provider-namespaced cycle store (existing store, file-backed).

    The existing ``ProviderCacheStore`` (one file keyed by provider —
    namespaces never leak) beside the supervisor pool; None when the
    pool home is unreadable (the cycle then runs store-less — cache
    check reads miss, remember skips the write, never raises).
    """
    try:
        from factory.net.tunnel_selection import ProviderCacheStore
        from tools.egress.supervisor import POOL_PATH as _pool
        path = str(_pool.parent / "provider_cycle_cache.json")
    except Exception:
        return None
    try:
        return ProviderCacheStore(path)
    except Exception:
        return None


def _pool_file_servers():
    """Server rows from the supervisor pool file (single definition).

    Closed handles (``with open`` — never a bare ``open`` leaking fds
    on this threaded server); [] when unreadable (callers treat an
    absent pool as no candidates, never an error).
    """
    try:
        from tools.egress.supervisor import POOL_PATH as _pool
        with open(str(_pool), encoding="utf-8") as handle:
            payload = json.load(handle)
        servers = (payload.get("servers") if isinstance(payload, dict)
                   else None) or []
    except (OSError, ValueError):
        return []
    return [s for s in servers if isinstance(s, dict)]


def _pool_snapshot_rows(lease_server_id="", clean_fn=None):
    """Supervisor pool snapshot rows for the cycle refresh (data only).

    OUR leased exit first (paid), then the pooled server ids in file
    order (paid) — the driver dedupes + paid-firsts them through the
    existing helpers. The fresh-whitelist leg arrives via ``clean_fn``
    (tests pass fakes — never the real cache file); the default is
    the T5 linker adapter, resolved at call time. File reads only
    (pool + whitelist); no network, no new egress path. Capped at 20
    (pool top-N scale).
    """
    rows = []
    if lease_server_id:
        rows.append({"id": str(lease_server_id), "source": "paid"})
    servers = _pool_file_servers()
    try:
        from factory.linking import google_clean as _gc
        clean_reader = (clean_fn if clean_fn is not None
                        else _gc.fresh_clean_exits)
        whitelist = list(clean_reader() or [])
    except Exception:
        whitelist = []
    for sid in list(whitelist) + [
            s.get("id") for s in servers if isinstance(s, dict)]:
        if isinstance(sid, str) and sid and all(
                r.get("id") != sid for r in rows):
            rows.append({"id": sid, "source": "paid"})
        if len(rows) >= 20:
            break
    return rows


def _cycle_ping_fn(proxy_url=""):
    """Ping closure over the snapshot (reachability only, never keys).

    Pool exits ping their pooled host/port; OUR leased exit pings the
    proxy loopback (supervisor reachability); unknown ids read
    unreachable (honest fallback, never a guess). Never raises.
    """
    try:
        from tools.egress.supervisor import tcp_ping as _ping
    except Exception:
        return lambda exit_id: None
    try:
        servers = _pool_file_servers()
        addrs = {s.get("id"): (s.get("host"), s.get("port"))
                 for s in servers if s.get("id")}
    except (OSError, ValueError):
        addrs = {}
    try:
        from urllib.parse import urlsplit as _split
        parts = _split(proxy_url or "")
        proxy_addr = ((parts.hostname or ""),
                      (parts.port or 0)) if proxy_url else ("", 0)
    except Exception:
        proxy_addr = ("", 0)

    def _ping_exit(exit_id):
        host, port = addrs.get(exit_id, (None, None))
        if host is None and proxy_addr[0]:
            host, port = proxy_addr
        try:
            return _ping(host, port, 1.0)
        except Exception:
            return None

    return _ping_exit


def provider_model_list(provider, timeout=30, *, lease_fn=None,
                         target_fn=None, clean_fn=None, verify_fn=None,
                         remember_fn=None, report_fn=None, tunneled=None,
                         env_map=None, file_paths=None,
                         registry_fn=None, wake_fn=None, health_fn=None,
                         state_log=None, pool_fn=None, ping_fn=None):
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

    The fetch walks the generic provider cycle
    (``factory.net.provider_cycle.run_cycle`` — cache check, refresh
    from the supervisor pool snapshot, ping, batched keyed prove,
    remember, done) thinly: the ordered state machine appends to
    ``state_log`` (when a list is passed) and the Persian interface
    lines ride the result. ``pool_fn``/``ping_fn`` inject the
    refresh/ping legs (tests pass fakes — never files or sockets).
    """
    import urllib.request as _url
    from factory.net.provider_cycle import run_cycle as _run_cycle

    name = str(provider or "").strip()
    _mgr = _request_manifest_manager()
    if name not in provider_registry.provider_names(_manager=_mgr):
        return None, "unknown provider: %s" % name
    try:
        row = provider_registry.resolve_provider(name, _manager=_mgr) or {}
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
        eff = _provider_key_var(name, _manager=_mgr)
        try:
            refs = list(provider_registry.ordered_key_vars(
                name, _manager=_mgr))
        except Exception:
            refs = []
        if not refs:
            refs = list(provider_registry.key_ref_for(
                name, "G1", _manager=_mgr)
                + provider_registry.key_ref_for(name, "G2", _manager=_mgr))
        for var in ([eff] if eff else []) + refs:
            if var and var not in var_order:
                var_order.append(var)
    except Exception:
        var_order = []
    key_value = ""
    key_paths = _extra_key_paths()
    for var in var_order:
        if _resolve is not None:
            try:
                hit = _resolve(var, file_paths=key_paths)
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
    _reg_fn = registry_fn
    if _reg_fn is None:
        _reg_fn = lambda n: provider_registry.resolve_provider(
            n, _manager=_mgr)
    route, _route_reason = route_for_provider(
        name, registry_fn=_reg_fn, tunneled=tunneled,
        env_map=env_map, file_paths=file_paths)
    endpoint, headers, ids_of, endpoint_error = _model_list_target(
        name, row, key_value)
    if route == "leased":
        lease_states = [] if state_log is not None else None
        lease, lease_error = lease_tunnel_for_run(
            name, lease_fn=lease_fn, target_fn=target_fn,
            clean_fn=clean_fn, verify_fn=verify_fn, tunneled=tunneled,
            env_map=env_map, file_paths=file_paths,
            wake_fn=wake_fn, health_fn=health_fn,
            state_log=lease_states)
        if state_log is not None and lease_states is not None:
            state_log.extend(lease_states)
        if lease_error:
            return None, ("%s models:list refused: %s"
                          % (name, lease_error))
        if endpoint_error:
            return None, endpoint_error
        proxy_url = str((lease or {}).get("proxy_url") or "")
        opener = _url.build_opener(_url.ProxyHandler(
            {"http": proxy_url, "https": proxy_url})) if proxy_url \
            else _url.build_opener()
        lease_sid = str((lease or {}).get("server_id") or "")
        lease_id = str((lease or {}).get("lease_id") or "")
        attempt = {}

        def _check(exit_id):
            # Single lease, single real fetch: only OUR leased exit is
            # ever attempted (siblings read unknown-skipped, no
            # network — the snapshot still orders honestly above).
            if lease_sid and exit_id != lease_sid:
                return "unknown", {"http": None, "skipped": True}
            if attempt.get("done"):
                prev = attempt.get("verdict", "unknown")
                return prev, dict(attempt.get("info") or {"http": None})
            req = _url.Request(endpoint, headers=headers)
            try:
                import time as _time
                _start = _time.monotonic()
                with opener.open(req, timeout=timeout) as resp:
                    data = json.load(resp)
                _latency_ms = int((_time.monotonic() - _start) * 1000)
            except Exception as exc:
                attempt["done"] = True
                attempt["verdict"] = "unknown"
                attempt["info"] = {"http": _http_code_of(exc)}
                attempt["exc"] = exc
                attempt["data"] = None
                return "unknown", dict(attempt["info"])
            attempt["done"] = True
            attempt["verdict"] = "clean"
            attempt["info"] = {"http": None,
                               "latency_ms": float(_latency_ms),
                               "payload": ids_of(data)}
            attempt["data"] = data
            return "clean", dict(attempt["info"])

        def _cool(exit_id, prov, code):
            # Quota-cool per exit: OUR server cools for the provider
            # (provider-scoped, others' leases untouched).
            if code != 429 or not lease_id or exit_id != lease_sid:
                return
            if report_fn is None and not _supervisor_token():
                return
            try:
                from factory.linking import probe_providers as _pp
                _pp.report_outcome(lease_id, "http429",
                                   provider=name, report_fn=report_fn)
                attempt["cooled"] = True
            except Exception:
                pass

        def _remember(exit_id, prov, ms):
            # Proven exit: a successful list through OUR lease is a
            # clean signal — report ok and warm its own
            # provider-scoped clean cache so the next lease prefers it
            # (supervisor cache-first, no restart; namespaces never
            # leak across providers). Best-effort, ours only.
            _report_lease_outcome(lease, name, None,
                                  report_fn=report_fn)
            try:
                from factory.linking import google_clean as _gc_m
                remember = (remember_fn if remember_fn is not None
                            else _gc_m.remember_success)
                if exit_id:
                    remember(exit_id, prov, ms)
            except Exception:
                pass

        res = _run_cycle(
            name, store=_cycle_store(),
            pool_fn=(pool_fn if pool_fn is not None
                     else lambda: _pool_snapshot_rows(
                         lease_sid, clean_fn=clean_fn)),
            ping_fn=(ping_fn if ping_fn is not None
                     else _cycle_ping_fn(proxy_url)),
            check_fn=_check, cool_fn=_cool, remember_fn=_remember,
            key_name=(var_order[0] if var_order else ""),
            tunneled=tunneled)
        if state_log is not None:
            state_log.extend(res.get("states") or [])
        if res.get("winner") is not None:
            return res.get("payload"), None
        exc = attempt.get("exc")
        if exc is not None and not (
                _http_code_of(exc) == 429
                and attempt.get("cooled")):
            _report_lease_outcome(lease, name, exc,
                                  report_fn=report_fn)
        return None, (_attributed_error(name, exc)
                      if exc is not None
                      else "%s models fetch failed: %s" % (
                          name, res.get("error") or "no clean exit"))
    if endpoint_error:
        return None, endpoint_error
    req = _url.Request(endpoint, headers=headers)
    attempt = {}

    def _direct_check(exit_id):
        req = _url.Request(endpoint, headers=headers)
        try:
            with _url.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
        except Exception as exc:
            # Single direct exit: keep the real failure for the
            # attributed error below (provider + kind + http — the
            # cycle states carry names + counts only, never values).
            attempt["exc"] = exc
            return "unknown", {"http": _http_code_of(exc),
                               "exc": type(exc).__name__}
        return "clean", {"http": None, "latency_ms": 0.0,
                         "payload": ids_of(data)}

    res = _run_cycle(
        name, store=None,
        pool_fn=lambda: [{"id": "direct", "source": "free"}],
        ping_fn=lambda exit_id: None,
        check_fn=_direct_check, cool_fn=lambda *a: None,
        remember_fn=lambda *a: None,
        key_name=(var_order[0] if var_order else ""))
    if state_log is not None:
        state_log.extend(res.get("states") or [])
    if res.get("winner") is not None:
        return res.get("payload"), None
    exc = attempt.get("exc")
    if exc is not None:
        return None, _attributed_error(name, exc)
    return None, _attributed_error(
        name, _CycleFetchFailed(res.get("error") or "no clean exit"))


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


# ─── Server-side file browser (operator-only console: plain start is ──
# LAN-visible with no auth, so treat every /api/files path as LAN-reachable)

_FILE_LIST_LIMIT = 500


def _browse_roots():
    """Operator starting points: data root first, then samples/runs/drives."""
    roots = []
    try:
        root = data_root()
        if root and os.path.isdir(root):
            roots.append({"path": root, "label": "data root"})
    except Exception:
        pass
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


#: Line-scan budget for _list_dir per-file facts (T09): files at or
#: below this size get exact-or-capped counts via _file_facts; bigger
#: files report size + mtime with an honest "—" lines label (never a
#: full unbounded scan per listing request).
_LIST_LINES_SCAN_CAP = 512 * 1024


def _list_entry_facts(full):
    """T09 facts for one listed file: size + capped lines + mtime.

    ``lines``/``lines_label`` come from the existing ``_file_facts``
    (cap ``_FILE_LINES_CAP`` → label ``"50000+"``) when the file fits
    ``_LIST_LINES_SCAN_CAP``; oversized files keep ``lines`` None with
    label ``"—"`` and a titled cause. ``mtime_iso`` (UTC) + T02
    ``format_moment`` ``mtime_relative``/``mtime_detail`` ride every
    file; unstatable mtimes stay None/"—" (honest empty, never raises).
    """
    try:
        size = os.path.getsize(full)
    except OSError:
        size = -1
    entry = {"size": size, "lines": None, "lines_label": "—",
             "lines_note": ("فایل بزرگ است — شمارش سطر در فهرست انجام "
                            "نشد"),
             "mtime_iso": None, "mtime_relative": "—", "mtime_detail": "—"}
    if 0 <= size <= _LIST_LINES_SCAN_CAP:
        try:
            facts = _file_facts(full)
        except Exception:
            facts = {}
        if facts:
            entry["lines"] = facts.get("lines")
            entry["lines_label"] = str(facts.get("lines_label", "—"))
            entry["lines_note"] = ""
    try:
        stamp = os.path.getmtime(full)
        iso = (datetime.datetime.fromtimestamp(
            stamp, datetime.timezone.utc).isoformat())
        entry["mtime_iso"] = iso
        try:
            from factory.webui import duration_fmt as _duration_fmt
            moment = _duration_fmt.format_moment(iso)
        except Exception:
            moment = {}
        entry["mtime_relative"] = str(moment.get("relative") or "—")
        entry["mtime_detail"] = str(moment.get("detail") or "—")
    except (OSError, ValueError, OverflowError):
        pass
    return entry


def _list_dir(absdir):
    """(ok, error, payload) listing of one absolute directory.

    Names + dir flags + sizes only — file contents are never read here
    (sample validation stays the separate /api/sample/validate path).
    T09: files also carry size-gated ``lines``/``lines_label`` (capped
    ``"50000+"``) + ``mtime_iso``/``mtime_relative``/``mtime_detail``
    (T02 ``format_moment``); folders carry no size claim at all.
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
                row = {"name": name, "is_dir": False}
                row.update(_list_entry_facts(full))
                files.append(row)
        except OSError:
            continue
    parent = os.path.dirname(want.rstrip(os.sep)) or None
    return True, "", {"dir": want, "parent": parent,
                      "entries": dirs + files,
                      "truncated": len(entries) > _FILE_LIST_LIMIT}


#: Line-count cap for data-file facts (the kaikki raw dump is multi-GB:
#: per-request counts stop after this many lines with an honest "N+").
_FILE_LINES_CAP = 50000


def _file_facts(path):
    """Bounded facts for one data file (existence + size always, lines capped).

    ``exists`` + ``size`` (bytes) are reported for every path; ``lines``
    counts at most ``_FILE_LINES_CAP`` lines — when the file holds more,
    ``lines`` stays at the cap with ``lines_label`` ``"50000+"`` and
    ``truncated`` True (never a full unbounded count per request).

    T10: ``mtime_iso`` (UTC) + T02 ``format_moment`` ``mtime_relative`` /
    ``mtime_detail`` ride every fact (dual calendar Asia/Tehran+UTC);
    missing/unstatable files keep ``None``/``"—"`` (honest empty).
    Additive keys only — existing callers/tests keep working.
    """
    info = {"path": path, "exists": False, "size": 0,
            "lines": 0, "lines_label": "0", "truncated": False,
            "mtime_iso": None, "mtime_relative": "—",
            "mtime_detail": "—"}
    try:
        info["exists"] = bool(path) and os.path.isfile(path)
    except (OSError, ValueError, TypeError):
        return info
    if not info["exists"]:
        return info
    try:
        info["size"] = os.path.getsize(path)
    except OSError:
        info["size"] = 0
    count, truncated = 0, False
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for _ in handle:
                count += 1
                if count > _FILE_LINES_CAP:
                    truncated = True
                    break
    except OSError:
        return info
    if truncated:
        info["lines"] = _FILE_LINES_CAP
        info["lines_label"] = "%d+" % _FILE_LINES_CAP
        info["truncated"] = True
    else:
        info["lines"] = count
        info["lines_label"] = str(count)
    try:
        stamp = os.path.getmtime(path)
        iso = (datetime.datetime.fromtimestamp(
            stamp, datetime.timezone.utc).isoformat())
        info["mtime_iso"] = iso
        try:
            from factory.webui import duration_fmt as _duration_fmt
            moment = _duration_fmt.format_moment(iso)
        except Exception:
            moment = {}
        info["mtime_relative"] = str(moment.get("relative") or "—")
        info["mtime_detail"] = str(moment.get("detail") or "—")
    except (OSError, ValueError, OverflowError):
        pass
    return info


def _data_file_facts():
    """kaikki_raw + screened facts for /api/files/roots (both paths resolved
    through their single sources: the kaikki raw default via the precard
    pipeline's data-root default, screened via _configured_path — no second
    resolver here).

    Short-TTL cached (``_FILE_FACTS_TTL``): every GET would otherwise
    synchronously line-scan up to 2x50k lines and stall the Flask
    worker under polling. Cache holds the last payload; callers get
    the same dict (treat as read-only).
    """
    now = time.monotonic()
    with _FILE_FACTS_LOCK:
        if (_FILE_FACTS_CACHE["payload"] is not None
                and now - _FILE_FACTS_CACHE["at"] < _FILE_FACTS_TTL):
            return _FILE_FACTS_CACHE["payload"]
    try:
        from factory.precard import pipeline as _pipe
        kaikki_raw = _pipe.DEFAULT_KAIKKI_RAW
    except Exception:
        kaikki_raw = ""
    try:
        screened = _configured_path(None, SCREENED_ENV_VAR,
                                    DEFAULT_SCREENED_PATH)
    except Exception:
        screened = DEFAULT_SCREENED_PATH
    payload = {"kaikki_raw": _file_facts(kaikki_raw),
               "screened": _file_facts(screened)}
    with _FILE_FACTS_LOCK:
        _FILE_FACTS_CACHE["payload"] = payload
        _FILE_FACTS_CACHE["at"] = time.monotonic()
    return payload


#: Short TTL (seconds) for ``_data_file_facts`` — bounds per-request
#: scan cost on the polling-heavy /api/files/roots endpoint.
_FILE_FACTS_TTL = 30.0
_FILE_FACTS_LOCK = threading.Lock()
_FILE_FACTS_CACHE = {"at": 0.0, "payload": None}


def _reset_file_facts_cache():
    """Clear the facts cache (test seam; production never calls this)."""
    with _FILE_FACTS_LOCK:
        _FILE_FACTS_CACHE["payload"] = None
        _FILE_FACTS_CACHE["at"] = 0.0


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
    """True when a pid still names a live process (best-effort).

    Windows note: ``os.kill(pid, 0)`` raises generic ``OSError``
    (WinError 87) — not ``ProcessLookupError`` — for dead pids, so it
    must map to False explicitly (a bare ``except Exception → True``
    reports every dead pid alive and restart-settle never fires).
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
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

#: Rate-scope states for judge presets (single owner of the enum — the
#: console selector posts one of these, the catalog renders it back).
JUDGE_RATE_SCOPES = ("model", "address", "account")

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
        entries = sorted(os.listdir(presets_dir()))
    except OSError:
        return []
    for entry in entries:
        if not entry.endswith(".json"):
            continue
        rec = _read_json_file(os.path.join(presets_dir(), entry))
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
        alt = _read_json_file(os.path.join(presets_dir(), safe + ".json"))
        if isinstance(alt, dict) and alt.get("name") == name:
            return alt
        # fall through to scan for exact display-name match
        for rec in list_presets():
            if rec.get("name") == name:
                return rec
        return None
    rec = _read_json_file(os.path.join(presets_dir(), safe + ".json"))
    return rec if isinstance(rec, dict) else None


def save_preset(fields):
    """Save a versioned preset; returns the stored record (version bumped).

    Two kinds: "run" (the whole compose form) and "judge" (judge knobs
    only: provider/model/rate caps/rate scope/optional label — plugs into
    the compose form). Old records without a kind read back as "run".
    Judge rate caps (max_rpm/max_rph/max_daily) store 0 for unlimited
    (empty input means unlimited); rate_scope is one of
    model/address/account (empty reads as model). Old judge records
    without these keys read back with the same defaults.

    Edit identity: an optional ``previous_name`` migrates a rename in
    one call (version continues, ``ready`` carries over, the old file
    is removed) so re-saving a loaded preset never leaves a duplicate
    behind. Fail-closed: an unknown ``previous_name``, or a ``name``
    that already belongs to another preset, raises ValueError and
    nothing is written.
    """
    name = str((fields or {}).get("name") or "").strip()
    if not name or not _PRESET_NAME_RX.match(name):
        raise ValueError("preset name must be 1..64 chars without / or \\")
    safe = _safe_filename(name)
    if not safe:
        raise ValueError("preset name must be 1..64 chars without / or \\")
    previous_name = str((fields or {}).get("previous_name") or "").strip()
    if previous_name and not _PRESET_NAME_RX.match(previous_name):
        raise ValueError(
            "previous preset name must be 1..64 chars without / or \\")
    renamed = bool(previous_name) and previous_name != name
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
    judge_extra = {}
    if kind == "judge":
        label = str((fields or {}).get("label") or "").strip()
        if len(label) > 64:
            raise ValueError("label must be at most 64 chars")
        judge_extra["label"] = label
        for cap in ("max_rpm", "max_rph", "max_daily"):
            try:
                value = int((fields or {}).get(cap, 0) or 0)
            except (TypeError, ValueError, OverflowError):
                raise ValueError("%s must be an integer >= 0 or empty" % cap)
            if value < 0:
                raise ValueError("%s must be >= 0 or empty" % cap)
            judge_extra[cap] = value
        scope = str((fields or {}).get("rate_scope") or "").strip() or "model"
        if scope not in JUDGE_RATE_SCOPES:
            raise ValueError("rate_scope must be one of %s" % "/".join(
                JUDGE_RATE_SCOPES))
        judge_extra["rate_scope"] = scope
    os.makedirs(presets_dir(), exist_ok=True)
    prev = get_preset(previous_name) if renamed else get_preset(name)
    if renamed and prev is None:
        raise ValueError("preset not found: %s" % previous_name)
    if renamed and get_preset(name) is not None:
        raise ValueError(
            "preset %r already exists "
            "(delete it first or pick another name)" % name)
    prev_safe = _safe_filename(previous_name) if renamed else safe
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
    rec.update(judge_extra)
    if (fields or {}).get("ready") is True or (
            prev or {}).get("ready") is True:
        rec["ready"] = True
    tmp = os.path.join(presets_dir(), safe + ".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(rec, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(presets_dir(), safe + ".json"))
    if renamed:
        # New record is durable before the old file goes: a failed
        # remove surfaces as 500 (retryable) instead of a silent twin.
        # Resolve the old file like delete_preset does (stale twins
        # may live under a scanned name, not the canonical stem).
        old_path = os.path.join(presets_dir(), prev_safe + ".json")
        if not os.path.isfile(old_path):
            for cand in list_presets():
                if cand.get("name") == previous_name:
                    old_path = os.path.join(
                        presets_dir(),
                        _safe_filename(cand["name"]) + ".json")
                    break
        new_path = os.path.join(presets_dir(), safe + ".json")
        if os.path.abspath(old_path) != os.path.abspath(new_path):
            try:
                os.remove(old_path)
            except OSError as exc:
                raise OSError(
                    "renamed to %r but the old record could not be "
                    "removed: %s" % (name, exc))
    return rec


def delete_preset(name):
    safe = _safe_filename(name)
    path = os.path.join(presets_dir(), safe + ".json")
    rec = get_preset(name)
    if rec is None or not os.path.isfile(path):
        # exact-name scan fallback (unicode names map 1:1, so this is rare)
        for cand in list_presets():
            if cand.get("name") == name:
                path = os.path.join(presets_dir(),
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


def _provider_key_var(provider, _manager=None):
    """Effective key variable for a built-in provider (name only).

    The operator mapping (provider card) wins; otherwise the first
    registry ref (convention group slot, then legacy fallbacks).
    ``_manager`` shares one manifest read across a request.
    """
    try:
        mapped = _key_var_mapping().get(str(provider or "").strip())
    except Exception:
        mapped = ""
    if mapped and _KEY_VAR_RX.match(str(mapped).strip().upper()):
        return str(mapped).strip().upper()
    try:
        refs = provider_registry.key_ref_for(provider, _manager=_manager)
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
            current = json.load(open(operator_keys_path(), encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        current[var] = stored
        tmp = operator_keys_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, operator_keys_path())
        try:
            os.chmod(operator_keys_path(), 0o600)
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
            current = json.load(open(operator_keys_path(), encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        if not isinstance(current, dict) or var not in current:
            return False
        del current[var]
        tmp = operator_keys_path() + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(current, handle, ensure_ascii=False, indent=1)
            os.replace(tmp, operator_keys_path())
            try:
                os.chmod(operator_keys_path(), 0o600)
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
            "key_count": int(presence.get("key_count") or 0),
            "active_keys": int(presence.get("key_count") or 0),
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


def _supervisor_sub_env():
    """Subscription env for a woken supervisor child (read-only).

    Resolved through the shared egress loader (this checkout's files,
    then the primary-checkout read-only fallback, then process env —
    values in-memory only, never logged or returned beyond the child
    env dict). Names only out.
    """
    out = {}
    try:
        from tools.egress import supervisor as _sup
        data = _sup.load_env() or {}
    except Exception:
        data = {}
    for var in ("EGRESS_SUB_URLS", "EGRESS_SUB_URL", "EGRESS_SUP_URL"):
        try:
            val = str(data.get(var, "") or "").strip()
        except Exception:
            val = ""
        if val:
            out[var] = val
    return out


def _supervisor_refresh(timeout=60):
    """Bearer-authed live subscription refresh (counts only out).

    POSTs the supervisor's own ``/v1/refresh`` (re-reads env +
    subscriptions server-side: placeholder lines skipped, deduped,
    pool saved only when non-empty), then returns
    (ok, info): info is the counts dict
    (servers/leases/healthy/before) or a plain operator line naming
    the bearer variable (never its value). Never raises.
    """
    import urllib.request as _url

    token = _supervisor_token()
    if not token:
        return False, ("no supervisor token resolves (%s) — paste it "
                       "once in the providers panel, then retry "
                       "(nothing spawned)" % SUPERVISOR_TOKEN_VAR)
    _refresh_egress_client_auth()
    try:
        req = _url.Request(
            _supervisor_url().rstrip("/") + "/v1/refresh",
            data=b"{}",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + token},
            method="POST")
        with _url.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as exc:
        return False, ("supervisor refresh failed (%s) (%s) — shared "
                       "infrastructure untouched, nothing spawned"
                       % (type(exc).__name__, SUPERVISOR_TOKEN_VAR))
    if not isinstance(data, dict):
        return False, ("supervisor refresh unreadable (bad shape) "
                       "(%s)" % SUPERVISOR_TOKEN_VAR)
    try:
        info = {"servers": int(data.get("servers") or 0),
                "leases": int(data.get("leases") or 0),
                "healthy": bool(data.get("healthy")),
                "before": int(data.get("before") or 0)}
    except (TypeError, ValueError):
        return False, ("supervisor refresh unreadable (bad counts) "
                       "(%s)" % SUPERVISOR_TOKEN_VAR)
    return True, info


def _wake_supervisor_background(port=None, spawn_fn=None, health_fn=None,
                                 timeout=5.0):
    """Background wake of the shared supervisor (best-effort, never raises).

    Health-first: a healthy supervisor is returned as-is (never
    restarted, never re-spawned). Otherwise the factory-domain entry
    (``factory.run.SUPERVISOR_SCRIPT``) is launched detached in the
    background — bearer + subscription sources ride the child env
    only (resolved read-only from this checkout plus the
    primary-checkout fallback, never argv/logs) — and health is
    re-polled on a bounded budget. Others' leases are never touched
    (no lease/report call exists on this path). ``spawn_fn``/
    ``health_fn`` inject the spawn + health legs (tests pass fakes,
    never a real process). Returns True when a healthy supervisor
    answers after the attempt OR the child was launched and is
    starting (a cold boot with subscription refresh outlasts a short
    budget — callers re-probe and report the fresh counts, never a
    stale label); False only when nothing was launched.
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
    launched = False
    try:
        if spawn_fn is not None:
            spawn_fn(target)
            launched = True
        else:
            env = dict(os.environ)
            tok = _supervisor_token()
            if tok:
                env[SUPERVISOR_TOKEN_VAR] = tok
            for var, val in _supervisor_sub_env().items():
                if val and not env.get(var):
                    env[var] = val
            subprocess.Popen(
                [sys.executable, script, "--port", str(target)],
                env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True)
            launched = True
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
    # Launched but still starting (a cold boot with subscription
    # refresh outlasts a short budget): report the wake in flight —
    # callers re-probe and state the fresh counts, never a stale down.
    return bool(launched)


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
    ``health_fn`` injects the health leg (() -> (ok, payload); tests pass
    fakes, never network). When a token resolves, the probe still runs
    (``health_fn`` when provided, else the read-only local
    ``supervisor_health_snapshot``): a down probe falls through to the
    wake branch below instead of reporting ready. A probe that cannot
    run (raises) keeps the old assume-alive path — never a blind wake
    on an unverifiable probe.
    Returns (ready_bool, error_or_None).
    """
    route, _reason = route_for_provider(
        provider, tunneled=tunneled, env_map=env_map,
        file_paths=file_paths)
    if route != "leased":
        return True, None
    if _supervisor_token():
        _probe = (health_fn if health_fn is not None
                  else supervisor_health_snapshot)
        try:
            _up, _ = _probe()
        except Exception:
            _up = True
        if _up:
            _touch_supervisor_active()
            return True, None
        # Token resolves but the probe says down: fall through to the
        # wake branch below (never report ready on a down supervisor).
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
                       "(%s) — retry this request in a few "
                       "seconds; manual start: %s"
                       % (SUPERVISOR_TOKEN_VAR, SUPERVISOR_START_CMD))
    return False, ("no supervisor token resolves (%s) "
                   "— the shared supervisor was woken in the background: "
                   "%s (nothing else touched)"
                   % (SUPERVISOR_TOKEN_VAR, SUPERVISOR_START_CMD))


#: Idle-sleep minutes — PARKED (owner number pending, never invented).
#: ``None`` means "no owner value yet": the idle path stays inert until
#: the owner configures a real number (env override below or a future
#: literal). Tests assert this parked default and drive the idle verdict
#: with injected minutes instead of any real duration.
IDLE_SLEEP_MINUTES = None

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
        return False, ("idle minutes parked (owner number pending — "
                       "set %s) (%s)"
                       % (SUPERVISOR_IDLE_MINUTES_ENV_VAR,
                          SUPERVISOR_TOKEN_VAR))
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

    Resolution order: process env, then this checkout's factory
    environment file (``_factory_env_value``: ``factory/.env``), then
    the shared supervisor-issued temp file (a woken child cannot change
    the parent environment, so the parent re-reads the token the
    supervisor workflow leaves behind), then the shared egress loader
    (``tools.egress.supervisor.load_env``: the canonical
    tools/egress/.env, then the factory/.env fallback, then the
    primary-checkout read-only fallback), then the file-anchored
    lease-policy resolver over this checkout plus the primary
    checkout's ``factory/.env`` + ``tools/egress/.env`` (read-only,
    so a worktree console sees the operator's primary bearer with
    zero manual copies), then the encrypted operator store (pasted
    once in the providers panel, decrypted fail-closed).
    Branch location plays no role beyond the read-only primary
    fallback: every lookup path is anchored at the module file
    (``__file__``), the primary root, or the shared temp directory,
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
        hit = _resolve(SUPERVISOR_TOKEN_VAR,
                       file_paths=_extra_key_paths()) or ""
        if hit:
            return hit
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
                       "(%s) — start the shared "
                       "supervisor first: %s (nothing spawned)"
                       % (SUPERVISOR_TOKEN_VAR, SUPERVISOR_START_CMD))
    _refresh_egress_client_auth()
    try:
        req = _url.Request(
            _supervisor_url().rstrip("/") + "/v1/health",
            headers={"Authorization": "Bearer " + token})
        with _url.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as exc:
        return False, ("supervisor unreachable at %s (%s) (%s) — "
                       "shared infrastructure untouched, nothing "
                       "spawned; start it with: %s"
                       % (_supervisor_url(), type(exc).__name__,
                          SUPERVISOR_TOKEN_VAR, SUPERVISOR_START_CMD))
    if not isinstance(data, dict):
        return False, "supervisor health unreadable (bad shape)"
    return True, {"servers": data.get("servers"),
                  "leases": data.get("leases"),
                  "healthy": bool(data.get("healthy"))}


#: Supervisor refusal meaning "pool has no link-bearing server":
#: never a dead end — the caller refreshes subscriptions and retries
#: the lease once before reporting (refresh-plus-prove, automatic).
NO_LINK_MARKER = "no link-bearing server"


def lease_tunnel_for_run(provider, *, lease_fn=None, target_fn=None,
                           clean_fn=None, verify_fn=None, tunneled=None,
                           env_map=None, file_paths=None, wake_fn=None,
                           health_fn=None, state_log=None,
                           refresh_fn=None):
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
    others' leases undisturbed). Empty-pool auto-recover: a lease
    refused for lack of a link-bearing server triggers one live
    subscription refresh (``refresh_fn`` injects it — tests pass
    fakes, never the network; default the bearer-authed
    ``_supervisor_refresh``) and retries the lease once, so the
    caller walks refresh-plus-prove instead of a dead-end message.
    Route-based, never Google-only.
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

    The whitelist orders through the generic provider cycle's
    ``refresh_candidates`` (dedupe + paid-first via the existing
    helpers — same head as before, never a new order); when
    ``state_log`` is a list, the ordered lease-cycle state machine
    (cache check, refresh, ping note, prove, remember, done — data
    plus Persian lines via ``build_fa_lines``) appends to it so the
    run-launch path shows the same state walk as the model-list path.
    """
    from factory.net.provider_cycle import (
        refresh_candidates as _refresh_candidates,
    )
    from factory.precard.provider_lease_policy import (
        norm_provider as _norm_lease)
    _lease_states = []
    _wlname = _norm_lease(provider)

    def _emit(states):
        _lease_states.extend(states)
        if state_log is not None:
            state_log.extend(states)
    route, _reason = route_for_provider(
        provider, tunneled=tunneled, env_map=env_map,
        file_paths=file_paths)
    if route != "leased":
        _emit([{"state": "cache_check", "provider": _wlname,
                "hit": False, "cached": 0},
               {"state": "refresh", "provider": _wlname,
                "raw": 0, "unique": 0, "candidates": []},
               {"state": "ping", "provider": _wlname,
                "pinged": 0, "reachable": 0,
                "note": "direct route — no tunnel cycle"},
               {"state": "prove", "provider": _wlname,
                "batch": 5, "keep": 1, "order": [],
                "clean": [], "blocked": [], "unknown": []},
               {"state": "remember", "provider": _wlname,
                "exit": "", "written": False},
               {"state": "done", "provider": _wlname,
                "winner": "direct", "count": 0,
                "cache_hit": False, "error": None,
                "route": "direct"}])
        return None, None
    ready, wake_error = _ensure_supervisor_for_leased(
        provider, wake_fn=wake_fn, health_fn=health_fn,
        tunneled=tunneled, env_map=env_map, file_paths=file_paths)
    if not ready:
        _emit([{"state": "cache_check", "provider": _wlname,
                "hit": False, "cached": 0},
               {"state": "refresh", "provider": _wlname,
                "raw": 0, "unique": 0, "candidates": []},
               {"state": "ping", "provider": _wlname,
                "pinged": 0, "reachable": 0,
                "note": "supervisor wake refused"},
               {"state": "prove", "provider": _wlname,
                "batch": 5, "keep": 1, "order": [],
                "clean": [], "blocked": [], "unknown": []},
               {"state": "remember", "provider": _wlname,
                "exit": "", "written": False},
               {"state": "done", "provider": _wlname,
                "winner": None, "count": 0, "cache_hit": False,
                "error": wake_error}])
        return None, wake_error
    token = _supervisor_token()
    if not token:
        _emit([{"state": "cache_check", "provider": _wlname,
                "hit": False, "cached": 0},
               {"state": "refresh", "provider": _wlname,
                "raw": 0, "unique": 0, "candidates": []},
               {"state": "ping", "provider": _wlname,
                "pinged": 0, "reachable": 0,
                "note": "no supervisor token"},
               {"state": "prove", "provider": _wlname,
                "batch": 5, "keep": 1, "order": [],
                "clean": [], "blocked": [], "unknown": []},
               {"state": "remember", "provider": _wlname,
                "exit": "", "written": False},
               {"state": "done", "provider": _wlname,
                "winner": None, "count": 0, "cache_hit": False,
                "error": "no supervisor token"}])
        return None, ("no supervisor token resolves (%s) "
                      "— start the shared supervisor first: %s "
                      "(nothing spawned)"
                      % (SUPERVISOR_TOKEN_VAR, SUPERVISOR_START_CMD))
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
        if NO_LINK_MARKER in msg:
            # Empty pool is recoverable: refresh subscriptions live
            # (placeholder lines skipped server-side, deduped) and
            # retry the lease once — the cycle states below record
            # the refresh walk, never a dead end on first failure.
            refresh = (refresh_fn if refresh_fn is not None
                       else _supervisor_refresh)
            try:
                _rok, _rinfo = refresh()
            except Exception:
                _rok, _rinfo = False, "refresh failed"
            _after = []
            if _rok and isinstance(_rinfo, dict):
                try:
                    _after = _pool_snapshot_rows(
                        "", clean_fn=clean_fn)
                except Exception:
                    _after = []
            _emit([{"state": "cache_check", "provider": _wlname,
                    "hit": False, "cached": 0},
                   {"state": "refresh", "provider": _wlname,
                    "raw": len(_after), "unique": len(_after),
                    "candidates": list(_after),
                    "note": ("auto refresh-plus-prove: %s"
                             % (_rinfo if isinstance(_rinfo, str)
                                else "refreshed"))},
                   {"state": "ping", "provider": _wlname,
                    "pinged": 0, "reachable": 0,
                    "note": "retrying lease after refresh"},
                   {"state": "prove", "provider": _wlname,
                    "batch": 5, "keep": 1, "order": [],
                    "clean": [], "blocked": [], "unknown": []},
                   {"state": "remember", "provider": _wlname,
                    "exit": "", "written": False},
                   {"state": "done", "provider": _wlname,
                    "winner": None, "count": 0, "cache_hit": False,
                    "error": None}])
            if _rok:
                try:
                    from factory.linking import probe_providers as _pp2
                    lease = _pp2.lease_tunnel(
                        provider, lease_fn=lease_fn, target_fn=target_fn)
                except Exception as exc:
                    lease = {"error": "lease",
                             "message": type(exc).__name__}
                if isinstance(lease, dict) and not lease.get("error"):
                    pass  # recovered: fall through to whitelist/verify
                else:
                    try:
                        msg = str((lease or {}).get("message") or msg)
                    except Exception:
                        pass
                    _emit([{"state": "done", "provider": _wlname,
                            "winner": None, "count": 0,
                            "cache_hit": False, "error": msg}])
                    return None, (
                        "supervisor refused the lease after a live "
                        "refresh%s (%s) — shared infrastructure "
                        "untouched; retry later"
                        % (": %s" % msg if msg else "",
                           SUPERVISOR_TOKEN_VAR))
            else:
                _rtext = (_rinfo if isinstance(_rinfo, str)
                          else "refresh refused")
                _emit([{"state": "done", "provider": _wlname,
                        "winner": None, "count": 0, "cache_hit": False,
                        "error": _rtext}])
                return None, ("supervisor has no link-bearing server "
                              "and the live refresh refused (%s) (%s) — "
                              "shared infrastructure untouched; retry "
                              "later" % (_rtext, SUPERVISOR_TOKEN_VAR))
        else:
            _emit([{"state": "cache_check", "provider": _wlname,
                    "hit": False, "cached": 0},
                   {"state": "refresh", "provider": _wlname,
                    "raw": 0, "unique": 0, "candidates": []},
                   {"state": "ping", "provider": _wlname,
                    "pinged": 0, "reachable": 0,
                    "note": "supervisor lease refused"},
                   {"state": "prove", "provider": _wlname,
                    "batch": 5, "keep": 1, "order": [],
                    "clean": [], "blocked": [], "unknown": []},
                   {"state": "remember", "provider": _wlname,
                    "exit": "", "written": False},
                   {"state": "done", "provider": _wlname,
                    "winner": None, "count": 0, "cache_hit": False,
                    "error": msg or "lease refused"}])
            return None, ("supervisor refused the lease%s (%s) — pick a "
                          "direct provider or retry later"
                          % (": %s" % msg if msg else "",
                             SUPERVISOR_TOKEN_VAR))
    _wl_raw, _wl_ordered, _verify_rec = [], [], {}
    try:
        from factory.linking import google_clean as _gc
        from factory.precard.provider_lease_policy import (
            norm_provider as _norm_p)
        if _norm_p(provider) == "google":
            clean = (clean_fn if clean_fn is not None
                     else _gc.fresh_clean_exits)
            _wl_raw = list(clean() or [])
            _wl_ordered = _refresh_candidates(
                [{"id": sid, "source": "paid"} for sid in _wl_raw])
            head = (_wl_ordered or [""])[0] or ""
            sid = str((lease or {}).get("server_id") or "")
            lease["clean_exit"] = head
            lease["clean"] = bool(sid and head and sid == head)
            lease["clean_note"] = _gc.clean_note(
                sid, [head] if head else [])
            verify = (verify_fn if verify_fn is not None
                      else _gc.verify_and_remember)
            _verify_rec = verify(
                str((lease or {}).get("proxy_url") or ""), sid,
                provider="google", timeout=10) or {}
    except Exception:
        pass
    _sid = str((lease or {}).get("server_id") or "")
    _proved = bool((_verify_rec or {}).get("ok")) or _wlname != "google"
    _remembered = bool((_verify_rec or {}).get("remembered"))
    _emit([{"state": "cache_check", "provider": _wlname,
            "hit": bool(_wl_ordered and _sid and _sid in _wl_ordered),
            "cached": len(_wl_ordered)},
           {"state": "refresh", "provider": _wlname,
            "raw": len(_wl_raw), "unique": len(_wl_ordered),
            "candidates": list(_wl_ordered)},
           {"state": "ping", "provider": _wlname,
            "pinged": 0, "reachable": 0,
            "note": "supervisor lease — no per-exit ping"},
           {"state": "prove", "provider": _wlname,
            "batch": 5, "keep": 1, "order": [_sid] if _sid else [],
            "clean": [_sid] if (_sid and _proved) else [],
            "blocked": [],
            "unknown": [] if (_sid and _proved) else (
                [_sid] if _sid else [])},
           {"state": "remember", "provider": _wlname,
            "exit": _sid if _remembered else "", "written": _remembered},
           {"state": "done", "provider": _wlname,
            "winner": _sid or None, "count": 0, "cache_hit": False,
            "error": None}])
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


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(os.path.join(SCRIPT_DIR, "static"), filename)


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
    states = []
    models, error = provider_model_list(provider, state_log=states)
    try:
        from factory.net.provider_cycle import (
            build_fa_lines as _cycle_lines)
        lines = _cycle_lines(provider, states)
    except Exception:
        lines = []
    cycle = {"states": states, "lines_fa": lines}
    if error is not None:
        status = 400 if error.startswith("no key resolves") else 502
        if error.startswith("unknown provider"):
            status = 404
        return jsonify({"provider": provider, "models": [],
                        "error": error, "cycle": cycle}), status
    return jsonify({"provider": provider, "models": models or [],
                    "count": len(models or []), "cycle": cycle})


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
    """Wake-on-demand: true probed state, never a stale label.

    Health-first (read-only): a supervisor that probes healthy
    (healthy flag plus live server/lease counts) returns woken True
    without spawning. A reachable-but-empty supervisor refreshes its
    subscriptions live first (placeholder lines skipped server-side)
    and re-probes; only an unreachable supervisor gets one
    background wake from the factory domain path (bearer +
    subscriptions ride the child env only). Every response carries
    the freshly probed counts, and every message names the bearer
    variable (never its value). Never touches others' leases.
    """
    def _counts(payload):
        if not isinstance(payload, dict):
            return {"servers": 0, "leases": 0, "healthy": False}
        try:
            return {"servers": int(payload.get("servers") or 0),
                    "leases": int(payload.get("leases") or 0),
                    "healthy": bool(payload.get("healthy"))}
        except (TypeError, ValueError):
            return {"servers": 0, "leases": 0, "healthy": False}

    try:
        ok, payload = supervisor_health_snapshot()
    except Exception:
        ok, payload = False, "health check failed"
    if ok and _counts(payload)["healthy"]:
        _touch_supervisor_active()
        return jsonify({"woken": True, "already_healthy": True,
                        "var": SUPERVISOR_TOKEN_VAR,
                        "health": _counts(payload)})
    refreshed = None
    if ok:
        # Reachable but not healthy (empty pool): refresh live, then
        # re-probe — a spawn would only collide on the same port.
        try:
            _rok, _rinfo = _supervisor_refresh()
        except Exception:
            _rok, _rinfo = False, "refresh failed"
        refreshed = _rinfo if isinstance(_rinfo, str) else dict(_rinfo)
        try:
            ok, payload = supervisor_health_snapshot()
        except Exception:
            ok, payload = False, "health check failed"
        if ok and _counts(payload)["healthy"]:
            _touch_supervisor_active()
            return jsonify({"woken": True, "already_healthy": False,
                            "var": SUPERVISOR_TOKEN_VAR,
                            "health": _counts(payload),
                            "refreshed": refreshed})
    # Explicit tap: a longer poll budget (a cold boot with live
    # subscription refresh takes seconds; the dev server is threaded
    # so other endpoints stay live meanwhile).
    woke = _wake_supervisor_background(timeout=45)
    if woke:
        _touch_supervisor_active()
        try:
            _ok2, _payload2 = supervisor_health_snapshot()
        except Exception:
            _ok2, _payload2 = False, "health check failed"
        _fresh = _counts(_payload2) if _ok2 else _counts({})
        if _fresh["healthy"]:
            _note = ("supervisor ready (%s servers, %s leases) (%s)"
                     % (_fresh["servers"], _fresh["leases"],
                        SUPERVISOR_TOKEN_VAR))
        else:
            _note = ("supervisor is starting in the background "
                     "(%s) — retry in a few seconds"
                     % SUPERVISOR_TOKEN_VAR)
        body = {"woken": True, "already_healthy": False,
                "var": SUPERVISOR_TOKEN_VAR,
                "health": _fresh,
                "note": _note}
        if refreshed is not None:
            body["refreshed"] = refreshed
        return jsonify(body)
    return jsonify({"woken": False, "already_healthy": False,
                    "var": SUPERVISOR_TOKEN_VAR,
                    "health": _counts(payload) if ok else _counts({}),
                    "error": payload if isinstance(payload, str)
                    else "wake refused (%s)" % SUPERVISOR_TOKEN_VAR}), 503


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
                        "reason": ("idle minutes parked (owner number "
                                   "pending — set %s) (%s)"
                                   % (SUPERVISOR_IDLE_MINUTES_ENV_VAR,
                                      SUPERVISOR_TOKEN_VAR))})
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
        # Both keys: the console reads `reason`, error-first API
        # clients read `error` — same line, bearer named, never valued.
        body["reason"] = reason
        body["error"] = reason
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
        _lease_states = []
    elif run_route == "leased" and not is_custom:
        _lease_states = []
        _lease, _lease_error = lease_tunnel_for_run(
            provider, state_log=_lease_states)
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
        _lease_states = []
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
    try:
        from factory.net.provider_cycle import (
            build_fa_lines as _run_cycle_lines)
        _run_lines = _run_cycle_lines(provider, _lease_states)
    except Exception:
        _run_lines = []
    return jsonify({"run": record,
                    "lease_cycle": {"states": _lease_states,
                                    "lines_fa": _run_lines}}), 201


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
    return jsonify({"roots": _browse_roots(),
                    "files": _data_file_facts()})


@app.route("/api/files/list", methods=["GET"])
def api_files_list():
    if not (request.args.get("dir") or "").strip():
        return jsonify({"error": "dir is required"}), 400
    ok, error, payload = _list_dir(request.args.get("dir") or "")
    if not ok:
        return jsonify({"error": error}), 400
    return jsonify(payload)


def _inside_dir(candidate, root):
    """True when abspath ``candidate`` is ``root`` or below it."""
    try:
        cand_abs = os.path.abspath(candidate)
        root_abs = os.path.abspath(root)
    except (OSError, ValueError, TypeError):
        return False
    try:
        return os.path.commonpath([root_abs, cand_abs]) == root_abs
    except (OSError, ValueError):
        return False


def _ops_allowed_roots():
    """Dirs the T09 dialog may create/rename/read words under.

    The shared data root plus every existing browse root (same rule
    the T06 pin validator uses — one resolver per root kind, no
    second registry here). Missing/unreadable roots simply drop out.
    """
    roots = []
    try:
        root = data_root()
        if root and os.path.isdir(root):
            roots.append(os.path.abspath(root))
    except Exception:
        pass
    try:
        for row in _browse_roots():
            path = (row or {}).get("path") or ""
            if path and os.path.isdir(path):
                roots.append(os.path.abspath(path))
    except Exception:
        pass
    return roots


def _ops_check_inside(abspath):
    """Fail-closed containment: abspath must sit under an allowed root."""
    return any(abspath and _inside_dir(abspath, root)
               for root in _ops_allowed_roots())


_DIR_NAME_RX = re.compile(r"^[^/\\]{1,64}$")


def _clean_ops_name(raw):
    """One path segment for mkdir/rename (no separators, no dot-dot)."""
    name = str(raw or "").strip()
    if not name or not _DIR_NAME_RX.match(name):
        return ""
    if name in (".", "..") or name.startswith("."):
        return ""
    return name


@app.route("/api/files/mkdir", methods=["POST"])
def api_files_mkdir():
    """T09 — create one subdir; delete HARD-BLOCKED (no such route)."""
    fields = request.get_json(force=True, silent=True) or {}
    parent = os.path.abspath(str(fields.get("dir") or ""))
    name = _clean_ops_name(fields.get("name"))
    if not parent or not os.path.isdir(parent):
        return jsonify({"error": "not a directory"}), 400
    if not name:
        return jsonify({"error": "bad name (one segment, no slashes)"}), 400
    if not _ops_check_inside(parent):
        return jsonify({"error": "outside the allowed roots"}), 400
    target = os.path.join(parent, name)
    if os.path.exists(target):
        return jsonify({"error": "already exists: %s" % name}), 409
    try:
        os.mkdir(target)
    except OSError as exc:
        return jsonify({"error": "mkdir failed: %s" % exc}), 500
    return jsonify({"path": target}), 200


@app.route("/api/files/rename", methods=["POST"])
def api_files_rename():
    """T09 — rename within the SAME parent dir (no moves, no delete)."""
    fields = request.get_json(force=True, silent=True) or {}
    src = os.path.abspath(str(fields.get("path") or ""))
    name = _clean_ops_name(fields.get("name"))
    if not src or not os.path.exists(src):
        return jsonify({"error": "not found"}), 400
    if not name:
        return jsonify({"error": "bad name (one segment, no slashes)"}), 400
    if not _ops_check_inside(src):
        return jsonify({"error": "outside the allowed roots"}), 400
    dst = os.path.join(os.path.dirname(src), name)
    if os.path.exists(dst):
        return jsonify({"error": "already exists: %s" % name}), 409
    try:
        os.rename(src, dst)
    except OSError as exc:
        return jsonify({"error": "rename failed: %s" % exc}), 500
    return jsonify({"path": dst}), 200


#: Word-read budget for the T09 input fill (never a full dump per click).
#: The word cap rides the screening run maximum (single source below):
#: the fill hands A1 exactly what the run will process (fail-fast over
#: the same count, never a larger truncated list).
_WORDS_READ_SIZE_CAP = 2 * 1024 * 1024


@app.route("/api/files/words", methods=["GET"])
def api_files_words():
    """T09 — bounded word fill for A1 pick-as-input (no typed paths).

    Reads one allowed-root file (size-capped, read whole: the old 1 MB
    head sniff truncated large JSON and misparsed it). JSON shapes are
    list-of-dicts via ``text`` fields, list-of-strings, or a single
    string; everything else rides the linker's ``read_wordlist`` line
    rule. Every candidate runs through the shared screening validators
    (``_screening_split_tokens`` + ``_SCREENING_WORD_RE`` + lowercase),
    so the fill agrees with what ``POST /api/screening/run`` parses —
    no silent drops, and the cap is the run maximum with an honest
    ``truncated`` flag. Upload stays T11-owned: this route never writes.
    """
    raw = str(request.args.get("path") or "").strip()
    if not raw:
        return jsonify({"error": "path is required"}), 400
    cand = os.path.abspath(raw)
    if not os.path.isfile(cand):
        return jsonify({"error": "not a file"}), 400
    if not _ops_check_inside(cand):
        return jsonify({"error": "outside the allowed roots"}), 400
    try:
        if os.path.getsize(cand) > _WORDS_READ_SIZE_CAP:
            return jsonify({"error": "file too large to fill"}), 400
    except OSError:
        return jsonify({"error": "not a file"}), 400
    words = []
    try:
        with open(cand, encoding="utf-8") as handle:
            body = handle.read()
        try:
            doc = json.loads(body)
        except ValueError:
            doc = None
        candidates: list = []
        if isinstance(doc, list):
            if all(isinstance(r, dict) for r in doc):
                candidates = [r.get("text") for r in doc
                              if isinstance(r.get("text"), str)]
            elif all(isinstance(r, str) for r in doc):
                candidates = list(doc)
        elif isinstance(doc, str):
            candidates = [doc]
        if not candidates and doc is None:
            from factory.linking import cli as _link_cli
            candidates = list(_link_cli.read_wordlist(cand) or [])
        words = _screening_fill_words(candidates)
    except (OSError, ValueError):
        return jsonify({"error": "unreadable file"}), 400
    total = len(words)
    if total > _SCREENING_WORDS_MAX:
        words = words[:_SCREENING_WORDS_MAX]
    return jsonify({"path": cand, "words": words, "total": total,
                    "truncated": total > len(words)})


#: Upload budget for the T11 dialog upload (never a large dump per click).
_UPLOAD_SIZE_CAP = 2 * 1024 * 1024


@app.route("/api/files/upload", methods=["POST"])
def api_files_upload():
    """T11 — upload one file into an allowlisted dir (data root + browse roots).

    Multipart ``{dir, file}``. The target dir must already exist inside
    ``_ops_allowed_roots`` (outside -> 400, never written); the file name
    is one segment via ``_clean_ops_name`` (400 when unusable); bodies
    over ``_UPLOAD_SIZE_CAP`` -> 400; an existing same-name file -> 409
    (never a silent overwrite — rename first). On success the file is
    listed by ``/api/files/list`` and re-pickable as dialog input.
    """
    parent = os.path.abspath(str(request.form.get("dir") or ""))
    if not parent or not os.path.isdir(parent):
        return jsonify({"error": "not a directory"}), 400
    if not _ops_check_inside(parent):
        return jsonify({"error": "outside the allowed roots"}), 400
    stored = request.files.get("file")
    if stored is None or not (stored.filename or "").strip():
        return jsonify({"error": "file is required"}), 400
    name = _clean_ops_name(stored.filename)
    if not name:
        return jsonify({"error": "bad name (one segment, no slashes)"}), 400
    try:
        blob = stored.read(_UPLOAD_SIZE_CAP + 1)
    except (OSError, ValueError):
        return jsonify({"error": "unreadable upload"}), 400
    if len(blob) > _UPLOAD_SIZE_CAP:
        return jsonify({"error": "file too large to upload"}), 400
    target = os.path.join(parent, name)
    if os.path.exists(target):
        return jsonify({"error": "already exists: %s" % name}), 409
    try:
        with open(target, "wb") as handle:
            handle.write(blob)
    except OSError as exc:
        return jsonify({"error": "upload failed: %s" % exc}), 500
    return jsonify({"path": target, "name": name,
                    "size": len(blob)}), 200


@app.route("/api/files/pins", methods=["GET"])
def api_files_pins_list():
    """T06 — shared pinned paths (OQ-4, one factory-wide file)."""
    from factory.webui import pinned_paths as _pins

    try:
        root = data_root()
    except Exception:
        root = ""
    return jsonify({"pins": _pins.load_pins(root)})


@app.route("/api/files/pins", methods=["POST"])
def api_files_pins_add():
    """T06 — pin a dir/file by name; 400 on invalid path/kind."""
    from factory.webui import pinned_paths as _pins

    fields = request.get_json(force=True, silent=True) or {}
    try:
        root = data_root()
    except Exception:
        root = ""
    try:
        roots = _browse_roots()
    except Exception:
        roots = []
    try:
        entry = _pins.add_pin(root, fields.get("name"),
                              fields.get("path"), fields.get("kind"),
                              extra_roots=roots)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"error": "save failed: %s" % exc}), 500
    return jsonify({"pin": entry}), 200


@app.route("/api/files/pins/<name>", methods=["DELETE"])
def api_files_pins_delete(name):
    """T06 — unpin by exact name (no cascade); 404 when absent."""
    from factory.webui import pinned_paths as _pins

    try:
        root = data_root()
    except Exception:
        root = ""
    try:
        removed = _pins.remove_pin(root, name)
    except OSError as exc:
        return jsonify({"error": "save failed: %s" % exc}), 500
    if not removed:
        return jsonify({"error": "pin not found: %s" % name}), 404
    return jsonify({"deleted": name})


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


# ─── Supervised arbitration batches (P01; import/approve land in W2) ───
# Thin routes over factory/webui/batches.py (single owner of batch logic).
# Import/approve/cancel staging routes arrive with P04 — only build, list,
# fetch-one, and cancel exist in this wave.

#: Serializes batch creation (the threaded server can run two creates
#: concurrently): build+save check-then-act runs under one lock so two
#: overlapping batches can never be born. Mirrors _APPROVE_LOCK.
_BATCH_CREATE_LOCK = threading.Lock()


def _batch_summary(rec):
    """Plan-shaped batch summary for dict rows AND BatchRecord dataclasses.

    (F1/F2: the first mount called ``rec.get`` on the dataclass → 500,
    and dropped ``answered``/``approved`` + ``md``/``json`` carriers.)
    """
    def _get(key, default=None):
        if isinstance(rec, dict):
            return rec.get(key, default)
        return getattr(rec, key, default)
    out = {"id": _get("id"), "size": _get("size"),
           "status": _get("status"),
           "answered": _get("answered", 0),
           "approved": _get("approved", 0),
           "created_at": _get("created_at")}
    for key in ("prompt_version", "prompt_hash"):
        val = _get(key)
        if val is not None:
            out[key] = val
    if out.get("id"):
        directory = _batches.batch_dir(str(out["id"]))
        out["md"] = os.path.join(directory, "batch.md")
        out["json"] = os.path.join(directory, "batch.json-data")
    return out


_BATCH_ID_RX = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _clean_batch_id(raw):
    """Strict batch id (restricted charset); rejects ``..``/separators."""
    name = str(raw or "").strip()
    if not _BATCH_ID_RX.match(name):
        return ""
    return name


@app.route("/api/batches", methods=["POST"])
def api_batch_create():
    fields = request.get_json(force=True, silent=True) or {}
    raw_size = (fields or {}).get("size")
    if raw_size is None or (isinstance(raw_size, str)
                            and not raw_size.strip()):
        size = _batches.DEFAULT_SIZE
    elif isinstance(raw_size, float) and not raw_size.is_integer():
        return jsonify({"error": "VALIDATION-size: size must be an "
                                 "integer 10..50"}), 400
    else:
        try:
            size = int(raw_size)
        except (TypeError, ValueError):
            return jsonify({"error": "VALIDATION-size: size must be an "
                                     "integer 10..50"}), 400
    screened = _configured_path("", SCREENED_ENV_VAR,
                                DEFAULT_SCREENED_PATH)
    try:
        with _BATCH_CREATE_LOCK:
            batch = _batches.build_batch(screened, size=size)
            saved = _batches.save_batch(batch)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"error": "save failed: %s" % exc}), 500
    return jsonify({"batch": _batch_summary(saved)}), 200


@app.route("/api/batches", methods=["GET"])
def api_batches():
    return jsonify({"batches": [_batch_summary(b)
                                for b in _batches.list_batches()]})


@app.route("/api/batches/<batch_id>", methods=["GET"])
def api_batch_fetch(batch_id):
    name = _clean_batch_id(batch_id)
    if not name:
        return jsonify({"error": "batch not found: %s"
                                 % str(batch_id or "").strip()}), 404
    directory = _batches.batch_dir(name)
    meta = _read_batch_meta(name)
    if meta is None:
        return jsonify({"error": "batch not found: %s" % name}), 404
    md_path = os.path.join(directory, "batch.md")
    data_path = os.path.join(directory, "batch.json-data")
    try:
        md_text = ""
        if os.path.isfile(md_path):
            with open(md_path, encoding="utf-8") as handle:
                md_text = handle.read()
        items = []
        if os.path.isfile(data_path):
            with open(data_path, encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                items = payload.get("items", [])
            else:
                return jsonify({"error": "unreadable batch %s: bad "
                                         "items shape" % name}), 500
    except (OSError, ValueError) as exc:
        return jsonify({"error": "unreadable batch %s: %s"
                                 % (name, exc)}), 500
    return jsonify({"batch": meta, "md": md_text, "items": items,
                    "staged": _batch_import.load_staged(name)})


@app.route("/api/batches/<batch_id>/cancel", methods=["POST"])
def api_batch_cancel(batch_id):
    name = _clean_batch_id(batch_id)
    if not name:
        return jsonify({"error": "batch not found: %s"
                                 % str(batch_id or "").strip()}), 404
    try:
        _batches.cancel_batch(name)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"cancelled": name})


def _read_batch_meta(name):
    """Batch meta dict or None (single loader — fetch + repair share it)."""
    try:
        with open(os.path.join(_batches.batch_dir(name), "batch.json"),
                  encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or not meta.get("id"):
        return None
    return meta


def _repair_bundle(name, exc):
    """Copy-ready repair text for a rejected sheet (P06 composer)."""
    meta = _read_batch_meta(name) or {"id": name}
    try:
        return _batch_repair.compose_repair_request(meta, exc)
    except Exception:
        return ""


@app.route("/api/batches/<batch_id>/import", methods=["POST"])
def api_batch_import(batch_id):
    name = _clean_batch_id(batch_id)
    if not name or not os.path.isfile(
            os.path.join(_batches.batch_dir(name), "batch.json")):
        return jsonify({"error": "batch not found: %s"
                                 % str(batch_id or "").strip()}), 404
    fields = request.get_json(force=True, silent=True) or {}
    sheet = (fields or {}).get("answer_sheet")
    if not isinstance(sheet, str) or not sheet.strip():
        return jsonify({"error": "VALIDATION-input: answer_sheet "
                                 "is required"}), 400
    try:
        result = _batch_import.stage_import(name, sheet)
    except _batch_import.BatchImportError as exc:
        return jsonify({"error": str(exc),
                        "failing_ids": list(exc.failing_ids or []),
                        "repair_request": _repair_bundle(name, exc)}), 422
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    result["status"] = "in_review"
    return jsonify(result), 200


@app.route("/api/batches/<batch_id>/approve", methods=["POST"])
def api_batch_approve(batch_id):
    name = _clean_batch_id(batch_id)
    if not name:
        return jsonify({"error": "batch not found: %s"
                                 % str(batch_id or "").strip()}), 404
    fields = request.get_json(force=True, silent=True) or {}
    ids = (fields or {}).get("ids") or []
    reviewer = str((fields or {}).get("reviewer") or "operator").strip() \
        or "operator"
    try:
        result = _batch_import.approve(name, ids, reviewer)
    except _batch_import.BatchImportError as exc:
        return jsonify({"error": str(exc),
                        "failing_ids": list(exc.failing_ids or [])}), 422
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    result["status"] = "imported"
    return jsonify(result), 200


# ─── Linker gallery viewing (P02) ──────────────────────────────────────
# Thin route over factory/webui/gallery.py (viewer.py core untouched).

def _gallery_ref_allowed(ref):
    """True when a gallery ``run`` ref stays inside known runs areas.

    Bare run ids (no separators/drive) always pass — they resolve
    internally. Anything path-shaped must realpath-resolve under the
    shared data root or this console's own dir; absolute strays get an
    honest 404 (LAN-visible console, no auth).
    """
    text = str(ref or "").strip()
    if not text:
        return False
    if ("/" not in text and "\\" not in text and ":" not in text
            and os.path.basename(text) == text):
        return True
    try:
        real = os.path.realpath(text)
    except OSError:
        return False
    try:
        roots = [os.path.realpath(data_root()),
                 os.path.realpath(SCRIPT_DIR)]
    except OSError:
        return False
    return any(real == root or real.startswith(root + os.sep)
               for root in roots)


@app.route("/api/gallery", methods=["GET"])
def api_gallery():
    ref = (request.args.get("run") or "").strip()
    if not ref:
        return jsonify({"error": "VALIDATION-run: ?run=<run-id-or-path> "
                                 "is required"}), 400
    if not _gallery_ref_allowed(ref):
        return jsonify({"error": "run not found: %s" % ref}), 404
    try:
        out = _gallery.build_gallery(ref)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except (OSError, ValueError) as exc:
        return jsonify({"error": "gallery build failed: %s" % exc}), 500
    try:
        with open(out, encoding="utf-8") as handle:
            html = handle.read()
    except OSError as exc:
        return jsonify({"error": "gallery unreadable: %s" % exc}), 500
    return Response(html, mimetype="text/html")


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


# ─── Managed provider registry API (dynamic manifest, names+counts only) ──
# Four routes over the manifest file (no Python edit ever adds a provider):
# create provider, delete provider (even defaults), add key at index or
# appended, delete key at index (higher indexes shift). Every response
# carries names + counts only — key VALUES never appear.

def _managed_create_provider(name, row):
    try:
        rec = provider_registry.create_provider(name, row or {})
    except ValueError as exc:
        return None, str(exc)
    return rec, ""


def _managed_delete_provider(name):
    try:
        ok = provider_registry.delete_provider(name)
    except Exception as exc:
        return False, str(exc)
    if not ok:
        return False, "unknown provider: %s" % (str(name or "").strip(),)
    return True, ""


@app.route("/api/managed_providers", methods=["POST"])
def api_managed_provider_create():
    """Create a provider data row (protocol/route/base_url validated)."""
    fields = request.get_json(force=True, silent=True) or {}
    if not isinstance(fields, dict):
        return jsonify({"error": "body must be a JSON object"}), 400
    name = str((fields or {}).get("name") or "").strip()
    key_vars = (fields or {}).get("key_vars") or []
    if isinstance(key_vars, str) or not isinstance(
            key_vars, (list, tuple)):
        return jsonify({"error": "key_vars must be a list of names"}), 400
    extras = (fields or {}).get("request_extras") or {}
    if not isinstance(extras, dict):
        return jsonify({"error": "request_extras must be an object"}), 400
    row = {
        "protocol": str((fields or {}).get("protocol") or "").strip(),
        "base_url": (fields or {}).get("base_url"),
        "route": str((fields or {}).get("route") or "direct").strip(),
        "key_vars": list(key_vars),
        "request_extras": dict(extras),
        "kind": str((fields or {}).get("kind") or "").strip().lower(),
        "trusted": bool((fields or {}).get("trusted") is True),
    }
    if not row["kind"]:
        del row["kind"]
    if not row["trusted"]:
        del row["trusted"]
    rec, error = _managed_create_provider(name, row)
    if rec is None:
        status = 409 if "exists" in (error or "") else 400
        return jsonify({"error": error}), status
    return jsonify({"provider": str(name or "").strip().lower(),
                    "row": {"name": str(name or "").strip().lower(),
                            "key_count": len(rec.get("key_vars") or [])}})


@app.route("/api/provider_probe", methods=["POST"])
def api_provider_probe():
    """Test an endpoint WITHOUT saving anything (pre-registration check).

    Body: {base_url, kind: local|cloud (default inferred), key_value?}.
    The key VALUE (cloud only) lives in-memory for this one fetch —
    never stored, logged, or returned. Answers {ok, count, models[]} or
    {ok: false, error} with the same kind rules as registration.
    """
    import urllib.request as _url

    fields = request.get_json(force=True, silent=True) or {}
    if not isinstance(fields, dict):
        return jsonify({"error": "body must be a JSON object"}), 400
    base = str((fields or {}).get("base_url") or "").strip()
    kind = str((fields or {}).get("kind") or "").strip().lower()
    if not base:
        return jsonify({"ok": False,
                        "error": "VALIDATION-base_url: endpoint is "
                                 "required"}), 200
    probe_row = {"protocol": "openai_compat", "base_url": base,
                 "route": "direct", "key_vars": []}
    if kind:
        probe_row["kind"] = kind
    try:
        from factory.precard.provider_manifest import (
            validate_row as _validate_row)
        ok, error = _validate_row("probe", probe_row)
    except Exception:
        ok, error = False, "validation unavailable"
    if not ok:
        return jsonify({"ok": False, "error": str(error)}), 200
    endpoint = _openai_models_endpoint(base)
    if not endpoint:
        return jsonify({"ok": False,
                        "error": "no /models endpoint for this base"}), 200
    try:
        from factory.precard.provider_manifest import (
            base_host_allowed as _host_ok)
        host_ok = _host_ok(base)
    except Exception:
        host_ok = False
    if not host_ok:
        return jsonify({"ok": False,
                        "error": "base host refused on re-resolve "
                                 "(loopback/localhost/public only; "
                                 "unresolvable names fail closed)"}), 200
    key_value = str((fields or {}).get("key_value") or "")
    trust_probe = bool((fields or {}).get("trust") is True)
    try:
        from factory.precard.provider_manifest import (
            is_loopback_host as _loop, _base_host as _bhost)
        loopback = _loop(_bhost(base))
    except Exception:
        loopback = False
    if key_value and not (loopback or trust_probe):
        return jsonify({"ok": False,
                        "error": "key is only sent to loopback or an "
                                 "explicitly trusted host (tick trust to "
                                 "probe with a key)"}), 200
    headers = {"Accept": "application/json"}
    if key_value:
        headers["Authorization"] = "Bearer " + key_value
    try:
        req = _url.Request(endpoint, headers=headers)
        with _url.urlopen(req, timeout=10) as resp:
            payload = json.load(resp)
        ids = _openai_model_ids(payload)
    except Exception as exc:
        return jsonify({"ok": False,
                        "error": "unreachable (%s)" % type(exc).__name__}), 200
    return jsonify({"ok": True, "count": len(ids),
                    "models": ids[:20]}), 200


@app.route("/api/managed_providers/<name>", methods=["DELETE"])
def api_managed_provider_delete(name):
    """Delete a provider, even defaults (removed stay gone)."""
    ok, error = _managed_delete_provider(name)
    if not ok:
        return jsonify({"error": error}), 404
    return jsonify({"deleted": str(name or "").strip().lower()})


@app.route("/api/managed_providers/<name>/keys", methods=["POST"])
def api_managed_provider_key_add(name):
    """Add a key slot at 1-based index (append when index absent)."""
    fields = request.get_json(force=True, silent=True) or {}
    index = (fields or {}).get("index", None)
    key_var = str((fields or {}).get("key_var") or "").strip().upper()
    try:
        slots = provider_registry.add_provider_key(name, index=index,
                                                   key_var=key_var)
    except KeyError:
        return jsonify(
            {"error": "unknown provider: %s" % str(name or "").strip()}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"provider": str(name or "").strip().lower(),
                    "key_count": len(slots)})


@app.route("/api/managed_providers/<name>/keys/<index>", methods=["DELETE"])
def api_managed_provider_key_delete(name, index):
    """Delete the key at 1-based index (higher indexes shift down)."""
    try:
        idx = int(str(index or "").strip())
    except (TypeError, ValueError):
        return jsonify({"error": "index must be a 1-based integer"}), 400
    try:
        provider_registry.delete_provider_key(name, idx)
    except KeyError:
        return jsonify(
            {"error": "unknown provider: %s" % str(name or "").strip()}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        count = int(provider_registry.key_count(name))
    except Exception:
        count = 0
    return jsonify({"provider": str(name or "").strip().lower(),
                    "deleted_index": idx, "key_count": count})


# ─── Screened browser + human labels (Steps 4-6, thin readers) ──────
# Read-only browser over the Step-2 screened export; append-only label
# store. Screening (factory.precard.prune) and scoring
# (factory.linking.linker arbitrate/signals) are never called and never
# modified — the candidates feed below only uses the linker's thin
# pure index accessors (cli.read_table + build_link_index/lookup_link)
# and the viewer's pure wordnet readers (resolver + parse_wn_parts +
# sensekey locator). Scoring, screening, evidence, and ranking code
# stay untouched. Join discipline: every row shows identifier + gloss
# together, never bare row numbers. Operator-only console (plain start
# binds all interfaces — LAN-visible with no auth — never localhost-only).

DEFAULT_SCREENED_PATH = (
    "W:/hamzaban_data_factory/proof-linker/screened/screened.jsonl")
#: Shared human-label store (outside git — same single-source data root
#: as presets/operator keys; run history stays per-console). Lazy helper
#: for the same reason as presets_dir()/operator_keys_path() above.
def labels_path():
    """Shared labels file, re-resolved per call (never cached)."""
    return os.path.join(data_root(), "webui", "labels.jsonl")


def _ensure_shared_store_migrated():
    """First-boot copy of legacy per-console operator data to the shared root.

    Copies each legacy slot (``presets/*.json``, ``operator_keys.json``,
    ``labels.jsonl`` under ``SCRIPT_DIR``) into the shared ``data_root()``
    store ONLY when the target slot is empty; never overwrites an existing
    shared file. Idempotent across restarts. Names only in logs — values
    never appear anywhere.
    """
    try:
        legacy_presets = os.path.join(SCRIPT_DIR, "presets")
        if os.path.abspath(presets_dir()) != os.path.abspath(legacy_presets):
            if os.path.isdir(legacy_presets):
                try:
                    os.makedirs(presets_dir(), exist_ok=True)
                except OSError:
                    pass
                try:
                    entries = sorted(os.listdir(legacy_presets))
                except OSError:
                    entries = []
                for entry in entries:
                    if not entry.endswith(".json"):
                        continue
                    src = os.path.join(legacy_presets, entry)
                    dst = os.path.join(presets_dir(), entry)
                    try:
                        if os.path.isfile(src) and not os.path.exists(dst):
                            shutil.copy2(src, dst)
                            app.logger.info(
                                "webui migrated preset %s", entry)
                    except OSError:
                        continue
        for legacy_name, shared_path in (
                ("operator_keys.json", operator_keys_path()),
                ("labels.jsonl", labels_path())):
            try:
                src = os.path.join(SCRIPT_DIR, legacy_name)
                if os.path.abspath(shared_path) == os.path.abspath(src):
                    continue
                if os.path.isfile(src) and not os.path.exists(shared_path):
                    parent = os.path.dirname(shared_path)
                    if parent:
                        try:
                            os.makedirs(parent, exist_ok=True)
                        except OSError:
                            continue
                    shutil.copy2(src, shared_path)
                    app.logger.info("webui migrated %s", legacy_name)
            except OSError:
                continue
    except Exception:
        pass


#: First-request migration guard: ``_ensure_shared_store_migrated`` must
#: run on every serve path (plain ``__main__`` and any WSGI/import serve),
#: so it also runs once before the first request. The ``__main__`` call
#: below stays (idempotent) so the receipt appears even with no traffic.
_MIGRATION_LOCK = threading.Lock()
_MIGRATED_ONCE = {"done": False}


@app.before_request
def _ensure_boot_migrated():
    """Run the shared-store migration once, on any serve path."""
    if _MIGRATED_ONCE["done"]:
        return
    with _MIGRATION_LOCK:
        if _MIGRATED_ONCE["done"]:
            return
        try:
            _ensure_shared_store_migrated()
        except Exception:
            pass
        _MIGRATED_ONCE["done"] = True

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


#: Screening-export job states: idle (never ran here) / running / completed
#: (exit 0) / failed (nonzero exit or operator abort). The live record
#: is in-memory; T04 additionally persists {run_id, pid, started_iso,
#: out_dir, out_name, words_hash, status} per spawn/settle to
#: ``<DATA_ROOT>/webui/screening_run_status.json`` (owner:
#: ``factory.webui.run_status``) so a console restart reconnects to the
#: same run_id with log tail + progress recovered from out_dir.
_SCREENING_LOG_MAX = 100

#: Log tail filename inside the export out_dir (pump tee, T04 reconnect).
_SCREENING_LOG_NAME = "screening.log"

#: Cabins served by GET /api/runs/history (single registry of run cabins).
_KNOWN_RUN_CABINS = frozenset({"screening"})

_SCREENING_LOCK = threading.Lock()
_SCREENING = {"proc": None, "pid": None, "status": "idle", "words": [],
              "out_dir": "", "started": None, "started_iso": None,
              "run_id": None, "words_hash": None,
              "exit_code": None, "log": [], "manifest": None, "note": ""}


def _default_screening_words():
    """Screening word list default (owned by the export script).

    Single source is ``factory.linking.export_screened.DEFAULT_WORDS``
    (read lazily — the adapter never keeps a rival literal); the
    fallback literal only covers an unreadable script module.
    """
    try:
        from factory.linking import export_screened as _export
        default = str(getattr(_export, "DEFAULT_WORDS", "") or "")
        if default.strip():
            return default
    except Exception:
        pass
    return "run,light,take,get,make"


def _screening_default_out_dir():
    """Default screening output dir under the factory data root."""
    try:
        root = data_root()
    except Exception:
        root = ""
    if not str(root or "").strip():
        return os.path.join(PROJECT_ROOT, "data", "proof-linker",
                             "screened")
    return os.path.join(str(root).strip(), "proof-linker", "screened")


#: Screening word-list bounds (T11 — OQ-2): at most this many lemmas,
#: each matching ``^[a-z-]{1,64}$`` (lowercase English lemma or hyphenated
#: form). Non-matching tokens are dropped; an empty result falls back to the
#: export script's own default list. Over-cap input FAILS FAST (no silent
#: trim) via ``_ScreeningOverCap`` carrying total + excess.
_SCREENING_WORDS_MAX = 2500
_SCREENING_WORD_RE = re.compile(r"^[a-z-]{1,64}$")


class _ScreeningOverCap(ValueError):
    """Raised when the parsed word list exceeds ``_SCREENING_WORDS_MAX``."""

    def __init__(self, total, excess):
        super(_ScreeningOverCap, self).__init__("words over cap")
        self.total = total
        self.excess = excess
        self.limit = _SCREENING_WORDS_MAX


def _screening_split_tokens(raw):
    """Raw words -> lowercase non-empty tokens (shared splitter).

    Single owner of the ``[Latin/Persian comma + newline]+`` split:
    both the run path (``_screening_parse_words``) and the read-only
    ledger preview consume it, so preview fresh/duplicate counts can
    never disagree with what the run actually processes over
    Persian-comma / multiline input.
    """
    return [w.strip().lower()
            for w in re.split(r"[,،\n\r]+", str(raw or ""))
            if w.strip()]


def _screening_fill_words(candidates):
    """Candidate strings -> run-agreement word list (shared validators).

    Agreement point between the data-dialog fill
    (``GET /api/files/words``) and the run path
    (``_screening_parse_words``): the shared ``_screening_split_tokens``
    splitter + ``_SCREENING_WORD_RE`` filter + lowercase, so A1 shows
    exactly what the run will process (no silent drops, no case
    drift). Pure: never reads disk, never falls back to defaults.
    """
    text = "\n".join(str(w or "") for w in (candidates or []))
    return [w for w in _screening_split_tokens(text)
            if _SCREENING_WORD_RE.match(w)]


def _screening_parse_words(raw):
    """Multiline+comma words -> validated lemma list (default when empty).

    Tokens split on commas (Latin/Persian) or newlines, stripped +
    lowercased, kept only when they match ``_SCREENING_WORD_RE``. Empty
    (or fully invalid) input falls back to the export script's own
    default word list (validated the same way). Over-cap input raises
    ``_ScreeningOverCap`` (fail-fast with excess count — never a silent
    trim, OQ-2).
    """
    words = [w for w in _screening_split_tokens(raw)
             if _SCREENING_WORD_RE.match(w)]
    if not words:
        words = [w.strip().lower()
                 for w in _default_screening_words().split(",")]
        words = [w for w in words if _SCREENING_WORD_RE.match(w)]
    if len(words) > _SCREENING_WORDS_MAX:
        raise _ScreeningOverCap(len(words),
                                len(words) - _SCREENING_WORDS_MAX)
    return words


#: Output-name alphabet (T11 — OQ-6): Persian (Arabic block) + Latin +
#: digits + ``-`` + ``_`` survive; every other run becomes one ``-``.
_SCREENING_NAME_RX = re.compile(r"[^\u0600-\u06FFa-zA-Z0-9\-_]+")


def _screening_clean_out_name(raw):
    """Sanitize a screening output name (fa+lat+digits+``-``+``_``).

    Foreign runs -> ``-``, dash runs collapse, edge ``-``/``_`` strip,
    latin lowercased, capped at 64 chars. Empty result means unusable.
    """
    name = _SCREENING_NAME_RX.sub(
        "-", str(raw or "").strip().lower())
    name = re.sub(r"-+", "-", name).strip("-_")
    return name[:64]


def _screening_out_dir_for_name(clean):
    """Resolve a sanitized output name under the confined screening root.

    Returns ``(True, resolved_dir)`` confined via
    ``_screening_safe_out_dir``; ``(False, reason)`` on empty/escape.
    """
    if not clean:
        return False, "bad out_name (empty after sanitize)"
    base = _screening_default_out_dir()
    return _screening_safe_out_dir(os.path.join(base, clean))


def _screening_next_free_name(clean):
    """First ``<clean>_v2`` … ``<clean>_v999`` with no dir on disk."""
    base = _screening_default_out_dir()
    for i in range(2, 1000):
        cand = "%s_v%d" % (clean, i)
        try:
            if not os.path.exists(os.path.join(base, cand)):
                return cand
        except (OSError, ValueError, TypeError):
            continue
    return ""


def _screening_safe_out_dir(raw):
    """Confine the requested screening output dir under the default root.

    Returns ``(True, resolved_dir)`` when ``raw`` is blank (default) or
    resolves inside ``_screening_default_out_dir()``; ``(False, reason)``
    on absolute/traversal escapes. The console binds LAN-visible with
    no auth, so arbitrary-path writes from a POST body are refused —
    never silently rewritten (the caller sees the 400 reason).
    """
    base = _screening_default_out_dir()
    cand = str(raw or "").strip() or base
    try:
        base_abs = os.path.abspath(base)
        cand_abs = os.path.abspath(cand)
    except (OSError, ValueError, TypeError):
        return False, "unresolvable out_dir"
    try:
        inside = os.path.commonpath([base_abs, cand_abs]) == base_abs
    except (OSError, ValueError):
        return False, "out_dir escapes the screening root"
    if not inside:
        return False, "out_dir escapes the screening root"
    return True, cand_abs


def _screening_manifest_summary(out_dir):
    """{kept_total, dropped_total, per_lemma[, drop_reasons]} from the manifest.

    Pure reader over ``screened.manifest.json`` (written by the export
    child on success): missing/unreadable file -> None (honest empty,
    never invented). Only the summary keys are surfaced. ``drop_reasons``
    (T01: ``{twin_r3, proper_r2, other}``) passes through verbatim when
    present and well-formed — legacy manifests without the key yield a
    summary without it (downstream renders ``—`` titled, never zeros).
    """
    path = os.path.join(str(out_dir or ""), "screened.manifest.json")
    try:
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    try:
        kept = int(manifest.get("kept_total") or 0)
    except (TypeError, ValueError):
        kept = 0
    try:
        dropped = int(manifest.get("dropped_total") or 0)
    except (TypeError, ValueError):
        dropped = 0
    per_lemma = manifest.get("per_lemma")
    if not isinstance(per_lemma, list):
        per_lemma = []
    summary = {"kept_total": kept, "dropped_total": dropped,
               "per_lemma": per_lemma}
    reasons = manifest.get("drop_reasons")
    if isinstance(reasons, dict):
        try:
            packed = {"twin_r3": int(reasons.get("twin_r3") or 0),
                      "proper_r2": int(reasons.get("proper_r2") or 0),
                      "other": int(reasons.get("other") or 0)}
        except (TypeError, ValueError):
            packed = None
        if packed is not None:
            summary["drop_reasons"] = packed
    return summary


def _screening_words_hash(words):
    """Short stable hash of the spawn word list (T04 status identity)."""
    try:
        digest = hashlib.sha256(
            ",".join(list(words or [])).encode("utf-8")).hexdigest()
    except Exception:
        return None
    return digest[:16]


def _screening_store_write_locked():
    """Persist the in-memory screening record to the T04 disk file.

    Caller must hold ``_SCREENING_LOCK``. Best-effort: a failed write
    never breaks the run (the T03 registry precedent) — reconnect just
    degrades to the previous file content. No-op before the first
    spawn (no ``run_id`` yet).
    """
    if not _SCREENING.get("run_id"):
        return
    try:
        from factory.webui import run_status as _run_status

        try:
            root = data_root()
        except Exception:
            root = ""
        out_dir = str(_SCREENING.get("out_dir") or "")
        try:
            out_name = os.path.basename(os.path.abspath(out_dir))
        except (OSError, ValueError, TypeError):
            out_name = ""
        _run_status.write(root, "screening", {
            "run_id": _SCREENING.get("run_id") or "",
            "pid": _SCREENING.get("pid"),
            "started_iso": _SCREENING.get("started_iso") or "",
            "out_dir": out_dir,
            "out_name": out_name,
            "words_hash": _SCREENING.get("words_hash"),
            "status": _SCREENING.get("status") or "unknown"})
    except Exception:
        pass


def _screening_log_tail(out_dir, limit=_SCREENING_LOG_MAX):
    """Last ``limit`` lines of the T04 pump log under ``out_dir``.

    Reads only the trailing ~64KB (long runs never load fully);
    missing/unreadable file -> ``[]`` (honest empty, never raises).
    """
    path = os.path.join(str(out_dir or ""), _SCREENING_LOG_NAME)
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            if size > 65536:
                handle.seek(max(0, size - 65536))
                handle.readline()
            lines = handle.read().splitlines()
    except (OSError, ValueError):
        return []
    try:
        keep = int(limit)
    except (TypeError, ValueError):
        keep = _SCREENING_LOG_MAX
    return lines[-keep:] if keep > 0 else []


def _screening_idle_snapshot():
    """Honest idle snapshot (no run anywhere — memory or disk)."""
    try:
        from factory.webui import duration_fmt as _duration_fmt

        elapsed_human = _duration_fmt.format_duration(None)
    except Exception:
        elapsed_human = None
    return {"status": "idle", "run_id": None, "resumed": False,
            "pid": None, "exit_code": None, "elapsed": None,
            "elapsed_human": elapsed_human, "started_iso": None,
            "words": [], "out_dir": "", "log": [], "manifest": None,
            "note": ""}


def _screening_disk_snapshot_locked():
    """Reconnect snapshot from the T04 disk file (holds ``_SCREENING_LOCK``).

    Fresh console process (restart/refresh with no in-memory proc):
    the same run_id comes back, with log tail + progress recovered
    from out_dir. A record still marked running whose pid died behind
    our back settles here (manifest present -> completed, else failed)
    and the disk file is updated to match. Missing/corrupt file ->
    honest idle. ``pid`` is a liveness probe only — never signalled.
    Never raises.
    """
    try:
        from factory.webui import run_status as _run_status
    except Exception:
        return _screening_idle_snapshot()
    try:
        root = data_root()
    except Exception:
        root = ""
    try:
        rec = _run_status.read(root, "screening")
    except Exception:
        rec = None
    if not rec:
        return _screening_idle_snapshot()
    try:
        from factory.webui import duration_fmt as _duration_fmt

        elapsed_human = _duration_fmt.format_duration(None)
    except Exception:
        elapsed_human = None
    run_id = rec.get("run_id")
    pid = rec.get("pid") if isinstance(rec.get("pid"), int) else None
    started_iso = (rec.get("started_iso")
                   if isinstance(rec.get("started_iso"), str) else None)
    out_dir = rec.get("out_dir") if isinstance(rec.get("out_dir"), str) \
        else ""
    status = rec.get("status") if isinstance(rec.get("status"), str) \
        else "unknown"
    if status not in ("running", "completed", "failed", "aborted"):
        status = "unknown"
    log = _screening_log_tail(out_dir)
    manifest = None
    if status == "running":
        try:
            alive = _pid_alive(pid) if pid is not None else False
        except Exception:
            alive = False
        if alive:
            return {"status": "running", "run_id": run_id,
                    "resumed": True, "pid": pid, "exit_code": None,
                    "elapsed": None, "elapsed_human": elapsed_human,
                    "started_iso": started_iso, "words": [],
                    "out_dir": out_dir, "log": log, "manifest": None,
                    "note": ""}
        summary = _screening_manifest_summary(out_dir)
        status = "completed" if summary is not None else "failed"
        manifest = summary
        try:
            settled = dict(rec)
            settled["status"] = status
            _run_status.write(root, "screening", settled)
        except Exception:
            pass
    elif status == "completed":
        manifest = _screening_manifest_summary(out_dir)
    return {"status": status, "run_id": run_id, "resumed": True,
            "pid": pid, "exit_code": None, "elapsed": None,
            "elapsed_human": elapsed_human, "started_iso": started_iso,
            "words": [], "out_dir": out_dir, "log": log,
            "manifest": manifest, "note": ""}


def _screening_public_locked():
    """Public screening snapshot (caller must hold ``_SCREENING_LOCK``).

    Polls the child once so a finished run settles to completed/failed
    on read; on success the manifest summary is attached. Elapsed is
    monotonic seconds since spawn (None before the first run); the raw
    ``elapsed`` key is kept for compat while ``elapsed_human`` (T02:
    Persian text, never a raw float) and ``started_iso`` (wall-clock
    UTC, for smart-relative stamps) are added alongside.
    """
    import time as _time

    proc = _SCREENING.get("proc")
    code = None
    if proc is not None:
        try:
            code = proc.poll()
        except Exception:
            code = None
    if code is not None and _SCREENING.get("status") == "running":
        _SCREENING["exit_code"] = code
        if code == 0:
            _SCREENING["status"] = "completed"
            _SCREENING["manifest"] = _screening_manifest_summary(
                _SCREENING.get("out_dir"))
        else:
            _SCREENING["status"] = "failed"
        _screening_store_write_locked()
    started = _SCREENING.get("started")
    try:
        elapsed = (_time.monotonic() - float(started)
                   if started is not None else None)
    except (TypeError, ValueError):
        elapsed = None
    try:
        from factory.webui import duration_fmt as _duration_fmt

        elapsed_human = _duration_fmt.format_duration(elapsed)
    except Exception:
        elapsed_human = None
    return {"status": _SCREENING.get("status"),
            "run_id": _SCREENING.get("run_id"),
            "resumed": False,
            "pid": _SCREENING.get("pid"),
            "exit_code": _SCREENING.get("exit_code"),
            "elapsed": elapsed,
            "elapsed_human": elapsed_human,
            "started_iso": _SCREENING.get("started_iso"),
            "words": list(_SCREENING.get("words") or []),
            "out_dir": _SCREENING.get("out_dir") or "",
            "log": list(_SCREENING.get("log") or [])[-_SCREENING_LOG_MAX:],
            "manifest": _SCREENING.get("manifest"),
            "note": _SCREENING.get("note") or ""}


def _screening_snapshot():
    """Public screening snapshot (locking wrapper, never raises).

    T04: with no in-memory proc (fresh process after a restart, or a
    never-ran console) the snapshot merges disk state so refresh /
    restart resume the SAME run_id with log tail + progress recovered
    from out_dir (``resumed: true``); otherwise the live record wins.
    """
    with _SCREENING_LOCK:
        proc = _SCREENING.get("proc")
        if proc is not None or _SCREENING.get("status") != "idle":
            return _screening_public_locked()
        try:
            return _screening_disk_snapshot_locked()
        except Exception:
            return _screening_idle_snapshot()


def _screening_pump(proc, log_path=None):
    """Drain a screening child into the combined ring buffer (thread).

    Stdout+stderr arrive merged (single chronological stream, max 100
    lines kept); T04 also tees each line to ``log_path`` (the
    ``screening.log`` under the run out_dir, best-effort) so a console
    restart recovers the tail from disk. On child exit a still-running
    record settles to completed/failed with the manifest summary on
    success, and the T04 disk file follows. An abort that already
    settled the record wins (never overwritten here). Best-effort —
    never raises, never touches other jobs.
    """
    handle = None
    if log_path:
        try:
            parent = os.path.dirname(str(log_path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            handle = open(str(log_path), "a", encoding="utf-8",
                          errors="replace")
        except OSError:
            handle = None
    try:
        stream = getattr(proc, "stdout", None)
        if stream is not None:
            for line in stream:
                try:
                    text = (line if isinstance(line, str)
                            else str(line or ""))
                except Exception:
                    continue
                with _SCREENING_LOCK:
                    _SCREENING["log"].append(text.rstrip("\n"))
                    del _SCREENING["log"][:-_SCREENING_LOG_MAX]
                if handle is not None:
                    try:
                        handle.write(text if text.endswith("\n")
                                     else text + "\n")
                        handle.flush()
                    except OSError:
                        try:
                            handle.close()
                        except OSError:
                            pass
                        handle = None
    except Exception:
        pass
    finally:
        if handle is not None:
            try:
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
                handle.close()
            except OSError:
                pass
    try:
        code = proc.wait()
    except Exception:
        code = None
    with _SCREENING_LOCK:
        if _SCREENING.get("status") != "running":
            return
        _SCREENING["exit_code"] = code
        if code == 0:
            _SCREENING["status"] = "completed"
            _SCREENING["manifest"] = _screening_manifest_summary(
                _SCREENING.get("out_dir"))
        else:
            _SCREENING["status"] = "failed"
        _screening_store_write_locked()


@app.route("/api/screening/exists", methods=["GET"])
def api_screening_exists():
    """T11 — collision preflight for an output name (read-only, never spawns).

    ``GET /api/screening/exists?out_name=demo`` ->
    ``{out_name, path, exists}``. The name is sanitized exactly like the
    run path (``_screening_clean_out_name``); 400 when nothing usable
    remains. The run dialog calls this BEFORE spawning; the POST handler
    re-checks, so skipping the preflight can never silently overwrite.
    """
    clean = _screening_clean_out_name(request.args.get("out_name") or "")
    if not clean:
        return jsonify({"error": "bad out_name (empty after sanitize)"}), 400
    ok, resolved = _screening_out_dir_for_name(clean)
    if not ok:
        return jsonify({"error": resolved}), 400
    try:
        exists = os.path.exists(resolved)
    except (OSError, ValueError, TypeError):
        exists = False
    return jsonify({"out_name": clean, "path": resolved, "exists": exists})


@app.route("/api/screening/run", methods=["POST"])
def api_screening_run():
    """Spawn the screened export (Step 2) in the background.

    Body {"words" (optional, comma/newline-separated; default is the export
    script's own word list), "out_name" (optional; sanitized T11 OQ-6 and
    resolved under the confined screening root), "out_dir" (optional;
    default ``<DATA_ROOT>/proof-linker/screened``), "collision"
    (optional; "" | "auto" | "overwrite"), "reprocess_duplicates" (bool,
    default false)}. The child is exactly
    ``python -m factory.linking.export_screened --words .. --out-dir
    ..`` (receipt argv, replays from a terminal); the long export
    never runs in the request thread — the handler spawns via
    ``subprocess.Popen`` and returns while a pump thread drains the
    merged stdout+stderr into the 100-line ring buffer. 409 while a
    run is already in flight; 201 with the running snapshot otherwise.
    400 when ``out_dir`` escapes the confined screening root, when the
    word list exceeds 2500 (OQ-2 fail-fast with excess count, never a
    silent trim), or when ``out_name`` is unusable. T11 collision: a
    named target that already exists -> 409 ``{collision: true}``
    unless ``collision`` is ``"auto"`` (next-free ``<name>_v2``) or
    ``"overwrite"`` (explicit, dialog-confirmed) — the dialog runs
    BEFORE the spawn, never a silent overwrite. T03:
    body may carry ``reprocess_duplicates`` (bool, default false) —
    fresh-only by default (already-screened lemmas from
    ``screened_registry.jsonl`` are skipped); explicit true reprocesses
    them. 400 when the fresh-only filter leaves no words.
    """
    fields = request.get_json(force=True, silent=True) or {}
    try:
        words = _screening_parse_words(fields.get("words"))
    except _ScreeningOverCap as exc:
        return jsonify({"error": "words over cap "
                                 "(limit %d, got %d, excess %d)"
                                 % (exc.limit, exc.total, exc.excess),
                        "over_cap": True, "limit": exc.limit,
                        "total": exc.total,
                        "excess": exc.excess}), 400
    reprocess = bool(fields.get("reprocess_duplicates", False))
    if not reprocess:
        try:
            from factory.linking import export_screened as _export

            try:
                _root = data_root()
            except Exception:
                _root = ""
            screened = _export.read_registry_lemmas(_root)
        except Exception:
            screened = set()
        fresh = [w for w in words if w not in screened]
        if not fresh:
            return jsonify({"error": "all words already screened "
                                     "(reprocess_duplicates to redo)",
                            "duplicate": list(words)}), 400
        words = fresh
    ok, out_dir = _screening_safe_out_dir(fields.get("out_dir"))
    if not ok:
        return jsonify({"error": out_dir}), 400
    out_name = ""
    raw_name = fields.get("out_name")
    if raw_name is not None and str(raw_name).strip():
        clean = _screening_clean_out_name(raw_name)
        if not clean:
            return jsonify(
                {"error": "bad out_name (empty after sanitize)"}), 400
        collision = str(fields.get("collision") or "").strip().lower()
        if collision not in ("", "auto", "overwrite"):
            return jsonify(
                {"error": "bad collision (auto|overwrite)"}), 400
        if collision == "auto":
            clean = _screening_next_free_name(clean)
            if not clean:
                return jsonify(
                    {"error": "no free name slot (v2..v999 taken)"}), 409
        ok, resolved = _screening_out_dir_for_name(clean)
        if not ok:
            return jsonify({"error": resolved}), 400
        if collision != "overwrite":
            try:
                taken = os.path.exists(resolved)
            except (OSError, ValueError, TypeError):
                taken = False
            if taken:
                return jsonify({"error": "output name already exists "
                                         "(pick auto/overwrite/rename/cancel)",
                                "collision": True, "out_name": clean,
                                "path": resolved}), 409
        out_dir, out_name = resolved, clean
    import time as _time

    with _SCREENING_LOCK:
        proc = _SCREENING.get("proc")
        try:
            busy = proc is not None and proc.poll() is None
        except Exception:
            busy = False
        if busy:
            return jsonify({"error": "screening already running",
                            "screening": _screening_public_locked()}), 409
        argv = [sys.executable, "-m", "factory.linking.export_screened",
                "--words", ",".join(words), "--out-dir", out_dir]
        try:
            proc = subprocess.Popen(
                argv, cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
        except OSError as exc:
            return jsonify({"error": "spawn failed: %s" % exc}), 500
        try:
            started_iso = datetime.datetime.now(
                datetime.timezone.utc).isoformat()
        except Exception:
            started_iso = None
        run_id = uuid.uuid4().hex
        _SCREENING.update(proc=proc, pid=_proc_pid(proc),
                          status="running", words=list(words),
                          out_dir=out_dir, started=_time.monotonic(),
                          started_iso=started_iso,
                          run_id=run_id,
                          words_hash=_screening_words_hash(words),
                          exit_code=None, log=[], manifest=None, note="")
        try:
            log_path = os.path.join(out_dir, _SCREENING_LOG_NAME)
        except (OSError, ValueError, TypeError):
            log_path = None
        threading.Thread(target=_screening_pump, args=(proc, log_path),
                         daemon=True).start()
        body = _screening_public_locked()
        _screening_store_write_locked()
    return jsonify({"screening": body}), 201


@app.route("/api/screening/status", methods=["GET"])
def api_screening_status():
    """Screening job snapshot: idle/running/completed/failed + elapsed.

    Carries the exit code, the single combined chronological tail
    (max 100 lines, stdout+stderr merged) and — on success — the
    manifest summary (kept_total/dropped_total/per_lemma). Never
    spawns, never signals.
    """
    return jsonify({"screening": _screening_snapshot()})


@app.route("/api/screening/ledger_preview", methods=["GET"])
def api_screening_ledger_preview():
    """T03 — fresh/duplicate split for a candidate word list (read-only).

    Query ``?words=a,b,c`` → ``{fresh, duplicate, fresh_count,
    dup_count}`` partitioned against ``screened_registry.jsonl`` (exact
    lowercase lemma match). Tokenizes through the shared
    ``_screening_split_tokens`` splitter so Persian-comma / multiline
    input previews exactly what the run parses. Never mutates; a
    missing registry means all-fresh. This is the A3 ledger-preview
    pane source.
    """
    raw = request.args.get("words") or ""
    words = [w for w in _screening_split_tokens(raw)
             if _SCREENING_WORD_RE.match(w)]
    try:
        from factory.linking import export_screened as _export

        try:
            _root = data_root()
        except Exception:
            _root = ""
        screened = _export.read_registry_lemmas(_root)
    except Exception:
        screened = set()
    fresh = [w for w in words if w not in screened]
    duplicate = [w for w in words if w in screened]
    return jsonify({"fresh": fresh, "duplicate": duplicate,
                    "fresh_count": len(fresh),
                    "dup_count": len(duplicate)})


@app.route("/api/screening/abort", methods=["POST"])
def api_screening_abort():
    """Stop the running screening child by pid only (never a blanket kill).

    SIGTERM on the recorded child, a short wait, then the kill
    fallback (same stop leg as run cancel). The record settles to
    failed with an operator-abort note. 409 when no run is in flight.
    """
    with _SCREENING_LOCK:
        proc = _SCREENING.get("proc")
        try:
            busy = proc is not None and proc.poll() is None
        except Exception:
            busy = False
        if not busy:
            return jsonify({"error": "no screening run in flight",
                            "screening": _screening_public_locked()}), 409
        pid = _SCREENING.get("pid")
    code, note = _terminate_child(proc, pid,
                                  grace_seconds=CANCEL_GRACE_SECONDS,
                                  verify=None)
    if code is None:
        try:
            code = proc.poll()
        except Exception:
            code = None
    with _SCREENING_LOCK:
        _SCREENING["exit_code"] = code
        _SCREENING["status"] = "failed"
        _SCREENING["note"] = ("aborted by operator%s"
                              % (note or ""))
        _screening_store_write_locked()
        body = _screening_public_locked()
    return jsonify({"screening": body})


@app.route("/api/runs/history", methods=["GET"])
def api_runs_history():
    """T05 — cabin-parametric run history (ADD-11 backend, read-only).

    ``GET /api/runs/history?cabin=screening`` -> ``{cabin, runs,
    skipped, truncated}`` scanned from
    ``<DATA_ROOT>/webui/<cabin>_runs/`` merged with the T04 status
    file for that cabin (newest last; the status file wins on equal
    ``run_id``). Per-run rows carry ``{run_id, out_name, out_dir,
    started_iso, status, kept_total, dropped_total}``. Unknown or
    missing cabin -> 400. Corrupt records are skipped + counted in
    ``skipped`` (never 500). Capped at 500 rows (``truncated: true``
    beyond, newest kept). Empty history -> ``runs: []``. No write
    path — history never mutates.
    """
    from factory.webui import run_status as _run_status

    cabin = (request.args.get("cabin") or "").strip()
    if cabin not in _KNOWN_RUN_CABINS:
        return jsonify({"error": "unknown cabin: %s" % cabin}), 400
    try:
        root = data_root()
    except Exception:
        root = ""
    payload = _run_status.history(root, cabin)
    # The T04 file carries identity only; totals for a completed live
    # run come from the export manifest under out_dir (read here, in
    # the adapter — never invented).
    try:
        live = _run_status.read(root, cabin) or {}
        live_id = live.get("run_id")
        if live_id and str(live.get("status") or "") == "completed":
            summary = _screening_manifest_summary(live.get("out_dir"))
            if summary is not None:
                for row in payload.get("runs") or []:
                    if row.get("run_id") == live_id:
                        row["kept_total"] = summary["kept_total"]
                        row["dropped_total"] = summary["dropped_total"]
    except Exception:
        pass
    return jsonify(payload)


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
    store = (request.args.get("store") or "").strip() or labels_path()
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
    store = str((fields or {}).get("store") or "").strip() or labels_path()
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
    address to open from a tablet vs loopback on this machine) plus an
    operator-only caution: the plain bind exposes key-accepting
    endpoints with no auth, with the loopback escape. An explicit
    override reproduces exactly with no note. Names only, no secrets.
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
        lines.append(
            "webui caution operator-only: plain start exposes "
            "key-accepting endpoints (/api/providers/<name>/key, "
            "/api/supervisor/token, /api/runs, /api/files/list, "
            "/api/labels) with no auth — trusted LAN only; pass "
            "--host 127.0.0.1 for loopback-only")
    return lines


if __name__ == "__main__":
    _args = parse_server_args()
    os.chdir(PROJECT_ROOT)
    os.makedirs(RUNS_DIR, exist_ok=True)
    _ensure_shared_store_migrated()
    # Boot receipt: proves the exact host/port the process bound
    # (operators match this line against the -BindHost/-Port they
    # passed to server_ctl.ps1; names only, no secrets).
    for _line in build_boot_lines(
            _args.host, _args.port, os.getpid(), _detect_lan_ipv4()):
        print(_line, flush=True)
    app.run(host=_args.host, port=_args.port)
