"""CARD-MODES T1 — canonical card-mode registry, schema columns, accessors,
and the deep `resolve_card_mode`/`resolve_card_mode_gate` resolvers.

Contract (locked 2026-08-15):
- Rule 4 precedence: user override -> plan value -> admin-global -> built-in
  `staged`; unknown stored values fall through (never crash).
- Rule 6 gates: per-card-type availability (`all`/`premium`), default `premium`.
- Schema changes verified on both fresh and upgraded DBs (see
  tests/test_migration_guards.py for the fresh+upgrade template).
"""

import os
import tempfile
import unittest

from services import db as db_module
from services.db import schema as db_schema
from services.db import users as users_module


def _column_names(table):
    with db_module.get_conn() as conn:
        return {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }


class CardModeRegistryTests(unittest.TestCase):
    """Canonical registry is exhaustive, unique, and self-consistent."""

    def test_card_types_are_unique(self):
        self.assertEqual(
            set(users_module.CARD_TYPES), {"first_exposure", "review"}
        )
        self.assertEqual(len(users_module.CARD_TYPES), len(set(users_module.CARD_TYPES)))

    def test_card_modes_are_unique_and_default_is_known(self):
        self.assertEqual(set(users_module.CARD_MODES), {"staged", "immediate"})
        self.assertEqual(len(users_module.CARD_MODES), len(set(users_module.CARD_MODES)))
        self.assertIn(users_module.DEFAULT_CARD_MODE, users_module.CARD_MODES)
        self.assertEqual(users_module.DEFAULT_CARD_MODE, "staged")

    def test_gate_values_are_unique_and_default_is_premium(self):
        self.assertEqual(set(users_module.CARD_MODE_GATES), {"all", "premium"})
        self.assertIn(users_module.DEFAULT_CARD_MODE_GATE, users_module.CARD_MODE_GATES)
        self.assertEqual(users_module.DEFAULT_CARD_MODE_GATE, "premium")


class CardModeSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "cardmodes.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_fresh_db_has_card_mode_columns(self):
        user_cols = _column_names("users")
        for col in ("first_exposure_mode", "review_mode"):
            self.assertIn(col, user_cols, f"users.{col} missing on fresh DB")
        plan_cols = _column_names("plans")
        for col in ("first_exposure_mode", "review_mode"):
            self.assertIn(col, plan_cols, f"plans.{col} missing on fresh DB")

    def test_init_db_idempotent_with_card_mode_columns(self):
        db_module.init_db()
        db_module.init_db()
        user_cols = _column_names("users")
        self.assertIn("first_exposure_mode", user_cols)
        self.assertIn("review_mode", user_cols)

    def test_global_card_mode_settings_seeded(self):
        expected = {
            "first_exposure_mode": "staged",
            "review_mode": "staged",
            "first_exposure_mode_gate": "premium",
            "review_mode_gate": "premium",
        }
        with db_module.get_conn() as conn:
            rows = {
                r["key"]: r["value"]
                for r in conn.execute(
                    "SELECT key, value FROM settings "
                    "WHERE key IN (?, ?, ?, ?)",
                    tuple(expected),
                ).fetchall()
            }
        self.assertEqual(rows, expected)


