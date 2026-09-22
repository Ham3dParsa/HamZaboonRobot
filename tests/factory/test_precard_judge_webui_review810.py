"""PR-810 review fixes: filename guard, scrubber reuse, operator ignores.

Behavior spec (from the reviewer must-fix items):
1. ``_safe_filename`` sanitizes ``/`` and ``\\`` (no traversal on the
   Windows server_ctl target) and two distinct display names never
   share one file (Persian collision guard).
2. ``scrub_secrets`` accepts pre-decrypted values so a run decrypts
   once and reuses the set per log line — output identical to the
   on-demand path; values never surface (names only elsewhere).
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.linking.webui import server as webui


def test_safe_filename_strips_separators_no_traversal():
    for evil in ("..\\..\\x", "../../etc/passwd", "a/b", "a\\b",
                 "..", ".", ""):
        safe = webui._safe_filename(evil)
        assert "/" not in safe and "\\" not in safe, safe
        assert safe, evil
    assert webui._safe_filename("..\\..\\x") != "..\\..\\x"
    # joined with the data dir + .json suffix the stem cannot escape it
    joined = os.path.join("presets",
                          webui._safe_filename("..\\..\\x") + ".json")
    assert os.path.dirname(joined) == "presets"


def test_safe_filename_keeps_ascii_and_persian():
    assert webui._safe_filename("witness-benchmark") == "witness-benchmark"
    assert webui._safe_filename("jt1") == "jt1"
    assert "سلام" in webui._safe_filename("سلام دنیا")


def test_safe_filename_persian_collision_two_names_two_files(tmp_path,
                                                             monkeypatch):
    # Two distinct 3-letter Persian names collapsed to ___.json before.
    first, second = "تست", "متن"
    assert first != second
    safe_first = webui._safe_filename(first)
    safe_second = webui._safe_filename(second)
    assert safe_first != safe_second
    assert "/" not in safe_first and "\\" not in safe_first
    assert "/" not in safe_second and "\\" not in safe_second

    monkeypatch.setattr(webui, "PRESETS_DIR", str(tmp_path))
    rec1 = webui.save_preset({"name": first, "provider": "avalai",
                              "model": "", "sample": "", "limit": 0,
                              "concurrency": 0, "out": "",
                              "progress_dir": "", "resume": "on"})
    rec2 = webui.save_preset({"name": second, "provider": "avalai",
                              "model": "", "sample": "", "limit": 0,
                              "concurrency": 0, "out": "",
                              "progress_dir": "", "resume": "on"})
    assert rec1["name"] == first and rec2["name"] == second
    files = sorted(p for p in os.listdir(str(tmp_path))
                   if p.endswith(".json"))
    assert len(files) == 2
    assert webui.get_preset(first)["name"] == first
    assert webui.get_preset(second)["name"] == second


def test_scrub_secrets_cached_values_identical_and_no_decrypt(monkeypatch):
    calls = {"n": 0}

    def _boom():
        calls["n"] += 1
        return {"K": "super-secret-value-12345"}

    monkeypatch.setattr(webui, "_operator_key_values", _boom)
    line = "hello super-secret-value-12345 world token=abc123"
    fresh = webui.scrub_secrets(line)
    assert "super-secret-value-12345" not in fresh
    assert calls["n"] == 1

    # Hot path: pre-decrypted set reused — zero decrypt calls, same output.
    calls["n"] = 0
    cached = ("super-secret-value-12345",)

    def _must_not_run():
        raise AssertionError("must reuse cached values, not decrypt")

    monkeypatch.setattr(webui, "_operator_key_values", _must_not_run)
    for _ in range(5):
        out = webui.scrub_secrets(line, extra_values=cached)
        assert out == webui.scrub_secrets(line, extra_values=cached)
        assert "super-secret-value-12345" not in out
    assert calls["n"] == 0


def test_scrub_secrets_back_compat_single_arg(monkeypatch):
    monkeypatch.setattr(webui, "_operator_key_values", lambda: {})
    assert webui.scrub_secrets("") == ""
    assert "x" in webui.scrub_secrets("x")
