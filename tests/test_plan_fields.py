"""Tests for the canonical plan-field registry (G3 F8/R8).

The plan-field registry (``services/plan_fields.py``) is the single owner of
the 5 admin-editable plan fields (display_name, price, query_quota,
max_sessions, cards_per_session): their type, DB write default, Persian label,
hint, and group. ``admin_plans.py``'s wizard must derive its step order,
labels, hints, group headers, validation, and the ``upsert_plan`` save mapping
from this registry (data-driven, per locked contract R1-A/R2-A/R3-A).

Anti-divergence invariant (mirrors test_preset_fields.py): the registry's field
names and write defaults MUST align with the canonical ``plans`` table columns,
so a schema change without a registry change fails loudly.
"""

import re
import unittest
from pathlib import Path

from services import plan_fields as pf

WIZARD_FIELDS = (
    "display_name",
    "price",
    "query_quota",
    "max_sessions",
    "cards_per_session",
)


def _plans_column_defaults() -> dict:
    """Parse the plans CREATE TABLE in services/db/schema.py -> col: default."""
    src = Path("services/db/schema.py").read_text(encoding="utf-8")
    block = re.search(r"CREATE TABLE IF NOT EXISTS plans \((.*?)\);", src, re.S).group(1)
    defaults = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        parts = line.split()
        col = parts[0]
        m = re.search(r"DEFAULT ([\w']+)", line)
        defaults[col] = int(m.group(1)) if m else ""
    return defaults


class PlanFieldRegistryTest(unittest.TestCase):
    def test_field_order_is_the_5_wizard_fields(self):
        self.assertEqual(tuple(pf.field_order()), WIZARD_FIELDS)

    def test_every_field_has_type_and_write_default(self):
        for name in pf.field_order():
            with self.subTest(name=name):
                meta = pf.plan_field(name)
                self.assertIn("type", meta)
                self.assertIn("write_default", meta)
                self.assertIn("label", meta)

    def test_unknown_field_raises_keyerror(self):
        with self.assertRaises(KeyError):
            pf.plan_field("this_is_not_a_plan_field")

    def test_write_defaults_align_with_plans_table_columns(self):
        col_defaults = _plans_column_defaults()
        for name in WIZARD_FIELDS:
            with self.subTest(name=name):
                self.assertEqual(pf.write_default(name), col_defaults[name])

    def test_write_defaults_exist_for_every_field(self):
        for name in WIZARD_FIELDS:
            self.assertIsNotNone(pf.write_default(name))

    def test_group_header_returns_header_and_hint_for_every_field(self):
        for name in WIZARD_FIELDS:
            with self.subTest(name=name):
                header, hint = pf.group_header(name)
                self.assertTrue(header)
                self.assertTrue(hint)

    def test_labels_and_hints_are_present(self):
        for name in WIZARD_FIELDS:
            with self.subTest(name=name):
                self.assertTrue(pf.field_label(name))

    def test_validate_value_display_name(self):
        self.assertEqual(pf.validate_value("display_name", "  طلایی  "), "طلایی")
        self.assertIsNone(pf.validate_value("display_name", "   "))

    def test_validate_value_int_fields(self):
        self.assertEqual(pf.validate_value("price", "120000"), 120000)
        self.assertEqual(pf.validate_value("query_quota", "7"), 7)
        self.assertIsNone(pf.validate_value("price", "-5"))
        self.assertIsNone(pf.validate_value("query_quota", "abc"))
        self.assertIsNone(pf.validate_value("cards_per_session", ""))

    def test_int_validation_rejects_float_and_bool_like(self):
        # int fields accept only integer input from the raw wizard string.
        self.assertIsNone(pf.validate_value("max_sessions", "2.5"))

    def test_unknown_field_validate_raises(self):
        with self.assertRaises(KeyError):
            pf.validate_value("nope", "1")

    def test_validate_plan_fields_passes(self):
        pf.validate_plan_fields()


if __name__ == "__main__":
    unittest.main()