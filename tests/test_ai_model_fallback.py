"""T2 (R2): _model returns resolve only - never invents a model (zero-hardcode phase 2).

``_model`` must return ``preset_fields.resolve(preset, "model")`` as-is (after
the ``opencode/`` prefix strip). In particular it must NOT apply its own
``or DEFAULT_AI_MODEL`` fallback: when resolve yields ``""`` (empty-model
preset - always the case once phase 3 drops the model ``config_default``),
``_model`` returns ``""`` so the absence surfaces as an explicit
provider/validation error instead of a silent gapgpt call.
"""

import unittest
from unittest.mock import patch

from services.ai import ai
from services.db.preset_registry import NoActivePresetError


class ModelFallbackTest(unittest.TestCase):
    def test_empty_resolve_returns_empty(self):
        preset = {"name": "p", "base_url": "https://example.com/v1", "model": ""}
        with patch("services.ai.ai.preset_fields.resolve", return_value="") as r:
            self.assertEqual(ai._model(preset), "")
        r.assert_called_once_with(preset, "model")

    def test_empty_model_unmocked_returns_empty(self):
        # T3 (R2 end-to-end): no patch on resolve — a real empty-model preset
        # yields "" so the absence surfaces as an explicit provider error.
        self.assertEqual(ai._model({"model": ""}), "")

    def test_stored_model_returned_as_is(self):
        self.assertEqual(ai._model({"model": "real-model"}), "real-model")

    def test_opencode_prefix_still_stripped(self):
        self.assertEqual(ai._model({"model": "opencode/foo"}), "foo")

    def test_none_preset_without_active_raises(self):
        with patch.object(
            ai.db,
            "get_active_preset",
            side_effect=NoActivePresetError("no enabled AI preset available"),
        ):
            with self.assertRaises(NoActivePresetError):
                ai._model(None)


if __name__ == "__main__":
    unittest.main()
