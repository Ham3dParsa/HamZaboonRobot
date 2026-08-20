"""A2-3 / R2 — single-source NFC `normalize_word` + backfill migration.

Locked contract (2026-08-20): owner = services/db/schema.py; NFC recipe
everywhere; full backfill of saved_words.normalized_word; on NFC collision
keep the most-recently-active row and delete the older duplicate.
"""

import os
import sqlite3
import tempfile
import unittest

from services import db
from services.db import schema as db_schema


class NormalizeWordSingleSourceTests(unittest.TestCase):
    """A2-3: public NFC normalize_word collapses canonically-equivalent forms."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def test_normalize_word_is_public_and_nfc(self):
        """Decomposed and precomposed spellings normalize to the same key."""
        self.assertEqual(
            db.normalize_word("cafe\u0301"),
            db.normalize_word("caf\u00e9"),
        )

    def test_saved_word_dedup_folds_nfc_equivalents(self):
        """A decomposed-spelling duplicate must not create a second saved card."""
        self.assertTrue(db.add_saved_word(1, "caf\u00e9", "fr"))
        # Same word typed in decomposed form: must NOT add a second card.
        self.assertFalse(db.add_saved_word(1, "cafe\u0301", "fr"))
        with db.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM saved_words WHERE user_id=1 AND lang='fr'"
            ).fetchone()["c"]
        self.assertEqual(count, 1)


class NormalizeBackfillMigrationTests(unittest.TestCase):
    """A2-3: init_db re-normalizes legacy saved_words.normalized_word (NFC)."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _seed_legacy_rows(self):
        """Insert rows with pre-NFC normalized_word, simulating legacy data.

        init_db runs first to create the schema; the backfill marker is then
        cleared so the subsequent re-init (in each test) re-runs the backfill
        against these freshly-seeded legacy rows.
        """
        db.init_db()
        with db.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # A pre-deploy DB has not yet run the NFC backfill.
            conn.execute(
                "DELETE FROM settings WHERE key='_migration_word_normalization_done'"
            )
            # Two rows that collide under NFC (precomposed vs decomposed "café").
            conn.execute(
                "INSERT INTO saved_words (user_id, word, lang, normalized_word, "
                "added_at, entry_source, first_exposure_done) "
                "VALUES (1, 'caf\u00e9', 'fr', 'caf\u00e9', "
                "'2026-01-01T00:00:00+00:00', 'manual', 1)"
            )
            conn.execute(
                "INSERT INTO saved_words (user_id, word, lang, normalized_word, "
                "added_at, last_review_at, entry_source, first_exposure_done) "
                "VALUES (1, 'cafe\u0301', 'fr', 'cafe\u0301', "
                "'2026-01-01T00:00:00+00:00', '2026-01-05T00:00:00+00:00', "
                "'manual', 1)"
            )
            conn.commit()

    def test_backfill_renormalizes_and_resolves_collision(self):
        """Re-init re-normalizes legacy rows; on collision keeps the more active."""
        self._seed_legacy_rows()
        db.init_db()
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT word, normalized_word, last_review_at FROM saved_words "
                "WHERE user_id=1 AND lang='fr'"
            ).fetchall()
        # Collision resolved: the more-active (last_review_at set) row survives.
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["word"], "cafe\u0301")
        # The surviving row's normalized_word is the NFC key.
        self.assertEqual(rows[0]["normalized_word"], db.normalize_word("cafe\u0301"))

    def test_backfill_is_idempotent(self):
        """A second init run does not change already-normalized rows."""
        self._seed_legacy_rows()
        db.init_db()
        with db.get_conn() as conn:
            before = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND lang='fr'"
            ).fetchall()
        db.init_db()
        with db.get_conn() as conn:
            after = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND lang='fr'"
            ).fetchall()
        self.assertEqual([r["id"] for r in before], [r["id"] for r in after])

    def test_backfill_tolerates_legacy_schema_without_added_at(self):
        """Backfill still re-normalizes when a legacy saved_words lacks added_at."""
        conn = sqlite3.connect(db.DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE saved_words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    word TEXT,
                    lang TEXT,
                    normalized_word TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO saved_words (user_id, word, lang, normalized_word) "
                "VALUES (1, 'cafe\u0301', 'fr', 'cafe\u0301')"
            )
            conn.commit()
        finally:
            conn.close()
        db.init_db()
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT normalized_word FROM saved_words "
                "WHERE user_id=1 AND lang='fr'"
            ).fetchone()
        self.assertEqual(row["normalized_word"], db.normalize_word("cafe\u0301"))

    def test_backfill_tolerates_null_word_rows(self):
        """A row with a NULL word must not abort init_db during the backfill."""
        db.init_db()
        with db.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM settings WHERE key='_migration_word_normalization_done'"
            )
            conn.execute(
                "INSERT INTO saved_words (user_id, word, lang, normalized_word) "
                "VALUES (1, NULL, 'fr', NULL)"
            )
            conn.commit()
        db.init_db()  # must not raise AttributeError on the NULL word
        with db.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM saved_words WHERE user_id=1 AND lang='fr'"
            ).fetchone()["c"]
        self.assertEqual(count, 1)