"""String-shape tests for the factory home WebUI console control script.

Behavior spec (T2 tidy output): every invocation prints exactly one
``status:`` line, one ``open:`` URL line per bound address (loopback plus
LAN when bound to all interfaces, each with its own live port probe),
and exactly one ``example:`` line on every path. STOP safety is
pid-file-only: ``Stop-Process -Id`` over the recorded pid, never a
blanket name/image kill. No I/O, no sockets, no spawned processes —
pure text assertions over the ps1, same style as the interface tests.
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
    # One status literal per branch (RUNNING / STALE / STOPPED); only
    # one branch ever executes, so every Show-Status call prints
    # exactly one status line.
    for state in ("status: RUNNING", "status: STALE", "status: STOPPED"):
        assert text.count('"%s' % state) == 1, state
    assert status_body.count('"status:') == 3
    # Stop paths each print exactly one status line (port_open probe).
    stop_body = _body(text, "Stop-Server")
    assert stop_body.count('"status:') == 3
    # Start paths never print a raw status line; they route through
    # Show-Status (already-running + success = 2 calls).
    start_body = _body(text, "Start-Server")
    assert start_body.count('"status:') == 0
    assert start_body.count("Show-Status") == 2


def test_ctl_per_address_url_lines():
    text = _text(CTL_PATH)
    links_body = _body(text, "Show-Links")
    # All-interfaces bind prints exactly two URL lines (LAN + loopback);
    # an explicit bind prints exactly that address (one URL line).
    assert links_body.count('"open (tablet/LAN): http://') == 1
    assert links_body.count('"open (this machine): http://127.0.0.1:') == 1
    assert links_body.count('"open: http://') == 1
    # Each printed address carries its own live port probe.
    assert links_body.count("port_open=") >= 3
    assert links_body.count("Test-PortOpen") >= 2
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


def test_ctl_example_line_every_path():
    text = _text(CTL_PATH)
    # Exactly one example-line shape, naming the status probe.
    assert len(re.findall(r'(?m)^\s*"example:', text)) == 1
    assert "server_ctl.ps1 status -Port" in text
    # Every emitting function carries the example to all its paths:
    # start has 5 exits (already-running, refused, missing, early-exit,
    # success), stop has 3 (no-pid, stale, success), usage has 1.
    assert _body(text, "Start-Server").count("Show-Example") >= 5
    assert _body(text, "Stop-Server").count("Show-Example") >= 3
    assert "Show-Example" in _body(text, "Show-Usage")
    # The dispatch tail covers status / empty / unknown-action paths.
    tail = text.split("switch ($NormalizedAction)", 1)[1]
    assert "Show-Example" in tail


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
