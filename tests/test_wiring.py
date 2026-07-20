import ast
import re
import unittest
from pathlib import Path


ALLOWLIST = {"srs:"}

# Directories to scan for InlineKeyboardButton callback_data
SCAN_DIRS = [Path("."), Path("handlers"), Path("config")]


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
