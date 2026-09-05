"""Nightly retention sweep wiring (T3, plan-retention R7).

  - Scheduler-level (fakes): the job calls each purge exactly once, in the
    locked cheapest-lock-first order.
  - Overrun: an exhausted budget stops cleanly with the remainder deferred.
  - Integration: one full nightly run on a fixture DB shrinks every table
    and keeps live rows.
  - Backup pin: background scheduling runs the backup daily 05:30 and the
    sweep daily 03:30 APP_TZ, leaving the pre-existing intervals untouched.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from services import db
from services import retention
from services import scheduling
from services import tts_cache
from services.db import schema as db_schema

EXPECTED_ORDER = (
    "hourly_usage",
    "query_expired",
    "session_reports",
    "config",
    "llm",
    "reviews",
    "sessions",
    "slots",
    "tts",
    "grammar",
)

OLD_TS = "2020-01-01T00:00:00+00:00"


class NightlyOrderTests(unittest.TestCase):
    def test_step_names_match_locked_order(self):
        self.assertEqual(retention.NIGHTLY_STEP_NAMES, EXPECTED_ORDER)

    def test_job_calls_each_purge_once_in_order(self):
        calls: list[str] = []
        patches = [
            patch.object(db, "prune_preset_hourly_usage",
                         side_effect=lambda *a, **k: calls.append("hourly_usage")),
            patch.object(db, "cleanup_expired_query_results",
                         side_effect=lambda *a, **k: calls.append("query_expired")),
            patch.object(db, "purge_expired_session_reports",
                         side_effect=lambda *a, **k: calls.append("session_reports") or 0),
            patch.object(db, "prune_config_tests",
                         side_effect=lambda *a, **k: calls.append("config") or 0),
            patch.object(db, "purge_old_llm_requests",
                         side_effect=lambda *a, **k: calls.append("llm") or 0),
            patch.object(db, "prune_old_review_events",
                         side_effect=lambda *a, **k: calls.append("reviews") or 0),
            patch.object(db, "purge_stale_study_sessions",
                         side_effect=lambda *a, **k: calls.append("sessions") or {}),
            patch.object(scheduling, "purge_old_session_slot_keys",
                         side_effect=lambda *a, **k: calls.append("slots") or 0),
            patch.object(tts_cache, "purge_tts_cache",
                         side_effect=lambda *a, **k: calls.append("tts") or {}),
            patch.object(db, "purge_grammar_tips",
                         side_effect=lambda *a, **k: calls.append("grammar") or 0),
        ]
        for p in patches:
            p.start()
        try:
            result = asyncio.run(retention.nightly_retention_job(MagicMock()))
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(calls, list(EXPECTED_ORDER))
        self.assertEqual(result["ran"], list(EXPECTED_ORDER))
        self.assertEqual(result["skipped"], [])

    def test_exhausted_budget_stops_cleanly_for_next_night(self):
        with patch.object(retention, "NIGHTLY_BUDGET_SECONDS", 0):
            result = asyncio.run(retention.nightly_retention_job(MagicMock()))
        self.assertEqual(result["ran"], [])
        self.assertEqual(result["skipped"], list(EXPECTED_ORDER))

    def test_overlapping_run_is_skipped_run_once(self):
        async def _hold():
            await retention._NIGHTLY_LOCK.acquire()
            try:
                result = await retention.nightly_retention_job(MagicMock())
            finally:
                retention._NIGHTLY_LOCK.release()
            return result

        result = asyncio.run(_hold())
        self.assertEqual(result["ran"], [])
        self.assertEqual(result["skipped"], list(EXPECTED_ORDER))


class NightlyIntegrationTests(unittest.TestCase):
    """One full sweep on a fixture DB: stale rows shrink, live rows survive."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db_path = db.DB_PATH
        self.prev_schema_db_path = db_schema.DB_PATH
        self.prev_tts_path = tts_cache.TTS_CACHE_DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        tts_cache.TTS_CACHE_DB_PATH = os.path.join(self.tempdir.name, "tts_cache.db")
        tts_cache._DB_INITIALIZED = False
        tts_cache.clear_lru()
        self._seed()

    def tearDown(self):
        db.DB_PATH = self.prev_db_path
        db_schema.DB_PATH = self.prev_schema_db_path
        tts_cache.TTS_CACHE_DB_PATH = self.prev_tts_path
        tts_cache._DB_INITIALIZED = False
        tts_cache.clear_lru()
        self.tempdir.cleanup()

    def _seed(self):
        now = db_schema._utc_now().isoformat()
        today = db_schema._today().isoformat()
        # llm_requests: 1 stale + 1 live.
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO llm_requests(request_id, created_at, request_date, "
                "user_id, plan, request_kind, model, outcome, prompt_tokens, "
                "completion_tokens, total_tokens, input_cost_usd_per_million, "
                "output_cost_usd_per_million, usd_to_toman_rate, cost_usd, "
                "cost_toman, latency_ms) VALUES "
                "('old-llm', ?, '2020-01-01', 1, 'free', 'ask', 'm', 'success', "
                "10, 10, 20, 0.25, 1.5, 100000, 1.0, 100000, 50), "
                "('live-llm', ?, ?, 1, 'free', 'ask', 'm', 'success', "
                "10, 10, 20, 0.25, 1.5, 100000, 1.0, 100000, 50)",
                (OLD_TS, now, today),
            )
            # query_results: 1 expired + 1 live.
            conn.execute(
                "INSERT INTO query_results(token, user_id, query_text, word, lang, "
                "result_json, created_at, expires_at) VALUES "
                "('tok-old', 1, 'q', 'w', 'en', '{}', ?, ?), "
                "('tok-live', 1, 'q', 'w', 'en', '{}', ?, ?)",
                (OLD_TS, OLD_TS, now,
                 (db_schema._utc_now() + datetime.timedelta(days=30)).isoformat()),
            )
            # session_reports: 1 stale + 1 live.
            conn.execute(
                "INSERT INTO session_reports(user_id, session_date, created_at, "
                "report_json, is_admin) VALUES (1, '2020-01-01', ?, '{}', 0), "
                "(1, ?, ?, '{}', 0)",
                (OLD_TS, today, now),
            )
            # config_tests: 1 stale + 1 live.
            conn.execute(
                "INSERT INTO config_tests(test_type, preset_name, prompt, result, "
                "created_at) VALUES ('t', 'p', 'q', '{}', ?), ('t', 'p', 'q', '{}', ?)",
                (OLD_TS, now),
            )
            # review_events: 3 stale for one card (keep 2 newest) + counter seed.
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, normalized_word) "
                "VALUES (1, 'w', 'en', 'w')"
            )
            wid = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1").fetchone()["id"]
            for idx, ts in enumerate(
                ("2020-01-01T00:00:00+00:00", "2020-01-02T00:00:00+00:00",
                 "2020-01-03T00:00:00+00:00")):
                conn.execute(
                    "INSERT INTO review_events(word_id, user_id, grade, "
                    "activity_type, outcome, created_at) VALUES (?, 1, 3, "
                    "'srs_review', 'recalled', ?)", (wid, ts))
            self.word_id = wid
            # study_sessions + ledger: 1 stale session + 1 live + 1 stale ledger.
            conn.execute(
                "INSERT INTO study_sessions(user_id, session_date, state_json, "
                "updated_at) VALUES (1, '2020-01-01', '{}', ?)", (OLD_TS,))
            conn.execute(
                "INSERT INTO session_grade_ledger(user_id, word_id, activity_type, "
                "graded_at) VALUES (1, 1, 'srs_review', ?)", (OLD_TS,))
            # slot keys: 1 stale + today's live.
            conn.execute(
                "INSERT INTO settings(key, value) VALUES "
                "('sessions_used_1_2020-01-01', '3'), (?, '1')",
                (f"sessions_used_1_{today}",))
            # hourly usage: 1 stale bucket + 1 live bucket.
            live_bucket = db_schema._utc_now().isoformat()[:13]
            conn.execute(
                "INSERT INTO preset_hourly_usage(preset_name, hour_bucket, "
                "request_count, token_count) VALUES ('p', '2020-01-01T00', 5, 50), "
                "('p', ?, 2, 20)", (live_bucket,))
            # grammar_tips: 1 retired row.
            conn.execute(
                "INSERT INTO grammar_tips(user_id, tip_date, title, lang, goal, "
                "level, tip_json, created_at) VALUES "
                "(1, '2020-01-01', 't', 'en', 'g', 'l', '{}', ?)", (OLD_TS,))
        # tts_cache: 1 stale entry + 1 live entry (isolated tts db).
        from services import tts as tts_mod

        self.old_tts_key = tts_mod.tts_cache_key("oldword", "en")
        tts_cache.put_cached(self.old_tts_key, "en", "oldword", "fid-old", "fu-old", None)
        conn = __import__("sqlite3").connect(tts_cache.TTS_CACHE_DB_PATH, timeout=10)
        try:
            conn.execute(
                "UPDATE tts_cache SET last_used_at=? WHERE cache_key=?",
                ((db_schema._utc_now() - datetime.timedelta(days=200)).isoformat(),
                 self.old_tts_key),
            )
            conn.commit()
        finally:
            conn.close()
        tts_cache.clear_lru()
        self.live_tts_key = tts_mod.tts_cache_key("liveword", "en")
        tts_cache.put_cached(self.live_tts_key, "en", "liveword", "fid-live", "fu-live", None)
        tts_cache.clear_lru()

    def _count(self, table, where="", params=()):
        with db.get_conn() as conn:
            return conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} " + (f"WHERE {where}" if where else ""),
                params,
            ).fetchone()["c"]

    def test_full_sweep_shrinks_tables_and_keeps_live_rows(self):
        result = asyncio.run(retention.nightly_retention_job(MagicMock()))
        self.assertEqual(result["skipped"], [])

        self.assertEqual(
            [r["request_id"] for r in self._ids("llm_requests", "request_id")],
            ["live-llm"])
        with db.get_conn() as conn:
            roll = conn.execute(
                "SELECT COUNT(*) AS c FROM llm_daily_rollup").fetchone()["c"]
        self.assertGreaterEqual(roll, 1)

        self.assertEqual(self._count("query_results"), 1)
        self.assertEqual(self._count("session_reports"), 1)
        self.assertEqual(self._count("config_tests"), 1)
        self.assertEqual(self._count("review_events"), 2)
        self.assertEqual(self._count("study_sessions"), 0)
        self.assertEqual(self._count("session_grade_ledger"), 0)
        self.assertEqual(self._count("grammar_tips"), 0)
        self.assertEqual(
            self._count("settings", "key LIKE 'sessions_used\\_%' ESCAPE '\\'"), 1)
        self.assertEqual(self._count("preset_hourly_usage"), 1)

        with db.get_conn() as conn:
            live = conn.execute(
                "SELECT request_id FROM llm_requests").fetchone()["request_id"]
            self.assertEqual(live, "live-llm")
            tok = conn.execute("SELECT token FROM query_results").fetchone()["token"]
            self.assertEqual(tok, "tok-live")

        import sqlite3 as _sqlite

        conn = _sqlite.connect(tts_cache.TTS_CACHE_DB_PATH, timeout=10)
        try:
            keys = {r[0] for r in conn.execute("SELECT cache_key FROM tts_cache")}
        finally:
            conn.close()
        self.assertEqual(keys, {self.live_tts_key})

    def _ids(self, table, col):
        with db.get_conn() as conn:
            return conn.execute(f"SELECT {col} FROM {table} ORDER BY {col}").fetchall()


