"""Tests for the canonical AI-preset field schema (J-B2 / deep module).

Verifies the small interface (preset_field / write_default / resolve / validate)
and the anti-divergence invariant: the registry's field names and write defaults
MUST match the canonical ``ai_presets`` table columns (schema._AI_PRESETS_COLUMNS),
so a schema change without a registry change fails loudly.
"""

import unittest

from config import (
    AI_MAX_OUTPUT_TOKENS,
    AI_TEMPERATURE,
    AI_TIMEOUT_SECONDS,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
)
from services.ai import preset_fields as pf
from services.db.schema import _AI_PRESETS_COLUMNS


def _column_defaults() -> dict:
    """Parse ai_presets column defaults: name -> (default_value or MISSING)."""
    out = {}
    for line in _AI_PRESETS_COLUMNS:
        parts = line.split()
        name = parts[0]
        if "DEFAULT" in line:
            val = line.split("DEFAULT ", 1)[1].strip()
            out[name] = _coerce(val)
        else:
            out[name] = None
    return out


def _coerce(val: str):
    if val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    if val in ("", "0", "1"):
        return int(val) if val.isdigit() else val
    try:
        return int(val)
    except ValueError:
        return float(val)


class PresetFieldRegistryTest(unittest.TestCase):
    def test_every_field_resolves(self):
        for name, meta in pf.PRESET_FIELDS.items():
            with self.subTest(name=name):
                got = pf.preset_field(name)
                self.assertEqual(got["type"], meta["type"])
                self.assertIn("write_default", got)

    def test_unknown_field_raises_keyerror(self):
        with self.assertRaises(KeyError):
            pf.preset_field("this_is_not_a_preset_field")

    def test_resolve_uses_preset_value(self):
        self.assertEqual(pf.resolve({"daily_batch_size": 12}, "daily_batch_size"), 12)
        self.assertEqual(pf.resolve({"base_url": "http://x"}, "base_url"), "http://x")

    def test_resolve_falls_back_to_write_default(self):
        self.assertEqual(pf.resolve({}, "daily_batch_size"), 6)
        self.assertEqual(pf.resolve({}, "max_rpm"), 30)
        self.assertEqual(pf.resolve({}, "max_concurrency"), 2)

    def test_resolve_config_default_for_env_fields(self):
        self.assertEqual(pf.resolve({}, "timeout_seconds"), AI_TIMEOUT_SECONDS)
        self.assertEqual(pf.resolve({}, "temperature"), AI_TEMPERATURE)
        self.assertEqual(pf.resolve({}, "max_output_tokens"), AI_MAX_OUTPUT_TOKENS)
        self.assertEqual(pf.resolve({}, "base_url"), DEFAULT_AI_BASE_URL)
        self.assertEqual(pf.resolve({}, "model"), DEFAULT_AI_MODEL)

    def test_resolve_ignores_empty_preset_value(self):
        self.assertEqual(pf.resolve({"base_url": ""}, "base_url"), DEFAULT_AI_BASE_URL)
        self.assertEqual(pf.resolve({"timeout_seconds": None}, "timeout_seconds"), AI_TIMEOUT_SECONDS)

    def test_write_value_preserves_stored_and_defaults_on_empty(self):
        self.assertEqual(pf.write_value({"timeout_seconds": 12.0}, "timeout_seconds"), 12.0)
        self.assertEqual(pf.write_value({"timeout_seconds": None}, "timeout_seconds"), 30.0)
        self.assertEqual(pf.write_value({"timeout_seconds": ""}, "timeout_seconds"), 30.0)
        self.assertEqual(pf.write_value({}, "temperature"), 0.6)
        self.assertEqual(pf.write_value({"temperature": 0.0}, "temperature"), 0.0)
        self.assertEqual(pf.write_value({"max_output_tokens": 0}, "max_output_tokens"), 0)

    def test_write_value_falls_back_to_write_default_not_config(self):
        self.assertEqual(pf.write_value({}, "timeout_seconds"), pf.write_default("timeout_seconds"))
        self.assertEqual(pf.write_value({}, "temperature"), pf.write_default("temperature"))
        self.assertEqual(pf.write_value({}, "max_output_tokens"), pf.write_default("max_output_tokens"))

    def test_validate_accepts_good_preset(self):
        pf.validate(
            {
                "name": "x",
                "base_url": "http://x",
                "model": "m",
                "daily_batch_size": 6,
                "max_rpm": 30,
                "timeout_seconds": 30.0,
                "input_cost_per_million": None,
            }
        )

    def test_validate_rejects_wrong_type(self):
        with self.assertRaises(ValueError):
            pf.validate({"daily_batch_size": "not-an-int"})
        with self.assertRaises(ValueError):
            pf.validate({"max_concurrency": True})

    def test_validate_ignores_unknown_fields(self):
        # Unknown fields are tolerated (forward-compat).
        pf.validate({"future_field": "whatever"})

    def test_validate_preset_fields_passes(self):
        pf.validate_preset_fields()

    def test_module_fields_match_ai_presets_columns(self):
        col_defaults = _column_defaults()
        self.assertEqual(set(pf.PRESET_FIELDS), set(col_defaults))
        for name, meta in pf.PRESET_FIELDS.items():
            expected = col_defaults[name]
            if expected is None:
                # Columns without a DEFAULT clause map to write_default None or "".
                self.assertIn(meta["write_default"], (None, ""))
            else:
                self.assertEqual(meta["write_default"], expected)

    def test_set_preset_defaults_source_module(self):
        import inspect

        from services.db import preset_registry

        sig = inspect.signature(preset_registry.set_preset)
        plain_fields = (
            "base_url",
            "model",
            "api_key",
            "daily_batch_size",
            "max_concurrency",
            "max_rpm",
            "max_tpm",
            "max_daily_req",
            "timeout_seconds",
            "temperature",
            "max_output_tokens",
            "is_emergency",
            "input_cost_per_million",
            "output_cost_per_million",
            "in_fallback_chain",
            "group_label",
        )
        for name in plain_fields:
            self.assertEqual(sig.parameters[name].default, pf.write_default(name), name)
        # priority/enabled stay None sentinels (preserve-on-conflict), not defaults.
        self.assertIsNone(sig.parameters["priority"].default)
        self.assertIsNone(sig.parameters["enabled"].default)


if __name__ == "__main__":
    unittest.main()