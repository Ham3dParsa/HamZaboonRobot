"""Dead-reference guard for WP2.

Fails CI if any symbol that a locked plan deliberately removed still exists
(or is referenced, imported, or defined) anywhere in production code.

Production code = bot.py, handlers/, services/, config/. Code an owner wants
to KEEP must either live outside those directories (tools/, docs/, tests/),
or be listed in PRESERVED_SYMBOLS with a why-comment.

Adding a banned symbol:
    When a plan deletes a symbol (e.g. a function, constant, or column-backed
    constant removed by the FSRS migration), add its name to BANNED_SYMBOLS
    with a why-comment. From then on, CI fails if it ever reappears.

Removing a banned symbol:
    Only remove an entry if the decision to delete it was reversed by the
    owner in a locked contract. Removing an entry silently re-enables the
    exact "leftover code survives the migration" failure mode this guard
    exists to prevent.
"""

import ast
import unittest
from pathlib import Path

# Root-relative production scan targets. Anything not in this set is never
# scanned: tools/, docs/, tests/, and archives are preservation zones.
PRODUCTION_SCAN_TARGETS = [
    Path("bot.py"),
    Path("handlers"),
    Path("services"),
    Path("config"),
]

# ---------------------------------------------------------------------------
# Banned / preserved registries
# ---------------------------------------------------------------------------

