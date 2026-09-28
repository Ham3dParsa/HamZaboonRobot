"""P08 flow integration: supervised-arbitration batch + gallery via routes.

Behavior-from-spec (frozen contracts in
``.opencode/plans/factory/plan-supervised-arbitration.md``), driven only
through the Flask routing layer (``factory/webui/server.py``), with DB
snapshot isolation per ``integration-test-proto`` and zero AI tokens
(answer sheets are static JSON — no model is ever called):

- (a) issue -> import -> approve: batch exports, answer sheet stages
  (``in_review``), operator approve finalizes a subset, approved rows
  append to ``labels.jsonl``, and the batch history (``GET /api/batches``)
  shows progress (answered/approved + statuses);
- (b) import rejection: a bad sheet rejects the WHOLE batch (422 +
  ``repair_request``), nothing is staged (status stays ``exported``,
  ``answers/`` empty, no labels), and a corrected sheet still imports;
- (c) gallery build for a synthetic run dir through
  ``GET /api/gallery?run=`` (plus honest 400/404 errors).
"""

from __future__ import annotations

import csv
import json
import os
import unittest

from tests.test_integration import helpers

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


TSV_HEADER = ["kaikki_sense_id", "wordnet_sensekey", "method", "evidence",
              "lemma", "kaikki_gloss"]

TSV_ROWS = [
    {"kaikki_sense_id": "en-run-en-verb-A",
     "wordnet_sensekey": "run%2:38:00::",
     "method": "LINK:2-sig", "evidence": "Sa:j=0.40+Sd:hyp=move",
     "lemma": "run", "kaikki_gloss": "To move fast."},
    {"kaikki_sense_id": "en-run-en-verb-B",
     "wordnet_sensekey": "-",
     "method": "UNMAPPED", "evidence": "0sig",
     "lemma": "run", "kaikki_gloss": "To own something."},
]

VERDICTS_DOC = {"verdicts": [
    {"kid": "en-run-en-verb-A", "lemma": "run", "verdict": "LINK",
     "winner_index": 1, "winner_sensekey": "run%2:38:00::",
     "wordnet_evidence": "move fast || words: run",
     "votes": [
         {"ok": True, "verdict": "LINK", "winner_index": 1},
         {"ok": True, "verdict": "LINK", "winner_index": 1},
     ]},
]}


def _write_run_dir(run_dir):
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "link_table.tsv"), "w",
              encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TSV_HEADER,
                                delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(TSV_ROWS)
    with open(os.path.join(run_dir, "verdicts.json"), "w",
              encoding="utf-8") as handle:
        json.dump(VERDICTS_DOC, handle, ensure_ascii=False)


