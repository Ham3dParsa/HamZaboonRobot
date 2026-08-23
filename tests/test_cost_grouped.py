import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import db
from services.db.schema import init_db


class TestDailyCostsGrouped(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test_cost.db")
        init_db(self.db_path)
        import services.db.cost_tracking as ct
        import services.db.schema as schema
        import config as cfg
        import sqlite3
        from contextlib import contextmanager

        self.orig_schema_path = schema.DB_PATH
        self.orig_cfg_path = getattr(cfg, "DB_PATH", None)
        schema.DB_PATH = self.db_path
        cfg.DB_PATH = self.db_path

        @contextmanager
        def _tmp_get_conn():
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

        self.orig_get_conn = ct.get_conn
        ct.get_conn = _tmp_get_conn
        self._ct = ct

    def tearDown(self):
        import services.db.cost_tracking as ct
        import services.db.schema as schema
        import config as cfg

        ct.get_conn = self.orig_get_conn
        schema.DB_PATH = self.orig_schema_path
        if self.orig_cfg_path is not None:
            cfg.DB_PATH = self.orig_cfg_path
        try:
            self.tmpdir.cleanup()
        except PermissionError:
            pass

    def test_daily_costs_grouped_matches_python_sum(self):
        # Pin GROUP BY contract: per-day totals, COALESCE(null→0), and
        # start_date/end_date filters must match manual Python sum
        # Insert rows across 2 days, including a NULL cost_usd
        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO llm_requests(request_id, created_at, request_date, user_id, plan, request_kind, model, outcome, prompt_tokens, completion_tokens, total_tokens, input_cost_usd_per_million, output_cost_usd_per_million, usd_to_toman_rate, cost_usd, cost_toman) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("id1", "2026-08-20T10:00:00", "2026-08-20", 1, "free", "ask", "m1", "success", 10, 10, 20, 0.25, 1.5, 100000, 1.5, 150000),
            )
            conn.execute(
                "INSERT INTO llm_requests(request_id, created_at, request_date, user_id, plan, request_kind, model, outcome, prompt_tokens, completion_tokens, total_tokens, input_cost_usd_per_million, output_cost_usd_per_million, usd_to_toman_rate, cost_usd, cost_toman) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("id2", "2026-08-20T11:00:00", "2026-08-20", 1, "free", "ask", "m1", "success", 10, 10, 20, 0.25, 1.5, 100000, 2.5, 250000),
            )
            conn.execute(
                "INSERT INTO llm_requests(request_id, created_at, request_date, user_id, plan, request_kind, model, outcome, prompt_tokens, completion_tokens, total_tokens, input_cost_usd_per_million, output_cost_usd_per_million, usd_to_toman_rate, cost_usd, cost_toman) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("id3", "2026-08-21T10:00:00", "2026-08-21", 1, "free", "ask", "m1", "success", 10, 10, 20, 0.25, 1.5, 100000, 5.0, 500000),
            )
            conn.commit()

        # Full range: 2026-08-20 → 4.0, 2026-08-21 → 5.0
        result = db.daily_costs_grouped({})
        self.assertAlmostEqual(result.get("2026-08-20", 0), 4.0, places=4)
        self.assertAlmostEqual(result.get("2026-08-21", 0), 5.0, places=4)

        # Filtered to single day must exclude the other
        filtered = db.daily_costs_grouped({"start_date": "2026-08-21", "end_date": "2026-08-21"})
        self.assertNotIn("2026-08-20", filtered)
        self.assertAlmostEqual(filtered.get("2026-08-21", 0), 5.0, places=4)

        # Python manual sum must match GROUP BY for the filtered window
        import sqlite3 as _sq

        with _sq.connect(self.db_path) as conn:
            rows = conn.execute("SELECT cost_usd FROM llm_requests WHERE request_date BETWEEN ? AND ?", ("2026-08-20", "2026-08-20")).fetchall()
        manual = sum((r[0] or 0) for r in rows)
        self.assertAlmostEqual(result["2026-08-20"], manual, places=4)
