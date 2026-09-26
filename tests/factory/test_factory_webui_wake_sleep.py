"""T7 wake-on-demand closed loop + idle sleep + wake/sleep buttons + state.

Behavior spec (plan-console-phase-08-wake-sleep):
- Wake gate truly closes the loop: no token -> background wake -> retry
  -> friendly wait line, never a raw error (fakes only, never a process).
- State surface: wake + sleep buttons + status badge wired to the
  /api/supervisor/wake + /api/supervisor/sleep endpoints.
- Idle sleep honors owner-configured minutes; the shipped default stays
  a parked constant (owner number pending, never invented).

Hermetic: fakes only, no processes, no network, no secret values.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.webui import server as webui


def test_wake_gate_closes_loop(monkeypatch):
    """No token -> wake -> retry -> friendly wait line, never raw error."""
    calls = {"wake": 0}

    def fake_wake():
        calls["wake"] += 1
        return True

    # Token absent before wake, resolves after the background wake leg.
    states = {"token": ""}
    monkeypatch.setattr(webui, "_supervisor_token",
                        lambda: states["token"])

    def fake_wake_and_issue():
        states["token"] = "faketoken123"
        return fake_wake()

    ready, error = webui._ensure_supervisor_for_leased(
        "google", wake_fn=fake_wake_and_issue,
        tunneled={"google": True})
    assert ready is True
    assert error is None
    assert calls["wake"] == 1

    # Still-down supervisor: friendly wait line, never a raw traceback.
    states["token"] = ""
    ready, error = webui._ensure_supervisor_for_leased(
        "google", wake_fn=lambda: True,
        tunneled={"google": True})
    assert ready is False
    assert isinstance(error, str) and "background" in error
    assert "Traceback" not in error

    # Healthy supervisor is never restarted: health-first short-circuit
    # touches neither spawn nor wake legs.
    spawned = {"n": 0}
    woke = webui._wake_supervisor_background(
        health_fn=lambda: (True, {"healthy": True}),
        spawn_fn=lambda port: spawned.__setitem__("n", spawned["n"] + 1),
        timeout=0.5)
    assert woke is True
    assert spawned["n"] == 0


def test_wake_sleep_buttons_wired():
    """Endpoints + button ids present (state surface wired, fakes only)."""
    rules = {str(r) for r in webui.app.url_map.iter_rules()}
    assert "/api/supervisor/wake" in rules
    assert "/api/supervisor/sleep" in rules
    html = open(webui.SCRIPT_DIR + os.sep + "index.html",
                encoding="utf-8").read()
    assert "btn-supervisor-wake" in html
    assert "btn-supervisor-sleep" in html
    assert "supervisor-lifecycle-state" in html
    assert "/api/supervisor/wake" in html
    assert "/api/supervisor/sleep" in html


def test_idle_sleep_uses_owner_minutes():
    """Idle path honors injected minutes; shipped default stays parked."""
    # Parked constant: owner number pending, never invented here.
    assert webui.IDLE_SLEEP_MINUTES is None
    now = 1_700_000_000.0
    # Injected minutes drive the verdict, not any real duration.
    assert webui.supervisor_idle_due(now - 120.0, now, minutes=1) is True
    assert webui.supervisor_idle_due(now - 120.0, now, minutes=60) is False
    # Parked default never sleeps on its own.
    assert webui.supervisor_idle_due(now - 10_000.0, now) is False
    # Others' leases are never disturbed: an active lease blocks sleep
    # even when the idle clock has expired.
    assert webui.supervisor_idle_due(
        now - 10_000.0, now, minutes=1, active_leases=2) is False
