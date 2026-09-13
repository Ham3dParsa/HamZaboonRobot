"""REF2-T6 seam guard: config/catalog.py split into catalog_* leaves.

Verbatim-split regression net (red-first): each leaf owns its registry
(languages/goals/levels + namespaces; toggles; card-types; settings-keys;
validators), ``config.catalog`` stays a pure re-export facade (zero caller
churn), and every leaf obeys the leaf-import law (``config`` + stdlib only).
"""

import ast
import unittest
from pathlib import Path

LEAF_OWNERSHIP = {
    "config/catalog_languages.py": [
        "LanguageOption", "GoalOption", "LevelOption",
        "LANGUAGES", "GOALS", "LEVELS", "DEFAULT_LEVEL",
        "CATALOG_NAMESPACES", "catalog_namespace",
        "language_label", "example_language_label", "language_guidance",
        "goal_label", "goal_hint",
        "level_label", "level_cefr", "level_prompt_guidance",
    ],
    "config/catalog_toggles.py": [
        "DISPLAY_TOGGLE_FIELDS", "HIGH_VALUE_TOGGLES",
        "LOW_VALUE_TOGGLES", "DISPLAY_TOGGLE_DEFAULTS",
    ],
    "config/catalog_card_types.py": [
        "CARD_TYPES", "CARD_MODES", "CARD_MODE_GATES",
        "DEFAULT_CARD_MODE", "DEFAULT_CARD_MODE_GATE",
        "SETTINGS_CARD_TYPES",
    ],
    "config/catalog_settings_keys.py": [
        "DEFAULT_MAINTENANCE_MESSAGE",
        "SETTINGS_KEYS", "settings_key", "validate_settings_keys",
    ],
    "config/catalog_validation.py": [
        "validate_catalog",
    ],
}


def _module_level_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
    return defined


class TestCatalogSplit(unittest.TestCase):
    def test_leaves_define_their_registries(self):
        for module, symbols in LEAF_OWNERSHIP.items():
            with self.subTest(module=module):
                self.assertTrue(
                    Path(module).is_file(), f"leaf module {module} missing"
                )
                defined = _module_level_definitions(Path(module))
                for symbol in symbols:
                    self.assertIn(
                        symbol, defined,
                        f"{module} does not define {symbol!r}",
                    )

    def test_facade_reexports_leaf_objects(self):
        import config.catalog as facade

        for module, symbols in LEAF_OWNERSHIP.items():
            with self.subTest(module=module):
                leaf = __import__(module[:-3].replace("/", "."), fromlist=symbols)
                for symbol in symbols:
                    self.assertTrue(
                        hasattr(facade, symbol),
                        f"facade config.catalog missing {symbol!r}",
                    )
                    self.assertIs(
                        getattr(facade, symbol), getattr(leaf, symbol),
                        f"facade {symbol!r} is not the leaf object",
                    )

    def test_leaf_import_law_config_and_stdlib_only(self):
        from sys import stdlib_module_names as _stdlib_names

        stdlib = set(_stdlib_names)
        for module in LEAF_OWNERSHIP:
            with self.subTest(module=module):
                tree = ast.parse(Path(module).read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        top = node.module.split(".")[0]
                        self.assertIn(
                            top, {"config", "__future__"} | stdlib,
                            f"{module} imports outside config/stdlib: {node.module}",
                        )
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            top = alias.name.split(".")[0]
                            self.assertIn(
                                top, {"config", "__future__"} | stdlib,
                                f"{module} imports outside config/stdlib: {alias.name}",
                            )

    def test_validators_green_through_facade(self):
        from config.catalog import validate_catalog, validate_settings_keys

        validate_settings_keys()
        validate_catalog()

    def test_settings_key_resolver_moves_with_keys(self):
        from config.catalog import settings_key
        from config.catalog_settings_keys import settings_key as leaf_settings_key

        self.assertIs(settings_key, leaf_settings_key)
        meta = settings_key("first_exposure_mode")
        self.assertEqual(meta["card_type"], "first_exposure")
        with self.assertRaises(KeyError):
            settings_key("no_such_key")


if __name__ == "__main__":
    unittest.main()