# Symbols that were deliberately deleted by a locked plan and must never
# reappear in production code. key = symbol name, value = why it is banned.
#
# NOTE (columns): removed DB *columns* are NOT tracked here — the AST scanner
# only sees identifiers, and column names appear as SQL string literals /
# dict keys, which are invisible to it. Track removed columns in
# BANNED_COLUMNS in tests/test_migration_guards.py instead (see the
# interval_idx entry there).
BANNED_SYMBOLS: dict[str, str] = {
    "_answer_callback_safely": (
        "removed by callback-notification foundation: semantic notify_callback() owns "
        "callback answer presentation and expected Telegram failures"
    ),
    "_custom_word_input_error": (
        "removed by custom-word-query Rule B: inline regex/heuristic validation in "
        "handlers/user.py replaced by the validate_word_query() seam in "
        "services/utils/validation.py (digit rejection, Unicode isalpha, no vowel "
        "heuristic)"
    ),
    "advance_word_review": (
        "removed by FSRS migration Phase 2: interval-ladder scheduling replaced "
        "by grade_word_review()/FSRS stability"
    ),
    "defer_word_review": (
        "removed by FSRS migration Phase 2: interval-ladder scheduling replaced "
        "by grade_word_review()/FSRS stability"
    ),
    "INTERVALS_DAYS": (
        "removed by FSRS migration Phase 2: [1,3,7,16,30] ladder replaced by "
        "FSRS-6 stability/difficulty scheduling"
    ),
    "IBTN_REMEMBERED": (
        "removed by FSRS migration Phase 2: old 2-button SRS labels replaced by "
        "4-grade review buttons"
    ),
    "IBTN_CONFIRM_CORRECT": (
        "removed by FSRS migration Phase 2: old 2-button SRS labels replaced by "
        "4-grade review buttons"
    ),
    "IBTN_REMIND_AGAIN": (
        "removed by FSRS migration Phase 2: old 2-button SRS labels replaced by "
        "4-grade review buttons"
    ),
    "IBTN_SAVE_PRESET": (
        "removed by preset-save-preview T3: orphaned export superseded by the "
        "edit-menu counter labels in config/keyboards/admin.py"
    ),
    "IBTN_DISCARD_ALL": (
        "removed by preset-save-preview T3: orphaned export superseded by the "
        "edit-menu counter labels in config/keyboards/admin.py"
    ),
    "srs_engine": (
        "removed by FSRS migration Phase 1c: services/srs_engine.py scaffold "
        "replaced by the services/session/ package"
    ),
    "_generate_daily_batch": (
        "removed by FSRS migration Phase 2: daily-card batch AI generation replaced "
        "by the reusable ai.ask_batch layer + saved-words FSRS flow"
    ),
    "_daily_avoid_words": (
        "removed by FSRS migration Phase 2: daily-card avoid-word tracking replaced "
        "by saved-words review flow"
    ),
    "_ensure_daily_cards": (
        "removed by FSRS migration Phase 2: daily-card priming replaced by the "
        "saved-words FSRS flow"
    ),
    "_ensure_next_daily_card": (
        "removed by FSRS migration Phase 2: daily-card delivery replaced by the "
        "saved-words FSRS flow"
    ),
    "_send_next_daily_card": (
        "removed by FSRS migration Phase 2: daily-card delivery replaced by the "
        "saved-words FSRS flow"
    ),
    "_send_card_from_store": (
        "removed by FSRS migration Phase 2: daily-card store delivery replaced by "
        "the saved-words FSRS flow"
    ),
    "send_daily_card_now": (
        "removed by FSRS migration Phase 2: manual daily-card send replaced by the "
        "saved-words FSRS flow"
    ),
    "_show_review_date": (
        "removed by FSRS migration Phase 2: daily-card review-date summary replaced "
        "by the saved-words FSRS flow"
    ),
    "start_srs_review": (
        "removed by FSRS migration Phase 2: legacy review-history menu replaced by "
        "the saved-words FSRS flow"
    ),
    "_show_review_menu": (
        "removed by FSRS migration Phase 2: legacy review menu replaced by the "
        "saved-words FSRS flow"
    ),
    "_handle_daily_prepare": (
        "removed by FSRS migration Phase 2: daily-card prepare callback replaced by "
        "the saved-words FSRS flow"
    ),
    "_review_history_page": (
        "removed by FSRS migration Phase 2: legacy review-history paging replaced by "
        "the saved-words FSRS flow"
    ),
    "_handle_srs_prepare": (
        "removed by FSRS migration Phase 2: SRS prepare callback replaced by the "
        "4-grade review flow"
    ),
    "daily_card_keyboard": (
        "removed by FSRS migration Phase 2: daily-card keyboard replaced by the "
        "saved-words FSRS flow"
    ),
    "daily_review_menu_keyboard": (
        "removed by FSRS migration Phase 2: legacy review menu keyboard removed with "
        "the saved-words FSRS flow"
    ),
    "daily_review_dates_keyboard": (
        "removed by FSRS migration Phase 2: legacy review-history keyboard removed "
        "with the saved-words FSRS flow"
    ),
    "srs_hidden_keyboard": (
        "removed by FSRS migration Phase 2: staged-reveal hidden keyboard replaced "
        "by the 4-grade review flow"
    ),
    "srs_revealed_keyboard": (
        "removed by FSRS migration Phase 2: staged-reveal shown keyboard replaced "
        "by the 4-grade review flow"
    ),
    "srs_review_keyboard": (
        "removed by FSRS migration Phase 2: legacy review keyboard replaced by the "
        "4-grade review flow"
    ),
    "get_daily_cards": (
        "removed by FSRS migration Phase 2b: daily persistence was replaced by "
        "saved_words first-exposure state"
    ),
    "get_recent_daily_words": (
        "removed by FSRS migration Phase 2b with the daily_cards table"
    ),
    "get_recent_daily_card_dates": (
        "removed by FSRS migration Phase 2b with the daily_cards table"
    ),
    "count_daily_cards": (
        "removed by FSRS migration Phase 2b with the daily_cards table"
    ),
    "add_daily_card": (
        "removed by FSRS migration Phase 2b: new cards enter saved_words"
    ),
    "update_daily_card_fields": (
        "removed by FSRS migration Phase 2b with the daily_cards table"
    ),
    "get_daily_progress": (
        "removed by FSRS migration Phase 2b with the daily_progress table"
    ),
    "set_daily_progress": (
        "removed by FSRS migration Phase 2b with the daily_progress table"
    ),
    "get_daily_card_session": (
        "removed by FSRS migration Phase 2b with daily_card_sessions"
    ),
    "ensure_daily_card_session": (
        "removed by FSRS migration Phase 2b with daily_card_sessions"
    ),
    "migrate_saved_words_to_fsrs": (
        "removed after the guarded daily_cards to saved_words migration completed"
    ),
    "ACTIVITY_REGISTRY": (
        "removed by architecture deepening finding #4: dormant UI registry never "
        "used by a production caller; study_handler owns rendering"
    ),
    "ActivityHandler": (
        "removed by architecture deepening finding #4: dormant UI-registry wrapper "
        "never used by a production caller"
    ),
    "get_interaction_ui": (
        "removed by architecture deepening finding #4: dormant UI lookup removed "
        "with the ActivityHandler registry"
    ),
    "build_session": (
        "removed by architecture deepening finding #4: duplicate generator "
        "assembler; build_session_list is the single handler-facing seam"
    ),
    "ai_custom_test_wizard_keyboard": (
        "removed by architecture deepening finding #2: dead keyboard with a latent "
        "catalog import error; inline _custom_test_step_lang is the canonical path"
    ),
    "format_srs_prompt": (
        "removed by #338 SRS staged-reveal: single hidden-instruction prompt replaced "
        "by the randomized prompt engine (format_srs_front_stage / format_srs_back_stage)"
    ),
    "SRS_HIDDEN_INSTRUCTION": (
        "removed by #338 SRS staged-reveal: generic spaced-repetition intro replaced "
        "by per-prompt-type instruct strings in the staged-reveal engine"
    ),
    "SRS_REVEAL_QUESTION": (
        "removed by #338 SRS staged-reveal: post-reveal text is SRS_POST_REVEAL and "
        "grading moved to the grade buttons"
    ),
    "get_phonetic_display_settings": (
        "removed by #338 phonetic-knob decision (owner, 2026-08-15): dead/ambiguous "
        "legacy admin knob never consumed by the render path; the phonetic display "
        "toggle is the single source of truth via display-toggle defaults"
    ),
    "DEFAULT_PHONETIC_SHOW_IPA": (
        "removed by #338 phonetic-knob decision (owner, 2026-08-15): env knob replaced "
        "by the admin-global phonetic display-toggle default"
    ),
    "PLANS": (
        "removed by J-B6 plan-identity leaf (config/plan_identity.py, 2026-08-17): "
        "duplicate plan-name map superseded by the canonical _PLANS registry + "
        "valid_plans()/plan_label(); config and services/db/plans.py now delegate to it"
    ),
    "PREMIUM_PLANS": (
        "removed by J-B6 plan-identity leaf (config/plan_identity.py, 2026-08-17): "
        "parallel premium-tier frozenset superseded by _PLANS premium flag + "
        "is_premium()/has_feature()"
    ),
    "tts_access": (
        "removed by #390 always-on pronunciation (owner, 2026-08-19): admin audio "
        "on/off knob retired; 🔊 is available to every plan with no toggle; stale "
        "settings row deleted at startup (services/db/schema.py)"
    ),
    "should_show_pronounce": (
        "removed by #390 always-on pronunciation (owner, 2026-08-19): per-user "
        "pronounce gate retired with tts_access"
    ),
    "show_pronounce": (
        "removed by #390 always-on pronunciation (owner, 2026-08-19): keyboards now "
        "always include the 🔊 row; callers no longer pass a show_pronounce flag"
    ),
    "phonetic_settings_keyboard": (
        "removed by #390 always-on pronunciation (owner, 2026-08-19): admin "
        "IPA/audio phonetics panel retired entirely"
    ),
    "IBTN_IPA": (
        "removed by #390 always-on pronunciation (owner, 2026-08-19): admin IPA "
        "on/off button retired with the phonetics panel"
    ),
    "IBTN_ADMIN_PHONETICS": (
        "removed by #390 always-on pronunciation (owner, 2026-08-19): admin phonetics "
        "menu button retired"
    ),
    "_phonetic_ipa_default": (
        "removed by #390 always-on pronunciation (owner, 2026-08-19): IPA default "
        "lookup helper retired with the phonetics panel"
    ),
    "_phonetic_settings_text": (
        "removed by #390 always-on pronunciation (owner, 2026-08-19): admin phonetics "
        "status text retired"
    ),
    "_send_voice_with_retry": (
        "removed by phase-03 retry seam move (R1): dead backward-compat wrapper "
        "with zero production callers; voice sends go through the unified "
        "_send_media_with_retry core owned by services/send_pretty.py"
    ),
    "_send_document_with_retry": (
        "removed by phase-03 retry seam move (R1): dead backward-compat wrapper "
        "with zero production callers; document sends go through the unified "
        "_send_media_with_retry core owned by services/send_pretty.py"
    ),
}

