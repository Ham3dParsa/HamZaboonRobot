"""P6 judge->AI preset migration tests (isolated data root).

Contract: flip kind judge->ai IN PLACE (same file, same version);
skip (never overwrite) when an ai record already owns the name, when
the record fails ai validation, or when the file is unreadable.
Run-kind records are never touched.
"""

from __future__ import annotations

import json
import os

import pytest

from factory.webui import server as webui


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = str(tmp_path / "data")
    presets = os.path.join(root, "webui", "presets")
    os.makedirs(presets)
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", root)
    return {"client": webui.app.test_client(), "presets": presets}


def _write(presets, filename, rec):
    with open(os.path.join(presets, filename), "w",
              encoding="utf-8") as handle:
        json.dump(rec, handle, ensure_ascii=False)


def _judge(name="j1", **kw):
    rec = {"name": name, "version": 3, "kind": "judge",
           "provider": "avalai", "model": "m", "max_rpm": 0,
           "max_rph": 0, "max_daily": 0, "rate_scope": "model"}
    rec.update(kw)
    return rec


def test_migrate_flips_kind_keeps_version(env):
    _write(env["presets"], "j1.json", _judge())
    body = env["client"].post("/api/presets/migrate").get_json()
    assert body["migrated"] == ["j1"]
    assert body["skipped"] == []
    with open(os.path.join(env["presets"], "j1.json"),
              encoding="utf-8") as handle:
        rec = json.load(handle)
    assert rec["kind"] == "ai"
    assert rec["version"] == 3
    assert rec["provider"] == "avalai"
    assert [p["name"] for p in
            env["client"].get("/api/ai_presets").get_json()["ai_presets"]] == ["j1"]


def test_migrate_never_overwrites_ai_owner(env):
    _write(env["presets"], "j1.json", _judge())
    sentinel = {"name": "j1", "version": 9, "kind": "ai",
                "provider": "groq", "model": "mine"}
    _write(env["presets"], "j1__ai.json", sentinel)
    body = env["client"].post("/api/presets/migrate").get_json()
    assert body["migrated"] == []
    assert [s["name"] for s in body["skipped"]] == ["j1"]
    with open(os.path.join(env["presets"], "j1__ai.json"),
              encoding="utf-8") as handle:
        assert json.load(handle) == sentinel


def test_migrate_skips_corrupt_and_run_records(env):
    with open(os.path.join(env["presets"], "bad.json"), "w",
              encoding="utf-8") as handle:
        handle.write("{broken")
    _write(env["presets"], "r1.json",
           {"name": "r1", "version": 1, "kind": "run",
            "provider": "avalai", "model": "", "limit": 5,
            "concurrency": 0, "resume": "on"})
    body = env["client"].post("/api/presets/migrate").get_json()
    assert body["migrated"] == []
    with open(os.path.join(env["presets"], "r1.json"),
              encoding="utf-8") as handle:
        assert json.load(handle)["kind"] == "run"


def test_migrate_idempotent(env):
    _write(env["presets"], "j1.json", _judge())
    first = env["client"].post("/api/presets/migrate").get_json()
    second = env["client"].post("/api/presets/migrate").get_json()
    assert first["migrated"] == ["j1"]
    assert second == {"migrated": [], "skipped": []}


def test_judge_write_rejected_with_migrate_pointer(env):
    resp = env["client"].post("/api/presets",
                              json={"name": "old", "provider": "avalai",
                                    "kind": "judge"})
    assert resp.status_code == 400
    assert "migrate" in resp.get_json()["error"]
