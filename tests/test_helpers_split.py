"""REF2-T3: helpers_pure + helpers_awaiting + helpers_llm + helpers_retry leaves.

Proves the ordered verbatim split preserves behavior (T1/T2 precedent):
- ``services/utils/helpers.py`` defines no functions/classes itself except the
  retained ``__getattr__`` send-pretty shim; it re-exports the exact same
  objects from the four new leaves (no parallel fallback definitions; old
  defs gone same PR).
- Import DAG is cycle-free: pure and retry import no sibling leaf at top
  level; awaiting imports no sibling at top level (facade-dynamic only, so
  the ``patch(helpers._edit_markup...)`` contract holds); llm may import
  awaiting/retry one-directionally. No leaf imports ``services.send_pretty``
  or ``bot`` at top level (live cycle — function-local only).
- Golden outputs are byte-identical through facade and leaf paths.
"""

import ast
import unittest
from pathlib import Path

from services.utils import (
    helpers,
    helpers_awaiting,
    helpers_llm,
    helpers_pure,
    helpers_retry,
)

PURE_NAMES = (
    "apply_log_level",
    "_user_activity_line",
    "_normalize_custom_word_input",
    "_is_cancel_input",
    "_CANCEL_INPUTS",
)

AWAITING_NAMES = (
    "clear_admin_pending_state",
    "_resolve_awaiting_tuple",
    "_store_awaiting_msg",
    "_clear_awaiting_prompt",
    "_rotate_awaiting_msg",
    "_ADMIN_PENDING_KEYS",
    "_AWAITING_PENDING_KEY",
)

LLM_NAMES = (
    "_start_llm_wait_state",
    "_finish_llm_wait_state",
    "_exit_awaiting_flow",
    "exit_admin_awaiting_cancel",
    "_edit_or_send",
)

RETRY_NAMES = (
    "_retry_backoff_base",
    "_retry_sleep",
    "_execute_telegram_action_with_retry",
    "_reset_telegram_cb",
    "_send_with_retry",
    "_edit_with_retry",
    "_edit_message_with_retry",
    "_edit_markup_with_retry",
    "_delete_with_retry",
    "_RETRY_BACKOFF_BASE_DEFAULT",
    "_RETRY_BACKOFF_BASE_MAX",
    "_RETRY_BACKOFF_SLEEP_MAX",
    "_TELEGRAM_RETRY_MAX_ATTEMPTS",
    "_TELEGRAM_RETRY_BASE_DELAY",
    "_TELEGRAM_RETRY_MAX_DELAY",
)


class TestHelpersReexportSurface(unittest.TestCase):
    def test_pure_names_reexport_same_objects(self):
        for name in PURE_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(helpers, name),
                    getattr(helpers_pure, name),
                    f"helpers.{name} must be the helpers_pure object",
                )

    def test_awaiting_names_reexport_same_objects(self):
        for name in AWAITING_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(helpers, name),
                    getattr(helpers_awaiting, name),
                    f"helpers.{name} must be the helpers_awaiting object",
                )

    def test_llm_names_reexport_same_objects(self):
        for name in LLM_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(helpers, name),
                    getattr(helpers_llm, name),
                    f"helpers.{name} must be the helpers_llm object",
                )

    def test_retry_names_reexport_same_objects(self):
        for name in RETRY_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(helpers, name),
                    getattr(helpers_retry, name),
                    f"helpers.{name} must be the helpers_retry object",
                )

    def test_facade_defines_nothing_except_getattr_shim(self):
        """Route-delete proof: facade holds imports/aliases + __getattr__ only."""
        tree = ast.parse(Path(helpers.__file__).read_text(encoding="utf-8"))
        defs = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        self.assertEqual(
            defs,
            ["__getattr__"],
            f"facade must define only __getattr__, found {defs}",
        )

    def test_golden_outputs_identical_through_both_paths(self):
        self.assertEqual(
            helpers._normalize_custom_word_input("  سلام\u200b  دنیا  "),
            helpers_pure._normalize_custom_word_input("  سلام\u200b  دنیا  "),
        )
        self.assertEqual(
            helpers._is_cancel_input("لغو"),
            helpers_pure._is_cancel_input("لغو"),
        )
        self.assertEqual(helpers._CANCEL_INPUTS, helpers_pure._CANCEL_INPUTS)
        self.assertEqual(
            helpers._TELEGRAM_RETRY_MAX_ATTEMPTS,
            helpers_retry._TELEGRAM_RETRY_MAX_ATTEMPTS,
        )
        self.assertEqual(
            helpers._ADMIN_PENDING_KEYS, helpers_awaiting._ADMIN_PENDING_KEYS
        )

    def test_leaf_import_law(self):
        """No leaf imports send_pretty/bot at top level (live cycle).

        Pure/retry/awaiting import no sibling leaf at top level; llm may
        import awaiting/retry one-directionally. Cross-leaf runtime calls
        that tests patch at the facade path (``_reset_telegram_cb``,
        ``_edit_markup_with_retry``, ``logger``) resolve dynamically via a
        function-local facade import (send_pretty precedent).
        """

        def top_imports(tree):
            mods = set()
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        mods.add(alias.name)
            return mods

        leaves = {
            "helpers_pure": helpers_pure,
            "helpers_awaiting": helpers_awaiting,
            "helpers_llm": helpers_llm,
            "helpers_retry": helpers_retry,
        }
        allowed_sibling = {
            "helpers_pure": set(),
            "helpers_awaiting": set(),
            "helpers_llm": {
                "services.utils.helpers_awaiting",
                "services.utils.helpers_retry",
            },
            "helpers_retry": set(),
        }
        for leaf_name, mod in leaves.items():
            with self.subTest(leaf=leaf_name):
                tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
                for imported in top_imports(tree):
                    self.assertFalse(
                        imported in ("services.send_pretty", "bot")
                        or imported.startswith("services.send_pretty.")
                        or imported == "bot",
                        f"{leaf_name} must not import {imported} at top level",
                    )
                    if imported.startswith("services.utils.helpers"):
                        self.assertIn(
                            imported,
                            allowed_sibling[leaf_name],
                            f"{leaf_name} must not import sibling {imported} "
                            f"at top level",
                        )


if __name__ == "__main__":
    unittest.main()
