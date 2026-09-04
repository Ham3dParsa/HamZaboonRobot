"""100-user load-simulation GREEN test (locked plan scale/plan-load-sim-100, T1).

Drives ``tools.load_sim.driver.run_load`` with n=100 seed=7 through the REAL
routers (``bot.callback_router`` / ``bot.text_router``) on an isolated SQLite
file (snapshot-DB isolation via ``tests/test_integration/helpers.py``), with
all Telegram sends and AI steps mocked (AI budget: 0 real tokens — the real
``services.ai.ai.ask_card`` provider is patched to raise if ever reached).

Locked R4 gates asserted here:
- grade-path p95 under 800ms,
- zero quota double-spend,
- zero report loss,
- error rate under 0.5%.
"""

import unittest
from unittest.mock import MagicMock, patch

from tests.test_integration import helpers


class LoadSim100FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import bot
        from services import db
        from services.db import schema as db_schema

        self._holder, self.db_path = helpers.fresh_db_from_snapshot()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        db.DB_PATH = self.db_path
        db_schema.DB_PATH = self.db_path
        db.init_db()
        self._offline = patch.object(bot, "_telegram_offline", False)
        self._offline.start()
        # Zero-real-token guard: any reach of the real provider fails loudly.
        self._no_real_ai = patch(
            "services.ai.ai.ask_card",
            new=MagicMock(side_effect=AssertionError("real AI must not run")),
        )
        self._no_real_ai.start()

    def tearDown(self):
        from services import db
        from services.db import schema as db_schema

        self._no_real_ai.stop()
        self._offline.stop()
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self._holder.cleanup()

    async def test_100_users_meet_locked_r4_gates(self):
        from tools.load_sim.driver import run_load

        metrics = await run_load(
            n=100, seed=7, db_path=self.db_path, bot_mock=None, ai_mock=None
        )

        self.assertEqual(metrics["total"], 100)
        for key in (
            "telegram_429",
            "telegram_retries",
            "db_busy_retries",
            "ai_timeouts",
            "quota_double_spend",
            "report_loss",
        ):
            self.assertIn(key, metrics)

        grade_p95 = metrics["grade_p95_ms"]
        self.assertLess(
            grade_p95, 800, f"grade-path p95 under 800ms, got {grade_p95:.1f}ms"
        )
        self.assertEqual(
            metrics["quota_double_spend"], 0, "zero quota double-spend"
        )
        self.assertEqual(metrics["report_loss"], 0, "zero report loss")
        self.assertGreater(
            metrics["real_grades"], 0, "at least one real grade reached production"
        )
        self.assertLess(
            metrics["error_rate"], 0.005, f"error rate under 0.5%, got {metrics['error_rate']:.4f}"
        )


if __name__ == "__main__":
    unittest.main()
