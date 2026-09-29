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
    monkeypatch.setenv("HAMZABAN_SCREENED_PATH", screened)
    return {"client": webui.app.test_client(), "screened": screened}


def test_create_happy_summary_shape(env):
    resp = env["client"].post("/api/batches",
                              json={
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
            json={ "size": bad})
        assert resp.status_code == 400, bad
        assert "VALIDATION" in resp.get_json()["error"]


def test_create_blank_size_defaults(env):
    for blank in (None, ""):
        resp = env["client"].post(
            "/api/batches",
            json={ "size": blank})
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


def test_concurrent_creates_serialize_to_one(env):
    import threading
    from factory.webui import server as _srv

    codes = []

    def _one():
        client = _srv.app.test_client()
        resp = client.post("/api/batches", json={"size": 10})
        codes.append(resp.status_code)

    threads = [threading.Thread(target=_one) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(codes) == [200, 400, 400, 400, 400]


def test_fetch_single_and_cancel_roundtrip(env):
    created = env["client"].post(
        "/api/batches",
        json={"size": 10}).get_json()["batch"]
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


def _make_batch(env, size=10):
    return env["client"].post(
        "/api/batches",
        json={"size": size}).get_json()["batch"]


def test_create_ignores_client_screened_path(env):
    """Exfiltration guard (R3): outside paths never become batch items."""
    resp = env["client"].post(
        "/api/batches",
        json={"screened_path": "C:/Windows/win.ini", "size": 10})
    assert resp.status_code == 200
    fetched = env["client"].get(
        "/api/batches/%s" % resp.get_json()["batch"]["id"]).get_json()
    assert [it["sense_id"] for it in fetched["items"]] == \
        ["run#%d" % i for i in range(10)]


def _sheet_for(env, batch_id, verdict="none"):
    items = env["client"].get(
        "/api/batches/%s" % batch_id).get_json()["items"]
    meta = env["client"].get(
        "/api/batches/%s" % batch_id).get_json()["batch"]
    return json.dumps({
        "model": "route-test",
        "prompt_hash": meta["prompt_hash"],
        "verdicts": [{"sense_id": it["sense_id"], "verdict": verdict,
                      "target_synset": None} for it in items],
    })


def test_import_stage_approve_roundtrip(env):
    batch = _make_batch(env)
    sheet = _sheet_for(env, batch["id"])
    staged = env["client"].post(
        "/api/batches/%s/import" % batch["id"],
        json={"answer_sheet": sheet}).get_json()
    assert staged["staged"] == 10
    assert staged["status"] == "in_review"
    items = env["client"].get(
        "/api/batches/%s" % batch["id"]).get_json()["items"]
    keep = [it["sense_id"] for it in items[:4]]
    done = env["client"].post(
        "/api/batches/%s/approve" % batch["id"],
        json={"ids": keep, "reviewer": "route-test"}).get_json()
    assert done["finalized"] == 4
    assert done["returned"] == 6
    assert done["status"] == "imported"


def test_import_requires_raw_string_not_object(env):
    """Pins the UI→route payload contract (F1): parsed object → 400."""
    batch = _make_batch(env)
    sheet = _sheet_for(env, batch["id"])
    resp = env["client"].post(
        "/api/batches/%s/import" % batch["id"],
        json={"answer_sheet": json.loads(sheet)})
    assert resp.status_code == 400
    ok = env["client"].post(
        "/api/batches/%s/import" % batch["id"],
        json={"answer_sheet": sheet})
    assert ok.status_code == 200


def test_import_reject_gives_repair(env):
    batch = _make_batch(env)
    bad = json.dumps({"model": "route-test",
                      "prompt_hash": batch["prompt_hash"],
                      "verdicts": [{"sense_id": "ghost#0",
                                    "verdict": "none",
                                    "target_synset": None}]})
    resp = env["client"].post(
        "/api/batches/%s/import" % batch["id"],
        json={"answer_sheet": bad})
    assert resp.status_code == 422
    body = resp.get_json()
    assert "ghost#0" in body["error"]
    assert body["repair_request"]
    assert batch["id"] in body["repair_request"]
    assert env["client"].post(
        "/api/batches/%s/import" % batch["id"],
        json={"answer_sheet": ""}).status_code == 400


def test_linking_history_aggregates_three_kinds(env):
    body = env['client'].get('/api/linking/history').get_json()
    assert body['runs'] == []
    created = env['client'].post('/api/batches', json={'size': 10}).get_json()['batch']
    body = env['client'].get('/api/linking/history').get_json()
    kinds = [r['kind'] for r in body['runs']]
    assert 'batch' in kinds
    row = [r for r in body['runs'] if r['kind'] == 'batch'][0]
    assert row['run_id'] == created['id']
    assert set(row) >= {'kind', 'run_id', 'out_name', 'status', 'created', 'detail'}
