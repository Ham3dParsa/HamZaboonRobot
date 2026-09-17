#!/usr/bin/env python3
"""Producer-side blast-radius helper (REV-2 edge-probe extension: REV-4).

Reads ``git diff <base>...HEAD``, extracts changed symbols with ``ast``,
refreshes the graphify index, runs bounded read-only graph queries, executes
hostile-input edge probes, and emits gitignored ``review-context.json`` for
the (read-only) reviewer to consume.

Stdlib only. Output carries symbols + file:line references only -- never
secrets, tokens, or message bodies.

Exit codes: 0 = context emitted (fresh graph, or degraded without one);
2 = stale graph (``built_at_commit != HEAD``): re-run ``graphify update .``.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import concurrent.futures
import inspect
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Bounds: keep producer cost predictable (contract R2).
MAX_QUERY_COMMANDS = 3
QUERY_BUDGET = 1000
MAX_SYMBOLS = 200
MAX_CALLERS = 20
MAX_CALLEES = 30
MAX_PROBE_FUNCTIONS = 8
PROBE_OUTPUT_LEN = 200
PROBE_TIMEOUT_SEC = 5.0

# Probe allowlist (R6): only known-pure modules are imported/probed by
# default. Everything else is skipped unless --allow-risky is passed.
# Matched on the dotted module name derived from the file relpath.
SAFE_MODULE_PREFIXES = (
    "services.utils.",
    "services.session.",
    "config.catalog",
)
SAFE_MODULE_EXACT = frozenset({
    "services.fsrs_core",
    "services.scheduling",
    "services.session",
    "config.catalog",
})
# Tests-local and synthetic helpers (exercised hermetically, no I/O).
SAFE_TEST_PREFIXES = ("tests.", "test_")
SAFE_BARE_PREFIXES = ("test_", "tmp_", "sampler", "probe")

# Production scan targets mirror tests/test_dead_code_guard.py.
PRODUCTION_SCAN_TARGETS = ("bot.py", "handlers", "services", "config")

# Hostile probe inputs (REV-4): falsy-vs-None, non-finite, case, negative.
_HOSTILE_LABELS = ("{}", "None", "NaN", "MiXeD-CaSe", "-1")
_HOSTILES: tuple = ({}, None, float("nan"), "MiXeD-CaSe", -1)


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Path = REPO_ROOT) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=600
        )
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"timeout: {exc}"
    return proc.returncode, proc.stdout, proc.stderr


def _head_sha() -> str | None:
    rc, out, _ = _run(["git", "rev-parse", "HEAD"])
    return out.strip() if rc == 0 and out.strip() else None


def _diff_py_files(base: str) -> tuple[list[str], str | None]:
    """Changed ``.py`` paths: committed range + working tree + untracked.

    Unions ``git diff <base>...HEAD`` with uncommitted working-tree changes
    (unstaged ``git diff`` + staged ``git diff --cached``) and untracked
    files (``git ls-files --others --exclude-standard``), so new files and
    uncommitted edits are visible to symbol extraction.
    """
    seen: set[str] = set()
    files: list[str] = []
    error: str | None = None

    def _add(out: str) -> None:
        for ln in out.splitlines():
            rel = ln.strip()
            if rel and rel not in seen:
                seen.add(rel)
                files.append(rel)

    rc, out, err = _run(
        ["git", "diff", f"{base}...HEAD", "--name-only", "--", "*.py"]
    )
    if rc != 0:
        error = err.strip() or f"git diff {base}...HEAD failed"
    else:
        _add(out)
    # Uncommitted changes: unstaged (worktree vs index) + staged (index).
    # Failures here are non-fatal; the committed range above is authoritative.
    for extra in (
        ["git", "diff", "--name-only", "--", "*.py"],
        ["git", "diff", "--cached", "--name-only", "--", "*.py"],
        ["git", "ls-files", "--others", "--exclude-standard", "--", "*.py"],
    ):
        rc2, out2, _ = _run(extra)
        if rc2 == 0:
            _add(out2)
    return files, error


def _show_at(ref: str, relpath: str) -> str | None:
    rc, out, _ = _run(["git", "show", f"{ref}:{relpath}"])
    return out if rc == 0 else None


def _ls_py_at(ref: str) -> list[str]:
    rc, out, _ = _run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--",
         "bot.py", "handlers", "services", "config"]
    )
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines()
            if ln.strip().endswith(".py")]


# --------------------------------------------------------------------------
# AST symbol extraction (patterns mirror tests/test_wiring.py collectors)
# --------------------------------------------------------------------------

def _extract_static_prefix(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        static = node.value.split("{")[0].rstrip(":")
        return static if static else None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                break
            else:
                break
        static = "".join(parts).rstrip(":")
        return static if static else None
    return None


def symbols_in_source(source: str, relpath: str) -> list[dict]:
    """Extract def/class/register/callback/import symbols from one module."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add(name: str, kind: str) -> None:
        key = (name, kind)
        if name and key not in seen:
            seen.add(key)
            found.append({"name": name, "file": relpath, "kind": kind})

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _add(node.name, "def")
        elif isinstance(node, ast.ClassDef):
            _add(node.name, "class")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _add(f"{node.name}.{sub.name}", "def")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "register") or (
                isinstance(func, ast.Attribute) and func.attr == "register"
            ):
                if node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    _add(node.args[0].value, "register")
                for kw in node.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) \
                            and isinstance(kw.value.value, str):
                        _add(kw.value.value, "register")
            is_button = (
                isinstance(func, ast.Name) and func.id == "InlineKeyboardButton"
            ) or (
                isinstance(func, ast.Attribute)
                and func.attr == "InlineKeyboardButton"
            )
            if is_button:
                for kw in node.keywords:
                    if kw.arg == "callback_data":
                        prefix = _extract_static_prefix(kw.value)
                        if prefix:
                            _add(prefix, "callback")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                for alias in node.names:
                    if alias.name != "*":
                        _add(f"{node.module}.{alias.name}", "import")
    return found


