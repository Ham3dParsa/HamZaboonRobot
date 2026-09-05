"""Retention purges: llm_requests 90d rollup + review_events 90d prune (T2).

Proves aggregate-then-drop exactness on fixture DBs:
  - old rows aggregate exactly into the rollup/counters, then vanish;
  - dashboard readers return identical totals before and after;
  - scheduling fields untouched; FSRS next-due identical;
  - migration works on fresh + upgraded DBs with row preservation.
"""

from __future__ import annotations

import datetime
import os
import tempfile
import threading
import unittest

from services import db
from services.db import schema as db_schema


OLD_TS = "2020-01-01T00:00:00+00:00"
OLD_TS2 = "2020-01-02T00:00:00+00:00"
OLD_TS3 = "2020-01-03T00:00:00+00:00"
OLD_DAY = "2020-01-01"
OLD_DAY2 = "2020-01-02"


class _DbCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_db_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    def _insert_llm(self, rid, date, created, cost_usd, tokens=20,
                    outcome="success", latency=100, user_id=1):
        prompt = tokens // 2
        completion = tokens - prompt
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO llm_requests(request_id, created_at, request_date, "
                "user_id, plan, request_kind, model, outcome, prompt_tokens, "
                "completion_tokens, total_tokens, input_cost_usd_per_million, "
                "output_cost_usd_per_million, usd_to_toman_rate, cost_usd, "
                "cost_toman, latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, ?, ?)",
                (rid, created, date, user_id, "free", "ask", "m1", outcome,
                 prompt, completion, tokens, 0.25, 1.5, 100000,
                 cost_usd, cost_usd * 100000, latency),
            )

    def _summarize_key(self, summary):
        return {
            key: summary.get(key)
            for key in (
                "request_count", "prompt_tokens", "completion_tokens",
                "total_tokens", "cost_usd", "cost_toman", "input_cost_usd",
                "output_cost_usd", "input_cost_toman", "output_cost_toman",
                "avg_latency_ms", "success_count", "billed_failure_count",
                "zero_cost_failure_count", "billed_failure_cost_usd",
                "billed_failure_cost_toman",
            )
        }

    def assertSummariesEqual(self, before, after):
        self.assertEqual(set(before), set(after))
        for key, value in before.items():
            if isinstance(value, float) or isinstance(after[key], float):
                self.assertAlmostEqual(float(after[key] or 0), float(value or 0),
                                       places=6, msg=key)
            else:
                self.assertEqual(after[key], value, msg=key)


