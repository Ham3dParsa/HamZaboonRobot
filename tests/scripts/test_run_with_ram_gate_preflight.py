"""Hermetic unit tests for the RAM-preflight serialize guard in
scripts/run_with_ram_gate.py (locked contract R1/R2/R4: idle-server allow,
20%-of-total floor).

No network, no model calls: socket reachability, the /v1/models list, and
psutil readings are mocked via monkeypatch on the module's seams
(_model_server_is_up, _loaded_model_count, _free_ram_bytes,
_total_ram_bytes). subprocess.Popen is faked where main() is exercised.
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


def _healthy_ram(monkeypatch, mod, free_gb=16, total_gb=16):
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: free_gb * GB)
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: total_gb * GB)


def test_loaded_server_with_many_workers_refuses(monkeypatch, capsys):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_loaded_model_count", lambda: 2)
    _healthy_ram(monkeypatch, mod)
    assert mod.run_preflight_checks(14) is None
    err = capsys.readouterr().err
    assert "Unload the model" in err
    assert "-n 4" not in err  # R4: never suggest lowering workers


def test_idle_server_with_zero_models_allows(monkeypatch, capsys):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_loaded_model_count", lambda: 0)
    _healthy_ram(monkeypatch, mod)
    assert mod.run_preflight_checks(14) == 14
    err = capsys.readouterr().err
    assert "0 models loaded" in err


def test_unreadable_model_list_refuses_fail_closed(monkeypatch, capsys):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_loaded_model_count", lambda: None)
    _healthy_ram(monkeypatch, mod)
    assert mod.run_preflight_checks(14) is None
    err = capsys.readouterr().err
    assert "fail-closed" in err
    assert "-n 4" not in err  # R4


def test_server_up_with_few_workers_passes(monkeypatch):
    # CI safety: -n 2 (below the workers > 4 trigger) never refuses.
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_loaded_model_count", lambda: 2)
    _healthy_ram(monkeypatch, mod)
    assert mod.run_preflight_checks(2) == 2


def test_mid_ram_caps_workers(monkeypatch, capsys):
    # 2GB free fits 7 workers (2048 // 260), not 14: auto-cap with a
    # notice, never a refusal and never a "lower your workers" advice.
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 2 * GB)
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: 16 * GB)
    assert mod.run_preflight_checks(14) == 7
    err = capsys.readouterr().err
    assert "capping requested 14" in err
    assert "-n 4" not in err  # R4


def test_bottom_ram_refuses(monkeypatch, capsys):
    # 400MB free fits 1 worker: below the 2-worker minimum -> refuse.
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: int(0.4 * GB))
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: 16 * GB)
    assert mod.run_preflight_checks(14) is None
    err = capsys.readouterr().err
    assert "REFUSE" in err
    assert "-n 4" not in err  # R4


def test_exact_cap_boundary(monkeypatch):
    # free == exactly 8 workers of budget runs all 8 with no notice path
    # taken for the cap (requested <= cap).
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 8 * 260 * 1024**2)
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: 20 * GB)
    assert mod.run_preflight_checks(8) == 8


def test_serial_always_proceeds(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: int(0.4 * GB))
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: 16 * GB)
    assert mod.run_preflight_checks(0) == 0


def test_happy_path_passes(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    _healthy_ram(monkeypatch, mod)
    assert mod.run_preflight_checks(14) == 14


def test_psutil_missing_skips_ram_check(monkeypatch):
    # psutil missing -> _free_ram_bytes()/_total_ram_bytes() are None;
    # preflight must not refuse so the existing fail-closed exit 2 path
    # downstream is preserved.
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "psutil", None)
    assert mod.run_preflight_checks(14) == 14


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
    _healthy_ram(monkeypatch, mod)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14", "--collect-only"]) == 0
    assert len(calls) == 1
    cmd = calls[0]
    assert "-n" in cmd and "14" in cmd and "--collect-only" in cmd


def test_main_loaded_server_refuses_without_launching(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_loaded_model_count", lambda: 1)
    _healthy_ram(monkeypatch, mod)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"]) == 1  # exit 1 preserved
    assert calls == []


def test_main_idle_server_proceeds_to_launch(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_loaded_model_count", lambda: 0)
    _healthy_ram(monkeypatch, mod)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"]) == 0
    assert len(calls) == 1


def test_main_unreadable_list_refuses_without_launching(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_loaded_model_count", lambda: None)
    _healthy_ram(monkeypatch, mod)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"]) == 1  # exit 1 preserved
    assert calls == []


def test_main_mid_ram_caps_and_launches(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 2 * GB)
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: 16 * GB)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"]) == 0
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[cmd.index("-n") + 1] == "7"


def test_main_bottom_ram_refuses_without_launching(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: int(0.4 * GB))
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: 16 * GB)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"]) == 1  # exit 1 preserved
    assert calls == []


@pytest.mark.parametrize("extra", [["--skip-preflight"]])
def test_main_skip_flag_bypasses_preflight(monkeypatch, extra):
    mod = _load_module(monkeypatch)
    # Hostile conditions that would otherwise refuse...
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_loaded_model_count", lambda: 3)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 1 * GB)
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: 16 * GB)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "14"] + extra) == 0
    assert len(calls) == 1


def test_main_skip_env_bypasses_preflight(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_loaded_model_count", lambda: 3)
    monkeypatch.setattr(mod, "_free_ram_bytes", lambda: 1 * GB)
    monkeypatch.setattr(mod, "_total_ram_bytes", lambda: 16 * GB)
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


class _FakeHTTPResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen_factory(monkeypatch, mod, body=None, exc=None):
    def _fake_urlopen(url, timeout=None):
        assert url == "http://127.0.0.1:1234/v1/models"
        if exc is not None:
            raise exc
        return _FakeHTTPResponse(body)

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen)


def test_loaded_model_count_parses_shapes(monkeypatch):
    import urllib.error
    mod = _load_module(monkeypatch)
    _fake_urlopen_factory(
        monkeypatch, mod, body=b'{"data": [{"id": "m"}, {"id": "n"}]}')
    assert mod._loaded_model_count() == 2
    _fake_urlopen_factory(monkeypatch, mod, body=b'{"data": []}')
    assert mod._loaded_model_count() == 0
    _fake_urlopen_factory(monkeypatch, mod, body=b'[{"id": "m"}]')
    assert mod._loaded_model_count() is None  # non-dict fails closed
    _fake_urlopen_factory(monkeypatch, mod, body=b'{"data": {}}')
    assert mod._loaded_model_count() is None  # non-list fails closed
    _fake_urlopen_factory(monkeypatch, mod, body=b'{"object": "list"}')
    assert mod._loaded_model_count() is None  # missing key fails closed
    _fake_urlopen_factory(monkeypatch, mod, body=b'not json')
    assert mod._loaded_model_count() is None
    _fake_urlopen_factory(
        monkeypatch, mod, exc=urllib.error.URLError("refused"))
    assert mod._loaded_model_count() is None


def test_worker_threshold_boundary(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: True)
    monkeypatch.setattr(mod, "_loaded_model_count", lambda: 1)
    _healthy_ram(monkeypatch, mod)
    assert mod.run_preflight_checks(4) == 4  # at threshold: allowed
    assert mod.run_preflight_checks(5) is None  # above threshold: refused


def test_default_workers_is_eight(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    _healthy_ram(monkeypatch, mod)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main([]) == 0
    assert calls[0][calls[0].index("-n") + 1] == "8"


def test_default_run_excludes_research(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    _healthy_ram(monkeypatch, mod)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    monkeypatch.delenv("HAMZABAN_INCLUDE_RESEARCH", raising=False)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "8"]) == 0
    cmd = calls[0]
    # NB: cmd[1] is the interpreter's own -m (python -m pytest);
    # the pytest -m option is the pair right before "not research".
    assert cmd[cmd.index("not research") - 1] == "-m"


def test_research_env_includes_research(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    _healthy_ram(monkeypatch, mod)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    monkeypatch.setenv("HAMZABAN_INCLUDE_RESEARCH", "1")
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "8"]) == 0
    assert "not research" not in calls[0]


def test_caller_m_flag_wins_over_research_default(monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "_model_server_is_up", lambda: False)
    _healthy_ram(monkeypatch, mod)
    monkeypatch.setattr(mod, "_peak_rss_mb", lambda pid: 100.0)
    monkeypatch.delenv("HAMZABAN_INCLUDE_RESEARCH", raising=False)
    calls = _fake_popen_factory(monkeypatch, mod, rc=0)
    assert mod.main(["-n", "8", "-m", "slow"]) == 0
    cmd = calls[0]
    assert "not research" not in cmd
    last_m = max(i for i, x in enumerate(cmd) if x == "-m")
    assert cmd[last_m + 1] == "slow"
