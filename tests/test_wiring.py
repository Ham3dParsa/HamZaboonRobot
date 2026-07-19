import re
import unittest


ALLOWLIST = {"srs:"}


def _collect_keyboard_prefixes():
    """Extract callback data prefixes from keyboards.py.

    Handles both static strings and f-strings, extracting the longest
    static prefix before the first runtime variable ({...}).
    """
    prefixes = set()
    with open("keyboards.py", encoding="utf-8") as f:
        text = f.read()

    for match in re.finditer(
        r'callback_data\s*=\s*(?:f?)["\']([^"\']+)["\']', text
    ):
        raw = match.group(1)
        static = raw.split("{")[0].rstrip(":")
        if static and ":" in static:
            prefixes.add(static)
        elif static and re.match(r"^[a-z][a-z_]+$", static):
            prefixes.add(static)

    return prefixes


def _collect_router_handlers():
    """Extract callback handler patterns from bot.py callback_router."""
    handlers = set()
    with open("bot.py", encoding="utf-8") as f:
        lines = f.readlines()

    in_router = False
    router_lines = []
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


def _prefix_matches_handler(prefix, handlers):
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


def _is_allowed(prefix):
    for allowed in ALLOWLIST:
        if prefix.startswith(allowed) or allowed.startswith(prefix):
            return True
    return False


class TestCallbackWiring(unittest.TestCase):
    def test_all_keyboard_callbacks_are_routed(self):
        prefixes = _collect_keyboard_prefixes()
        handlers = _collect_router_handlers()

        orphaned = []
        for prefix in sorted(prefixes):
            if _is_allowed(prefix):
                continue
            if not _prefix_matches_handler(prefix, handlers):
                orphaned.append(prefix)

        if orphaned:
            msg = "Unrouted callback prefixes:\n"
            for o in orphaned:
                msg += f"  {o}\n"
            self.fail(msg)

    def test_allowlist_prefixes_exist_in_keyboards(self):
        with open("keyboards.py", encoding="utf-8") as f:
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
