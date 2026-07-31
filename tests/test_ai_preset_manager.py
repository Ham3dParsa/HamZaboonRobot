import os
import tempfile
import unittest

from services import db
from services.db import schema as db_schema
from tools.AI_preset_manager.server import app


class ClonePresetApiTest(unittest.TestCase):
    """Regression tests for the AI Preset Manager clone endpoint."""

    SOURCE = "src_preset"

    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        new_path = os.path.join(cls.tempdir.name, "test.sqlite")
        cls._prev_db = db.DB_PATH
        cls._prev_db_schema = db_schema.DB_PATH
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.set_preset(
            name=cls.SOURCE,
            base_url="https://example.com/v1",
            model="test-model",
            api_key="$TEST_KEY",
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
        )
        db.set_preset_priority(cls.SOURCE, 4)
        db.set_preset_enabled(cls.SOURCE, False)
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls._prev_db
        db_schema.DB_PATH = cls._prev_db_schema
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
        self.assertEqual(p["api_key"], "$TEST_KEY")
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
        self.assertEqual(p["is_custom"], 1)

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