class CardModeResolverTests(unittest.TestCase):
    """Rule 4 precedence: user -> plan -> admin-global -> built-in default."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "cardmodes.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()
        users_module.create_user_if_needed(1, "tester")
        with db_module.get_conn() as conn:
            conn.execute("UPDATE users SET plan='silver' WHERE user_id=1")
            conn.commit()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_missing_user_falls_back_to_builtin_default(self):
        self.assertEqual(users_module.resolve_card_mode(999, "first_exposure"), "staged")
        self.assertEqual(users_module.resolve_card_mode(999, "review"), "staged")

    def test_global_setting_wins_over_builtin_default(self):
        users_module.set_global_card_mode("first_exposure", "immediate")
        self.assertEqual(users_module.resolve_card_mode(999, "first_exposure"), "immediate")

    def test_plan_value_wins_over_global(self):
        users_module.set_global_card_mode("review", "immediate")
        users_module.set_plan_card_mode("silver", "review", "staged")
        self.assertEqual(users_module.resolve_card_mode(1, "review"), "staged")

    def test_user_value_wins_over_plan_and_global(self):
        users_module.set_global_card_mode("first_exposure", "immediate")
        users_module.set_plan_card_mode("silver", "first_exposure", "immediate")
        users_module.set_user_card_mode(1, "first_exposure", "staged")
        self.assertEqual(users_module.resolve_card_mode(1, "first_exposure"), "staged")

    def test_unknown_user_value_falls_through_to_plan(self):
        users_module.set_plan_card_mode("silver", "review", "immediate")
        with db_module.get_conn() as conn:
            conn.execute(
                "UPDATE users SET review_mode='bogus' WHERE user_id=1"
            )
            conn.commit()
        self.assertEqual(users_module.resolve_card_mode(1, "review"), "immediate")

    def test_unknown_plan_value_falls_through_to_global(self):
        users_module.set_global_card_mode("first_exposure", "immediate")
        with db_module.get_conn() as conn:
            conn.execute(
                "UPDATE plans SET first_exposure_mode='weird' WHERE name='silver'"
            )
            conn.commit()
        self.assertEqual(users_module.resolve_card_mode(1, "first_exposure"), "immediate")

    def test_missing_plan_row_falls_through_to_global(self):
        users_module.set_global_card_mode("review", "immediate")
        with db_module.get_conn() as conn:
            conn.execute("UPDATE users SET plan='ghost_plan' WHERE user_id=1")
            conn.commit()
        self.assertEqual(users_module.resolve_card_mode(1, "review"), "immediate")

    def test_unknown_global_value_falls_through_to_default(self):
        """A bogus value stored directly in the global setting must fall back
        to the built-in default (contract: unknown values fall through at
        EVERY level, including the global one)."""
        with db_module.get_conn() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES ('first_exposure_mode', 'bogus') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            conn.commit()
        self.assertEqual(users_module.resolve_card_mode(999, "first_exposure"), "staged")

    def test_unknown_card_type_raises(self):
        with self.assertRaises(ValueError):
            users_module.resolve_card_mode(1, "bogus_type")

    def test_unknown_card_mode_raises_on_write(self):
        with self.assertRaises(ValueError):
            users_module.set_user_card_mode(1, "first_exposure", "bogus_mode")
        with self.assertRaises(ValueError):
            users_module.set_plan_card_mode("silver", "first_exposure", "bogus_mode")
        with self.assertRaises(ValueError):
            users_module.set_global_card_mode("first_exposure", "bogus_mode")


class CardModeGateTests(unittest.TestCase):
    """Rule 6: per-card-type availability, default premium."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "cardmodes.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def _user_with_plan(self, user_id, plan):
        users_module.create_user_if_needed(user_id, f"u{user_id}")
        with db_module.get_conn() as conn:
            conn.execute("UPDATE users SET plan=? WHERE user_id=?", (plan, user_id))
            conn.commit()

    def test_gate_defaults_to_premium(self):
        self.assertEqual(users_module.resolve_card_mode_gate("first_exposure"), "premium")
        self.assertEqual(users_module.resolve_card_mode_gate("review"), "premium")

    def test_unknown_stored_gate_falls_back_to_premium(self):
        """A bogus value stored directly in the gate setting must fall back to
        the default gate (contract: unknown stored values never crash)."""
        with db_module.get_conn() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES ('review_mode_gate', 'bogus') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            conn.commit()
        self.assertEqual(users_module.resolve_card_mode_gate("review"), "premium")

    def test_premium_gate_excludes_free_and_includes_bronze(self):
        self._user_with_plan(10, "free")
        self._user_with_plan(11, "bronze")
        self.assertFalse(users_module.card_mode_available(10, "first_exposure"))
        self.assertTrue(users_module.card_mode_available(11, "first_exposure"))

    def test_premium_gate_includes_paid_plans(self):
        for plan in ("silver", "gold", "emerald"):
            with self.subTest(plan=plan):
                user_id = {"silver": 20, "gold": 21, "emerald": 22}[plan]
                self._user_with_plan(user_id, plan)
                self.assertTrue(users_module.card_mode_available(user_id, "review"))

    def test_all_gate_opens_to_everyone(self):
        users_module.set_card_mode_gate("first_exposure", "all")
        self._user_with_plan(30, "free")
        self.assertTrue(users_module.card_mode_available(30, "first_exposure"))

    def test_gates_are_per_card_type(self):
        users_module.set_card_mode_gate("first_exposure", "all")
        self._user_with_plan(40, "free")
        self.assertTrue(users_module.card_mode_available(40, "first_exposure"))
        self.assertFalse(users_module.card_mode_available(40, "review"))

    def test_unknown_gate_raises(self):
        with self.assertRaises(ValueError):
            users_module.set_card_mode_gate("review", "bogus_gate")


