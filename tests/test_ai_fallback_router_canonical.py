"""REF5-T6 canonical-ownership tests: the AI fallback router lives in fallback_router.py.

Proves the pure-first split, following the T1-T4 alias pattern:
- ``services/ai/fallback_router.py`` is the single source of truth for
  ``_call_ai_limited`` (+ rate/daily checks ``_is_daily_exhausted``,
  ``_is_preset_rate_limited``, ``_log_preset_usage``), ``_retry_primary_preset``
  (lazy primary-name resolution), and the ``AllPresetsExhausted`` /
  ``AIRequestTimedOut`` chain.
- ``services/ai/llm_services.py`` keeps thin re-export aliases only (no
  canonical definitions), so existing callers (bot.py, tests) keep working.
- Behavior is byte-identical: chain + single ``usage_map`` (BOT-3) + backoff
  skip + deadline + slot finally + ``AllPresetsExhausted`` chaining the last
  error. Limiter (T4) + chain/cost (T5) seams are consumed, not moved.
- Naive-risk pins: no rate-check split (one batched usage read per call);
  no per-error backoff reset (ALL failures count, R13); volume unchanged
  (reorder, never extra retry).
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from services.ai import fallback_router, llm_services


class FallbackRouterCanonicalOwnershipTest(unittest.TestCase):
    """fallback_router.py owns the router; llm_services.py only re-exports it."""

    def test_aliases_are_identical_objects(self):
        self.assertIs(llm_services.AllPresetsExhausted, fallback_router.AllPresetsExhausted)
        self.assertIs(llm_services.AIRequestTimedOut, fallback_router.AIRequestTimedOut)
        self.assertIs(llm_services._is_daily_exhausted, fallback_router._is_daily_exhausted)
        self.assertIs(
            llm_services._is_preset_rate_limited,
            fallback_router._is_preset_rate_limited,
        )
        self.assertIs(llm_services._log_preset_usage, fallback_router._log_preset_usage)
        self.assertIs(llm_services._call_ai_limited, fallback_router._call_ai_limited)
        self.assertIs(
            llm_services._retry_primary_preset,
            fallback_router._retry_primary_preset,
        )

    def test_llm_services_defines_no_canonical_router_symbols(self):
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
            "AllPresetsExhausted",
            "AIRequestTimedOut",
            "_is_daily_exhausted",
            "_is_preset_rate_limited",
            "_log_preset_usage",
            "_call_ai_limited",
            "_retry_primary_preset",
        ):
            self.assertNotIn(
                symbol,
                defined,
                f"{symbol} still defined in llm_services.py",
            )

    def test_router_consumes_frozen_seams_without_redefining(self):
        """Limiter (T4) + chain/cost (T5) seams are consumed, not moved."""
        tree = ast.parse(
            Path("services/ai/fallback_router.py").read_text(encoding="utf-8")
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
            "_preset_in_backoff",
            "_maybe_prune_hourly_usage",
            "resolve_costs",
            "ReadCache",
            "get_chain",
        ):
            self.assertNotIn(
                symbol,
                defined,
                f"{symbol} must stay in its owner module, not fallback_router.py",
            )


class FallbackRouterLazyRetryTest(unittest.TestCase):
    """The :377 lazy fix survives the move: a set primary name costs zero
    extra ``get_active_preset_name`` lookups; a missing one costs exactly one."""

    def test_lazy_primary_resolution_preserved(self):
        import os
        import tempfile
        from unittest import mock

        from services import db
        from services.db import schema as db_schema

        tempdir = tempfile.TemporaryDirectory()
        prev_db, prev_schema = db.DB_PATH, db_schema.DB_PATH
        db.DB_PATH = os.path.join(tempdir.name, "t.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        try:
            db.init_db()
            for p in db.get_presets():
                db.delete_preset(p["name"])
            db.set_preset(
                name="pa",
                base_url="http://test.local/v1",
                model="test-model",
                api_key="sk-test",
                is_emergency=0,
                in_fallback_chain=1,
            )
            db.set_preset_priority("pa", 0)
            db.set_preset_enabled("pa", 1)
            db.set_setting("ai_primary_preset", "pa")
            db.set_bool_setting("ai_fallback_active", True)
            real = db.get_active_preset_name
            calls = {"n": 0}

            def counting():
                calls["n"] += 1
                return real()

            with (
                mock.patch.object(db, "get_active_preset_name", counting),
                mock.patch.object(
                    fallback_router.ai,
                    "test_connection",
                    return_value={"success": True},
                ),
            ):
                fallback_router._retry_primary_preset()
            self.assertEqual(calls["n"], 0, "set primary must not resolve the default")
        finally:
            db.DB_PATH = prev_db
            db_schema.DB_PATH = prev_schema
            tempdir.cleanup()


if __name__ == "__main__":
    unittest.main()