class LlmRetentionPurgeTests(_DbCase):
    def test_purge_aggregates_exactly_then_deletes(self):
        self._insert_llm("old1", OLD_DAY, OLD_TS, 1.5, tokens=20,
                         outcome="success", latency=100)
        self._insert_llm("old2", OLD_DAY, OLD_TS2, 2.5, tokens=40,
                         outcome="failure_billed", latency=300)
        self._insert_llm("old3", OLD_DAY2, OLD_TS3, 5.0, tokens=10,
                         outcome="failure_zero_cost", latency=None)
        today = db_schema._today().isoformat()
        now = db_schema._utc_now().isoformat()
        self._insert_llm("new1", today, now, 7.0, tokens=30,
                         outcome="success", latency=200)
        before_summary = self._summarize_key(db.summarize_llm_requests({}))
        before_daily = db.daily_costs_grouped({})
        before_count = db.count_llm_requests_since("2000-01-01")
        self.assertEqual(before_count, 4)

        deleted = db.purge_old_llm_requests()
        self.assertEqual(deleted, 3)

        with db.get_conn() as conn:
            cutoff = (db_schema._today() - datetime.timedelta(days=90)).isoformat()
            left = conn.execute(
                "SELECT COUNT(*) AS c FROM llm_requests WHERE request_date < ?",
                (cutoff,),
            ).fetchone()["c"]
            self.assertEqual(left, 0)
            remaining = conn.execute(
                "SELECT request_id FROM llm_requests ORDER BY request_id"
            ).fetchall()
            self.assertEqual([r["request_id"] for r in remaining], ["new1"])
            roll = {r["request_date"]: dict(r) for r in conn.execute(
                "SELECT * FROM llm_daily_rollup ORDER BY request_date").fetchall()}
        self.assertEqual(set(roll), {OLD_DAY, OLD_DAY2})
        self.assertEqual(roll[OLD_DAY]["request_count"], 2)
        self.assertAlmostEqual(roll[OLD_DAY]["cost_usd"], 4.0, places=6)
        self.assertEqual(roll[OLD_DAY]["total_tokens"], 60)
        self.assertEqual(roll[OLD_DAY]["success_count"], 1)
        self.assertEqual(roll[OLD_DAY]["billed_failure_count"], 1)
        self.assertEqual(roll[OLD_DAY]["latency_count"], 2)
        self.assertEqual(roll[OLD_DAY2]["request_count"], 1)
        self.assertAlmostEqual(roll[OLD_DAY2]["cost_usd"], 5.0, places=6)
        self.assertEqual(roll[OLD_DAY2]["zero_cost_failure_count"], 1)
        self.assertEqual(roll[OLD_DAY2]["latency_count"], 0)

        after_summary = self._summarize_key(db.summarize_llm_requests({}))
        self.assertSummariesEqual(before_summary, after_summary)
        self.assertSummariesEqual(
            self._summarize_key(db.summarize_llm_requests(
                {"start_date": "2000-01-01", "end_date": "2100-01-01"})),
            after_summary,
        )
        after_daily = db.daily_costs_grouped({})
        self.assertEqual(set(after_daily), set(before_daily))
        for day, value in before_daily.items():
            self.assertAlmostEqual(after_daily[day], value, places=6, msg=day)
        self.assertEqual(db.count_llm_requests_since("2000-01-01"), before_count)
        # Recent-window readers untouched.
        recent = db.recent_llm_requests({}, limit=10)
        self.assertIn("new1", [r["request_id"] for r in recent])
        # Idempotent re-run.
        self.assertEqual(db.purge_old_llm_requests(), 0)
        self.assertSummariesEqual(
            before_summary, self._summarize_key(db.summarize_llm_requests({})))

    def test_dimensional_filters_stay_raw_only(self):
        self._insert_llm("old9", OLD_DAY, OLD_TS, 1.0)
        db.purge_old_llm_requests()
        # Dimensional filter cannot use the per-day rollup: raw-only, no crash.
        self.assertEqual(
            db.summarize_llm_requests({"plan": "free"}).get("request_count"), 0)
        self.assertEqual(db.breakdown_llm_requests("plan", {"plan": "free"}), [])

    def test_concurrent_double_run_does_not_double_rollup(self):
        # Two overlapping purgers race the same old rows: the sums live inside
        # the same transaction as the UPSERT+DELETE, so the loser re-selects
        # only rows the winner has not deleted yet and adds nothing twice.
        self._insert_llm("oldA", OLD_DAY, OLD_TS, 1.5, tokens=20,
                         outcome="success", latency=100)
        self._insert_llm("oldB", OLD_DAY, OLD_TS2, 2.5, tokens=40,
                         outcome="failure_billed", latency=300)
        barrier = threading.Barrier(2)
        results: list = []
        errors: list = []

        def _run():
            try:
                barrier.wait(timeout=10)
                results.append(db.purge_old_llm_requests())
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        workers = [threading.Thread(target=_run) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        self.assertFalse(
            [w for w in workers if w.is_alive()], "purge threads hung")
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(sorted(results), [0, 2])
        with db.get_conn() as conn:
            roll = {r["request_date"]: dict(r) for r in conn.execute(
                "SELECT * FROM llm_daily_rollup").fetchall()}
        self.assertEqual(roll[OLD_DAY]["request_count"], 2)
        self.assertAlmostEqual(roll[OLD_DAY]["cost_usd"], 4.0, places=6)
        # Steady state afterwards: nothing left to roll up.
        self.assertEqual(db.purge_old_llm_requests(), 0)


class ReviewRetentionPruneTests(_DbCase):
    def _word(self, user_id=1, word="hello"):
        db.create_user_if_needed(user_id, "learner")
        db.add_saved_word(user_id, word, "en", {"word": word})
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT id FROM saved_words WHERE user_id=?", (user_id,)).fetchone()["id"]

    def _insert_event(self, word_id, user_id, grade, created, outcome=None):
        outcome = outcome or ("again" if grade == 1 else "recalled")
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO review_events(word_id, user_id, grade, activity_type, "
                "outcome, created_at) VALUES (?, ?, ?, 'srs_review', ?, ?)",
                (word_id, user_id, grade, outcome, created),
            )

    def _counters(self, word_id):
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT total_reviews, lapses, stability, difficulty, "
                "last_review_at, next_review_at, next_review "
                "FROM saved_words WHERE id=?", (word_id,)).fetchone()
        return dict(row)

    def test_grade_path_increments_counters(self):
        wid = self._word()
        db.record_review_event(wid, 1, 3, "srs_review")
        self.assertEqual((self._counters(wid)["total_reviews"],
                          self._counters(wid)["lapses"]), (1, 0))
        db.record_review_event(wid, 1, 1, "srs_review")
        self.assertEqual((self._counters(wid)["total_reviews"],
                          self._counters(wid)["lapses"]), (2, 1))

    def test_prune_keep_rule_counters_and_scheduling_exact(self):
        wid = self._word()
        # 5 old legacy rows (bypass the counter path on purpose) + 1 recent.
        for idx, grade in enumerate([1, 2, 3, 4, 2]):
            self._insert_event(wid, 1, grade, f"2020-01-0{idx + 1}T00:00:00+00:00")
        db.record_review_event(wid, 1, 3, "srs_review")
        with db.get_conn() as conn:
            before_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM review_events WHERE word_id=? "
                "ORDER BY created_at DESC, id DESC", (wid,)).fetchall()]
        keep_expected = set(before_ids[:2])
        before_events = db.recent_events_for_words([wid], 1, per_word=2)
        before_sched = self._counters(wid)
        total_before = db.count_review_events_total()
        stats_before = db.get_user_learning_stats(1)["review_events"]
        self.assertEqual(total_before, 1)  # only the API-recorded row counted
        self.assertEqual(stats_before, 1)

        pruned = db.prune_old_review_events()
        self.assertEqual(pruned, 4)

        with db.get_conn() as conn:
            after_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM review_events WHERE word_id=?", (wid,)).fetchall()]
        self.assertEqual(set(after_ids), keep_expected)
        # Counters healed to lifetime totals (6 events, 1 lapse).
        after_sched = self._counters(wid)
        self.assertEqual(after_sched["total_reviews"], 6)
        self.assertEqual(after_sched["lapses"], 1)
        # Scheduling fields untouched.
        for key in ("stability", "difficulty", "last_review_at",
                    "next_review_at", "next_review"):
            self.assertEqual(after_sched[key], before_sched[key], msg=key)
        # Readers identical / exact.
        self.assertEqual(db.recent_events_for_words([wid], 1, per_word=2),
                         before_events)
        self.assertEqual(db.count_review_events_total(), 6)
        self.assertEqual(db.get_user_learning_stats(1)["review_events"], 6)
        # Idempotent.
        self.assertEqual(db.prune_old_review_events(), 0)
        self.assertEqual(db.count_review_events_total(), 6)

    def test_prune_chunked_batches_match_single_pass(self):
        wid = self._word()
        for idx, grade in enumerate([1, 2, 3, 4, 2]):
            self._insert_event(wid, 1, grade, f"2020-01-0{idx + 1}T00:00:00+00:00")
        db.record_review_event(wid, 1, 3, "srs_review")
        pruned = db.prune_old_review_events(batch=2)
        self.assertEqual(pruned, 4)
        with db.get_conn() as conn:
            remaining = conn.execute(
                "SELECT COUNT(*) AS c FROM review_events WHERE word_id=?",
                (wid,)).fetchone()["c"]
        self.assertEqual(remaining, 2)
        after = self._counters(wid)
        self.assertEqual((after["total_reviews"], after["lapses"]), (6, 1))
        # Idempotent.
        self.assertEqual(db.prune_old_review_events(), 0)

    def test_grade_after_prune_stays_exact(self):
        wid = self._word()
        self._insert_event(wid, 1, 2, OLD_TS)
        self._insert_event(wid, 1, 2, OLD_TS2)
        self._insert_event(wid, 1, 1, OLD_TS3)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE saved_words SET first_exposure_done=1, "
                "last_review_at='2020-02-01T00:00:00+00:00', "
                "next_review_at='2020-02-02T00:00:00+00:00' WHERE id=?", (wid,))
        db.prune_old_review_events()
        before = self._counters(wid)
        self.assertEqual((before["total_reviews"], before["lapses"]), (3, 1))
        result = db.grade_word_review(wid, 3, 1)
        self.assertTrue(result.ok)
        db.record_review_event(wid, 1, 3, "srs_review")
        after = self._counters(wid)
        self.assertEqual((after["total_reviews"], after["lapses"]), (4, 1))
        self.assertNotEqual(after["next_review_at"], before["next_review_at"])
        self.assertEqual(db.count_review_events_total(), 4)

    def test_migration_backfill_batches_by_id_range(self):
        import sqlite3 as _sqlite
        from unittest.mock import patch as _patch

        path = os.path.join(self.tempdir.name, "batched.sqlite")
        # NOTE: sqlite3.Connection is not closed by the context manager
        # (it only commits); close explicitly so Windows can clean up.
        conn = _sqlite.connect(path)
        try:
            conn.executescript(
                "CREATE TABLE saved_words (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER, word TEXT, lang TEXT, normalized_word TEXT, "
                "card_data TEXT, next_review TEXT, added_at TEXT); "
                "CREATE TABLE review_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "word_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
                "outcome TEXT NOT NULL, grade INTEGER, activity_type TEXT, "
                "created_at TEXT NOT NULL); "
                "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT); "
                "INSERT INTO settings(key, value) VALUES ('fsrs_migration_done', '1'); "
            )
            for idx in range(5):
                conn.execute(
                    "INSERT INTO saved_words(user_id, word, lang, normalized_word) "
                    "VALUES (1, ?, 'en', ?)", (f"w{idx}", f"w{idx}"))
                wid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute(
                    "INSERT INTO review_events(word_id, user_id, outcome, grade, "
                    "created_at) VALUES (?, 1, 'recalled', 3, "
                    "'2020-01-01T00:00:00+00:00'), (?, 1, 'again', 1, "
                    "'2020-01-02T00:00:00+00:00')", (wid, wid))
            conn.commit()
        finally:
            conn.close()
        db.DB_PATH = path
        db_schema.DB_PATH = path
        with _patch.object(db_schema, "_BACKFILL_BATCH", 2):
            db.init_db()
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT total_reviews, lapses FROM saved_words ORDER BY id").fetchall()
            marker = conn.execute(
                "SELECT value FROM settings WHERE key='_migration_review_counters_done'"
            ).fetchone()
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual((row["total_reviews"], row["lapses"]), (2, 1))
        self.assertEqual(marker["value"], "1")

    def test_migration_backfill_on_upgrade(self):
        import sqlite3 as _sqlite

        path = os.path.join(self.tempdir.name, "upgrade.sqlite")
        # NOTE: sqlite3.Connection is not closed by the context manager
        # (it only commits); close explicitly so Windows can clean up.
        conn = _sqlite.connect(path)
        try:
            conn.executescript(
                "CREATE TABLE saved_words (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER, word TEXT, lang TEXT, normalized_word TEXT, "
                "card_data TEXT, next_review TEXT, added_at TEXT); "
                "CREATE TABLE review_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "word_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
                "outcome TEXT NOT NULL, grade INTEGER, activity_type TEXT, "
                "created_at TEXT NOT NULL); "
                "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT); "
                "INSERT INTO settings(key, value) VALUES ('fsrs_migration_done', '1'); "
                "INSERT INTO saved_words(user_id, word, lang, normalized_word) "
                "VALUES (1, 'keep', 'en', 'keep'); "
                "INSERT INTO review_events(word_id, user_id, outcome, grade, "
                "created_at) VALUES (1, 1, 'recalled', 3, '2020-01-01T00:00:00+00:00'), "
                "(1, 1, 'again', 1, '2020-01-02T00:00:00+00:00'), "
                "(1, 1, 'again', NULL, '2020-01-03T00:00:00+00:00');"
            )
            conn.commit()
        finally:
            conn.close()
        db.DB_PATH = path
        db_schema.DB_PATH = path
        db.init_db()
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT total_reviews, lapses, word FROM saved_words").fetchone()
            self.assertEqual(row["word"], "keep")
            self.assertEqual(row["total_reviews"], 3)
            self.assertEqual(row["lapses"], 2)
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("llm_daily_rollup", tables)
        # Idempotent re-init keeps counters, not doubled.
        db.init_db()
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT total_reviews, lapses FROM saved_words").fetchone()
        self.assertEqual((row["total_reviews"], row["lapses"]), (3, 2))


if __name__ == "__main__":
    unittest.main()