class CardModeAccessorPersistenceTests(unittest.TestCase):
    """Writes persist, validate, and never wipe unrelated data."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "cardmodes.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()
        users_module.create_user_if_needed(1, "tester")
        with db_module.get_conn() as conn:
            conn.execute("UPDATE users SET plan='silver' WHERE user_id=1")
            conn.commit()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_set_user_card_mode_persists(self):
        users_module.set_user_card_mode(1, "first_exposure", "immediate")
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT first_exposure_mode FROM users WHERE user_id=1"
            ).fetchone()
        self.assertEqual(row["first_exposure_mode"], "immediate")

    def test_set_user_card_mode_on_missing_user_is_safe(self):
        users_module.set_user_card_mode(999, "review", "immediate")
        self.assertEqual(users_module.resolve_card_mode(999, "review"), "staged")

    def test_set_plan_card_mode_persists_without_touching_quota(self):
        with db_module.get_conn() as conn:
            conn.execute(
                "UPDATE plans SET query_quota=42 WHERE name='silver'"
            )
            conn.commit()
        users_module.set_plan_card_mode("silver", "first_exposure", "immediate")
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT query_quota, first_exposure_mode FROM plans WHERE name='silver'"
            ).fetchone()
        self.assertEqual(row["query_quota"], 42)
        self.assertEqual(row["first_exposure_mode"], "immediate")

    def test_global_mode_and_gate_persist(self):
        users_module.set_global_card_mode("review", "immediate")
        users_module.set_card_mode_gate("review", "all")
        self.assertEqual(users_module.resolve_card_mode(999, "review"), "immediate")
        self.assertEqual(users_module.resolve_card_mode_gate("review"), "all")

    def test_upsert_plan_preserves_modes_on_edit(self):
        """Editing a plan through upsert_plan must not wipe stored mode values
        (upsert_plan intentionally does not touch the mode columns)."""
        users_module.set_plan_card_mode("silver", "first_exposure", "immediate")
        db_module.upsert_plan(
            "silver", "نقره‌ای", 0, query_quota=7, max_sessions=3,
            cards_per_session=5,
        )
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT first_exposure_mode, review_mode, query_quota "
                "FROM plans WHERE name='silver'"
            ).fetchone()
        self.assertEqual(row["first_exposure_mode"], "immediate")
        self.assertIsNone(row["review_mode"])
        self.assertEqual(row["query_quota"], 7)

    def test_new_plan_via_upsert_has_null_modes(self):
        """Re-inserting an absent canonical plan through upsert_plan creates a
        fresh row with NULL modes, so the resolver falls through to the
        admin-global mode."""
        with db_module.get_conn() as conn:
            conn.execute("DELETE FROM plans WHERE name='gold'")
        db_module.upsert_plan(
            "gold", "طلایی", 0, query_quota=12, max_sessions=4,
            cards_per_session=7,
        )
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT first_exposure_mode, review_mode FROM plans "
                "WHERE name='gold'"
            ).fetchone()
        self.assertIsNone(row["first_exposure_mode"])
        self.assertIsNone(row["review_mode"])


if __name__ == "__main__":
    unittest.main()