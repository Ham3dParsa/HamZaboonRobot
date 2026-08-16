"""R3 consolidation tests: ``DisplayToggleService`` is the single owner of
display-toggle state and precedence resolution (forced > user > global > catalog).

Existing behavior (precedence, string normalization) is covered by
``tests/test_reliability.py`` via the public ``services.db`` facade. These tests
lock the consolidation contract: the facade delegates resolve to the service, the
service is the only place that encodes precedence, and unknown fields are
rejected everywhere.
"""

import os
import tempfile
import unittest

from config.catalog import DISPLAY_TOGGLE_FIELDS

from services import db
from services.db import schema as db_schema
from services.db import users as users_module
from services.db import settings as settings_module
from services.db.display_toggles import (
    DisplayToggleService,
    get_effective,
    get_global_defaults,
    set_forced,
    set_global_defaults,
    set_user_toggle,
)


class DisplayToggleServiceTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        # Isolate from global/user drift left by other tests.
        db.set_setting("display_toggle_defaults", "")
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def test_facade_delegates_to_service(self):
        svc = DisplayToggleService()
        self.assertEqual(db.get_display_toggles(1), svc.get_effective(1))

    def test_single_ownership_consolidation(self):
        """R3 consolidation invariant: the facade delegates to the ONE owner
        module, so precedence resolution is not duplicated across services/db."""
        # users.* display-toggle API resolves to display_toggles functions (no
        # second precedence implementation hiding in users.py).
        self.assertIs(users_module._get_display_toggles, get_effective)
        self.assertIs(users_module._set_display_toggle, set_user_toggle)
        self.assertIs(users_module._set_display_toggle_forced, set_forced)
        # settings.* admin-defaults API delegates to the owner's accessors.
        self.assertEqual(
            settings_module.get_display_toggle_defaults(),
            get_global_defaults(),
        )
        # After consolidation the precedence columns are read/written in exactly
        # one place (display_toggles.py). users.py must not re-implement it.
        with open(users_module.__file__, encoding="utf-8") as handle:
            users_src = handle.read()
        self.assertNotIn("display_toggles_forced", users_src)
        with open(settings_module.__file__, encoding="utf-8") as handle:
            settings_src = handle.read()
        self.assertNotIn("display_toggles_forced", settings_src)

    def test_precedence_forced_over_user_over_default(self):
        field = "synonyms"
        self.assertTrue(get_global_defaults()[field])

        set_global_defaults({field: False})
        self.assertFalse(db.get_display_toggles(1)[field])

        set_user_toggle(1, field, True)
        self.assertTrue(db.get_display_toggles(1)[field])

        set_forced(1, field, False)
        self.assertFalse(db.get_display_toggles(1)[field])

        set_forced(1, field, True)
        self.assertTrue(db.get_display_toggles(1)[field])

    def test_missing_user_resolves_complete_defaults(self):
        effective = get_effective(999999)
        self.assertEqual(set(effective), set(DISPLAY_TOGGLE_FIELDS))
        for value in effective.values():
            self.assertIsInstance(value, bool)

    def test_unknown_field_rejected_everywhere(self):
        with self.assertRaises(ValueError):
            set_user_toggle(1, "not_a_field", True)
        with self.assertRaises(ValueError):
            set_forced(1, "not_a_field", True)
        with self.assertRaises(ValueError):
            set_global_defaults({"not_a_field": True})

    def test_global_defaults_complete_and_stale_keys_ignored(self):
        over = {f: False for f in DISPLAY_TOGGLE_FIELDS}
        set_global_defaults(over)
        got = get_global_defaults()
        self.assertEqual(set(got), set(DISPLAY_TOGGLE_FIELDS))
        self.assertTrue(all(not v for v in got.values()))

        db.set_setting("display_toggle_defaults", '{"synonyms": false, "ghost": true}')
        got2 = get_global_defaults()
        self.assertNotIn("ghost", got2)
        self.assertFalse(got2["synonyms"])

    def test_string_values_normalized(self):
        set_user_toggle(1, "phonetic", "false")
        self.assertFalse(get_effective(1)["phonetic"])
        set_forced(1, "grammar_tip", "on")
        self.assertTrue(get_effective(1)["grammar_tip"])


if __name__ == "__main__":
    unittest.main()