def collect_changed_symbols(py_files: list[str]) -> list[dict]:
    """Parse working-tree copies of changed files (covers uncommitted edits)."""
    symbols: list[dict] = []
    for rel in py_files:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue  # deleted file: nothing to parse
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        symbols.extend(symbols_in_source(source, rel))
        if len(symbols) >= MAX_SYMBOLS:
            break
    return symbols[:MAX_SYMBOLS]


# --------------------------------------------------------------------------
# Wiring delta (keyboard prefixes vs router branches)
# --------------------------------------------------------------------------

def _prefix_matches_handler(prefix: str, handlers: set[str]) -> bool:
    """Mirror of tests/test_wiring.py::_prefix_matches_handler."""
    for handler in handlers:
        if prefix == handler:
            return True
        if handler.endswith(":") and prefix.startswith(handler.rstrip(":")):
            return True
        if handler.endswith(":") and (prefix + ":").startswith(handler):
            return True
        if ":" in prefix and not handler.endswith(":"):
            if prefix.split(":")[0] == handler:
                return True
    return False


def _prefixes_and_handlers_from_sources(
    get_source,
    relpaths: list[str],
) -> tuple[set[str], set[str]]:
    """Collect callback prefixes + router handler patterns from sources.

    ``get_source(relpath)`` returns module text or None; ``relpaths`` are the
    candidate keyboard/router files. Mirrors the test_wiring.py collectors.
    """
    import re

    prefixes: set[str] = set()
    handlers: set[str] = set()
    for rel in relpaths:
        source = get_source(rel)
        if source is None:
            continue
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "register") or (
                isinstance(func, ast.Attribute) and func.attr == "register"
            ):
                if node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    handlers.add(node.args[0].value)
            is_button = (
                isinstance(func, ast.Name) and func.id == "InlineKeyboardButton"
            ) or (
                isinstance(func, ast.Attribute)
                and func.attr == "InlineKeyboardButton"
            )
            if is_button:
                for kw in node.keywords:
                    if kw.arg == "callback_data":
                        prefix = _extract_static_prefix(kw.value)
                        if prefix:
                            prefixes.add(prefix)
        if rel == "bot.py":
            for m in re.finditer(r'data\s*==\s*"([^"]+)"', source):
                handlers.add(m.group(1))
            for m in re.finditer(r"data\s*in\s*\{([^}]+)\}", source):
                for item in re.finditer(r'"([^"]+)"', m.group(1)):
                    handlers.add(item.group(1))
            for m in re.finditer(r'data\.startswith\("([^"]+)"\)', source):
                handlers.add(m.group(1))
    return prefixes, handlers


