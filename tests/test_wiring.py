import ast
import re
import unittest
from pathlib import Path


ALLOWLIST = {"srs:"}

# Directories to scan for InlineKeyboardButton callback_data
SCAN_DIRS = [Path("."), Path("handlers"), Path("config")]

# Production modules whose imported symbols must resolve to real definitions.
# Used by the reverse-direction checks: a leftover import/route to a deleted
# handler must fail CI instead of surfacing at runtime.
PRODUCTION_SOURCES = [
    Path("bot.py"),
    Path("handlers"),
    Path("services"),
    Path("config"),
]


def _production_py_files():
    """Yield every production .py file (bot.py + handlers/services/config)."""
    for target in PRODUCTION_SOURCES:
        if target.is_file():
            yield target
        elif target.is_dir():
            yield from sorted(target.rglob("*.py"))


def _defined_names(tree: ast.AST) -> set[str]:
    """Names defined at module level in a parsed AST."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                names.add(local)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _resolve_import(tree: ast.AST, name: str) -> str | None:
    """Return the module path that *name* is imported from, or None.

    Only resolves project-internal modules (handlers.*, services.*, config.*,
    bot). External packages (telegram, stdlib) are trusted and skipped.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            if not (
                node.module.startswith("handlers.")
                or node.module.startswith("services.")
                or node.module.startswith("config.")
                or node.module == "config"
                or node.module in ("handlers", "services")
            ):
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                if local == name:
                    return node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                if local == name:
                    # import services.db -> module services.db (top package)
                    return alias.name.split(".")[0]
    return None


def _module_path(module: str) -> Path | None:
    """Resolve a dotted module name to its .py file (module.py or
    module/__init__.py), or None if the module does not exist on disk."""
    rel = module.replace(".", "/")
    candidates = [Path(rel + ".py"), Path(rel) / "__init__.py"]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _is_project_internal(module: str) -> bool:
    """True if *module* is inside the project's production packages."""
    return (
        module in ("handlers", "services", "config", "bot")
        or module.startswith("handlers.")
        or module.startswith("services.")
        or module.startswith("config.")
    )


def _module_has_symbol(module: str, symbol: str) -> bool:
    """Check that *symbol* is importable from a project-internal *module*.

    Resolves the module to its file (module.py or module/__init__.py) and
    scans its module-level definitions, including its own re-exports and
    submodules. External (stdlib/third-party) imports are trusted.
    """
    # A submodule of this module (e.g. `from services.ai import ai` where
    # services/ai/ai.py exists) always resolves.
    if _module_path(f"{module}.{symbol}") is not None:
        return True

    target = _module_path(module)
    if target is None:
        # The module no longer exists on disk: a leftover import from a
        # deleted module (e.g. `from services.srs_engine import X`) is broken.
        return False

    try:
        tree = ast.parse(target.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return True

    defined = _defined_names(tree)
    if symbol in defined:
        return True

    # Symbol may be re-exported: search this module's own imports. Only
    # recurse into project-internal modules; external re-exports are trusted.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            for alias in node.names:
                if (alias.asname or alias.name) == symbol:
                    if _is_project_internal(node.module):
                        return _module_has_symbol(node.module, alias.name)
                    return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.asname or alias.name.split(".")[0]) == symbol:
                    # `import os` etc. re-exported from a trusted module.
                    return True
    return False


def _unresolved_imports() -> dict[str, list[str]]:
    """Return {module: [symbols]} for imports that cannot resolve.

    Only project-internal imports are checked; external packages are trusted.
    For `from M import X as Y`, the real symbol X is what must exist in M.
    """
    broken: dict[str, list[str]] = {}
    for filepath in _production_py_files():
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not node.module:
                continue
            if not (
                node.module.startswith("handlers.")
                or node.module.startswith("services.")
                or node.module.startswith("config.")
                or node.module in ("config", "handlers", "services")
            ):
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if not _module_has_symbol(node.module, alias.name):
                    broken.setdefault(node.module, []).append(alias.name)
    return broken


def _router_call_targets_in_tree(tree: ast.AST) -> set[str]:
    """Collect every module-level function name invoked inside a
    callback_router function in a parsed AST."""
    import builtins

    targets: set[str] = set()
    builtin_names = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != "callback_router":
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                if isinstance(sub.func, ast.Name) and sub.func.id not in builtin_names:
                    targets.add(sub.func.id)
    return targets


def _collect_router_call_targets() -> set[str]:
    """Collect every module-level function name invoked inside callback_router."""
    tree = ast.parse(Path("bot.py").read_text(encoding="utf-8"))
    return _router_call_targets_in_tree(tree)


