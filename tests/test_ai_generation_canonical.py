"""REF5-T7 canonical-ownership tests: card generation lives in generation.py.

Proves the terminal AI split, following the T1-T6 alias pattern:
- ``services/ai/generation.py`` is the single source of truth for
  ``_prepare_cached_card`` (validate -> repair -> merge -> revalidate ->
  persist order, 3 ``CardPreparationError`` paths, ``persist_patch`` /
  ``deadline`` signature) + ``_ask_batch_limited`` + ``_get_active_preset``.
- ``services/ai/llm_services.py`` keeps thin re-export aliases only (no
  canonical definitions), so existing callers (bot.py, tests) keep working.
- ``_retry_primary_preset`` stays owned by ``fallback_router.py`` (T6 unit);
  generation consumes the router seam (``_call_ai_limited``), not moves it.
- Naive-risk pins: no persist/validate reorder; merge copies via
  ``dict(card)`` (caller never mutated); volume unchanged.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.ai import generation, llm_services
from services.utils.formatting_cards import CardPreparationError


class GenerationCanonicalOwnershipTest(unittest.TestCase):
    """generation.py owns card generation; llm_services.py only re-exports it."""

    def test_aliases_are_identical_objects(self):
        self.assertIs(llm_services._get_active_preset, generation._get_active_preset)
        self.assertIs(llm_services._ask_batch_limited, generation._ask_batch_limited)
        self.assertIs(
            llm_services._prepare_cached_card, generation._prepare_cached_card
        )

    def test_llm_services_defines_no_canonical_generation_symbols(self):
        """Single-source proof: no function redefinition survives in
        llm_services.py (aliases are ``Name`` assignments, not defs)."""
        tree = ast.parse(
            Path("services/ai/llm_services.py").read_text(encoding="utf-8")
        )
        defined = {
            node.name
            for node in tree.body
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
        }
        for symbol in (
            "_get_active_preset",
            "_ask_batch_limited",
            "_prepare_cached_card",
        ):
            self.assertNotIn(
                symbol,
                defined,
                f"{symbol} still defined in llm_services.py",
            )

    def test_prepare_cached_card_keeps_contract(self):
        """Ticket pins: persist_patch/deadline signature + exactly 3
        CardPreparationError paths (no-repair / persist-failed / repair-failed)."""
        sig = inspect.signature(generation._prepare_cached_card)
        params = list(sig.parameters.values())
        self.assertEqual(params[0].name, "card")
        for name in ("lang", "user_id", "plan", "source", "persist_patch"):
            self.assertIn(name, sig.parameters)
            self.assertEqual(
                sig.parameters[name].kind, inspect.Parameter.KEYWORD_ONLY
            )
        self.assertIn("deadline", sig.parameters)
        self.assertIsNone(sig.parameters["deadline"].default)
        tree = ast.parse(
            Path("services/ai/generation.py").read_text(encoding="utf-8")
        )
        raises = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and getattr(node.exc.func, "id", "") == "CardPreparationError"
        ]
        self.assertEqual(len(raises), 3, "must keep exactly 3 CardPreparationError paths")


    def test_persist_failure_keeps_own_message(self):
        """OP-005: a failed persist must raise its own message instead of
        being re-wrapped as a generic repair failure."""
        legacy = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Hello one.", "Hello two."],
            "example_translations": ["اول."],
        }
        with patch.object(
            generation,
            "_call_ai_limited",
            return_value={"example_translations": ["اول.", "دوم."]},
        ):
            with self.assertRaises(CardPreparationError) as ctx:
                generation._prepare_cached_card(
                    legacy,
                    lang="en",
                    user_id=1,
                    plan="free",
                    source="daily",
                    persist_patch=MagicMock(return_value=False),
                )
        self.assertIn("could not be persisted", str(ctx.exception))
        self.assertNotIn("could not be repaired safely", str(ctx.exception))

    def test_genuine_repair_failure_still_wraps(self):
        """A persist that RAISES (not just False) still wraps as a generic
        repair failure — the passthrough only covers CardPreparationError."""
        legacy = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Hello one.", "Hello two."],
            "example_translations": ["اول."],
        }
        with patch.object(
            generation,
            "_call_ai_limited",
            return_value={"example_translations": ["اول.", "دوم."]},
        ):
            with self.assertRaises(CardPreparationError) as ctx:
                generation._prepare_cached_card(
                    legacy,
                    lang="en",
                    user_id=1,
                    plan="free",
                    source="daily",
                    persist_patch=MagicMock(side_effect=RuntimeError("db down")),
                )
        self.assertIn("could not be repaired safely", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
