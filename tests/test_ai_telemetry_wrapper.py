import inspect
import unittest
from unittest.mock import Mock, patch

from services.ai import ai, telemetry


class _OutcomeProbe:
    """Capture the outcome passed to _log_llm_request for one call."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return None


class TelemetryOutcomeTests(unittest.TestCase):
    """The cost-outcome rule (billed vs zero-cost) is defined once and shared
    by every tracked AI call through a single wrapper.

    REF5-T3: the wrapper lives in ``services.ai.telemetry``; ``ai.*`` are
    thin re-export aliases, so the probes patch the telemetry owner while the
    calls go through the ``ai`` alias path."""

    def _run_ask_json(self, request_json_return, request_json_side_effect=None):
        probe = _OutcomeProbe()
        with (
            patch.object(ai, "_request_json", return_value=request_json_return, side_effect=request_json_side_effect),
            patch.object(telemetry, "_log_llm_request", side_effect=probe),
            patch.object(ai, "_model", return_value="test-model"),
        ):
            try:
                ai.ask_json("system", request_kind="grammar_tip")
            except Exception:
                pass
        return probe.calls

    def test_success_classifies_as_success(self):
        calls = self._run_ask_json({"some": "value"})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["outcome"], "success")

    def test_billed_failure_when_usage_present(self):
        # _request_json sets telemetry["usage"] then raises a non-429 error
        def fail_with_usage(*args, **kwargs):
            tele = kwargs["telemetry"]
            tele["usage"] = Mock()
            tele["model"] = "test-model"
            raise ValueError("boom after usage")

        calls = self._run_ask_json(None, request_json_side_effect=fail_with_usage)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["outcome"], "failure_billed")

    def test_zero_cost_failure_when_no_usage(self):
        def fail_before_usage(*args, **kwargs):
            raise ValueError("boom before usage")

        calls = self._run_ask_json(None, request_json_side_effect=fail_before_usage)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["outcome"], "failure_zero_cost")

    def test_all_tracked_calls_share_the_outcome_rule(self):
        # The billed-vs-zero-cost decision lives in exactly one place.
        src = inspect.getsource(telemetry._call_tracked)
        self.assertEqual(src.count('"failure_billed"'), 1)
        self.assertEqual(src.count("failure_zero_cost"), 1)
        self.assertIs(ai._call_tracked, telemetry._call_tracked)
        # No inline ternary survives in the four wrapped call sites.
        for name in ("repair_card", "ask_json", "ask_card", "ask_batch"):
            call_src = inspect.getsource(getattr(ai, name))
            self.assertNotIn('"failure_billed"', call_src)
            self.assertNotIn("failure_zero_cost", call_src)

    def test_custom_log_target_is_honored(self):
        # A test-only caller can route the record to a custom writer instead
        # of the llm_requests table.
        captured: list[dict] = []

        def custom_writer(**kwargs):
            captured.append(kwargs)

        with (
            patch.object(ai, "_request_json", return_value={"some": "value"}),
            patch.object(ai, "_model", return_value="test-model"),
        ):
            try:
                ai._call_tracked(
                    lambda tele: ai._request_json(
                        "system",
                        request_kind="grammar_tip",
                        telemetry=tele,
                    ),
                    request_kind="grammar_tip",
                    log_target=custom_writer,
                )
            except Exception:
                pass

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["outcome"], "success")

    def test_default_log_target_is_llm_requests_writer(self):
        # Without log_target, the wrapper logs via _log_llm_request.
        probe = _OutcomeProbe()
        with (
            patch.object(ai, "_request_json", return_value={"some": "value"}),
            patch.object(telemetry, "_log_llm_request", side_effect=probe),
            patch.object(ai, "_model", return_value="test-model"),
        ):
            try:
                ai.ask_json("system", request_kind="grammar_tip")
            except Exception:
                pass
        self.assertEqual(len(probe.calls), 1)

    def test_batch_validation_is_visible_to_the_finally_log(self):
        # ask_batch populates telemetry["batch_validation"] before the model
        # call so the finally log can report batch diagnostics.
        probe = _OutcomeProbe()
        with (
            patch.object(ai, "_request_json", return_value=[{"w": "a"}]),
            patch.object(telemetry, "_log_llm_request", side_effect=probe),
            patch.object(ai, "_model", return_value="test-model"),
        ):
            try:
                ai.ask_batch("prompt", expected_count=1)
            except Exception:
                pass
        self.assertEqual(len(probe.calls), 1)
        self.assertIn("batch_validation", probe.calls[0]["telemetry"])

    def test_model_fallback_uses_active_preset_model(self):
        # When fn records no model, the finally writer falls back to _model.
        captured: dict = {}

        def writer(**kwargs):
            captured.update(kwargs)

        with patch.object(ai, "_model", return_value="fallback-model"):
            result = telemetry._call_tracked(
                lambda tele: "ok",
                request_kind="json",
                log_target=writer,
            )
        self.assertEqual(captured["model"], "fallback-model")
        self.assertEqual(captured["outcome"], "success")
        self.assertEqual(result.value, "ok")

    def test_explicit_telemetry_model_wins_over_fallback(self):
        captured: dict = {}

        def writer(**kwargs):
            captured.update(kwargs)

        def _run(tele):
            tele["model"] = "explicit-model"
            return "ok"

        with patch.object(ai, "_model", return_value="fallback-model"):
            telemetry._call_tracked(_run, request_kind="json", log_target=writer)
        self.assertEqual(captured["model"], "explicit-model")


class TelemetryAliasTests(unittest.TestCase):
    """REF5-T3: ai.* remain as re-export aliases of telemetry (dead-ref guard)."""

    def test_ai_reexports_are_telemetry_objects(self):
        self.assertIs(ai._log_llm_request, telemetry._log_llm_request)
        self.assertIs(ai._call_tracked, telemetry._call_tracked)
        self.assertIs(ai.TrackedResult, telemetry.TrackedResult)
        self.assertIs(ai._COST_OUTCOME_ICON, telemetry._COST_OUTCOME_ICON)


if __name__ == "__main__":
    unittest.main()
