"""P01 batch export builder tests (frozen contracts, behavior-first).

Covers the phase-01 acceptance rows:
- oldest-first + dedup vs labels.jsonl / active batches (cancelled releases)
- size clamp 10-50, default 25, VALIDATION-* errors on bad size/empty queue
- md contains system block + version + hash + exact answer-sheet template
- json round-trips items
- bad screened lines skipped (tolerant parse, never crash)
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from factory.webui import batches


def _write_screened(path, senses):
    with open(path, "w", encoding="utf-8") as handle:
        for entry in senses:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _sense(short, full, gloss="a gloss", example="an example", tags=None, lemma="run"):
    return {
        "lemma": lemma,
        "sense": {
            "sense_id": short,
            "id": full,
            "glosses": [gloss],
            "examples": [{"text": example}],
            "tags": tags or ["verb"],
        },
    }


def _write_table(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("kaikki_sense_id\twordnet_sensekey\tmethod\tevidence\tprovenance\n")
        for kid, skey in rows:
            handle.write("%s\t%s\tLINK:2-sig\te\tp\n" % (kid, skey))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = str(tmp_path / "data")
    os.makedirs(root)
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", root)
    screened = str(tmp_path / "screened.jsonl")
    table = str(tmp_path / "table.tsv")
    labels = os.path.join(root, "webui", "labels.jsonl")
    return {"root": root, "screened": screened, "table": table, "labels": labels}


def _30_senses():
    return [_sense("run#%d" % i, "en-run-en-verb-%d" % i) for i in range(30)]


def test_oldest_first_order(env):
    _write_screened(env["screened"], _30_senses())
    _write_table(env["table"], [])
    batch = batches.build_batch(env["screened"], 10, table_path=env["table"])
    assert [it["sense_id"] for it in batch.items] == ["run#%d" % i for i in range(10)]


def test_default_size_is_25(env):
    _write_screened(env["screened"], _30_senses())
    _write_table(env["table"], [])
    batch = batches.build_batch(env["screened"], table_path=env["table"])
    assert batch.size == 25
    assert len(batch.items) == 25


def test_size_clamp_rejects(env):
    _write_screened(env["screened"], _30_senses())
    _write_table(env["table"], [])
    for bad in (0, 9, 51, 200, "25", None.__class__ and "x"):
        with pytest.raises(ValueError, match="VALIDATION-"):
            batches.build_batch(env["screened"], bad, table_path=env["table"])


def test_empty_queue_rejects(env):
    _write_screened(env["screened"], [])
    _write_table(env["table"], [])
    with pytest.raises(ValueError, match="VALIDATION-"):
        batches.build_batch(env["screened"], 10, table_path=env["table"])


def test_bad_screened_lines_skipped(env):
    _write_screened(env["screened"], _30_senses())
    with open(env["screened"], "a", encoding="utf-8") as handle:
        handle.write("not json at all\n")
        handle.write("[1, 2]\n")
        handle.write('{"lemma": "run"}\n')
        handle.write('{"lemma": "run", "sense": {"id": "x"}}\n')
        handle.write("\n")
    _write_table(env["table"], [])
    batch = batches.build_batch(env["screened"], 10, table_path=env["table"])
    assert len(batch.items) == 10
    assert batch.items[0]["sense_id"] == "run#0"


def test_dedup_vs_labels(env):
    _write_screened(env["screened"], _30_senses())
    _write_table(env["table"], [])
    os.makedirs(os.path.dirname(env["labels"]), exist_ok=True)
    with open(env["labels"], "w", encoding="utf-8") as handle:
        for i in range(5):
            handle.write(json.dumps({
                "sense_id": "run#%d" % i, "lemma": "run",
                "target_synset": None, "verdict": "none",
                "stratum": "gold", "annotator": "op",
                "created_at": "2026-01-01T00:00:00+00:00",
            }) + "\n")
    batch = batches.build_batch(env["screened"], 10, table_path=env["table"])
    assert batch.items[0]["sense_id"] == "run#5"


def test_dedup_vs_active_batch_and_cancel_releases(env):
    _write_screened(env["screened"], _30_senses())
    _write_table(env["table"], [])
    first = batches.build_batch(env["screened"], 10, table_path=env["table"])
    batches.save_batch(first)
    # Active (exported) batch blocks re-export (R4 anti-rework).
    with pytest.raises(ValueError, match="VALIDATION-"):
        batches.build_batch(env["screened"], 10, table_path=env["table"])
    batches.cancel_batch(first.id)
    second = batches.build_batch(env["screened"], 10, table_path=env["table"])
    # Cancelled batch releases its ids back to the queue.
    assert [it["sense_id"] for it in second.items] == ["run#%d" % i for i in range(10)]


def test_candidates_from_mechanical_table(env):
    _write_screened(env["screened"], [_sense("run#0", "en-run-en-verb-0")])
    _write_table(env["table"], [
        ("en-run-en-verb-0", "run%2:38:00::"),
        ("en-run-en-verb-0", "run%2:38:00::"),  # duplicate row dedups
        ("en-run-en-verb-0", "-"),  # MANUAL-NONE marker is never a candidate
    ])
    batch = batches.build_batch(env["screened"], 10, table_path=env["table"])
    # Queue smaller than minimum still exports what exists (no padding).
    assert len(batch.items) == 1
    cands = batch.items[0]["candidates"]
    assert [c["synset_id"] for c in cands] == ["run%2:38:00::"]
    assert set(cands[0]) == {"synset_id", "definition", "example", "tags"}


def test_item_shape(env):
    _write_screened(env["screened"], [_sense("run#0", "en-run-en-verb-0")])
    _write_table(env["table"], [])
    batch = batches.build_batch(env["screened"], 10, table_path=env["table"])
    item = batch.items[0]
    assert set(item) == {"sense_id", "lemma", "definition", "example",
                         "tags", "candidates"}
    assert item["lemma"] == "run"
    assert item["definition"] == "a gloss"
    assert item["example"] == "an example"
    assert item["tags"] == ["verb"]


def test_markdown_carries_system_block_version_hash_template(env):
    _write_screened(env["screened"], [_sense("run#0", "en-run-en-verb-0")])
    _write_table(env["table"], [])
    batch = batches.build_batch(env["screened"], 10, table_path=env["table"])
    md = batches.render_markdown(batch)
    assert batch.prompt_version in md
    assert batch.prompt_hash in md
    assert "run#0" in md
    # Exact answer-sheet template markers.
    assert '"verdicts"' in md
    assert '"target_synset"' in md
    assert '"prompt_hash"' in md
    assert '"model"' in md


def test_prompt_hash_matches_file(env):
    _write_screened(env["screened"], [_sense("run#0", "en-run-en-verb-0")])
    _write_table(env["table"], [])
    batch = batches.build_batch(env["screened"], 10, table_path=env["table"])
    raw = open(batches.prompt_path(), "rb").read()
    assert batch.prompt_hash == hashlib.sha256(raw).hexdigest()
    assert batch.prompt_version == "v1"


def test_json_round_trips_items(env):
    _write_screened(env["screened"], _30_senses())
    _write_table(env["table"], [])
    batch = batches.build_batch(env["screened"], 10, table_path=env["table"])
    payload = json.loads(batches.render_json(batch))
    assert payload["id"] == batch.id
    assert payload["prompt_hash"] == batch.prompt_hash
    assert [it["sense_id"] for it in payload["items"]] == [
        it["sense_id"] for it in batch.items]


def test_save_and_list_batches(env):
    _write_screened(env["screened"], _30_senses())
    _write_table(env["table"], [])
    batch = batches.build_batch(env["screened"], 10, table_path=env["table"])
    saved = batches.save_batch(batch)
    assert saved.status == "exported"
    rows = batches.list_batches()
    assert len(rows) == 1
    assert rows[0]["id"] == batch.id
    assert rows[0]["size"] == 10
    assert rows[0]["status"] == "exported"
    assert rows[0]["answered"] == 0
    assert rows[0]["approved"] == 0
    assert "created_at" in rows[0]
    base = os.path.join(env["root"], "webui", "batches", batch.id)
    for name in ("batch.json", "batch.md", "batch.json-data"):
        assert os.path.isfile(os.path.join(base, name))
    assert os.path.isdir(os.path.join(base, "answers"))
