"""REF3-T2: chunked IN (<=500) + ROW_NUMBER window equivalence.

Exact-equivalence vs the unchunked reference (single-IN query + Python
slice) for ``recent_events_for_words`` and ``get_saved_words_by_ids``:
>500 ids, boundary 500/501, empty/missing/dup ids, per_word 1/2/5.
Chunk discipline: each IN-list <= 500 placeholders and total IN-queries
<= ceil(n/500) (== ceil proves real chunking for n > 500).

No shape change: result containers/row keys identical to pre-change.
"""

from __future__ import annotations

import math
import os
import re
import tempfile
import unittest
from unittest import mock

from services import db
from services.db import schema as db_schema
from services.db import reviews as reviews_mod
from services.db import words as words_mod

_CHUNK = 500


class _ConnProxy:
    def __init__(self, real, calls):
        self._real = real
        self._calls = calls

    def execute(self, sql, params=()):
        self._calls.append((sql, tuple(params)))
        return self._real.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _CMProxy:
    def __init__(self, real_cm, calls):
        self._real_cm = real_cm
        self._calls = calls
        self._real = None

    def __enter__(self):
        self._real = self._real_cm.__enter__()
        return _ConnProxy(self._real, self._calls)

    def __exit__(self, *args):
        return self._real_cm.__exit__(*args)


def _patched_get_conn(real_get_conn, calls):
    def _inner():
        return _CMProxy(real_get_conn(), calls)
    return _inner


def _in_placeholders(sql: str) -> int:
    """Placeholders of the single IN-list (ignores user_id / rn params)."""
    match = re.search(r"IN\s*\(([^)]*)\)", sql)
    assert match is not None, f"no IN-list found in SQL: {sql!r}"
    return match.group(1).count("?")


class ChunkInEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_db_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    # -- helpers ------------------------------------------------------
    def _word_ids(self, n: int) -> list[int]:
        with db.transaction() as conn:
            for i in range(n):
                conn.execute(
                    "INSERT INTO saved_words(user_id, word, lang, "
                    "normalized_word, next_review, review_status, added_at, "
                    "first_exposure_done, stability, difficulty, entry_source) "
                    "VALUES (?, ?, 'en', ?, date('now'), 'idle', "
                    "datetime('now'), 0, 0.0, 5.0, 'manual')",
                    (1, f"w{i}", f"w{i}"),
                )
            rows = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 ORDER BY id ASC"
            ).fetchall()
        return [int(r["id"]) for r in rows]

    def _insert_events(self, word_id: int, grades: list[int], base: str) -> None:
        with db.transaction() as conn:
            for i, grade in enumerate(grades):
                conn.execute(
                    "INSERT INTO review_events(word_id, user_id, grade, "
                    "activity_type, grade_source, outcome, created_at) "
                    "VALUES (?, 1, ?, 'srs_review', 'direct_button', "
                    "'recalled', ?)",
                    (word_id, grade, f"{base}{i:04d}"),
                )

    def _reference_recent(self, word_ids, user_id, per_word):
        """Pre-change oracle: single IN query, ORDER BY, Python slice."""
        if not word_ids:
            return {}
        placeholders = ",".join("?" * len(word_ids))
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT word_id, grade, activity_type, created_at "
                "FROM review_events "
                f"WHERE user_id=? AND word_id IN ({placeholders}) "
                "ORDER BY word_id, created_at DESC, id DESC",
                (user_id, *word_ids),
            ).fetchall()
        grouped: dict[int, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row["word_id"], []).append(dict(row))
        return {wid: evs[:per_word] for wid, evs in grouped.items()}

    def _reference_by_ids(self, word_ids, user_id):
        if not word_ids:
            return []
        placeholders = ",".join("?" * len(word_ids))
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_words "
                f"WHERE user_id=? AND id IN ({placeholders})",
                (user_id, *word_ids),
            ).fetchall()
        by_id = {row["id"]: dict(row) for row in rows}
        return [by_id[wid] for wid in word_ids if wid in by_id]

    def _run_recent_tracked(self, word_ids, per_word):
        calls: list = []
        real = reviews_mod.get_conn
        with mock.patch.object(
            reviews_mod, "get_conn", _patched_get_conn(real, calls)
        ):
            result = db.recent_events_for_words(word_ids, 1, per_word=per_word)
        return result, calls

    def _run_by_ids_tracked(self, word_ids):
        calls: list = []
        real = words_mod.get_conn
        with mock.patch.object(
            words_mod, "get_conn", _patched_get_conn(real, calls)
        ):
            result = db.get_saved_words_by_ids(word_ids, 1)
        return [dict(r) for r in result], calls

    def _assert_chunk_discipline(self, calls, n):
        self.assertLessEqual(len(calls), math.ceil(n / _CHUNK))
        if n > _CHUNK:
            self.assertEqual(len(calls), math.ceil(n / _CHUNK))
        for sql, _params in calls:
            self.assertLessEqual(_in_placeholders(sql), _CHUNK)

    # -- recent_events_for_words --------------------------------------
    def test_recent_empty_opens_no_query(self):
        result, calls = self._run_recent_tracked([], per_word=2)
        self.assertEqual(result, {})
        self.assertEqual(calls, [])

    def test_recent_equivalence_1200_ids(self):
        wids = self._word_ids(1200)
        for idx, wid in enumerate(wids):
            grades = [2, 3, 4][: (idx % 3) + 1]
            self._insert_events(wid, grades, f"2026-01-{(idx % 28) + 1:02d}T00:")
        result, calls = self._run_recent_tracked(wids, per_word=2)
        self.assertEqual(result, self._reference_recent(wids, 1, 2))
        self._assert_chunk_discipline(calls, 1200)

    def test_recent_boundary_500_501(self):
        wids = self._word_ids(501)
        for wid in wids:
            self._insert_events(wid, [2, 3], "2026-02-01T00:")
        result500, calls500 = self._run_recent_tracked(wids[:500], per_word=2)
        self.assertEqual(result500, self._reference_recent(wids[:500], 1, 2))
        self._assert_chunk_discipline(calls500, 500)
        result501, calls501 = self._run_recent_tracked(wids, per_word=2)
        self.assertEqual(result501, self._reference_recent(wids, 1, 2))
        self._assert_chunk_discipline(calls501, 501)

    def test_recent_missing_dup_ids(self):
        wids = self._word_ids(5)
        for wid in wids:
            self._insert_events(wid, [2, 4, 3], "2026-03-01T00:")
        mixed = [wids[0], 999999, wids[0], wids[2], 888888, wids[2]]
        result, _calls = self._run_recent_tracked(mixed, per_word=2)
        self.assertEqual(result, self._reference_recent(mixed, 1, 2))
        self.assertNotIn(999999, result)
        self.assertNotIn(888888, result)

    def test_recent_per_word_1_2_5(self):
        wids = self._word_ids(600)
        for wid in wids:
            self._insert_events(
                wid, [1, 2, 3, 4, 2, 3], "2026-04-01T00:"
            )
        for per_word in (1, 2, 5):
            with self.subTest(per_word=per_word):
                result, calls = self._run_recent_tracked(wids, per_word)
                self.assertEqual(
                    result, self._reference_recent(wids, 1, per_word)
                )
                for evs in result.values():
                    self.assertLessEqual(len(evs), per_word)
                self._assert_chunk_discipline(calls, 600)

    def test_recent_tiebreaker_id_desc(self):
        wids = self._word_ids(1)
        wid = wids[0]
        with db.transaction() as conn:
            for grade in (2, 4):
                conn.execute(
                    "INSERT INTO review_events(word_id, user_id, grade, "
                    "activity_type, grade_source, outcome, created_at) "
                    "VALUES (?, 1, ?, 'srs_review', 'direct_button', "
                    "'recalled', '2026-05-01T00:00:00+00:00')",
                    (wid, grade),
                )
        result, _calls = self._run_recent_tracked([wid], per_word=2)
        self.assertEqual([e["grade"] for e in result[wid]], [4, 2])

    # -- get_saved_words_by_ids ----------------------------------------
    def test_by_ids_empty_opens_no_query(self):
        result, calls = self._run_by_ids_tracked([])
        self.assertEqual(result, [])
        self.assertEqual(calls, [])

    def test_by_ids_equivalence_1200_order_restore(self):
        wids = self._word_ids(1200)
        shuffled = wids[::-1]
        result, calls = self._run_by_ids_tracked(shuffled)
        self.assertEqual(result, self._reference_by_ids(shuffled, 1))
        self.assertEqual(
            [r["id"] for r in result], [w for w in shuffled if w in set(wids)]
        )
        self._assert_chunk_discipline(calls, 1200)

    def test_by_ids_boundary_500_501(self):
        wids = self._word_ids(501)
        result500, calls500 = self._run_by_ids_tracked(wids[:500])
        self.assertEqual(result500, self._reference_by_ids(wids[:500], 1))
        self._assert_chunk_discipline(calls500, 500)
        result501, calls501 = self._run_by_ids_tracked(wids)
        self.assertEqual(result501, self._reference_by_ids(wids, 1))
        self._assert_chunk_discipline(calls501, 501)

    def test_by_ids_missing_dup_order(self):
        wids = self._word_ids(5)
        mixed = [wids[3], 999999, wids[1], wids[3], wids[0]]
        result, _calls = self._run_by_ids_tracked(mixed)
        expected = self._reference_by_ids(mixed, 1)
        self.assertEqual([r["id"] for r in result], [r["id"] for r in expected])


if __name__ == "__main__":
    unittest.main()