def _head_keyboard_files() -> list[str]:
    rels: list[str] = []
    for target in ("bot.py", "handlers", "services", "config"):
        path = REPO_ROOT / target
        if path.is_file() and path.suffix == ".py":
            rels.append(target)
        elif path.is_dir():
            if target == "config":
                rels.extend(
                    sorted(
                        str(p.relative_to(REPO_ROOT)).replace("\\", "/")
                        for p in path.rglob("*.py")
                    )
                )
            else:
                rels.extend(
                    sorted(
                        str(p.relative_to(REPO_ROOT)).replace("\\", "/")
                        for p in path.glob("*.py")
                    )
                )
    return rels


def _read_working_tree(rel: str) -> str | None:
    path = REPO_ROOT / rel
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def diff_prefix_sets(
    base: set[str], head: set[str]
) -> tuple[list[str], list[str]]:
    """Return (added, removed) sorted prefix lists for a wiring delta."""
    return sorted(head - base), sorted(base - head)


def compute_wiring_delta(base: str) -> dict:
    """Compare callback prefixes at <base> vs working tree."""
    head_prefixes, head_handlers = _prefixes_and_handlers_from_sources(
        _read_working_tree, _head_keyboard_files()
    )
    base_files = [f for f in _ls_py_at(base)
                  if f == "bot.py" or f.startswith(
                      ("handlers/", "services/", "config/"))]
    base_prefixes, _ = _prefixes_and_handlers_from_sources(
        lambda rel: _show_at(base, rel), base_files
    )
    added, removed = diff_prefix_sets(base_prefixes, head_prefixes)
    orphaned = sorted(
        p for p in head_prefixes
        if not _prefix_matches_handler(p, head_handlers)
    )
    return {
        "added_prefixes": added,
        "removed_prefixes": removed,
        "orphaned": orphaned,
    }


# --------------------------------------------------------------------------
# Dead refs (banned-symbol scan; owner registry stays in the guard test)
# --------------------------------------------------------------------------

def _banned_symbols_from_guard() -> dict[str, str]:
    """Read BANNED_SYMBOLS keys from tests/test_dead_code_guard.py via AST.

    The guard file stays the single source of truth; this helper only reads
    it (no import side effects).
    """
    path = REPO_ROOT / "tests" / "test_dead_code_guard.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "BANNED_SYMBOLS" in targets and isinstance(node.value, ast.Dict):
                banned: dict[str, str] = {}
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        banned[key.value] = ""
                return banned
    return {}


