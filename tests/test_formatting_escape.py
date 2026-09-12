"""REF2-T1: formatting_escape leaf + formatting.py re-export shim surface.

Proves the verbatim split preserves behavior:
- ``services/utils/formatting.py`` re-exports the exact same function objects
  (no parallel fallback definitions).
- The leaf module imports stdlib only (never ``validation`` — chain-inversion
  risk from the ticket).
- Golden outputs are byte-identical through both import paths.
"""

import ast
import unittest
from pathlib import Path

from services.utils import formatting, formatting_escape

LEAF_NAMES = (
    "escape_mdv2",
    "escape_mdv2_code",
    "to_persian_digits",
    "html_escape",
)


class TestReexportSurface(unittest.TestCase):
    def test_shim_reexports_same_objects(self):
        for name in LEAF_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(formatting, name),
                    getattr(formatting_escape, name),
                    f"formatting.{name} must be the formatting_escape object",
                )

    def test_golden_outputs_identical_through_both_paths(self):
        cases = [
            ("escape_mdv2", ("*سلام* _test_ [x](y)!",), "\\*سلام\\* \\_test\\_ \\[x\\]\\(y\\)\\!"),
            ("escape_mdv2_code", ("a`b\\c",), "a\\`b\\\\c"),
            ("to_persian_digits", ("0123456789",), "۰۱۲۳۴۵۶۷۸۹"),
            ("to_persian_digits", (2026,), "۲۰۲۶"),
            ("html_escape", ('<a href="x&y">',), '&lt;a href=&quot;x&amp;y&quot;&gt;'),
            ("html_escape", (None,), ""),
        ]
        for name, args, expected in cases:
            with self.subTest(name=name, args=args):
                self.assertEqual(getattr(formatting_escape, name)(*args), expected)
                self.assertEqual(getattr(formatting, name)(*args), expected)

    def test_leaf_imports_stdlib_only(self):
        tree = ast.parse(
            Path(formatting_escape.__file__).read_text(encoding="utf-8")
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    self.assertIn(
                        top, ("html", "re"),
                        f"leaf must import stdlib only, found import {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".")[0]
                self.assertNotIn(
                    module, ("services", "config"),
                    f"leaf must not pull {node.module} (chain-inversion risk)",
                )
        # Explicit negative: validation chain must never load via the leaf.
        self.assertNotIn("services.utils.validation", str(tree))


if __name__ == "__main__":
    unittest.main()
