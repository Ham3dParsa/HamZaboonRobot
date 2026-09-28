"""P04 batch import + approve tests (frozen contracts, behavior-first).

Covers the phase-04 P04 half (P06 repair composer is the sibling's):

- validate_answer_sheet: happy path + every strict-reject class
  (unknown sense_id / bad enum / link-without-target / none-with-target /
  prompt_hash mismatch / model missing / coverage gap / duplicate /
  non-JSON) — whole batch rejected via farsi BatchImportError, never
  partial.
- stage_import: happy path sets in_review (+answers stored, labels
  untouched); rejects leave batch + labels untouched.
- approve: subset finalize appends labels.jsonl with
  annotator=gemini:<batch-id>; rejected return to pool (re-exportable
  after cancel); status imported with counts.
"""

from __future__ import annotations

import json
import os

import pytest

from factory.webui import batches


def _write_screened(path, senses):
    with open(path, "w", encoding="utf-8") as handle:
        for entry in senses:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _sense(short, full, gloss="a gloss", example="an example",
           tags=None, lemma="run"):
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


def _write_table(path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("kaikki_sense_id\twordnet_sensekey\tmethod\tevidence\tprovenance\n")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = str(tmp_path / "data")
    os.makedirs(root)
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", root)
    screened = str(tmp_path / "screened.jsonl")
    table = str(tmp_path / "table.tsv")
    labels = os.path.join(root, "webui", "labels.jsonl")
    return {"root": root, "screened": screened, "table": table,
            "labels": labels}


def _12_senses():
    return [_sense("run#%d" % i, "en-run-en-verb-%d" % i) for i in range(12)]


def _make_batch(env):
    _write_screened(env["screened"], _12_senses())
    _write_table(env["table"])
    batch = batches.build_batch(env["screened"], 10,
                                table_path=env["table"])
    return batches.save_batch(batch)


def _sheet(batch, mutate=None):
    verdicts = []
    for pos, item in enumerate(batch.items):
        if pos % 2 == 0:
            verdicts.append({"sense_id": item["sense_id"],
                             "verdict": "link",
                             "target_synset": "run%2:38:00::"})
        else:
            verdicts.append({"sense_id": item["sense_id"],
                             "verdict": "none",
                             "target_synset": None})
    payload = {"model": "gemini-2.5-flash",
               "prompt_hash": batch.prompt_hash,
               "verdicts": verdicts}
    if mutate:
        mutate(payload)
    return json.dumps(payload, ensure_ascii=False)


def _batch_import():
    from factory.webui import batch_import

    return batch_import


def _meta(batch_id, env):
    with open(os.path.join(env["root"], "webui", "batches",
                           batch_id, "batch.json"),
              encoding="utf-8") as handle:
        return json.load(handle)


def _answers(batch_id, env):
    base = os.path.join(env["root"], "webui", "batches",
                        batch_id, "answers")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    return names


# --- validate_answer_sheet -------------------------------------------------


def test_validate_happy_returns_staged_in_batch_order(env):
    mod = _batch_import()
    batch = _make_batch(env)
    staged = mod.validate_answer_sheet(batch, _sheet(batch))
    assert [v["sense_id"] for v in staged] == [
        it["sense_id"] for it in batch.items]
    assert staged[0] == {"sense_id": "run#0", "verdict": "link",
                         "target_synset": "run%2:38:00::"}
    assert staged[1] == {"sense_id": "run#1", "verdict": "none",
                         "target_synset": None}


def test_validate_accepts_sheet_wrapped_in_chat_prose(env):
    mod = _batch_import()
    batch = _make_batch(env)
    text = ("Sure! Here is my answer sheet:\n```json\n%s\n```\nHope it helps!"
            % _sheet(batch))
    staged = mod.validate_answer_sheet(batch, text)
    assert len(staged) == 10


def test_validate_rejects_unknown_sense_id(env):
    mod = _batch_import()
    batch = _make_batch(env)

    def mutate(payload):
        payload["verdicts"][0]["sense_id"] = "ghost#9"

    with pytest.raises(mod.BatchImportError) as excinfo:
        mod.validate_answer_sheet(batch, _sheet(batch, mutate))
    assert "ghost#9" in str(excinfo.value)
    assert list(excinfo.value.failing_ids) == ["ghost#9"]


def test_validate_rejects_bad_enum(env):
    mod = _batch_import()
    batch = _make_batch(env)

    def mutate(payload):
        payload["verdicts"][3]["verdict"] = "maybe"

    with pytest.raises(mod.BatchImportError) as excinfo:
        mod.validate_answer_sheet(batch, _sheet(batch, mutate))
    assert "run#3" in str(excinfo.value)


@pytest.mark.parametrize("target", [None, "", "   "])
def test_validate_rejects_link_without_target(env, target):
    mod = _batch_import()
    batch = _make_batch(env)

    def mutate(payload):
        payload["verdicts"][0]["target_synset"] = target

    with pytest.raises(mod.BatchImportError) as excinfo:
        mod.validate_answer_sheet(batch, _sheet(batch, mutate))
    assert "run#0" in str(excinfo.value)


def test_validate_rejects_none_with_target(env):
    mod = _batch_import()
    batch = _make_batch(env)

    def mutate(payload):
        payload["verdicts"][1]["target_synset"] = "run%2:38:00::"

    with pytest.raises(mod.BatchImportError) as excinfo:
        mod.validate_answer_sheet(batch, _sheet(batch, mutate))
    assert "run#1" in str(excinfo.value)


def test_validate_rejects_prompt_hash_mismatch(env):
    mod = _batch_import()
    batch = _make_batch(env)

    def mutate(payload):
        payload["prompt_hash"] = "0" * 64

    with pytest.raises(mod.BatchImportError):
        mod.validate_answer_sheet(batch, _sheet(batch, mutate))


@pytest.mark.parametrize("model", [None, "", "   "])
def test_validate_rejects_missing_model(env, model):
    mod = _batch_import()
    batch = _make_batch(env)

    def mutate(payload):
        if model is None:
            del payload["model"]
        else:
            payload["model"] = model

    with pytest.raises(mod.BatchImportError):
        mod.validate_answer_sheet(batch, _sheet(batch, mutate))


def test_validate_rejects_coverage_gap(env):
    mod = _batch_import()
    batch = _make_batch(env)

    def mutate(payload):
        payload["verdicts"] = payload["verdicts"][:-1]

    with pytest.raises(mod.BatchImportError) as excinfo:
        mod.validate_answer_sheet(batch, _sheet(batch, mutate))
    assert "run#9" in str(excinfo.value)


def test_validate_rejects_duplicate_sense_id(env):
    mod = _batch_import()
    batch = _make_batch(env)

    def mutate(payload):
        payload["verdicts"].append(dict(payload["verdicts"][0]))

    with pytest.raises(mod.BatchImportError) as excinfo:
        mod.validate_answer_sheet(batch, _sheet(batch, mutate))
    assert "run#0" in str(excinfo.value)


def test_validate_rejects_non_json(env):
    mod = _batch_import()
    batch = _make_batch(env)
    with pytest.raises(mod.BatchImportError):
        mod.validate_answer_sheet(batch, "here is my review, looks good!")


def test_validate_rejects_non_dict_json(env):
    mod = _batch_import()
    batch = _make_batch(env)
    with pytest.raises(mod.BatchImportError):
        mod.validate_answer_sheet(batch, "[1, 2, 3]")


def test_validate_rejects_verdicts_not_a_list(env):
    mod = _batch_import()
    batch = _make_batch(env)

    def mutate(payload):
        payload["verdicts"] = {"sense_id": "run#0"}

    with pytest.raises(mod.BatchImportError):
        mod.validate_answer_sheet(batch, _sheet(batch, mutate))


# --- stage_import ------------------------------------------------------------


def test_stage_happy_sets_in_review(env):
    mod = _batch_import()
    batch = _make_batch(env)
    out = mod.stage_import(batch.id, _sheet(batch))
    assert out == {"staged": 10}
    meta = _meta(batch.id, env)
    assert meta["status"] == "in_review"
    assert meta["answered"] == 10
    assert meta["approved"] == 0
    assert len(_answers(batch.id, env)) == 1
    # Nothing finalized yet: labels store untouched.
    assert not os.path.exists(env["labels"])


def test_stage_reject_leaves_batch_untouched(env):
    mod = _batch_import()
    batch = _make_batch(env)

    def mutate(payload):
        payload["verdicts"][2]["verdict"] = "maybe"

    with pytest.raises(mod.BatchImportError):
        mod.stage_import(batch.id, _sheet(batch, mutate))
    meta = _meta(batch.id, env)
    assert meta["status"] == "exported"
    assert meta["answered"] == 0
    assert _answers(batch.id, env) == []
    assert not os.path.exists(env["labels"])


def test_stage_unknown_batch(env):
    mod = _batch_import()
    with pytest.raises(ValueError, match="VALIDATION-unknown-batch"):
        mod.stage_import("no-such-batch", "{}")


def test_stage_twice_rejected(env):
    mod = _batch_import()
    batch = _make_batch(env)
    mod.stage_import(batch.id, _sheet(batch))
    with pytest.raises(mod.BatchImportError):
        mod.stage_import(batch.id, _sheet(batch))
    assert len(_answers(batch.id, env)) == 1


# --- approve -----------------------------------------------------------------


def test_approve_happy_subset(env):
    mod = _batch_import()
    batch = _make_batch(env)
    mod.stage_import(batch.id, _sheet(batch))
    keep = [it["sense_id"] for it in batch.items[:6]]
    out = mod.approve(batch.id, keep, "op1")
    assert out == {"finalized": 6, "returned": 4}

    with open(env["labels"], encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    assert len(records) == 6
    assert [r["sense_id"] for r in records] == keep
    for rec in records:
        assert rec["annotator"] == "gemini:%s" % batch.id
        assert rec["stratum"] == "supervised"
        assert rec["lemma"] == "run"
    by_id = {r["sense_id"]: r for r in records}
    assert by_id["run#0"]["verdict"] == "link"
    assert by_id["run#0"]["target_synset"] == "run%2:38:00::"
    assert by_id["run#1"]["verdict"] == "none"
    assert by_id["run#1"]["target_synset"] is None

    meta = _meta(batch.id, env)
    assert meta["status"] == "imported"
    assert meta["approved"] == 6
    assert meta["returned"] == 4
    assert meta["reviewed_by"] == "op1"


def test_approve_unknown_id_rejected_labels_untouched(env):
    mod = _batch_import()
    batch = _make_batch(env)
    mod.stage_import(batch.id, _sheet(batch))
    with pytest.raises(mod.BatchImportError):
        mod.approve(batch.id, ["run#0", "ghost#9"], "op1")
    assert not os.path.exists(env["labels"])
    assert _meta(batch.id, env)["status"] == "in_review"


def test_approve_on_unstaged_batch_rejected(env):
    mod = _batch_import()
    batch = _make_batch(env)
    with pytest.raises(mod.BatchImportError):
        mod.approve(batch.id, [it["sense_id"] for it in batch.items], "op1")
    assert not os.path.exists(env["labels"])


def test_approve_empty_reviewer_rejected(env):
    mod = _batch_import()
    batch = _make_batch(env)
    mod.stage_import(batch.id, _sheet(batch))
    with pytest.raises(mod.BatchImportError):
        mod.approve(batch.id, ["run#0"], "   ")
    assert not os.path.exists(env["labels"])


def test_approve_empty_ids_finalizes_zero(env):
    mod = _batch_import()
    batch = _make_batch(env)
    mod.stage_import(batch.id, _sheet(batch))
    out = mod.approve(batch.id, [], "op1")
    assert out == {"finalized": 0, "returned": 10}
    assert not os.path.exists(env["labels"])
    assert _meta(batch.id, env)["status"] == "imported"


def test_rejected_ids_reexportable_after_cancel(env):
    mod = _batch_import()
    batch = _make_batch(env)
    mod.stage_import(batch.id, _sheet(batch))
    keep = [it["sense_id"] for it in batch.items[:6]]
    mod.approve(batch.id, keep, "op1")
    batches.cancel_batch(batch.id)
    nxt = batches.build_batch(env["screened"], 10, table_path=env["table"])
    got = [it["sense_id"] for it in nxt.items]
    # Approved ids are judged (labels); rejected ids return to the queue.
    for sid in keep:
        assert sid not in got
    assert "run#6" in got and "run#9" in got