def _unresolved_router_targets(
    tree: ast.AST, local_defs: set[str], targets: set[str]
) -> list[str]:
    """Return descriptions of router call targets that do not resolve.

    A target resolves if it is defined in the module, or imported from a
    project-internal module that still has the symbol. Private helpers must
    be defined in the module itself.
    """
    unresolved: list[str] = []
    for target in sorted(targets):
        if target.startswith("_"):
            # Private helpers should be defined in bot.py itself.
            if target not in local_defs:
                unresolved.append(f"{target} (private, not defined in bot.py)")
            continue
        if target in local_defs:
            continue
        module = _resolve_import(tree, target)
        if module is None:
            unresolved.append(f"{target} (not defined and not imported)")
        elif not _module_has_symbol(module, target):
            unresolved.append(f"{target} (imported from {module}, not found)")
    return unresolved


def _extract_static_prefix(node: ast.AST) -> str | None:
    """Extract the longest static prefix from a callback_data AST node.

    Handles:
    - Constant strings:  ``callback_data="admin:foo:bar"``
    - JoinedStr (f-strings): ``callback_data=f"admin:foo:{var}"``
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        raw = node.value
        static = raw.split("{")[0].rstrip(":")
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


def _collect_all_callback_prefixes() -> set[str]:
    """Scan all project Python files with AST for InlineKeyboardButton callback_data.

    Searches bot.py, handlers/*.py, and config/*.py for every
    ``InlineKeyboardButton(..., callback_data=...)`` call and extracts the
    longest static prefix from each callback_data value.
    """
    prefixes: set[str] = set()
    source_files: list[Path] = []
    for d in SCAN_DIRS:
        if d.is_dir():
            source_files.extend(sorted(d.glob("*.py")))
        elif d.is_file():
            source_files.append(d)

    for filepath in source_files:
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Match InlineKeyboardButton(...) — both direct name and qualified (telegram.InlineKeyboardButton)
            is_button = False
            if isinstance(func, ast.Name) and func.id == "InlineKeyboardButton":
                is_button = True
            elif isinstance(func, ast.Attribute) and func.attr == "InlineKeyboardButton":
                is_button = True
            if not is_button:
                continue

            for kw in node.keywords:
                if kw.arg == "callback_data":
                    prefix = _extract_static_prefix(kw.value)
                    if prefix:
                        prefixes.add(prefix)

    return prefixes


def _collect_router_handlers() -> set[str]:
    """Extract callback handler patterns from bot.py callback_router."""
    handlers: set[str] = set()
    with open("bot.py", encoding="utf-8") as f:
        lines = f.readlines()

    in_router = False
    router_lines: list[str] = []
    for line in lines:
        stripped = line.rstrip()
        if stripped.startswith("async def callback_router"):
            in_router = True
            continue
        if in_router:
            if stripped.startswith("async def "):
                break
            if stripped.startswith("def ") and not stripped.startswith("def "):
                continue
            router_lines.append(stripped)

    text = "\n".join(router_lines)

    for match in re.finditer(r'data\s*==\s*"([^"]+)"', text):
        handlers.add(match.group(1))

    for match in re.finditer(r"data\s*in\s*\{([^}]+)\}", text):
        body = match.group(1)
        for item in re.finditer(r'"([^"]+)"', body):
            handlers.add(item.group(1))

    for match in re.finditer(r'data\.startswith\("([^"]+)"\)', text):
        handlers.add(match.group(1))

    return handlers


def _collect_admin_sub_actions() -> set[str]:
    """Extract action patterns from _handle_admin_callback in handlers/admin.py.

    Returns action strings from ``action == "..."`` and
    ``action.startswith("...")`` comparisons.
    """
    actions: set[str] = set()
    with open("handlers/admin.py", encoding="utf-8") as f:
        lines = f.readlines()

    in_func = False
    for i, line in enumerate(lines):
        if "async def _handle_admin_callback" in line:
            in_func = True
            continue
        if in_func:
            stripped = line.strip()
            if stripped.startswith("async def "):
                break
            m = re.search(r'action\s*==\s*"([^"]+)"', stripped)
            if m:
                actions.add(m.group(1))
            m = re.search(r'action\.startswith\("([^"]+)"\)', stripped)
            if m:
                actions.add(m.group(1))

    return actions


def _prefix_matches_handler(prefix: str, handlers: set[str]) -> bool:
    """Check whether *prefix* is covered by at least one router *handlers* entry."""
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


def _is_allowed(prefix: str) -> bool:
    for allowed in ALLOWLIST:
        if prefix.startswith(allowed) or allowed.startswith(prefix):
            return True
    return False


class TestCallbackWiring(unittest.TestCase):
    """Verifies that every InlineKeyboardButton callback_data string built
    anywhere in the project has a matching dispatch branch in the callback
    router (and in sub-routers where applicable)."""

    def test_all_callback_prefixes_are_routed(self):
        """Every callback_data prefix from all project files must have a
        matching ``data == ...``, ``data.startswith(...)``, or
        ``data in {...}`` branch in ``callback_router``."""
        prefixes = _collect_all_callback_prefixes()
        handlers = _collect_router_handlers()

        orphaned = []
        for prefix in sorted(prefixes):
            if _is_allowed(prefix):
                continue
            if not _prefix_matches_handler(prefix, handlers):
                orphaned.append(prefix)

        if orphaned:
            msg = "Unrouted callback prefixes (no matching branch in callback_router):\n"
            for o in orphaned:
                msg += f"  {o}\n"
            self.fail(msg)

    def test_admin_sub_router_has_all_actions(self):
        """Every ``admin:``-prefixed callback prefix must have a matching
        ``action == ...`` or ``action.startswith(...)`` branch in
        ``_handle_admin_callback``."""
        all_prefixes = _collect_all_callback_prefixes()
        actions = _collect_admin_sub_actions()

        orphaned = []
        for prefix in sorted(all_prefixes):
            if not prefix.startswith("admin:"):
                continue
            # Strip "admin:" to get the sub-action
            sub = prefix[len("admin:"):]
            if not _prefix_matches_handler(sub, actions):
                orphaned.append(prefix)

        if orphaned:
            msg = (
                "admin:-prefixed callbacks with no matching branch "
                "in _handle_admin_callback:\n"
            )
            for o in orphaned:
                msg += f"  {o}\n"
            self.fail(msg)

    def test_allowlist_prefixes_exist_in_keyboards(self):
        with open("config/keyboards.py", encoding="utf-8") as f:
            kbd_text = f.read()
        for allowed in ALLOWLIST:
            if allowed not in kbd_text:
                self.fail(
                    f"ALLOWLIST prefix '{allowed}' not found in keyboards.py"
                )

    def test_router_catches_at_least_one_prefix(self):
        handlers = _collect_router_handlers()
        self.assertGreater(
            len(handlers), 5, "Router seems empty or not parsed correctly"
        )

    # ------------------------------------------------------------------
    # Reverse direction: routes and imports must resolve to real symbols.
    # ------------------------------------------------------------------

    def test_router_call_targets_resolve(self):
        """Every function name invoked inside callback_router must be either
        defined in bot.py or imported from a resolvable project module."""
        tree = ast.parse(Path("bot.py").read_text(encoding="utf-8"))
        unresolved = _unresolved_router_targets(
            tree, _defined_names(tree), _collect_router_call_targets()
        )

        if unresolved:
            msg = "callback_router calls targets that do not resolve:\n"
            for u in unresolved:
                msg += f"  {u}\n"
            self.fail(msg)

    def test_all_production_imports_resolve(self):
        """Every project-internal `from X import Y` in production code must
        resolve to an existing symbol (including re-exports). A leftover import
        of a deleted handler/symbol fails CI instead of crashing at runtime."""
        broken = _unresolved_imports()
        if broken:
            msg = "Unresolved production imports:\n"
            for module, symbols in sorted(broken.items()):
                for s in sorted(symbols):
                    msg += f"  from {module} import {s}\n"
            self.fail(msg)

    def test_reverse_wiring_detects_deleted_handler(self):
        """Regression: the reverse-direction check must actually catch the
        failure it exists to prevent, using the real helpers.

        (a) A router call to a handler that no longer exists and was never
            imported must be flagged by _unresolved_router_targets.
        (b) An import from a module that no longer exists must be flagged by
            _module_has_symbol / _unresolved_imports.
        (c) Resolvable imports must not be flagged.
        """
        source = (
            "from handlers.study_handler import handle_study_start\n"
            "from config import _user_presentation\n"
            "\n"
            "async def callback_router(data):\n"
            "    if data.startswith('study:'):\n"
            "        return await handle_study_start()\n"
            "    if data.startswith('srs:'):\n"
            "        return await _deleted_private_helper()\n"
            "    if data.startswith('old:'):\n"
            "        return await advance_word_review()\n"
            "    return await _user_presentation()\n"
        )
        tree = ast.parse(source)
        targets = _router_call_targets_in_tree(tree)

        # advance_word_review is called but not imported -> must be flagged.
        self.assertIn("advance_word_review", targets)
        # A deleted private helper (not defined, not imported) -> must be flagged.
        self.assertIn("_deleted_private_helper", targets)
        unresolved = _unresolved_router_targets(
            tree, _defined_names(tree), targets
        )
        self.assertTrue(
            any("advance_word_review" in u for u in unresolved),
            f"deleted-handler call was not flagged: {unresolved}",
        )
        self.assertTrue(
            any("_deleted_private_helper" in u for u in unresolved),
            f"deleted private helper was not flagged: {unresolved}",
        )
        # Imported, resolvable handlers must not be flagged.
        self.assertTrue(
            all("handle_study_start" not in u for u in unresolved),
            f"resolvable handler was wrongly flagged: {unresolved}",
        )
        self.assertTrue(
            all("_user_presentation" not in u for u in unresolved),
            f"resolvable config helper was wrongly flagged: {unresolved}",
        )

        # (b) import from a deleted module must not resolve.
        self.assertFalse(
            _module_has_symbol("services.srs_engine", "advance_word_review"),
            "import from a deleted module resolved",
        )
        # (c) import from an existing module resolves.
        self.assertTrue(
            _module_has_symbol("handlers.study_handler", "handle_study_start"),
            "resolvable import was rejected",
        )
