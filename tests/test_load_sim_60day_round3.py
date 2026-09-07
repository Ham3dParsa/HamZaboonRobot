"""Proof tests for 60-day load-sim round 3, T6 (V1-V3).

Harness-only, zero production change: V1 virtual app-day clock (in-harness
pinning of the production date seams, restored on exit), V2 per-table
growth attribution at milestone days, V3 fidelity resource envelope (RSS
delta, CPU seconds, grade + loop-lag percentiles). No production code is
touched; zero real AI tokens (fidelity miniature reuses the patient fake).
"""

import datetime
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_integration import helpers

EXPECTED_GROWTH_TABLES = (
    "saved_words",
    "review_events",
    "query_results",
    "session_reports",
    "llm_requests",
    "study_sessions",
    "ledger",
)

# Production files the virtual clock reads but must never modify.
_PRODUCTION_DATE_OWNERS = (
    "config/__init__.py",
    "services/db/schema.py",
    "services/db/users.py",
    "services/db/words.py",
    "services/db/sessions.py",
    "services/db/cost_tracking.py",
    "services/db/__init__.py",
    "services/scheduling.py",
    "services/utils/formatting.py",
    "handlers/study_handler.py",
    "handlers/user.py",
    "bot.py",
)


class VirtualClockSeamsTests(unittest.TestCase):
    def setUp(self):
        from services import db
        from services.db import schema as db_schema

        self._holder, self.db_path = helpers.fresh_db_from_snapshot()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        db.DB_PATH = self.db_path
        db_schema.DB_PATH = self.db_path
        db.init_db()

    def tearDown(self):
        from services import db
        from services.db import schema as db_schema

        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self._holder.cleanup()

    def test_virtual_day_pins_quota_streak_and_report_dates(self):
        import config
        from services import db
        from services import scheduling
        from tools.load_sim.virtual_clock import virtual_day

        real_today = datetime.datetime.now(config.APP_TZ).date().isoformat()
        d1 = (
            datetime.date.fromisoformat(real_today)
            - datetime.timedelta(days=9)
        ).isoformat()
        uid = 953001
        db.create_user_if_needed(uid, "virtualclock")

        with virtual_day(d1):
            self.assertEqual(config._app_today(), d1)
            self.assertTrue(db.reserve_word_query(uid, 5))
            row = db.get_user(uid)
            self.assertEqual(row["words_asked_date"], d1)
            status = db.get_quota_status(uid)
            self.assertIsNotNone(status)
            self.assertEqual(status["word_query"]["used"], 1)
            self.assertTrue(
                scheduling._session_key(uid).endswith(f"_{d1}")
            )
            self.assertEqual(db.touch_streak(uid), 1)
            row = db.get_user(uid)
            self.assertEqual(row["last_active_date"], d1)
            import handlers.study_handler as study_handler

            self.assertEqual(study_handler._app_today(), d1)

        self.assertEqual(config._app_today(), real_today)

    def test_virtual_day_gives_each_day_a_fresh_quota(self):
        from services import db
        from tools.load_sim.virtual_clock import virtual_day

        import config

        real_today = datetime.datetime.now(config.APP_TZ).date().isoformat()
        d1 = (
            datetime.date.fromisoformat(real_today)
            - datetime.timedelta(days=3)
        ).isoformat()
        d2 = (
            datetime.date.fromisoformat(real_today)
            - datetime.timedelta(days=2)
        ).isoformat()
        uid = 953002
        db.create_user_if_needed(uid, "virtualquota")

        with virtual_day(d1):
            self.assertTrue(db.reserve_word_query(uid, 1))
            # Day-1 quota exhausted on the virtual day.
            self.assertFalse(db.reserve_word_query(uid, 1))
        with virtual_day(d2):
            # A new virtual day starts from zero (would still fail on the
            # real clock, where both reserves share one app-day).
            self.assertTrue(db.reserve_word_query(uid, 1))
            row = db.get_user(uid)
            self.assertEqual(row["words_asked_date"], d2)

    def test_virtual_day_streak_accumulates_across_days(self):
        from services import db
        from tools.load_sim.virtual_clock import virtual_day

        import config

        real_today = datetime.datetime.now(config.APP_TZ).date().isoformat()
        d1 = (
            datetime.date.fromisoformat(real_today)
            - datetime.timedelta(days=5)
        ).isoformat()
        d2 = (
            datetime.date.fromisoformat(real_today)
            - datetime.timedelta(days=4)
        ).isoformat()
        uid = 953003
        db.create_user_if_needed(uid, "virtualstreak")

        with virtual_day(d1):
            self.assertEqual(db.touch_streak(uid), 1)
        with virtual_day(d2):
            # Consecutive virtual days increment (a real-today touch between
            # them would have reset this to 1).
            self.assertEqual(db.touch_streak(uid), 2)

    def test_production_files_mention_no_virtual_clock(self):
        for rel in _PRODUCTION_DATE_OWNERS:
            src = Path(rel).read_text(encoding="utf-8")
            self.assertNotIn("virtual_day", src, rel)
            self.assertNotIn("virtual_clock", src, rel)


