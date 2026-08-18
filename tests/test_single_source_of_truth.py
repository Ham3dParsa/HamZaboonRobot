"""Single-source-of-truth guard (R4, AGENTS.md §3).

Fails CI if a curated domain keyword is *defined* anywhere outside its owning
module. Definitions are the divergence risk §2.2.1 targets: consumer
references and imports are legitimate and never flagged; redefining a domain
concept (function, class, or registry constant) in a second module is exactly
the "parallel fallback" the owner made single-source-of-truth to prevent.

Scan scope is production code only: config/, services/, handlers/, bot.py.
tools/, docs/, tests/, and archives are preservation zones and never scanned.

Adding a keyword:
    Add the identifier name + its owner module path to DOMAIN_KEYWORDS. The
    owner is the module defined in AGENTS.md §3/§4 as the single source for
    that concept. Keep the entry only if a *definition* of that identifier
    would be a genuine duplicate today.

Removing a keyword:
    Only remove it if the owner reversed the single-source decision in a
    locked contract. Removing silently re-enables the "second fallback
    survives" failure mode this guard exists to prevent.

Known limitation (documented, accepted): ``_definitions`` inspects only direct
    module-level children of the AST body. A definition nested inside a
    top-level ``if``/``try``/``with`` block would evade detection. This is a
    deliberate trade-off: such guards are rare in this codebase, the full
    suite still exercises every owner, and widening the scan risks flagging
    legitimate consumers. Revisit if a nested module-level duplicate ever
    survives a merge.

Generic-looking keywords (``register``, ``dispatch``, ``register_flow``) are
    retained deliberately: each is the verified single module-level definition
    of the callback/flow routing seam. A consumer module *imports* these
    (e.g. ``from handlers.flows import register_flow``); imports are not
    definitions and never trip the guard. They are kept so the routing
    regulators themselves stay single-sourced. Re-evaluating their genericness
    is a maintenance decision, not a correctness one.
"""

import ast
import unittest
from pathlib import Path

# Owner module paths are repo-root-relative, POSIX-style (forward slashes).
# Only *definitions* are checked; references/imports never trip this guard.
DOMAIN_KEYWORDS: dict[str, str] = {
    # config/catalog.py owns language/goal/level metadata (AGENTS.md §4).
    "LANGUAGES": "config/catalog.py",
    "GOALS": "config/catalog.py",
    "LEVELS": "config/catalog.py",
    "language_label": "config/catalog.py",
    "goal_label": "config/catalog.py",
    "level_label": "config/catalog.py",
    "catalog_namespace": "config/catalog.py",
    "validate_catalog": "config/catalog.py",
    # config/plan_identity.py owns plan-set membership + tiering (AGENTS.md §4).
    "_PLANS": "config/plan_identity.py",
    "_FEATURE_MIN_RANK": "config/plan_identity.py",
    "valid_plans": "config/plan_identity.py",
    "is_premium": "config/plan_identity.py",
    "plan_label": "config/plan_identity.py",
    "has_feature": "config/plan_identity.py",
    "feature_audience": "config/plan_identity.py",
    # services/utils/formatting.py owns learner-facing escaping (AGENTS.md §5).
    "escape_mdv2": "services/utils/formatting.py",
    "escape_mdv2_code": "services/utils/formatting.py",
    "to_persian_digits": "services/utils/formatting.py",
    "format_card": "services/utils/formatting.py",
    "html_escape": "services/utils/formatting.py",
    # services/utils/validation.py owns word-query validation.
    "validate_word_query": "services/utils/validation.py",
    "_CUSTOM_WORD_MAX_WORDS": "services/utils/validation.py",
    # services/fsrs_core.py owns the pure FSRS-6 engine (AGENTS.md §4).
    "DEFAULT_FSRS_CONFIG": "services/fsrs_core.py",
    "compute_retrievability": "services/fsrs_core.py",
    "compute_interval": "services/fsrs_core.py",
    "initial_stability": "services/fsrs_core.py",
    "update_stability": "services/fsrs_core.py",
    "update_difficulty": "services/fsrs_core.py",
    "short_term_stability": "services/fsrs_core.py",
    # services/db/key_crypto.py owns key encryption (fail-closed, AGENTS.md §5).
    "encrypt_secret": "services/db/key_crypto.py",
    "decrypt_secret": "services/db/key_crypto.py",
    "mask_key": "services/db/key_crypto.py",
    "encrypt_for_storage": "services/db/key_crypto.py",
    # services/session/grade_policy.py owns grade resolution (AGENTS.md §4).
    "GRADE_POLICIES": "services/session/grade_policy.py",
    "resolve_grade": "services/session/grade_policy.py",
    "GradePolicy": "services/session/grade_policy.py",
    # services/session/assembly.py owns the 3-tier assembler (AGENTS.md §4).
    "build_session_list": "services/session/assembly.py",
    "generate_tier3_node": "services/session/assembly.py",
    # services/routing.py owns the callback routing registry (AGENTS.md §4).
    "ROUTES": "services/routing.py",
    "register": "services/routing.py",
    "dispatch": "services/routing.py",
    # handlers/flows.py owns the awaiting text-input flow registry (AGENTS.md §4).
    # (bot.py is the Telegram MessageHandler entry that *calls* flows' router,
    # so `text_router` is excluded: it is a name collision, not a domain duplicate.)
    "register_flow": "handlers/flows.py",
    "resolve_flow": "handlers/flows.py",
    "is_admin_awaiting": "handlers/flows.py",
    # services/db/display_toggles.py owns display-toggle state (AGENTS.md §4, R3).
    "get_effective": "services/db/display_toggles.py",
    "get_global_defaults": "services/db/display_toggles.py",
    "set_global_defaults": "services/db/display_toggles.py",
    "set_forced": "services/db/display_toggles.py",
}

