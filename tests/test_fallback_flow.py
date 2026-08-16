import os
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

from services import db
from services.db import schema as db_schema
from services.ai import ai
from services.ai.llm_services import _call_ai_limited, AllPresetsExhausted, AIRequestTimedOut


def _seed_test_presets(presets_data: list[dict]):
    """Insert test presets directly into the database."""
    for p in presets_data:
        db.set_preset(
            name=p["name"],
            base_url=p.get("base_url", "http://test.local/v1"),
            model=p.get("model", "test-model"),
            api_key=p.get("api_key", "sk-test"),
            is_emergency=p.get("is_emergency", 0),
            in_fallback_chain=p.get("in_fallback_chain", 1),
        )
        db.set_preset_priority(p["name"], p.get("priority", 0))
        db.set_preset_enabled(p["name"], p.get("enabled", 1))


class FallbackChainTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_db_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        # Clean seed presets so only our test presets exist
        for p in db.get_presets():
            db.delete_preset(p["name"])
        # Reset the shared limiter store so failure/backoff counters do not
        # leak between test methods that reuse the same short preset names.
        from services.ai import llm_services
        llm_services.get_limiter_store().reset()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    @patch("services.ai.llm_services._is_preset_rate_limited", return_value=False)
    def test_grammar_tip_fallback_chain(self, _mock_rate):
        """Fallback: first preset fails (RateLimitError), second succeeds."""
        _seed_test_presets([
            {"name": "preset_a", "priority": 0},
            {"name": "preset_b", "priority": 1},
        ])

        call_count = {"a": 0, "b": 0}

        def mock_ask_json(*args, **kwargs):
            preset_name = kwargs["preset"]["name"]
            if preset_name == "preset_a":
                call_count["a"] += 1
                raise ai.RateLimitError("429 too many requests")
            call_count["b"] += 1
            return {"result": "success", "preset": preset_name}

        result = _call_ai_limited(mock_ask_json, request_kind="grammar_tip")

        self.assertEqual(call_count["a"], 1, "preset_a should be called once")
        self.assertEqual(call_count["b"], 1, "preset_b should be called once")
        self.assertEqual(result, {"result": "success", "preset": "preset_b"})

    @patch("services.ai.llm_services._is_preset_rate_limited", return_value=False)
    def test_word_query_fallback_chain(self, _mock_rate):
        """Fallback: first preset fails (RateLimitError), second succeeds."""
        _seed_test_presets([
            {"name": "preset_a", "priority": 0},
            {"name": "preset_b", "priority": 1},
        ])

        call_order = []

        def mock_ask_card(*args, **kwargs):
            preset_name = kwargs["preset"]["name"]
            call_order.append(preset_name)
            if preset_name == "preset_a":
                raise ai.RateLimitError("429 too many requests")
            return {"card": "test", "preset": preset_name}

        result = _call_ai_limited(mock_ask_card, request_kind="custom_word")

        self.assertEqual(call_order, ["preset_a", "preset_b"])
        self.assertEqual(result["preset"], "preset_b")

    @patch("services.ai.llm_services._is_preset_rate_limited", return_value=False)
    def test_all_presets_exhausted(self, _mock_rate):
        """When all presets are rate-limited, AllPresetsExhausted is raised."""
        _seed_test_presets([
            {"name": "preset_a", "priority": 0},
        ])

        def always_429(*args, **kwargs):
            raise ai.RateLimitError("429 too many requests")

        with self.assertRaises(AllPresetsExhausted):
            _call_ai_limited(always_429, request_kind="grammar_tip")

    @patch("services.ai.llm_services._is_preset_rate_limited", return_value=False)
    def test_in_fallback_chain_exclusion(self, _mock_rate):
        """Preset B with in_fallback_chain=0 is skipped in chain but callable directly."""
        _seed_test_presets([
            {"name": "preset_a", "priority": 0, "in_fallback_chain": 1},
            {"name": "preset_b", "priority": 1, "in_fallback_chain": 0},
        ])

        call_order = []

        def mock_func(*args, **kwargs):
            preset_name = kwargs["preset"]["name"]
            call_order.append(preset_name)
            if preset_name == "preset_a":
                raise ai.RateLimitError("429 too many requests")
            return {"preset": preset_name}

        with self.assertRaises(AllPresetsExhausted):
            _call_ai_limited(mock_func, request_kind="grammar_tip")

        self.assertEqual(call_order, ["preset_a"], "preset_b should not be in chain")

        # Verify preset_b works when explicitly included in the chain
        with patch("services.ai.llm_services.db.get_fallback_chain_presets") as mock_chain:
            mock_chain.return_value = [{"name": "preset_b", "priority": 0, "in_fallback_chain": 0}]
            result = _call_ai_limited(mock_func, request_kind="grammar_tip")
            self.assertEqual(result, {"preset": "preset_b"})

    @patch("services.ai.llm_services._is_preset_rate_limited", return_value=False)
    def test_past_deadline_aborts_before_calling_any_preset(self, _mock_rate):
        """An already-expired deadline must abort before any preset runs."""
        _seed_test_presets([
            {"name": "preset_a", "priority": 0},
            {"name": "preset_b", "priority": 1},
        ])

        call_order = []

        def mock_func(*args, **kwargs):
            call_order.append(kwargs["preset"]["name"])
            return {"result": "success"}

        with self.assertRaises(AIRequestTimedOut):
            _call_ai_limited(
                mock_func,
                request_kind="custom_word",
                deadline=time.monotonic() - 1,
            )

        self.assertEqual(call_order, [], "no preset should be called after deadline")

    @patch("services.ai.llm_services._is_preset_rate_limited", return_value=False)
    def test_rpm_wait_loop_honors_deadline(self, _mock_rate):
        """A saturated RPM queue must not spin forever; deadline aborts it."""
        _seed_test_presets([
            {"name": "preset_a", "priority": 0},
        ])

        from services.ai import llm_services

        limiter = llm_services._get_limiter_for_preset({"name": "preset_a"})
        limiter["request_times"].clear()
        now = time.monotonic()
        for _ in range(30):  # max_rpm default is 30 -> queue stays full
            limiter["request_times"].append(now)

        def mock_func(*args, **kwargs):
            return {"result": "success"}

        try:
            start = time.monotonic()
            with self.assertRaises(AIRequestTimedOut):
                _call_ai_limited(
                    mock_func,
                    request_kind="custom_word",
                    deadline=now + 1.0,
                )
            elapsed = time.monotonic() - start
            self.assertLess(elapsed, 30, "deadline should abort the RPM wait loop quickly")
        finally:
            limiter["request_times"].clear()


if __name__ == "__main__":
    unittest.main()
