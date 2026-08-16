"""J-B1 hardening tests: real-token TPM logging, lazy LimiterStore limits, compact unification.

Covers the three AI-track rules that need focused verification beyond the
existing fallback/backoff tests:

- Rule 2 (BUG-1): ``_log_preset_usage`` reads the real provider token count
  from the ``TrackedResult`` telemetry so the TPM cap is enforced, instead of
  always logging 0 tokens.
- Rule 3 (BUG-5): ``LimiterStore`` reads RPM/TPM/concurrency limits lazily from
  the preset on each acquisition, so an admin edit applies immediately.
- Rule 4 (F4): the card output-format decision is unified behind
  ``prompts.card_output_is_compact()`` and the shared ``build_prompt_prelude``
  header is consumed by the daily-card builder.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from services import db as db_module
from services.db import schema as db_schema
from services.ai import ai
from services.ai import llm_services
from services.ai import prompts


def _seed_preset(name: str = "preset_a", **overrides):
    db_module.set_preset(
        name=name,
        base_url=overrides.get("base_url", "http://test.local/v1"),
        model=overrides.get("model", "test-model"),
        api_key=overrides.get("api_key", "sk-test"),
        max_concurrency=overrides.get("max_concurrency", 2),
        max_rpm=overrides.get("max_rpm", 30),
        max_tpm=overrides.get("max_tpm", 0),
        max_daily_req=overrides.get("max_daily_req", 0),
        is_emergency=overrides.get("is_emergency", 0),
        in_fallback_chain=overrides.get("in_fallback_chain", 1),
    )
    db_module.set_preset_priority(name, overrides.get("priority", 0))
    db_module.set_preset_enabled(name, overrides.get("enabled", 1))
    return db_module.get_preset(name)


class _LimiterIsolatedDb(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db = db_module.DB_PATH
        self.old_schema = db_schema.DB_PATH
        db_module.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db_module.DB_PATH
        db_module.init_db()
        for existing in db_module.get_presets():
            db_module.delete_preset(existing["name"])
        llm_services.get_limiter_store().reset()

    def tearDown(self):
        llm_services.get_limiter_store().reset()
        db_module.DB_PATH = self.old_db
        db_schema.DB_PATH = self.old_schema
        self.tempdir.cleanup()


class RealTokenTpmLoggingTest(_LimiterIsolatedDb):
    """Rule 2 (BUG-1) — real token counts reach hourly usage and the TPM cap."""

    def test_log_preset_usage_reads_tokens_from_tracked_result(self):
        preset = _seed_preset("pa")
        result = ai.TrackedResult(
            value={"card": "ok"},
            telemetry={
                "usage": SimpleNamespace(total_tokens=42),
            },
        )
        llm_services._log_preset_usage(preset, result)

        hour_bucket = __import__("time").strftime(
            "%Y-%m-%dT%H:00:00", __import__("time").gmtime()
        )
        req_count, token_count = db_module.get_hourly_usage("pa", hours_back=24)
        self.assertEqual(req_count, 1)
        self.assertEqual(token_count, 42)

        limiter = llm_services.get_limiter_store().limiter_for(preset)
        with limiter["token_lock"]:
            self.assertEqual(sum(tc for _, tc in limiter["token_times"]), 42)

    def test_log_preset_usage_defaults_to_zero_for_plain_dict(self):
        # A non-TrackedResult (plain dict, e.g. a mock) logs the request with 0
        # tokens — it must not crash and must still count the request.
        preset = _seed_preset("pb")
        llm_services._log_preset_usage(preset, {"card": "ok"})
        req_count, token_count = db_module.get_hourly_usage("pb", hours_back=24)
        self.assertEqual(req_count, 1)
        self.assertEqual(token_count, 0)

    def test_tpm_cap_enforced_from_real_token_count(self):
        # After logging 1200 tokens in a 60s window with max_tpm=1000, the
        # preset must be flagged as rate-limited (TPM path).
        preset = _seed_preset("pc", max_tpm=1000)
        result = ai.TrackedResult(
            value={"card": "ok"},
            telemetry={"usage": SimpleNamespace(total_tokens=1200)},
        )
        llm_services._log_preset_usage(preset, result)
        self.assertTrue(llm_services._is_preset_rate_limited(preset))


class LazyLimiterLimitsTest(_LimiterIsolatedDb):
    """Rule 3 (BUG-5) — RPM/TPM/concurrency read lazily so admin edits apply."""

    def test_limiter_store_rebuilds_semaphore_on_concurrency_change(self):
        store = llm_services.get_limiter_store()
        preset = _seed_preset("pd", max_concurrency=2)
        state = store.limiter_for(preset)
        self.assertEqual(state["slots_capacity"], 2)
        old_slots = state["slots"]

        # Admin edits max_concurrency up; the next acquisition must reflect it.
        db_module.set_preset(
            name="pd",
            base_url="http://test.local/v1",
            model="test-model",
            api_key="sk-test",
            max_concurrency=5,
            is_emergency=0,
            in_fallback_chain=1,
        )
        preset = db_module.get_preset("pd")
        state2 = store.limiter_for(preset)
        self.assertEqual(state2["slots_capacity"], 5)
        self.assertIsNot(state2["slots"], old_slots)

    def test_max_rpm_read_lazily_from_preset(self):
        preset = _seed_preset("pe")
        self.assertEqual(llm_services._limiter_store._max_rpm(preset), 30)
        preset["max_rpm"] = 3
        self.assertEqual(llm_services._limiter_store._max_rpm(preset), 3)


class CompactDecisionUnificationTest(unittest.TestCase):
    """Rule 4 (F4) — one compact decision and a shared prompt prelude."""

    def test_card_output_is_compact_reflects_env(self):
        with mock.patch.object(prompts, "AI_CARD_OUTPUT_FORMAT", "compact_json"):
            self.assertTrue(prompts.card_output_is_compact())
        with mock.patch.object(prompts, "AI_CARD_OUTPUT_FORMAT", "json"):
            self.assertFalse(prompts.card_output_is_compact())

    def test_build_prompt_prelude_centralizes_guidance(self):
        prelude = prompts.build_prompt_prelude("en", "general", "beginner")
        self.assertIn("هدف کاربر:", prelude)
        self.assertIn("سطح کاربر:", prelude)

    def test_daily_card_builder_consumes_prelude(self):
        from config.catalog import language_label, goal_label, level_label
        prompt = prompts.daily_card_system_prompt("en", "general", "beginner")
        self.assertIn(language_label("en"), prompt)
        self.assertIn(goal_label("general"), prompt)
        self.assertIn(level_label("beginner"), prompt)

    def test_custom_word_query_uses_compact_helper(self):
        import services.word_query as wq
        # Force the compact decision deterministically so the test does not
        # depend on the ambient AI_CARD_OUTPUT_FORMAT env value.
        with mock.patch.object(prompts, "AI_CARD_OUTPUT_FORMAT", "compact_json"):
            self.assertEqual(
                wq._build_system_prompt("en", "beginner").count('"word"'), 0
            )


if __name__ == "__main__":
    unittest.main()