class BackupScheduleTests(unittest.TestCase):
    def test_nightly_and_backup_pinned_daily_outside_purge_hour_and_peak(self):
        import bot as bot_mod

        class FakeQueue:
            def __init__(self):
                self.repeating = []
                self.daily = []

            def run_repeating(self, cb, interval=None, first=None):
                self.repeating.append((cb, interval, first))

            def run_daily(self, cb, time=None, days=None):
                self.daily.append((cb, time))

        queue = FakeQueue()
        with patch.object(bot_mod, "OWNER_ID", 0):
            bot_mod.setup_background_jobs(queue)

        daily = {cb.__name__: t for cb, t in queue.daily}
        self.assertIn("nightly_retention_job", daily)
        self.assertIn("auto_backup_job", daily)
        nightly_t = daily["nightly_retention_job"]
        backup_t = daily["auto_backup_job"]
        self.assertEqual((nightly_t.hour, nightly_t.minute), (3, 30))
        self.assertEqual((backup_t.hour, backup_t.minute), (5, 30))
        self.assertEqual(str(nightly_t.tzinfo), str(backup_t.tzinfo))
        # Backup no longer fires on a repeating interval into the purge hour.
        repeating_names = [cb.__name__ for cb, _, _ in queue.repeating]
        self.assertNotIn("auto_backup_job", repeating_names)
        # Pre-existing intervals untouched: health / query-cleanup / grace.
        by_name = {cb.__name__: (i, f) for cb, i, f in queue.repeating}
        from config import CONNECTION_HEALTH_INTERVAL_SECONDS

        self.assertEqual(by_name["connection_health_job"],
                         (CONNECTION_HEALTH_INTERVAL_SECONDS,
                          CONNECTION_HEALTH_INTERVAL_SECONDS))
        self.assertEqual(by_name["cleanup_query_results_job"], (1800, 1800))
        self.assertEqual(by_name["grace_reset_job"], (1800, 1800))


if __name__ == "__main__":
    unittest.main()
