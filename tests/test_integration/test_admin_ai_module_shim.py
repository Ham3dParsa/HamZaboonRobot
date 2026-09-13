"""Kilo WARNING regression (PR #679): the ``handlers.admin_ai`` module
``__class__``-mutation shim must warn when it cannot install itself —
never silently ``pass`` (silent disable breaks ``patch(...)`` tests
with obscure ``AttributeError``)."""

from __future__ import annotations

import sys
import unittest


class AdminAiModuleShimTest(unittest.TestCase):
    def test_shim_failure_warns_instead_of_silent_pass(self):
        import handlers.admin_ai as facade

        real_entry = sys.modules["handlers.admin_ai"]
        # Plain object() forbids __class__ assignment -> deterministic TypeError.
        sys.modules["handlers.admin_ai"] = object()
        try:
            with self.assertLogs("handlers.admin_ai", level="WARNING") as logs:
                facade._switch_module_class()
        finally:
            sys.modules["handlers.admin_ai"] = real_entry
        self.assertTrue(
            any("patch-propagation" in line for line in logs.output),
            f"expected shim-disabled warning, got: {logs.output}",
        )
