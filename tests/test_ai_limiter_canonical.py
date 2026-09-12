"""REF5-T4 canonical-ownership tests: the AI limiter lives in limiter.py.

Proves the pure-first split, following the T1-T3 alias pattern:
- ``services/ai/limiter.py`` is the single source of truth for
  ``LimiterStore`` (+ reset/swap-guard seam), the prune throttle
  (``_maybe_prune_hourly_usage``, ~1x/hour, off the hot path), the backoff
  predicate (``_preset_in_backoff``) and the limiter constants.
- ``services/ai/llm_services.py`` keeps thin re-export aliases only (no
  canonical definitions), so existing callers keep working unchanged.
- Behavior is byte-identical: sync ``BoundedSemaphore`` + ``in_flight`` +
  mid-flight swap guard + ``reset()``; NO async rewrite.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest import mock

from services.ai import limiter, llm_services


class LimiterCanonicalOwnershipTest(unittest.TestCase):
    """limiter.py owns the limiter; llm_services.py only re-exports it."""

    def test_aliases_are_identical_objects(self):
        self.assertIs(llm_services.LimiterStore, limiter.LimiterStore)
        self.assertIs(llm_services.get_limiter_store, limiter.get_limiter_store)
        self.assertIs(llm_services._limiter_store, limiter._limiter_store)
        self.assertIs(
            llm_services._maybe_prune_hourly_usage,
            limiter._maybe_prune_hourly_usage,
        )
        self.assertIs(
            llm_services._get_limiter_for_preset,
            limiter._get_limiter_for_preset,
        )
        self.assertIs(
            llm_services._preset_in_backoff, limiter._preset_in_backoff
        )

    def test_constants_match_canonical_values(self):
        self.assertEqual(limiter.FAILURE_THRESHOLD, 3)
        self.assertEqual(limiter.BACKOFF_SECONDS, 60)
        self.assertEqual(limiter._PRUNE_INTERVAL_SECONDS, 3600)
        self.assertEqual(
            llm_services.FAILURE_THRESHOLD, limiter.FAILURE_THRESHOLD
        )
        self.assertEqual(llm_services.BACKOFF_SECONDS, limiter.BACKOFF_SECONDS)

    def test_llm_services_defines_no_canonical_limiter_symbols(self):
        """Single-source proof: no class/function redefinition survives in
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
            "LimiterStore",
            "get_limiter_store",
            "_maybe_prune_hourly_usage",
            "_get_limiter_for_preset",
            "_preset_in_backoff",
        ):
            self.assertNotIn(
                symbol,
                defined,
                f"{symbol} still defined in llm_services.py",
            )


class LimiterBehaviorPreservedTest(unittest.TestCase):
    """Prune throttle + backoff predicate behave exactly as before the move."""

    def test_prune_throttled_to_once_per_hour(self):
        old = limiter._last_hourly_prune
        limiter._last_hourly_prune = 0.0
        try:
            with mock.patch.object(
                limiter, "db"
            ) as mock_db, mock.patch.object(
                limiter.time, "monotonic", return_value=10_000.0
            ):
                pruner = mock_db.prune_preset_hourly_usage
                limiter._maybe_prune_hourly_usage()
                limiter._maybe_prune_hourly_usage()
                self.assertEqual(
                    pruner.call_count, 1, "prune must run at most once per hour"
                )
        finally:
            limiter._last_hourly_prune = old

    def test_preset_in_backoff_predicate(self):
        now = limiter.time.monotonic()
        self.assertTrue(
            limiter._preset_in_backoff({"backoff_until": now + 60}, now=now)
        )
        self.assertFalse(
            limiter._preset_in_backoff({"backoff_until": now - 1}, now=now)
        )
        self.assertFalse(
            limiter._preset_in_backoff({"backoff_until": 0.0}, now=now)
        )

    def test_reset_seam_clears_state(self):
        store = limiter.get_limiter_store()
        store.limiter_for({"name": "canonical-probe", "max_concurrency": 2})
        self.assertIn("canonical-probe", store._states)
        store.reset()
        self.assertEqual(store._states, {})


if __name__ == "__main__":
    unittest.main()