# Symbols that are intentionally retained even though they are no longer
# referenced by the current flow. key = symbol name, value = why it is kept.
# The guard skips these, so they never trip CI.
PRESERVED_SYMBOLS: dict[str, str] = {
    "get_conn": "core database choke point; intentionally retained",
}


def _symbols_in_tree(tree: ast.AST) -> set[str]:
    """Collect every identifier-shaped symbol in a parsed module."""
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # import foo.bar as baz -> symbol is the local name (baz / foo)
                found.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    found.add(alias.asname or alias.name)

    return found


def _iter_production_files():
    for target in PRODUCTION_SCAN_TARGETS:
        if target.is_file():
            yield target
        elif target.is_dir():
            yield from sorted(target.rglob("*.py"))


def _production_file_count() -> int:
    return sum(1 for _ in _iter_production_files())


def find_banned_hits() -> dict[str, list[str]]:
    """Return {banned_symbol: [file_path, ...]} for every banned symbol that
    appears anywhere in production code."""
    hits: dict[str, list[str]] = {sym: [] for sym in BANNED_SYMBOLS}

    for filepath in _iter_production_files():
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            # A syntax error in production is caught elsewhere (compile_all,
            # ruff); the guard must not crash the suite on malformed files.
            continue

        symbols = _symbols_in_tree(tree)
        for sym in BANNED_SYMBOLS:
            if sym in symbols:
                hits[sym].append(str(filepath))

    return hits


