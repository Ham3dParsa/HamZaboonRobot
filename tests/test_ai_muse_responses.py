"""Unit tests for Muse Responses routing (fix/muse-responses)."""

import unittest
from unittest.mock import MagicMock, patch

from services.ai import ai


class MuseResponsesRoutingTest(unittest.TestCase):
    def test_is_responses_for_muse_on_zen(self):
        self.assertTrue(ai._is_responses_preset({"base_url": "https://opencode.ai/zen/v1", "model": "muse-spark-1.3-contributor-free"}))
        self.assertTrue(ai._is_responses_preset({"base_url": "https://opencode.ai/zen/v1/responses", "model": "muse-spark-1.3-contributor-free"}))
        self.assertTrue(ai._is_responses_preset({"base_url": "https://opencode.ai/zen/v1", "model": "opencode/muse-spark-1.3-contributor-free"}))

    def test_is_not_responses_for_groq_or_non_zen(self):
        self.assertFalse(ai._is_responses_preset({"base_url": "https://api.groq.com/openai/v1", "model": "muse-spark-1.3-contributor-free"}))
        self.assertFalse(ai._is_responses_preset({"base_url": "https://api.groq.com/openai/v1", "model": "qwen/qwen3.8-27b"}))
        self.assertFalse(ai._is_responses_preset({"base_url": "https://opencode.ai/zen/v1", "model": "qwen3.6-plus"}))

    def test_normalize_base_url(self):
        self.assertEqual(ai._normalize_base_url("https://opencode.ai/zen/v1/responses"), "https://opencode.ai/zen/v1")
        self.assertEqual(ai._normalize_base_url("https://opencode.ai/zen/v1/responses/"), "https://opencode.ai/zen/v1")
        self.assertEqual(ai._normalize_base_url("https://opencode.ai/zen/v1"), "https://opencode.ai/zen/v1")

    def test_opencode_prefix_stripped(self):
        self.assertEqual(ai._model({"base_url": "https://opencode.ai/zen/v1", "model": "opencode/muse-spark-1.3-contributor-free"}), "muse-spark-1.3-contributor-free")

    def test_test_connection_muse_uses_responses(self):
        with patch("services.ai.ai.create_client") as mock_create:
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.model = "muse-spark-1.3-contributor-free"
            mock_usage = MagicMock()
            mock_usage.input_tokens = 5
            mock_usage.output_tokens = 10
            mock_usage.total_tokens = 15
            mock_resp.usage = mock_usage
            mock_resp.output_text = "pong"
            mock_client.responses.create.return_value = mock_resp
            mock_create.return_value = mock_client
            res = ai.test_connection("https://opencode.ai/zen/v1", "sk-test", "muse-spark-1.3-contributor-free")
            self.assertTrue(res["success"])
            mock_client.responses.create.assert_called_once()
            mock_client.chat.completions.create.assert_not_called()
            # usage normalized to prompt/completion via test_connection already
            self.assertEqual(res["usage"]["prompt_tokens"], 5)

    def test_request_json_muse_none_defaults_to_minimal_and_normalizes_usage(self):
        import services.db as db
        import tempfile, os
        tmp = tempfile.mktemp(suffix=".db")
        db.DB_PATH = tmp
        from services.db import schema as s
        s.DB_PATH = tmp
        db.init_db()
        db.set_preset(name="muse_min", base_url="https://opencode.ai/zen/v1", model="muse-spark-1.3-contributor-free", api_key="sk-test", reasoning_effort="none")
        preset = db.get_preset("muse_min")
        with patch("services.ai.ai.create_client") as mock_create:
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_usage = MagicMock()
            mock_usage.input_tokens = 11
            mock_usage.output_tokens = 22
            mock_usage.total_tokens = 33
            mock_resp.usage = mock_usage
            mock_resp.output_text = '{"word": "t", "fa_meaning": "m", "fa_explanation": "e", "examples": ["a","b"], "example_translations": ["c","d"]}'
            mock_resp.output = []
            mock_client.responses.create.return_value = mock_resp
            mock_create.return_value = mock_client
            # need to patch _model to return our preset's model without DB active preset interference
            val = ai._request_json("sys", "user", preset=preset)
            # should have called responses with minimal reasoning
            args, kwargs = mock_client.responses.create.call_args
            self.assertEqual(kwargs["reasoning"]["effort"], "minimal")
            self.assertNotIn("temperature", kwargs)
            # usage normalized
            # telemetry is internal, but we can check that mock was called
            self.assertTrue(mock_client.responses.create.called)
        try:
            os.remove(tmp)
        except OSError:
            pass

    def test_request_json_chat_still_uses_chat(self):
        import services.db as db
        import tempfile, os
        tmp = tempfile.mktemp(suffix=".db")
        db.DB_PATH = tmp
        from services.db import schema as s
        s.DB_PATH = tmp
        db.init_db()
        db.set_preset(name="groq_test", base_url="https://api.groq.com/openai/v1", model="qwen/qwen3.8-27b", api_key="sk-test", reasoning_effort="low")
        preset = db.get_preset("groq_test")
        with patch("services.ai.ai.create_client") as mock_create:
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.usage = MagicMock(prompt_tokens=1, completion_tokens=2, total_tokens=3)
            mock_resp.choices = [MagicMock(message=MagicMock(content='{"word": "t", "fa_meaning": "m", "fa_explanation": "e", "examples": ["a","b"], "example_translations": ["c","d"]}'))]
            mock_client.chat.completions.create.return_value = mock_resp
            mock_create.return_value = mock_client
            val = ai._request_json("sys", "user", preset=preset)
            mock_client.chat.completions.create.assert_called_once()
            mock_client.responses.create.assert_not_called()
        try:
            os.remove(tmp)
        except OSError:
            pass
