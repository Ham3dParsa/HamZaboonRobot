"""String-shape tests for the factory home WebUI console control script.

Behavior spec (tidy colored output): every invocation prints a compact
``-- console :<port> --`` header, exactly one ``state`` line (RUNNING /
STALE / STOPPED / FOREIGN-PORT-HELD), a ``bind`` line, and one probed
link line per bound address (tablet plus local when bound to all
interfaces). A quiet one-line ``hint:`` appears on bare invocations
and error paths only — never after a clean status/start/stop. STOP
safety is pid-file-only: ``Stop-Process -Id`` over the recorded pid,
never a blanket name/image kill. No I/O, no sockets, no spawned
processes — pure text assertions over the ps1.
"""

import os
import re
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

CTL_PATH = os.path.join(PROJECT_ROOT, "factory", "webui", "server_ctl.ps1")
SHIM_PATH = os.path.join(PROJECT_ROOT, "factory", "linking", "webui",
                         "server_ctl.ps1")


def _text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _body(text, name):
    """Source of ``function <name>`` only (up to the next function def)."""
    match = re.search(r"(?ms)^function\s+%s\b(.*?)(?=^function\s+|\Z)"
                      % re.escape(name), text)
    assert match is not None, "missing function " + name
    return match.group(1)


def _code(text):
    """Executable code only: block-comment prose may name the ban."""
    return re.sub(r"(?ms)<#.*?#>", "", text)


def test_ctl_status_line_shape():
    text = _text(CTL_PATH)
    status_body = _body(text, "Show-Status")
    # One state literal per branch (RUNNING / STALE / STOPPED /
    # FOREIGN-PORT-HELD); only one branch ever executes, so every
    # Show-Status call prints exactly one state line. STOPPED must
    # never print alongside an open port — the no-pidfile branch
    # splits into STOPPED (port closed) vs FOREIGN-PORT-HELD (open).
    for state in ("RUNNING", "STALE", "STOPPED", "FOREIGN-PORT-HELD"):
        assert status_body.count("state   " + state) == 1, state
    assert status_body.count('"  state') == 4
    # Header plus bind line on every status.
    assert status_body.count('"-- console :') == 1
    assert status_body.count('"  bind') == 1
    # Stop paths each print exactly one probed port line (open/closed
    # variants = 3 paths x 2).
    stop_body = _body(text, "Stop-Server")
    assert stop_body.count('"  port') == 6
    # Start paths never print a raw state line; they route through
    # Show-Status (already-running + success = 2 calls).
    start_body = _body(text, "Start-Server")
    assert start_body.count('"  state') == 0
    assert start_body.count("Show-Status") == 2


def test_ctl_per_address_url_lines():
    text = _text(CTL_PATH)
    links_body = _body(text, "Show-Links")
    # All-interfaces bind prints exactly two link lines (tablet + local),
    # each with an open/closed probe variant; an explicit bind prints
    # exactly that address (one link line, open/closed variants).
    assert links_body.count('"  tablet  http://') == 2
    assert links_body.count('"  local   http://127.0.0.1:') == 2
    assert links_body.count('"  open    http://') == 2
    # Each printed address carries its own live port probe.
    assert links_body.count("Test-PortOpen") >= 3
    # Probing an all-interfaces bind targets loopback (0.0.0.0 is not
    # connectable); one shared helper owns that mapping and every
    # probing call site uses it.
    assert "function Get-ProbeHost" in text
    assert "Get-ProbeHost" in _body(text, "Get-Status")
    assert "Get-ProbeHost" in _body(text, "Start-Server")
    assert "Get-ProbeHost" in _body(text, "Stop-Server")
    # The shim forwards the bind override as-is (no second registry).
    shim = _text(SHIM_PATH)
    assert "-BindHost $BindHost" in shim


def test_ctl_hint_line_quiet_paths():
    text = _text(CTL_PATH)
    # Exactly one hint-line shape.
    assert text.count('"hint:') == 1
    # Error paths carry the hint: start has 3 (refused, missing,
    # early-exit), stop has 2 (no-pid, stale), usage has 1.
    assert _body(text, "Start-Server").count("Show-Hint") == 3
    assert _body(text, "Stop-Server").count("Show-Hint") == 2
    assert "Show-Hint" in _body(text, "Show-Usage")
    # The dispatch tail covers the bare path (status + hint); the
    # unknown-action path routes through usage.
    tail = text.split("switch ($NormalizedAction)", 1)[1]
    assert "Show-Hint" in tail
    # Clean paths print no hint: status action, start success, stop
    # success. The status dispatch arm is hint-free.
    status_arm = re.search(r'(?m)^\s*"status"\s*\{(.*?)\}', tail).group(1)
    assert "Show-Hint" not in status_arm


def test_ctl_pid_only_safety():
    text = _text(CTL_PATH)
    code = _code(text)
    # The only signal allowed: the exact pid recorded in the pid file.
    assert "Stop-Process -Id $pidVal" in code
    assert code.count("Stop-Process") == 1
    # No blanket kills anywhere in either control-script copy.
    for path in (CTL_PATH, SHIM_PATH):
        body = _code(_text(path))
        assert "Stop-Process -Name" not in body, path
        assert "taskkill /IM" not in body, path
        assert "pkill" not in body, path
        assert "Get-Process -Name" not in body, path


def test_ctl_usage_names_lan_exposure_and_loopback_escape():
    text = _text(CTL_PATH)
    usage = _body(text, "Show-Usage")
    assert "LAN-visible" in usage
    assert "operator-only" in usage
    assert "no auth" in usage
    assert "-BindHost 127.0.0.1" in usage
