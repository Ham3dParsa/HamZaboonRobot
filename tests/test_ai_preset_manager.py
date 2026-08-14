import os
import tempfile
import unittest
from unittest import mock

import config

from services import db
from services.db import schema as db_schema
from tools.AI_preset_manager.server import app

TEST_MASTER_KEY = "sd4H8UUr5ONYISGXcx468OQwFaUxaktNGGTPs9TBESg="


class ClonePresetApiTest(unittest.TestCase):
    """Regression tests for the AI Preset Manager clone endpoint."""

    SOURCE = "src_preset"
    SOURCE_KEY = "sk-clone-source-plain-123456789"

    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        new_path = os.path.join(cls.tempdir.name, "test.sqlite")
        cls._prev_db = db.DB_PATH
        cls._prev_db_schema = db_schema.DB_PATH
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        cls._master = mock.patch.object(config, "AI_MASTER_KEY", TEST_MASTER_KEY)
        cls._master.start()
        db.init_db()
        # A second enabled preset keeps the DB in a realistic state: Phase 4
        # removed auto-seeded builtins, so a disabled preset must coexist with
        # at least one other enabled preset for the R12 guard to permit it.
        db.set_preset(name="enabled_other", base_url="https://example.com/v1", model="m")
        db.set_preset(
            name=cls.SOURCE,
            base_url="https://example.com/v1",
            model="test-model",
            api_key=cls.SOURCE_KEY,
            temperature=0.7,
            max_output_tokens=2048,
            timeout_seconds=12.5,
            max_daily_req=3,
            max_concurrency=5,
            max_rpm=10,
            max_tpm=100,
            is_emergency=1,
            in_fallback_chain=0,
            group_label="g",
            input_cost_per_million=0.5,
            output_cost_per_million=1.5,
            enabled=0,
        )
        db.set_preset_priority(cls.SOURCE, 4)
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls._prev_db
        db_schema.DB_PATH = cls._prev_db_schema
        cls._master.stop()
        cls.tempdir.cleanup()

    def test_clone_copies_all_settings(self):
        resp = self.client.post(
            f"/api/presets/{self.SOURCE}/clone",
            json={"name": "clone_full"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["name"], "clone_full")

        p = db.get_preset("clone_full")
        self.assertIsNotNone(p)
        self.assertEqual(p["base_url"], "https://example.com/v1")
        self.assertEqual(p["model"], "test-model")
        self.assertNotEqual(p["api_key"], self.SOURCE_KEY)
        self.assertTrue(p["api_key"].startswith("v1:"))
        self.assertEqual(db.resolve_preset_key(p), self.SOURCE_KEY)
        self.assertEqual(p["temperature"], 0.7)
        self.assertEqual(p["max_output_tokens"], 2048)
        self.assertEqual(p["timeout_seconds"], 12.5)
        self.assertEqual(p["max_daily_req"], 3)
        self.assertEqual(p["max_concurrency"], 5)
        self.assertEqual(p["max_rpm"], 10)
        self.assertEqual(p["max_tpm"], 100)
        self.assertEqual(p["is_emergency"], 1)
        self.assertEqual(p["in_fallback_chain"], 0)
        self.assertEqual(p["group_label"], "g")
        self.assertEqual(p["input_cost_per_million"], 0.5)
        self.assertEqual(p["output_cost_per_million"], 1.5)
        self.assertEqual(p["priority"], 4)
        self.assertEqual(p["enabled"], 0)
        self.assertNotIn("is_custom", p, "is_custom column must be gone")

    def test_clone_default_name_uses_suffix(self):
        resp = self.client.post(f"/api/presets/{self.SOURCE}/clone", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["name"], f"{self.SOURCE}_copy")

    def test_clone_duplicate_name_returns_409(self):
        resp = self.client.post(
            f"/api/presets/{self.SOURCE}/clone",
            json={"name": "clone_dup"},
        )
        self.assertEqual(resp.status_code, 200)
        resp2 = self.client.post(
            f"/api/presets/{self.SOURCE}/clone",
            json={"name": "clone_dup"},
        )
        self.assertEqual(resp2.status_code, 409)

    def test_clone_missing_source_returns_404(self):
        resp = self.client.post("/api/presets/nonexistent/clone", json={})
        self.assertEqual(resp.status_code, 404)

    def test_put_rejects_removed_cost_fields(self):
        for field in ("cost_per_req", "cost_per_1k_tokens"):
            resp = self.client.put(
                f"/api/presets/{self.SOURCE}",
                json={field: 0.1},
            )
            self.assertEqual(resp.status_code, 400, field)

    def test_put_valid_field_still_works(self):
        resp = self.client.put(
            f"/api/presets/{self.SOURCE}",
            json={"temperature": 0.9},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(db.get_preset(self.SOURCE)["temperature"], 0.9)


if __name__ == "__main__":
    unittest.main()
