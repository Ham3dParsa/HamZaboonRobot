"""Phase 2 R13b tests: failure-count-all, temporary backoff, recover-to-preferred.

Locked via owner decision (count ALL failures — 429/connection/timeout; at a
consecutive-failure threshold temporarily sideline the preset; route to the next
stable preset; after the backoff expires, return to the preferred/highest-
priority preset). No user-quota interaction in scope (R13 covers preset RPD only).
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from services import db
from services.db import schema as db_schema
from services.ai import ai
from services.ai import llm_services
from services.ai.llm_services import _call_ai_limited, AllPresetsExhausted


def _seed(presets_data):
    for p in presets_data:
        db.set_preset(
            name=p["name"],
            base_url=p.get("base_url", "http://test.local/v1"),
            model=p.get("model", "test-model"),
            api_key=p.get("api_key", "sk-test"),
            is_custom=1,
            is_emergency=p.get("is_emergency", 0),
            priority=p.get("priority", 0),
            in_fallback_chain=p.get("in_fallback_chain", 1),
        )
        db.set_preset_priority(p["name"], p.get("priority", 0))
        db.set_preset_enabled(p["name"], p.get("enabled", 1))


class _BackoffIsolatedDb(unittest.TestCase):
    def setUp(self):
        self.tempdir = __import__("tempfile").TemporaryDirectory()
        self.t0 = db.DB_PATH
        self.t1 = db_schema.DB_PATH
        db.DB_PATH = __import__("os").path.join(self.tempdir.name, "t.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        for existing in db.get_presets():
            db.delete_preset(existing["name"])
        llm_services._get_limiter_for_preset._states = {}

    def tearDown(self):
        llm_services._get_limiter_for_preset._states = {}
        db.DB_PATH = self.t0
        db_schema.DB_PATH = self.t1
        self.tempdir.cleanup()


class CountAllFailuresBackoffTests(_BackoffIsolatedDb):
    def _call_success(self):
        def ok(*a, **k):
            return {"preset": k["preset"]["name"]}

        return _call_ai_limited(ok, request_kind="grammar_tip")

    @patch("services.ai.llm_services._is_preset_rate_limited", return_value=False)
    def test_single_transient_failure_routes_to_next(self, _):
        """One failure (even 429) must not be penalized yet; next preset serves."""
        _seed([
            {"name": "pa", "priority": 0},
            {"name": "pb", "priority": 1},
        ])

        def mock(*a, **k):
            if k["preset"]["name"] == "pa":
                raise ai.RateLimitError("429 too many requests")
            return {"preset": "pb"}

        result = _call_ai_limited(mock, request_kind="grammar_tip")
        self.assertEqual(result, {"preset": "pb"})

    @patch("services.ai.llm_services._is_preset_rate_limited", return_value=False)
    def test_reaches_threshold_then_sidelined_and_routes_to_next(self, _):
        """After reaching the consecutive-failure threshold, the failing preset is
        temporarily sidelined and a later call routes straight to the stable one."""
        _seed([
            {"name": "pa", "priority": 0},
        ])
        calls = {"pa": 0, "pb": 0}

        def fail_pa(*a, **k):
            name = k["preset"]["name"]
            calls[name] += 1
            if name == "pa":
                raise ai.RateLimitError("429 too many requests")
            return {"preset": name}

        # Exhaust pa's threshold so it becomes sidelined (in backoff). No other
        # preset is seeded, so each call exhausts and raises AllPresetsExhausted.
        for _ in range(llm_services.FAILURE_THRESHOLD):
            with self.assertRaises(AllPresetsExhausted):
                _call_ai_limited(fail_pa, request_kind="grammar_tip")

        # Add a stable preset; pa is sidelined, pb serves immediately.
        _seed([{"name": "pb", "priority": 1}])
        calls["pa"] = 0
        calls["pb"] = 0
        result = _call_ai_limited(fail_pa, request_kind="grammar_tip")
        self.assertEqual(result, {"preset": "pb"})
        self.assertEqual(calls["pb"], 1, "stable preset should serve once")
        self.assertEqual(calls["pa"], 0, "sidelined preset should not be called")

    @patch("services.ai.llm_services._is_preset_rate_limited", return_value=False)
    def test_backoff_expiry_recovers_preferred(self, _):
        """After the backoff window expires, the preferred/highest-priority preset
        is tried again and serves on success."""
        _seed([
            {"name": "pa", "priority": 0},
            {"name": "pb", "priority": 1},
        ])
        calls = {"pa": 0, "pb": 0}

        def fail_then_ok(*a, **k):
            name = k["preset"]["name"]
            calls[name] += 1
            if name == "pa" and not getattr(fail_then_ok, "turned_on", False):
                raise ai.RateLimitError("429 too many requests")
            return {"preset": name}

        # Sidelined: exhaust pa's threshold while pb is down too, so the call
        # raises instead of a sneaking pb success clearing it.
        calls["pb"] = 0
        # Override pb to fail during the exhaustion pass so threshold is reached.
        def fail_all(*a, **k):
            raise ai.RateLimitError("429 too many requests")

        with patch("services.ai.llm_services.db.get_fallback_chain_presets") as mock_chain:
            mock_chain.return_value = [
                db.get_preset("pa"), db.get_preset("pb"),
            ]
            for _ in range(llm_services.FAILURE_THRESHOLD):
                with self.assertRaises(AllPresetsExhausted):
                    _call_ai_limited(fail_all, request_kind="grammar_tip")

        # Fast-forward: pretend the backoff window elapsed.
        limiter = llm_services._get_limiter_for_preset(db.get_preset("pa"))
        limiter["backoff_until"] = time.monotonic() - 1
        fail_then_ok.turned_on = True

        result = _call_ai_limited(fail_then_ok, request_kind="grammar_tip")
        self.assertEqual(result, {"preset": "pa"}, "preferred preset should recover")


if __name__ == "__main__":
    unittest.main()