class TestDeadCodeGuard(unittest.TestCase):
    """The guard: no deliberately-removed symbol may survive in production."""

    def test_production_contains_no_banned_symbols(self):
        hits = find_banned_hits()
        offending = {sym: files for sym, files in hits.items() if files}
        if offending:
            msg = "Banned symbols still present in production code:\n"
            for sym, files in offending.items():
                msg += f"  {sym}  (why: {BANNED_SYMBOLS[sym]})\n"
                for f in files:
                    msg += f"    {f}\n"
            self.fail(msg)

    def test_registry_entries_require_why(self):
        for sym, why in BANNED_SYMBOLS.items():
            self.assertGreaterEqual(len(sym), 1, "banned symbol name empty")
            self.assertTrue(
                why and why.strip(),
                f"BANNED_SYMBOLS[{sym}] needs a why-comment",
            )
        for sym, why in PRESERVED_SYMBOLS.items():
            self.assertTrue(
                why and why.strip(),
                f"PRESERVED_SYMBOLS[{sym}] needs a why-comment",
            )

    def test_scan_scope_is_production_only(self):
        """tools/, docs/, tests/ are never scanned and can never trip the guard."""
        allowed_roots = ("bot.py", "handlers", "services", "config")
        for target in PRODUCTION_SCAN_TARGETS:
            self.assertTrue(
                str(target) in allowed_roots,
                f"scan target {target} is outside the production allowlist",
            )

    def test_production_sources_are_found(self):
        """Fail loudly (not vacuously pass) if run from the wrong working
        directory: the guard must prove it actually scanned real files."""
        count = _production_file_count()
        self.assertGreater(
            count,
            10,
            f"only {count} production .py files found; "
            "is this test running from the repo root?",
        )


class TestScannerDetection(unittest.TestCase):
    """Unit-test the scanner: prove it detects a banned symbol in each form
    (definition, reference, attribute access, import) using synthetic code."""

    def _detects(self, source: str) -> bool:
        tree = ast.parse(source)
        return "synthetic_banned_symbol" in _symbols_in_tree(tree)

    def test_detects_function_definition(self):
        self.assertTrue(self._detects("def synthetic_banned_symbol():\n    pass\n"))

    def test_detects_class_definition(self):
        self.assertTrue(self._detects("class synthetic_banned_symbol:\n    pass\n"))

    def test_detects_name_reference(self):
        self.assertTrue(self._detects("x = synthetic_banned_symbol\n"))

    def test_detects_attribute_access(self):
        self.assertTrue(self._detects("db.synthetic_banned_symbol()\n"))

    def test_detects_import(self):
        self.assertTrue(self._detects("from legacy import synthetic_banned_symbol\n"))

    def test_detects_import_as(self):
        self.assertTrue(self._detects("from legacy import x as synthetic_banned_symbol\n"))

    def test_ignores_similar_but_distinct_names(self):
        self.assertFalse(self._detects("synthetic_banned_symbol_extra = 1\n"))
        self.assertFalse(self._detects("synthetic_banned = 1\n"))

    def test_preserved_symbols_never_flagged(self):
        """PRESERVED symbols are intentionally retained; the guard must never
        report them. The guard only scans BANNED_SYMBOLS, and the registries
        must stay disjoint so a retained symbol can never be banned."""
        hits = find_banned_hits()
        for sym in PRESERVED_SYMBOLS:
            self.assertNotIn(sym, hits, f"preserved symbol {sym} was flagged")
        self.assertEqual(
            set(PRESERVED_SYMBOLS) & set(BANNED_SYMBOLS),
            set(),
            "a symbol cannot be both banned and preserved",
        )


if __name__ == "__main__":
    unittest.main()