class Round3FidelityMiniatureTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_miniature_growth_attribution_and_resources(self):
        from tools.load_sim.multiday import run_multiday_fidelity

        result = await run_multiday_fidelity(
            n=4,
            seed=11,
            db_path=self.db_path,
            days=3,
            patient=True,
            fast_scale=0.0001,
            query_cap=1,
        )
        self.assertEqual(result["violations"], [])

        # V2: one day-1 milestone snapshot naming exactly the ticket tables.
        growth = result["growth_by_table"]
        self.assertEqual(len(growth), 1)
        entry = growth[0]
        self.assertEqual(entry["day_n"], 1)
        self.assertEqual(tuple(entry["tables"].keys()), EXPECTED_GROWTH_TABLES)
        for name in EXPECTED_GROWTH_TABLES:
            self.assertIsInstance(entry["tables"][name], int)
            self.assertGreaterEqual(entry["tables"][name], 0)
        self.assertGreater(entry["db_bytes"], 0)
        # The fidelity replay really wrote: grades + review events exist.
        self.assertGreater(entry["tables"]["saved_words"], 0)
        self.assertGreater(entry["tables"]["review_events"], 0)

        # V3: resource envelope keys exist with sane ordering.
        res = result["fidelity_resources"]
        self.assertEqual(
            set(res.keys()),
            {
                "rss_before",
                "rss_after",
                "rss_delta",
                "cpu_seconds",
                "grade_ms",
                "loop_lag_ms",
            },
        )
        self.assertIsInstance(res["rss_delta"], int)
        self.assertEqual(res["rss_delta"], res["rss_after"] - res["rss_before"])
        self.assertGreaterEqual(res["cpu_seconds"], 0.0)
        for key in ("grade_ms", "loop_lag_ms"):
            dist = res[key]
            self.assertEqual(
                set(dist.keys()), {"p50", "p90", "p95", "p99", "max", "count"}
            )
            self.assertLessEqual(dist["p50"], dist["p90"])
            self.assertLessEqual(dist["p90"], dist["p95"])
            self.assertLessEqual(dist["p95"], dist["p99"])
            self.assertLessEqual(dist["p99"], dist["max"])
        self.assertGreater(res["grade_ms"]["count"], 0)
        self.assertGreater(res["grade_ms"]["max"], 0.0)
        self.assertGreater(res["loop_lag_ms"]["count"], 0)

        # Per-day grade latencies feed the aggregate.
        total_grades = sum(
            len(fday.get("grade_latencies_ms", []))
            for fday in result["fidelity_days"]
        )
        self.assertEqual(total_grades, res["grade_ms"]["count"])


if __name__ == "__main__":
    unittest.main()
