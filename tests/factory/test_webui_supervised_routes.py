"""Route-level crash tests for supervised batches + gallery (W1 reviewer F1-F3).

Covers the server.py seam only (batches.py layer has its own suite):
create-happy summary shape, size coercion, unknown/traversal ids, gallery
missing-arg/unknown-run. Isolated via HAMZABAN_DATA_ROOT (tmp).
"""

from __future__ import annotations

import json
import os

import pytest

from factory.webui import server as webui


def _write_screened(path, n=12):
    with open(path, "w", encoding="utf-8") as handle:
        for i in range(n):
            handle.write(json.dumps({
                "lemma": "run",
                "sense": {
                    "sense_id": "run#%d" % i,
                    "id": "en-run-en-verb-%d" % i,
                    "glosses": ["gloss %d" % i],
                    "examples": [{"text": "example %d" % i}],
                    "tags": ["verb"],
                },
            }, ensure_ascii=False) + "\n")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = str(tmp_path / "data")
    os.makedirs(root)
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", root)
    screened = str(tmp_path / "screened.jsonl")
    _write_screened(screened)
    return {"client": webui.app.test_client(), "screened": screened}


def test_create_happy_summary_shape(env):
    resp = env["client"].post("/api/batches",
                              json={"screened_path": env["screened"],
                                    "size": 10})
    assert resp.status_code == 200, resp.get_json()
    batch = resp.get_json()["batch"]
    assert batch["size"] == 10
    assert batch["status"] == "exported"
    assert batch["answered"] == 0 and batch["approved"] == 0
    assert batch["md"].endswith("batch.md")
    assert batch["json"].endswith("batch.json-data")


def test_create_size_coercion(env):
    for bad in (0, 9, 51, "abc", 10.5):
        resp = env["client"].post(
            "/api/batches",
            json={"screened_path": env["screened"], "size": bad})
        assert resp.status_code == 400, bad
        assert "VALIDATION" in resp.get_json()["error"]


def test_create_blank_size_defaults(env):
    for blank in (None, ""):
        resp = env["client"].post(
            "/api/batches",
            json={"screened_path": env["screened"], "size": blank})
        assert resp.status_code == 200, blank
        bid = resp.get_json()["batch"]["id"]
        assert env["client"].post(
            "/api/batches/%s/cancel" % bid).status_code == 200


def test_fetch_cancel_unknown_and_traversal(env):
    assert env["client"].get("/api/batches/nope").status_code == 404
    assert env["client"].get("/api/batches/..").status_code == 404
    resp = env["client"].post("/api/batches/nope/cancel")
    assert resp.status_code == 400
    assert "VALIDATION-unknown-batch" in resp.get_json()["error"]
    assert env["client"].post("/api/batches/../x/cancel").status_code == 404


def test_fetch_single_and_cancel_roundtrip(env):
    created = env["client"].post(
        "/api/batches",
        json={"screened_path": env["screened"], "size": 10}).get_json()["batch"]
    fetched = env["client"].get(
        "/api/batches/%s" % created["id"]).get_json()
    assert len(fetched["items"]) == 10
    assert "system" in fetched["md"].lower() \
        or "prompt" in fetched["md"].lower()
    assert env["client"].post(
        "/api/batches/%s/cancel" % created["id"]).status_code == 200
    listed = env["client"].get("/api/batches").get_json()["batches"]
    assert listed[0]["status"] == "cancelled"


def test_gallery_missing_and_unknown(env):
    assert env["client"].get("/api/gallery").status_code == 400
    resp = env["client"].get("/api/gallery?run=no-such-run")
    assert resp.status_code == 404
