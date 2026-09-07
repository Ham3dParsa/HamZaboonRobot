"""Theme catalog tests (issue #467).

Locks the frozen ``config/themes.py`` registry: exactly two themes, fail-closed
reads, identical key sets, Persian-law strings, and the ``users.theme_id``
get/set helpers (fail-fast writes, fail-closed reads).
"""

import os
import sqlite3
import tempfile
import unittest
from types import MappingProxyType

from config.themes import (
    DEFAULT_THEME_ID,
    THEMES,
    get_theme,
    validate_themes,
)

from services import db
from services.db import schema as db_schema
from services.db import users as users_module


FORBIDDEN = ("·", "—", "|")


def _all_learner_strings(spec) -> list[str]:
    out = []
    for key, value in spec.items():
        if key in ("heat", "has_animation"):
            continue
        out.append(value)
    out.extend(spec["heat"].values())
    return out


class ThemeRegistryTest(unittest.TestCase):
    def test_exactly_two_themes(self):
        self.assertEqual(set(THEMES), {"fire_temple", "star"})

    def test_default_in_registry(self):
        self.assertEqual(DEFAULT_THEME_ID, "fire_temple")
        self.assertIn(DEFAULT_THEME_ID, THEMES)

    def test_validate_passes(self):
        validate_themes()

    def test_same_key_set(self):
        reference = set(THEMES[DEFAULT_THEME_ID].keys())
        for theme_id, spec in THEMES.items():
            self.assertEqual(set(spec.keys()), reference, theme_id)

    def test_no_stage_labels(self):
        for theme_id, spec in THEMES.items():
            for key in spec.keys():
                self.assertNotIn("stage", key.lower(), f"{theme_id}.{key}")

    def test_registry_frozen(self):
        self.assertIsInstance(THEMES, MappingProxyType)
        with self.assertRaises(TypeError):
            THEMES["sneaky"] = {}
        for theme_id, spec in THEMES.items():
            self.assertIsInstance(spec, MappingProxyType, theme_id)
            with self.assertRaises(TypeError):
                spec["sneaky"] = "x"
            self.assertIsInstance(spec["heat"], MappingProxyType, theme_id)
            with self.assertRaises(TypeError):
                spec["heat"][9] = "x"

    def test_fire_temple_spot_values(self):
        fire = THEMES["fire_temple"]
        self.assertEqual(fire["label"], "آتشکده هم‌زبان")
        self.assertEqual(fire["streak"], "پیوستگی")
        self.assertEqual(fire["shield"], "فرشته نجات")
        self.assertEqual(fire["best_streak"], "بلندترین پیوستگی")
        self.assertEqual(fire["xp"], "امتیاز")
        self.assertEqual(
            dict(fire["heat"]),
            {1: "یک‌آتیشه 🔥", 2: "دوآتیشه 🔥🔥", 3: "سه‌آتیشه 🔥🔥🔥"},
        )
        self.assertEqual(fire["status_title"], "🏛️ آتشکده شما")
        self.assertEqual(fire["profile_today"], "وضعیت امروز")
        self.assertEqual(fire["profile_total"], "آمار کلی")
        self.assertEqual(fire["event_first"], "یک‌آتیشه شدی")
        self.assertEqual(fire["event_milestone_1"], "دوآتیشه شدی، ۴۰٪ نشست‌های امروز")
        self.assertEqual(fire["event_milestone_2"], "سه‌آتیشه، روز کامل")
        self.assertIs(fire["has_animation"], True)

    def test_star_spot_values(self):
        star = THEMES["star"]
        self.assertEqual(star["label"], "ستاره")
        self.assertEqual(star["shield"], "سپر 🛡️")
        self.assertEqual(
            dict(star["heat"]),
            {1: "تک‌ستاره ★", 2: "دوستاره ★★", 3: "سه‌ستاره ★★★"},
        )
        self.assertEqual(star["status_title"], "⭐ نمای شما")
        self.assertIs(star["has_animation"], False)


class ThemeFallbackTest(unittest.TestCase):
    def test_unknown_id_fails_closed_to_default(self):
        self.assertIs(get_theme("nope"), THEMES[DEFAULT_THEME_ID])
        self.assertIs(get_theme(""), THEMES[DEFAULT_THEME_ID])
        self.assertIs(get_theme(None), THEMES[DEFAULT_THEME_ID])

    def test_known_ids_resolve(self):
        self.assertIs(get_theme("fire_temple"), THEMES["fire_temple"])
        self.assertIs(get_theme("star"), THEMES["star"])


class ThemePersianLawTest(unittest.TestCase):
    def test_no_forbidden_chars(self):
        for theme_id, spec in THEMES.items():
            for text in _all_learner_strings(spec):
                for bad in FORBIDDEN:
                    self.assertNotIn(bad, text, f"{theme_id}: {text!r}")

    def test_lists_use_persian_comma(self):
        self.assertIn("،", THEMES["fire_temple"]["event_milestone_1"])
        self.assertIn("،", THEMES["fire_temple"]["event_milestone_2"])


class UserThemeDbTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def test_default_theme_is_fire_temple(self):
        self.assertEqual(users_module.get_user_theme(1), "fire_temple")

    def test_set_and_get_roundtrip(self):
        users_module.set_user_theme(1, "star")
        self.assertEqual(users_module.get_user_theme(1), "star")
        users_module.set_user_theme(1, "fire_temple")
        self.assertEqual(users_module.get_user_theme(1), "fire_temple")

    def test_set_unknown_raises(self):
        with self.assertRaises(ValueError):
            users_module.set_user_theme(1, "nope")

    def test_unknown_stored_value_fails_closed(self):
        with db_schema.transaction() as conn:
            conn.execute("UPDATE users SET theme_id=? WHERE user_id=?", ("nope", 1))
        self.assertEqual(users_module.get_user_theme(1), "fire_temple")

    def test_migration_adds_column_to_legacy_db(self):
        legacy_path = os.path.join(self.tempdir.name, "legacy.sqlite")
        conn = sqlite3.connect(legacy_path)
        try:
            conn.execute(
                "CREATE TABLE users (user_id INTEGER PRIMARY KEY, username TEXT)"
            )
            conn.execute("INSERT INTO users(user_id) VALUES (7)")
            conn.commit()
        finally:
            conn.close()
        db_schema.init_db(legacy_path)
        check = sqlite3.connect(legacy_path)
        try:
            cols = {row[1] for row in check.execute("PRAGMA table_info(users)")}
            self.assertIn("theme_id", cols)
        finally:
            check.close()


if __name__ == "__main__":
    unittest.main()
