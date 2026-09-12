"""REF3-T4: lazy preset defaults — call-count reduction, no caching.

``_retry_primary_preset`` (services/ai/fallback_router.py, re-exported by
services/ai/llm_services.py) must read the
``ai_primary_preset`` setting first and resolve the expensive
``get_active_preset_name()`` default only when the setting is empty.
``get_fallback_status`` (services/db/preset_registry.py) must fetch both
settings first and call ``_first_enabled_name()`` at most once.

Behavior (None/empty/missing matrix) must stay byte-identical; only the
number of extra queries changes: settings set -> zero extra lookups,
unset -> exactly one.
"""

import os
import tempfile
import unittest
from unittest import mock

from services import db
from services.db import schema as db_schema
from services.db import preset_registry
from services.ai import llm_services


def _seed(names):
    for i, name in enumerate(names):
        db.set_preset(
            name=name,
            base_url="http://test.local/v1",
            model="test-model",
            api_key="sk-test",
            is_emergency=0,
            in_fallback_chain=1,
        )
        db.set_preset_priority(name, i)
        db.set_preset_enabled(name, 1)


def _delete_setting(key):
    with db_schema.transaction() as conn:
        conn.execute("DELETE FROM settings WHERE key=?", (key,))


class _IsolatedDb(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_db_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        for p in db.get_presets():
            db.delete_preset(p["name"])

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()


class StatusLazinessTests(_IsolatedDb):
    def _counted_first_enabled(self):
        real = preset_registry._first_enabled_name
        calls = {"n": 0}

        def counting():
            calls["n"] += 1
            return real()

        return calls, counting

    def test_both_set_zero_extra_queries(self):
        """Both settings present -> no _first_enabled_name call at all."""
        _seed(["pa"])
        db.set_setting("ai_primary_preset", "pa")
        db.set_setting("ai_fallback_preset", "pa")
        calls, counting = self._counted_first_enabled()
        with mock.patch.object(preset_registry, "_first_enabled_name", counting):
            status = preset_registry.get_fallback_status()
        self.assertEqual(calls["n"], 0, "set settings must not trigger extra queries")
        self.assertEqual(status["primary_preset"], "pa")
        self.assertEqual(status["fallback_preset"], "pa")

    def test_both_unset_exactly_one_query(self):
        """Both settings missing -> exactly one _first_enabled_name call."""
        _seed(["pa"])
        _delete_setting("ai_primary_preset")
        _delete_setting("ai_fallback_preset")
        calls, counting = self._counted_first_enabled()
        with mock.patch.object(preset_registry, "_first_enabled_name", counting):
            status = preset_registry.get_fallback_status()
        self.assertEqual(calls["n"], 1, "unset settings must share a single lookup")
        self.assertEqual(status["primary_preset"], "pa")
        self.assertEqual(status["fallback_preset"], "pa")

    def test_primary_set_fallback_unset_exactly_one_query(self):
        """Only fallback missing -> exactly one _first_enabled_name call."""
        _seed(["pa"])
        db.set_setting("ai_primary_preset", "pa")
        _delete_setting("ai_fallback_preset")
        calls, counting = self._counted_first_enabled()
        with mock.patch.object(preset_registry, "_first_enabled_name", counting):
            status = preset_registry.get_fallback_status()
        self.assertEqual(calls["n"], 1, "one missing side must cost exactly one lookup")
        self.assertEqual(status["primary_preset"], "pa")
        self.assertEqual(status["fallback_preset"], "pa")


class StatusMatrixTests(_IsolatedDb):
    def test_missing_empty_name_matrix_byte_identical(self):
        """None/empty/missing matrix: values identical to eager-default semantics.

        Original semantics under test:
        - primary missing -> _first_enabled_name() (None when nothing enabled)
        - primary present (even "") -> stored value verbatim
        - fallback missing/empty -> _first_enabled_name() or ""
        - fallback present non-empty -> stored value verbatim
        """
        for with_preset in (False, True):
            if with_preset:
                _seed(["pa"])
            first = "pa" if with_preset else None
            cases = [
                ("MISSING", "MISSING", first, first or ""),
                ("MISSING", "", first, first or ""),
                ("MISSING", "pa", first, "pa"),
                ("MISSING", "ghost", first, "ghost"),
                ("", "MISSING", "", first or ""),
                ("", "", "", first or ""),
                ("pa", "MISSING", "pa", first or ""),
                ("pa", "", "pa", first or ""),
                ("pa", "pa", "pa", "pa"),
                ("ghost", "ghost", "ghost", "ghost"),
            ]
            for primary_raw, fallback_raw, exp_primary, exp_fallback in cases:
                with self.subTest(
                    with_preset=with_preset,
                    primary=primary_raw,
                    fallback=fallback_raw,
                ):
                    if primary_raw == "MISSING":
                        _delete_setting("ai_primary_preset")
                    else:
                        db.set_setting("ai_primary_preset", primary_raw)
                    if fallback_raw == "MISSING":
                        _delete_setting("ai_fallback_preset")
                    else:
                        db.set_setting("ai_fallback_preset", fallback_raw)
                    status = preset_registry.get_fallback_status()
                    self.assertEqual(status["primary_preset"], exp_primary)
                    self.assertEqual(status["fallback_preset"], exp_fallback)
            for p in db.get_presets():
                db.delete_preset(p["name"])


class RetryPrimaryLazinessTests(_IsolatedDb):
    def test_primary_set_skips_active_name_resolution(self):
        """ai_primary_preset set -> get_active_preset_name() never runs."""
        _seed(["pa"])
        db.set_setting("ai_primary_preset", "pa")
        db.set_bool_setting("ai_fallback_active", True)
        real = db.get_active_preset_name
        calls = {"n": 0}

        def counting():
            calls["n"] += 1
            return real()

        with (
            mock.patch.object(db, "get_active_preset_name", counting),
            mock.patch.object(
                llm_services.ai, "test_connection",
                return_value={"success": True},
            ),
        ):
            llm_services._retry_primary_preset()
        self.assertEqual(calls["n"], 0, "set primary must not resolve the default")
        self.assertFalse(db.get_bool_setting("ai_fallback_active", False))

    def test_primary_unset_resolves_default_once(self):
        """ai_primary_preset missing -> get_active_preset_name() runs exactly once."""
        _seed(["pa"])
        _delete_setting("ai_primary_preset")
        db.set_bool_setting("ai_fallback_active", True)
        real = db.get_active_preset_name
        calls = {"n": 0}

        def counting():
            calls["n"] += 1
            return real()

        with (
            mock.patch.object(db, "get_active_preset_name", counting),
            mock.patch.object(
                llm_services.ai, "test_connection",
                return_value={"success": True},
            ),
        ):
            llm_services._retry_primary_preset()
        self.assertEqual(calls["n"], 1, "missing primary must resolve the default once")
        self.assertFalse(db.get_bool_setting("ai_fallback_active", False))

    def test_unknown_primary_warns_and_keeps_fallback(self):
        """Unknown primary name -> warning path, fallback stays active."""
        _seed(["pa"])
        db.set_setting("ai_primary_preset", "ghost")
        db.set_bool_setting("ai_fallback_active", True)
        with mock.patch.object(
            llm_services.ai, "test_connection",
            return_value={"success": True},
        ):
            llm_services._retry_primary_preset()
        self.assertTrue(db.get_bool_setting("ai_fallback_active", True))


if __name__ == "__main__":
    unittest.main()
