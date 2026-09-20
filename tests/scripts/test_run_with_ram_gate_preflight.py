"""Hermetic unit tests for the RAM-preflight serialize guard in
scripts/run_with_ram_gate.py (locked contract R1/R2/R4).

No network, no model calls: socket reachability and psutil readings are
mocked via monkeypatch on the module's seams (_model_server_is_up,
_free_ram_bytes). subprocess.Popen is faked where main() is exercised.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "run_with_ram_gate.py"
)


def _load_module(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "run_with_ram_gate_preflight_under_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


GB = 1024**3


def test_server_up_with_many_workers_refuses(monkeypatch, capsys):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 16 * GB)
    assert mod.run_preflight_checks(14) == 1
    err = capsys.readouterr().err
    assert "Stop the model server, then re-run" in err
    assert "-n 4" not in err  # R4: never suggest lowering workers


def test_server_up_with_few_workers_passes(monkeypatch):
    # CI safety: -n 2 (below the workers > 4 trigger) never refuses.
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 16 * GB)
    assert mod.run_preflight_checks(2) is None


def test_low_ram_refuses(monkeypatch, capsys):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 5 * GB)
    assert mod.run_preflight_checks(14) == 1
    err = capsys.readouterr().err
    assert "6GB" in err
    assert "-n 4" not in err  # R4


def test_happy_path_passes(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 16 * GB)
    assert mod.run_preflight_checks(14) is None


def test_psutil_missing_skips_ram_check(monkeypatch):
    # psutil missing -> _free_ram_bytes() is None; preflight must not refuse
    # so the existing fail-closed exit 2 path downstream is preserved.
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "psutil", None)
    assert mod.run_preflight_checks(14) is None


class _FakeProc:
    def __init__(self, calls, rc=0, warmups=3):
        self._calls = calls
        self.pid = 12345
        self.returncode = rc
        self._polls = 0
        self._warmups = warmups

    def poll(self):
        # Stay "alive" for a few samples so the RAM loop collects peak.
        self._polls += 1
        if self._polls <= self._warmups:
            return None
        return self.returncode

    def wait(self):
        return self.returncode


def _fake_popen_factory(monkeypatch, mod, rc=0):
    calls = []

    def _fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return _FakeProc(calls, rc)

    monkeypatch.setattr(mod.subprocess, "Popen", _fake_popen)
    return calls


def test_main_happy_path_passes_args_through(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 16 * GB)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14", "--collect-only"]) == 0
    assert len(calls) == 1
    cmd = calls[0]
    assert "-n" in cmd and "14" in cmd and "--collect-only" in cmd


def test_main_server_up_refuses_without_launching(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 16 * GB)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"]) == 1  # exit 1 preserved
    assert calls == []


def test_main_low_ram_refuses_without_launching(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 2 * GB)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"]) == 1  # exit 1 preserved
    assert calls == []


@pytest.mark.parametrize("extra", [["--skip-preflight"]])
def test_main_skip_flag_bypasses_preflight(monkeypatch, extra):
    mod = _load_module(monkeypatch)
    # Hostile conditions that would otherwise refuse...
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 1 * GB)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"] + extra) == 0
    assert len(calls) == 1


def test_main_skip_env_bypasses_preflight(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 1 * GB)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    monkeypatch.setenv("HAMZABAN_SKIP_PREFLIGHT", "1")
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"]) == 0
    assert len(calls) == 1


def test_main_psutil_missing_exit_2_preserved(monkeypatch):
    # Fail-closed exit 2 path downstream of the preflight is unchanged.
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "psutil", None)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"]) == 2  # exit 2 preserved
    assert len(calls) == 1
