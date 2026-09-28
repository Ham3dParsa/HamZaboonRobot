"""T05 — GET /api/runs/history?cabin= screening history (read-only).

Behavior spec (server docstring + factory/webui/run_status.py):
- ``GET /api/runs/history?cabin=screening`` -> ``{cabin, runs,
  skipped, truncated}`` scanned from ``<DATA_ROOT>/webui/
  screening_runs/`` merged with the T04 status file (newest last).
- Corrupt records are skipped + counted in ``skipped`` (never 500).
- Empty history -> ``runs: []``. Unknown/missing cabin -> 400.
- No write path — history never mutates; cabins never leak.

Hermetic: tmp data root, Flask test client, plain run.json seeds.
No network, no processes, no secrets.
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.webui import server as webui


@pytest.fixture()
def _roots(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", str(tmp_path))
    return tmp_path


def _seed_run(root, cabin, run_id, started_iso, kept=None, dropped=None,
              status="completed"):
    run_dir = os.path.join(str(root), "webui", "%s_runs" % cabin, run_id)
    os.makedirs(run_dir, exist_ok=True)
    record = {"run_id": run_id, "out_name": run_id,
              "out_dir": run_dir, "started_iso": started_iso,
              "status": status}
    if kept is not None:
        record["kept_total"] = kept
    if dropped is not None:
        record["dropped_total"] = dropped
    with open(os.path.join(run_dir, "run.json"), "w",
              encoding="utf-8") as handle:
        json.dump(record, handle)
    return run_dir


def test_history_lists_three_runs_newest_last(_roots):
    """Three seeded runs come back newest-last with kept/dropped."""
    _seed_run(_roots, "screening", "run-old",
              "2026-09-25T00:00:00+00:00", kept=1, dropped=2)
    _seed_run(_roots, "screening", "run-mid",
              "2026-09-26T00:00:00+00:00", kept=3, dropped=4)
    _seed_run(_roots, "screening", "run-new",
              "2026-09-27T00:00:00+00:00", kept=5, dropped=6)
    body = webui.app.test_client().get(
        "/api/runs/history?cabin=screening").get_json()
    assert body["cabin"] == "screening"
    assert [r["run_id"] for r in body["runs"]] == [
        "run-old", "run-mid", "run-new"]
    assert [(r["kept_total"], r["dropped_total"]) for r in body["runs"]] == [
        (1, 2), (3, 4), (5, 6)]
    assert body["skipped"] == 0
    assert body["truncated"] is False


def test_corrupt_run_dir_skipped_and_counted(_roots):
    """Broken JSON + missing run.json are counted, never a 500."""
    _seed_run(_roots, "screening", "run-good",
              "2026-09-27T00:00:00+00:00", kept=7, dropped=1)
    broken = os.path.join(str(_roots), "webui", "screening_runs",
                          "run-broken")
    os.makedirs(broken, exist_ok=True)
    with open(os.path.join(broken, "run.json"), "w",
              encoding="utf-8") as handle:
        handle.write("{broken")
    empty = os.path.join(str(_roots), "webui", "screening_runs",
                         "run-empty")
    os.makedirs(empty, exist_ok=True)
    resp = webui.app.test_client().get(
        "/api/runs/history?cabin=screening")
    assert resp.status_code == 200
    body = resp.get_json()
    assert [r["run_id"] for r in body["runs"]] == ["run-good"]
    assert body["skipped"] == 2


def test_empty_store_returns_empty_runs(_roots):
    """No runs dir and no status file -> runs: []."""
    resp = webui.app.test_client().get(
        "/api/runs/history?cabin=screening")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["cabin"] == "screening"
    assert body["runs"] == []
    assert body["skipped"] == 0
    assert body["truncated"] is False


def test_unknown_cabin_returns_400(_roots):
    """A cabin outside the server allowlist is a 400, never a 500."""
    resp = webui.app.test_client().get(
        "/api/runs/history?cabin=no-such-cabin")
    assert resp.status_code == 400
    assert "unknown cabin" in resp.get_json()["error"]
    resp = webui.app.test_client().get("/api/runs/history")
    assert resp.status_code == 400


def test_cross_cabin_isolation(_roots):
    """A linking run dir never appears under cabin=screening."""
    _seed_run(_roots, "screening", "run-s1",
              "2026-09-27T00:00:00+00:00", kept=2, dropped=0)
    _seed_run(_roots, "linking", "run-l1",
              "2026-09-27T00:00:01+00:00", kept=9, dropped=9)
    body = webui.app.test_client().get(
        "/api/runs/history?cabin=screening").get_json()
    assert [r["run_id"] for r in body["runs"]] == ["run-s1"]