def _symbols_in_tree(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    found.add(alias.asname or alias.name)
    return found


def _iter_production_files() -> list[Path]:
    files: list[Path] = []
    for target in PRODUCTION_SCAN_TARGETS:
        path = REPO_ROOT / target
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
    return files


def compute_dead_refs() -> dict:
    """Return {"hits": {symbol: [files]}} for banned symbols still present."""
    banned = _banned_symbols_from_guard()
    hits: dict[str, list[str]] = {}
    for filepath in _iter_production_files():
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
            continue
        symbols = _symbols_in_tree(tree)
        rel = str(filepath.relative_to(REPO_ROOT)).replace("\\", "/")
        for sym in banned:
            if sym in symbols:
                hits.setdefault(sym, []).append(rel)
    return {"hits": {k: sorted(v) for k, v in sorted(hits.items())}}


# --------------------------------------------------------------------------
# Graphify (bounded, read-only; freshness-gated)
# --------------------------------------------------------------------------

def _graph_path(override: str | None) -> Path:
    if override:
        return Path(override)
    return REPO_ROOT / "graphify-out" / "graph.json"


def _read_built_commit(graph_json: Path) -> str | None:
    try:
        data = json.loads(graph_json.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if isinstance(data, dict):
        built = data.get("built_at_commit")
        if isinstance(built, str) and built.strip():
            return built.strip()
    return None


def run_graph_queries(
    symbols: list[str], graph_json: Path
) -> dict[str, bool]:
    """Run up to MAX_QUERY_COMMANDS read-only queries; return {sym: ok}.

    Only ``query --budget N`` is used here (``explain``/``path`` are the only
    other permitted commands; ``cluster-only``/``affected`` never run).
    Rows are still built from an AST scan (exact file:line); the query run
    only corroborates, recorded in the row's ``via`` field.
    """
    ok: dict[str, bool] = {}
    for sym in symbols[:MAX_QUERY_COMMANDS]:
        _rc, _out, _err = _run(
            ["graphify", "query", f"callers and callees of {sym}",
             "--budget", str(QUERY_BUDGET),
             "--graph", str(graph_json)]
        )
        ok[sym] = _rc == 0
    return ok


def callers_of(symbol: str) -> tuple[list[str], bool]:
    """AST-derived call sites ``path:line`` for *symbol* (exact, HEAD-fresh)."""
    bare = symbol.split(".")[-1]
    callers: list[str] = []
    capped = False
    for filepath in _iter_production_files():
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
            continue
        rel = str(filepath.relative_to(REPO_ROOT)).replace("\\", "/")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            hit = (isinstance(func, ast.Name) and func.id == bare) or (
                isinstance(func, ast.Attribute) and func.attr == bare
            )
            if hit:
                callers.append(f"{rel}:{node.lineno}")
                if len(callers) >= MAX_CALLERS:
                    capped = True
                    break
        if capped:
            break
    return sorted(callers), capped


def callees_of(symbol: str, def_file: str | None) -> list[str]:
    """Names invoked inside *symbol*'s own definition (empty if not found)."""
    if not def_file:
        return []
    path = REPO_ROOT / def_file
    if not path.is_file():
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
        return []
    bare = symbol.split(".")[-1]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == bare:
            called: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    if isinstance(func, ast.Name):
                        called.add(func.id)
                    elif isinstance(func, ast.Attribute):
                        called.add(func.attr)
            called.discard(bare)
            return sorted(called)[:MAX_CALLEES]
    return []


def build_blast_radius(
    symbols: list[dict], query_ok: dict[str, bool], queried: bool
) -> tuple[list[dict], bool]:
    """Build blast-radius rows for def/class symbols; report truncation."""
    rows: list[dict] = []
    truncated = False
    targets = [s for s in symbols if s["kind"] in ("def", "class")]
    if len(targets) > MAX_QUERY_COMMANDS:
        truncated = True
    for sym in targets:
        name = sym["name"]
        callers, callers_capped = callers_of(name)
        if callers_capped:
            truncated = True
        if name in query_ok:
            via = "query+ast" if query_ok[name] else "ast-scan (query failed)"
        elif queried:
            via = "ast-scan (over query cap)"
        else:
            via = "ast-scan (no graph)"
        rows.append({
            "symbol": name,
            "callers": callers,
            "callees": callees_of(name, sym.get("file")),
            "via": via,
        })
    return rows, truncated


# --------------------------------------------------------------------------
# Edge probes (REV-4): hostile inputs, crashes recorded as data
# --------------------------------------------------------------------------

def _module_for_relpath(rel: str) -> str | None:
    if not rel.endswith(".py"):
        return None
    mod = rel[:-3].replace("/", ".").replace("\\", ".")
    if mod.endswith(".__init__"):
        mod = mod[: -len(".__init__")]
    if not mod or mod.startswith("."):
        return None
    return mod


def _probe_argsets(fn) -> list[tuple[tuple, dict]]:
    """Argument sets: bare call (if allowed) + each hostile filling required."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return []
    params = list(sig.parameters.values())
    argsets: list[tuple[tuple, dict]] = []
    seen: set[str] = set()

    def _push(args_t: tuple, kwargs_d: dict) -> None:
        # Zero-param functions would otherwise emit one bare row plus five
        # identical bare rows (one per hostile); collapse exact duplicates.
        key = repr((args_t, sorted(kwargs_d.items())))
        if key not in seen:
            seen.add(key)
            argsets.append((args_t, kwargs_d))

    has_required = any(
        p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                       inspect.Parameter.POSITIONAL_OR_KEYWORD,
                       inspect.Parameter.KEYWORD_ONLY)
        for p in params
    )
    if not has_required:
        _push((), {})
    for hostile in _HOSTILES:
        args: list = []
        kwargs: dict = {}
        for p in params:
            if p.kind == inspect.Parameter.VAR_POSITIONAL:
                continue
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                continue
            if p.default is inspect.Parameter.empty:
                if p.kind == inspect.Parameter.KEYWORD_ONLY:
                    kwargs[p.name] = hostile
                else:
                    args.append(hostile)
        if not args and not kwargs and any(
            p.kind
            in (inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL)
            for p in params
        ):
            # All-optional signature (e.g. f(opts=None)): the falsy-vs-None
            # class of bugs only shows when the hostile is actually passed,
            # so fill the first positional slot explicitly.
            args.append(hostile)
        _push(tuple(args), kwargs)
        if len(argsets) >= 6:
            break
    return argsets


def _fmt_input(name: str, args: tuple, kwargs: dict) -> str:
    parts = [repr(a) for a in args]
    parts.extend(f"{k}={v!r}" for k, v in kwargs.items())
    return f"{name}({', '.join(parts)})"


def _is_allowlisted_probe_module(mod: str) -> bool:
    """True if *mod* is known-pure (no Telegram/DB/network side effects)."""
    if mod in SAFE_MODULE_EXACT or mod.startswith(SAFE_MODULE_PREFIXES):
        return True
    if mod.startswith(SAFE_TEST_PREFIXES):
        return True
    if "." not in mod and mod.startswith(SAFE_BARE_PREFIXES):
        return True
    return False


def is_risky_module(mod: str) -> bool:
    """True if *mod* must be skipped by edge probes unless --allow-risky.

    Allowlist semantics (R6): only known-pure modules probe by default --
    services/utils.*, services.fsrs_core, services.scheduling,
    services/session.*, config catalog modules, and tests-local/synthetic
    helpers. Everything else (handlers/, services/db/, services/ai/,
    bot.py, scripts/, ...) is skipped.
    """
    return not _is_allowlisted_probe_module(mod)


def _invoke_once(fn, args: tuple, kwargs: dict):
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return result


# Credential redaction (W4): probe outputs persist into review-context.json,
# so anything shaped like a credential is replaced before persisting.
REDACTED_PROBE_OUTPUT = "[redacted: possible credential]"
_SENSITIVE_NAME_TOKENS = frozenset({
    "key", "keys", "token", "tokens", "secret", "secrets",
    "passwd", "password", "auth",
})
_CRED_SHAPE_PATTERNS = (
    re.compile(r"sk-"),
    re.compile(r"ghp_"),
    re.compile(r"AIza"),
    re.compile(r"xox-"),
    # Long opaque hex/base64 blobs (>= 32 chars): API keys, digests-as-keys.
    re.compile(r"[A-Za-z0-9_+\-/=]{32,}"),
)


def _looks_like_credential(fn, text: str) -> bool:
    """True if the probed function or its output text looks credential-ish."""
    hay = f"{getattr(fn, '__module__', '') or ''} " \
          f"{getattr(fn, '__name__', '') or ''}".lower()
    if any(tok in _SENSITIVE_NAME_TOKENS
           for tok in re.split(r"[^a-z0-9]+", hay)):
        return True
    return any(pat.search(text) for pat in _CRED_SHAPE_PATTERNS)


class _DaemonThreadPool(concurrent.futures.ThreadPoolExecutor):
    """ThreadPoolExecutor whose workers are daemon threads (W1).

    Mirrors the installed ThreadPoolExecutor._adjust_thread_count except
    workers are created daemonized, so a hung probe never blocks
    interpreter exit. The pool is managed explicitly (no ``with`` block):
    on timeout the caller runs ``shutdown(wait=False,
    cancel_futures=True)`` instead of the blocking ``wait=True`` exit.
    """

    def _adjust_thread_count(self) -> None:
        import threading
        import weakref

        from concurrent.futures.thread import _worker, _threads_queues

        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = "%s_%d" % (self._thread_name_prefix or self,
                                     num_threads)
            t = threading.Thread(
                name=thread_name,
                target=_worker,
                args=(
                    weakref.ref(self, weakref_cb),
                    self._work_queue,
                    self._initializer,
                    self._initargs,
                ),
                daemon=True,
            )
            t.start()
            self._threads.add(t)
            _threads_queues[t] = self._work_queue


def probe_call(
    fn, args: tuple, kwargs: dict, timeout: float = PROBE_TIMEOUT_SEC
) -> str:
    """Call once with a per-call timeout; crashes/timeouts are data."""
    pool = _DaemonThreadPool(max_workers=1, thread_name_prefix="rbr-probe")
    try:
        future = pool.submit(_invoke_once, fn, args, kwargs)
        try:
            result = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            return f"timeout: exceeded {timeout:g}s"
        except BaseException as exc:  # noqa: BLE001 -- probe must not raise
            pool.shutdown(wait=True)  # task finished; worker idle, no block
            text = f"{type(exc).__name__}: {str(exc)}"
            if _looks_like_credential(fn, str(exc)):
                text = REDACTED_PROBE_OUTPUT
            return f"raise: {text[:PROBE_OUTPUT_LEN]}"
        else:
            pool.shutdown(wait=True)  # task finished; worker idle, no block
            raw = repr(result)
            if _looks_like_credential(fn, raw):
                return f"return: {REDACTED_PROBE_OUTPUT}"
            return f"return: {raw[:PROBE_OUTPUT_LEN]}"
    except BaseException as exc:  # noqa: BLE001 -- probe must not raise
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        return f"raise: {type(exc).__name__}: {str(exc)[:PROBE_OUTPUT_LEN]}"


def probe_function(
    dotted: str, fn, timeout: float = PROBE_TIMEOUT_SEC
) -> list[dict]:
    """Probe one function with hostile inputs; return edge_probe rows."""
    name = getattr(fn, "__name__", str(fn))
    rows: list[dict] = []
    for args, kwargs in _probe_argsets(fn):
        rows.append({
            "function": f"{dotted}.{name}",
            "input": _fmt_input(name, args, kwargs),
            "output": probe_call(fn, args, kwargs, timeout=timeout),
        })
    return rows


def run_edge_probes(
    symbols: list[dict],
    allow_risky: bool = False,
    timeout: float = PROBE_TIMEOUT_SEC,
) -> tuple[list[dict], bool]:
    """Import touched modules, probe changed functions; return (rows, trunc).

    Only allowlisted known-pure modules probe by default; every other
    module is skipped unless *allow_risky* is True. Every skip is recorded
    as a data row (never silent). Each probe call is bounded by *timeout*
    seconds.
    """
    if REPO_ROOT.as_posix() not in sys.path:
        sys.path.insert(0, REPO_ROOT.as_posix())
    import importlib

    rows: list[dict] = []
    truncated = False
    probed = 0
    by_module: dict[str, list[str]] = {}
    for sym in symbols:
        if sym["kind"] != "def" or "." in sym["name"]:
            continue  # methods need a receiver; classes need constructors
        mod = _module_for_relpath(sym["file"])
        if mod is None:
            continue
        by_module.setdefault(mod, []).append(sym["name"])
    for mod, names in sorted(by_module.items()):
        if probed >= MAX_PROBE_FUNCTIONS:
            truncated = True
            break
        if is_risky_module(mod) and not allow_risky:
            rows.append({
                "function": mod,
                "input": "skipped: risky-module",
                "output": "skipped: risky module "
                          f"({mod}) requires --allow-risky",
            })
            continue
        try:
            module = importlib.import_module(mod)
        except BaseException as exc:  # noqa: BLE001 -- recorded as data
            rows.append({
                "function": mod,
                "input": "import",
                "output": f"import-failed: {type(exc).__name__}: "
                          f"{str(exc)[:PROBE_OUTPUT_LEN]}",
            })
            continue
        for name in names:
            if probed >= MAX_PROBE_FUNCTIONS:
                truncated = True
                break
            fn = getattr(module, name, None)
            if not callable(fn) or inspect.isclass(fn):
                continue
            probed += 1
            rows.extend(probe_function(mod, fn, timeout=timeout))
    return rows, truncated


# --------------------------------------------------------------------------
# Assembly + CLI
# --------------------------------------------------------------------------

def build_context(
    base: str,
    graph_json: Path,
    run_update: bool,
    run_probes: bool,
    run_graph: bool,
    allow_risky: bool = False,
    probe_timeout: float = PROBE_TIMEOUT_SEC,
    graph_explicit: bool = False,
) -> tuple[dict, str | None, int]:
    """Assemble the review context.

    Returns (context, stderr_note, exit_code). Exit 2 means stale graph.
    """
    head_sha = _head_sha() or "unknown"
    diff_error: str | None = None
    py_files, diff_error = _diff_py_files(base)
    changed_symbols = collect_changed_symbols(py_files)

    wiring_delta = compute_wiring_delta(base)
    dead_refs = compute_dead_refs()
    edge_probes: list[dict] = []
    probes_truncated = False
    if run_probes:
        edge_probes, probes_truncated = run_edge_probes(
            changed_symbols, allow_risky=allow_risky, timeout=probe_timeout
        )

    graph_built: str | None = None
    fresh = False
    note: str | None = diff_error
    blast_radius: list[dict] = []
    radius_truncated = False
    queried = False

    if run_graph and not graph_explicit \
            and shutil.which("graphify") is None:
        note = ((note + "; " if note else "")
                + "graphify not found: blast_radius from AST scan only")
        blast_radius, radius_truncated = build_blast_radius(
            changed_symbols, {}, False
        )
    elif run_graph:
        if run_update:
            rc, _out, err = _run(["graphify", "update", "."])
            if rc != 0:
                note = ((note + "; " if note else "")
                        + f"graphify update failed: {err.strip()[:200]}")
        if graph_json.is_file():
            graph_built = _read_built_commit(graph_json)
            fresh = isinstance(graph_built, str) and graph_built == head_sha
            if graph_built is None:
                note = ((note + "; " if note else "")
                        + "graph.json has no built_at_commit")
        else:
            note = ((note + "; " if note else "")
                    + "graph.json absent: blast_radius from AST scan only")
        if graph_built is not None and not fresh:
            query_ok: dict[str, bool] = {}
        else:
            def_names = [s["name"] for s in changed_symbols
                         if s["kind"] in ("def", "class")]
            query_ok = run_graph_queries(def_names, graph_json) if fresh else {}
            queried = bool(query_ok)
        blast_radius, radius_truncated = build_blast_radius(
            changed_symbols, query_ok if fresh else {}, queried
        )
    else:
        blast_radius, radius_truncated = build_blast_radius(
            changed_symbols, {}, False
        )

    truncated = probes_truncated or radius_truncated \
        or len(changed_symbols) >= MAX_SYMBOLS

    context = {
        "base": base,
        "head_sha": head_sha,
        "built_at_commit": graph_built,
        "fresh": fresh,
        "changed_symbols": changed_symbols,
        "blast_radius": blast_radius,
        "wiring_delta": wiring_delta,
        "dead_refs": dead_refs,
        "edge_probes": edge_probes,
        "truncated": truncated,
    }

    exit_code = 0
    if run_graph and graph_built is not None and not fresh:
        note = ((note + "; " if note else "")
                + "stale graph: re-run `graphify update .`")
        exit_code = 2
    return context, note, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Producer-side blast-radius + edge-probe helper. "
                    "Emits gitignored review-context.json."
    )
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--out", default="review-context.json")
    parser.add_argument("--graph", default=None,
                        help="override path to graph.json")
    parser.add_argument("--no-update", action="store_true",
                        help="skip `graphify update .`, read existing graph")
    parser.add_argument("--no-graph", action="store_true",
                        help="skip graphify entirely (AST scan only)")
    parser.add_argument("--no-probes", action="store_true",
                        help="skip hostile-input edge probes")
    parser.add_argument("--allow-risky", action="store_true",
                         help="probe non-allowlisted modules (handlers/, "
                              "services/db/, services/ai/, bot.py, ...)")
    parser.add_argument("--probe-timeout", type=float, default=PROBE_TIMEOUT_SEC,
                        help="per-probe-call timeout in seconds")
    args = parser.parse_args(argv)

    context, note, exit_code = build_context(
        base=args.base,
        graph_json=_graph_path(args.graph),
        run_update=not args.no_update,
        run_probes=not args.no_probes,
        run_graph=not args.no_graph,
        allow_risky=args.allow_risky,
        probe_timeout=args.probe_timeout,
        graph_explicit=args.graph is not None,
    )
    out_path = Path(args.out)
    out_path.write_text(json.dumps(context, indent=2), encoding="utf-8")
    summary = (
        f"wrote {out_path} fresh={context['fresh']} "
        f"symbols={len(context['changed_symbols'])} "
        f"rows={len(context['blast_radius'])} "
        f"probes={len(context['edge_probes'])}"
    )
    if note:
        summary += f" note={note}"
    print(summary)
    if exit_code == 2:
        print("stale graph: re-run `graphify update .`", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
