import unittest
from unittest.mock import Mock, patch

from services.ai import ai


class _OutcomeProbe:
    """Capture the outcome passed to _log_llm_request for one call."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return None


class TelemetryOutcomeTests(unittest.TestCase):
    """The cost-outcome rule (billed vs zero-cost) is defined once and shared
    by every tracked AI call through a single wrapper."""

    def _run_ask_json(self, request_json_return, request_json_side_effect=None):
        probe = _OutcomeProbe()
        with (
            patch.object(ai, "_request_json", return_value=request_json_return, side_effect=request_json_side_effect),
            patch.object(ai, "_log_llm_request", side_effect=probe),
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
            telemetry = kwargs["telemetry"]
            telemetry["usage"] = Mock()
            telemetry["model"] = "test-model"
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
        import inspect
        src = inspect.getsource(ai._call_tracked)
        self.assertEqual(src.count('"failure_billed"'), 1)
        self.assertEqual(src.count("failure_zero_cost"), 1)
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
                    lambda telemetry: ai._request_json(
                        "system",
                        request_kind="grammar_tip",
                        telemetry=telemetry,
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
            patch.object(ai, "_log_llm_request", side_effect=probe),
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
            patch.object(ai, "_log_llm_request", side_effect=probe),
            patch.object(ai, "_model", return_value="test-model"),
        ):
            try:
                ai.ask_batch("prompt", expected_count=1)
            except Exception:
                pass
        self.assertEqual(len(probe.calls), 1)
        self.assertIn("batch_validation", probe.calls[0]["telemetry"])


if __name__ == "__main__":
    unittest.main()