class _SupervisedIsolation(unittest.TestCase):
    def setUp(self):
        from services import db
        from services.db import schema as db_schema

        self._holder, self.db_path = helpers.fresh_db_from_snapshot()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        db.DB_PATH = self.db_path
        db_schema.DB_PATH = self.db_path
        db.init_db()
        import tempfile

        self._root_holder = tempfile.TemporaryDirectory()
        self.data_root = os.path.join(self._root_holder.name, "data")
        os.makedirs(self.data_root)
        self._prev_data_root = os.environ.get("HAMZABAN_DATA_ROOT")
        os.environ["HAMZABAN_DATA_ROOT"] = self.data_root
        self.screened = os.path.join(self._root_holder.name,
                                     "screened.jsonl")
        _write_screened(self.screened)
        self._prev_screened = os.environ.get("HAMZABAN_SCREENED_PATH")
        os.environ["HAMZABAN_SCREENED_PATH"] = self.screened
        self.client = webui.app.test_client()

    def tearDown(self):
        from services import db
        from services.db import schema as db_schema

        if self._prev_data_root is None:
            os.environ.pop("HAMZABAN_DATA_ROOT", None)
        else:
            os.environ["HAMZABAN_DATA_ROOT"] = self._prev_data_root
        if self._prev_screened is None:
            os.environ.pop("HAMZABAN_SCREENED_PATH", None)
        else:
            os.environ["HAMZABAN_SCREENED_PATH"] = self._prev_screened
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self._root_holder.cleanup()
        self._holder.cleanup()

    def _labels_path(self):
        return os.path.join(self.data_root, "webui", "labels.jsonl")

    def _read_labels(self):
        path = self._labels_path()
        if not os.path.isfile(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def _issue_batch(self, size=10):
        resp = self.client.post("/api/batches", json={"size": size})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        return resp.get_json()["batch"]

    def _sheet_for(self, batch_id, verdict="none"):
        fetched = self.client.get("/api/batches/%s" % batch_id).get_json()
        return json.dumps({
            "model": "p08-synthetic",
            "prompt_hash": fetched["batch"]["prompt_hash"],
            "verdicts": [{"sense_id": it["sense_id"], "verdict": verdict,
                          "target_synset": None}
                         for it in fetched["items"]],
        })


class SupervisedArbitrationHappyFlowTests(_SupervisedIsolation):
    def test_issue_import_approve_labels_and_history(self):
        batch = self._issue_batch(size=10)
        self.assertEqual(batch["status"], "exported")
        self.assertEqual(batch["answered"], 0)
        self.assertEqual(batch["approved"], 0)

        fetched = self.client.get(
            "/api/batches/%s" % batch["id"]).get_json()
        self.assertEqual(len(fetched["items"]), 10)
        self.assertTrue(fetched["md"].strip())

        staged = self.client.post(
            "/api/batches/%s/import" % batch["id"],
            json={"answer_sheet": self._sheet_for(batch["id"])})
        self.assertEqual(staged.status_code, 200, staged.get_json())
        self.assertEqual(staged.get_json()["staged"], 10)
        self.assertEqual(staged.get_json()["status"], "in_review")

        history = self.client.get("/api/batches").get_json()["batches"]
        progress = [b for b in history if b["id"] == batch["id"]][0]
        self.assertEqual(progress["status"], "in_review")
        self.assertEqual(progress["answered"], 10)

        keep = [it["sense_id"] for it in fetched["items"][:4]]
        done = self.client.post(
            "/api/batches/%s/approve" % batch["id"],
            json={"ids": keep, "reviewer": "p08-operator"})
        self.assertEqual(done.status_code, 200, done.get_json())
        self.assertEqual(done.get_json()["finalized"], 4)
        self.assertEqual(done.get_json()["returned"], 6)
        self.assertEqual(done.get_json()["status"], "imported")

        stored = self._read_labels()
        self.assertEqual(len(stored), 4)
        for rec in stored:
            self.assertIn(rec["sense_id"], keep)
            self.assertEqual(rec["verdict"], "none")
            self.assertIsNone(rec["target_synset"])
            self.assertEqual(rec["stratum"], "supervised")
            self.assertEqual(rec["annotator"],
                             "p08-synthetic:%s" % batch["id"])

        history = self.client.get("/api/batches").get_json()["batches"]
        final = [b for b in history if b["id"] == batch["id"]][0]
        self.assertEqual(final["status"], "imported")
        self.assertEqual(final["approved"], 4)


class SupervisedArbitrationRejectFlowTests(_SupervisedIsolation):
    def test_import_rejection_whole_batch_repair_nothing_staged(self):
        batch = self._issue_batch(size=10)
        bad = json.dumps({"model": "p08-synthetic",
                          "prompt_hash": batch["prompt_hash"],
                          "verdicts": [{"sense_id": "ghost#0",
                                        "verdict": "none",
                                        "target_synset": None}]})
        resp = self.client.post(
            "/api/batches/%s/import" % batch["id"],
            json={"answer_sheet": bad})
        self.assertEqual(resp.status_code, 422, resp.get_json())
        body = resp.get_json()
        self.assertIn("ghost#0", body["error"])
        self.assertIn("ghost#0", body.get("failing_ids") or [])
        self.assertTrue((body.get("repair_request") or "").strip())
        self.assertIn(batch["id"], body["repair_request"])

        fetched = self.client.get(
            "/api/batches/%s" % batch["id"]).get_json()
        self.assertEqual(fetched["batch"]["status"], "exported")
        self.assertEqual(fetched["batch"]["answered"], 0)

        answers_dir = os.path.join(
            self.data_root, "webui", "batches", batch["id"], "answers")
        staged_files = [n for n in os.listdir(answers_dir)
                        if n.endswith(".json")] if os.path.isdir(
                            answers_dir) else []
        self.assertEqual(staged_files, [])
        self.assertEqual(self._read_labels(), [])

        retry = self.client.post(
            "/api/batches/%s/import" % batch["id"],
            json={"answer_sheet": self._sheet_for(batch["id"])})
        self.assertEqual(retry.status_code, 200, retry.get_json())
        self.assertEqual(retry.get_json()["staged"], 10)


class SupervisedGalleryFlowTests(_SupervisedIsolation):
    def test_gallery_build_for_synthetic_run(self):
        run_dir = os.path.join(self.data_root, "run_demo")
        _write_run_dir(run_dir)
        resp = self.client.get("/api/gallery", query_string={"run": run_dir})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.content_type)
        page = resp.get_data(as_text=True)
        self.assertIn("<html", page)
        self.assertIn("To move fast.", page)
        gallery_path = os.path.join(run_dir, "gallery.html")
        self.assertTrue(os.path.isfile(gallery_path))

    def test_gallery_honest_missing_errors(self):
        self.assertEqual(self.client.get("/api/gallery").status_code, 400)
        missing = self.client.get(
            "/api/gallery", query_string={"run": "no-such-run"})
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