PRODUCTION_SCAN_TARGETS = [
    Path("bot.py"),
    Path("config"),
    Path("services"),
    Path("handlers"),
]


def _definitions(tree: ast.AST) -> set[str]:
    """Collect every identifier DEFINED at module level in a parsed module.

    Definitions are the single-source divergence risk: function/class names
    and module-level assignments that a parallel fallback would re-define.
    Function-local variables that merely shadow a keyword (e.g. a local
    ``plan_label = ...`` inside a consumer handler) are NOT domain
    duplicates and are intentionally excluded — only module-level definitions
    can create a second source of truth. Import aliases and bare references
    are never definitions either.
    """
    defined: set[str] = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in _assign_targets(node):
                defined.add(target)

    return defined


def _assign_targets(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets: list[ast.expr] = list(node.targets) if isinstance(node, ast.Assign) else []
    if isinstance(node, ast.AnnAssign) and node.target is not None:
        targets.append(node.target)
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                if isinstance(elt, ast.Name):
                    names.append(elt.id)
    return names


def _iter_production_files():
    for target in PRODUCTION_SCAN_TARGETS:
        if target.is_file():
            yield target
        elif target.is_dir():
            yield from sorted(target.rglob("*.py"))


def _production_file_count() -> int:
    return sum(1 for _ in _iter_production_files())


def find_out_of_owner_definitions() -> dict[str, list[str]]:
    """Return {keyword: [file_path, ...]} for every keyword defined in a
    module other than its declared owner."""
    hits: dict[str, list[str]] = {}

    for filepath in _iter_production_files():
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        defined = _definitions(tree)
        posix = filepath.as_posix()
        for keyword, owner in DOMAIN_KEYWORDS.items():
            if keyword in defined and posix != owner:
                hits.setdefault(keyword, []).append(str(filepath))

    return hits


class TestSingleSourceOfTruth(unittest.TestCase):
    """The gate: no curated domain keyword may be defined outside its owner."""

    def test_no_domain_keyword_defined_outside_owner(self):
        hits = find_out_of_owner_definitions()
        if hits:
            msg = "Domain keywords defined outside their single source of truth:\n"
            for keyword, files in hits.items():
                msg += f"  {keyword}  (owner: {DOMAIN_KEYWORDS[keyword]})\n"
                for f in files:
                    msg += f"    {f}\n"
            self.fail(msg)

    def test_registry_has_no_empty_entries(self):
        for keyword, owner in DOMAIN_KEYWORDS.items():
            self.assertGreaterEqual(len(keyword), 1, "keyword empty")
            self.assertTrue(
                owner and owner.endswith(".py"),
                f"DOMAIN_KEYWORDS[{keyword}] owner must be a .py path, got {owner!r}",
            )

    def test_every_owner_module_exists(self):
        for keyword, owner in DOMAIN_KEYWORDS.items():
            self.assertTrue(
                Path(owner).exists(),
                f"owner module {owner} for '{keyword}' does not exist",
            )

    def test_scan_scope_is_production_only(self):
        allowed_roots = ("bot.py", "config", "services", "handlers")
        for target in PRODUCTION_SCAN_TARGETS:
            self.assertTrue(
                str(target) in allowed_roots,
                f"scan target {target} is outside the production allowlist",
            )

    def test_production_sources_are_found(self):
        """Fail loudly (not vacuously pass) if run from the wrong working
        directory: the gate must prove it actually scanned real files."""
        count = _production_file_count()
        self.assertGreater(
            count,
            10,
            f"only {count} production .py files found; "
            "is this test running from the repo root?",
        )

    def test_every_keyword_owner_actually_defines_it(self):
        """Each declared owner must define its keyword, so the map never
        points at an owner that merely references (but does not own) it."""
        for keyword, owner in DOMAIN_KEYWORDS.items():
            path = Path(owner)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                self.fail(f"owner {owner} for '{keyword}' failed to parse")
            self.assertIn(
                keyword,
                _definitions(tree),
                f"owner {owner} does not define '{keyword}'",
            )


class TestScannerDetection(unittest.TestCase):
    """Unit-test the definition scanner: prove it detects a module-level
    redefinition (the real divergence) and ignores references, imports, and
    function-local shadows (legitimate consumer code)."""

    def _defines(self, source: str, keyword: str) -> bool:
        tree = ast.parse(source)
        return keyword in _definitions(tree)

    def test_detects_module_level_function_def(self):
        self.assertTrue(self._defines("def synthetic_owner_fn():\n    pass\n", "synthetic_owner_fn"))

    def test_detects_module_level_class_def(self):
        self.assertTrue(self._defines("class SyntheticOwner:\n    pass\n", "SyntheticOwner"))

    def test_detects_module_level_assignment(self):
        self.assertTrue(self._defines("SYNTHETIC_REGISTRY = {}\n", "SYNTHETIC_REGISTRY"))

    def test_detects_module_level_annassign(self):
        self.assertTrue(self._defines("SYNTHETIC_MAX: int = 4\n", "SYNTHETIC_MAX"))

    def test_detects_multi_target_assignment(self):
        self.assertTrue(self._defines("A = B = 1\n", "A"))
        self.assertTrue(self._defines("A = B = 1\n", "B"))

    def test_ignores_function_local_shadow(self):
        """A consumer handler may legally use a local variable that shadows a
        keyword; that is not a domain duplicate."""
        self.assertFalse(self._defines("def handler():\n    plan_label = 'x'\n", "plan_label"))

    def test_ignores_bare_reference(self):
        self.assertFalse(self._defines("x = plan_label\n", "plan_label"))

    def test_ignores_import(self):
        self.assertFalse(self._defines("from config.plan_identity import plan_label\n", "plan_label"))

    def test_ignores_import_as(self):
        self.assertFalse(
            self._defines("from config.plan_identity import plan_label as lbl\n", "plan_label")
        )

    def test_ignores_attribute_access(self):
        self.assertFalse(self._defines("config.plan_label()\n", "plan_label"))


if __name__ == "__main__":
    unittest.main()