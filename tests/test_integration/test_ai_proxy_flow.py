import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from services import db
from services.db import schema as db_schema


class AiProxyFlowTest(unittest.IsolatedAsyncioTestCase):
    """AI proxy via AI_PROXY_URL must timeout correctly, validate scheme,
    require socksio for socks5://, and not leak credentials."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = path
        db_schema.DB_PATH = path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def test_proxy_timeout_is_passed_as_httpx_timeout(self):
        import services.ai.ai as ai_module
        from config import AI_TIMEOUT_SECONDS

        with patch.object(ai_module, "AI_PROXY_URL", "http://127.0.0.1:8080"):
            with patch("services.ai.ai.httpx") as mock_httpx:
                mock_httpx.Timeout.return_value = "TO"
                mock_client_cls = MagicMock()
                mock_openai = MagicMock()
                mock_openai.return_value = MagicMock(close=MagicMock())
                with patch.object(ai_module, "_HttpxClient", mock_client_cls):
                    with patch("services.ai.ai.OpenAI", mock_openai):
                        mock_client_cls.return_value = MagicMock()
                        mock_client_cls.return_value.timeout = "TO"
                        preset = {"name": "p", "base_url": "http://x", "model": "m", "timeout_seconds": 42}
                        with patch("services.db.resolve_preset_key", return_value="sk"):
                            ai_module.create_client(preset)
                mock_httpx.Timeout.assert_called_with(42)
                mock_client_cls.assert_called_with(proxy="http://127.0.0.1:8080", timeout="TO", trust_env=False)

    def test_invalid_scheme_disables_proxy(self):
        import services.ai.ai as ai_module
        import httpx as _httpx

        with patch.object(ai_module, "AI_PROXY_URL", "ftp://bad:21"):
            mock_client_cls = MagicMock(side_effect=_httpx.InvalidURL("bad url"))
            with patch.object(ai_module, "_HttpxClient", mock_client_cls):
                with patch("services.ai.ai.OpenAI") as mock_openai:
                    mock_openai.return_value = MagicMock(close=MagicMock())
                    preset = {"name": "p", "base_url": "http://x", "model": "m", "timeout_seconds": 5}
                    with patch("services.db.resolve_preset_key", return_value="sk"):
                        client = ai_module.create_client(preset)
                        mock_client_cls.assert_called_once()
                        # proxy failed -> OpenAI called with http_client=None
                        _, kwargs = mock_openai.call_args
                        self.assertIsNone(kwargs.get("http_client"))
                    client.close()

    def test_proxy_client_is_closed_after_request(self):
        import services.ai.ai as ai_module

        mock_openai = MagicMock()
        mock_resp = MagicMock()
        mock_resp.usage = None
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"word":"hello","fa_meaning":"سلام","fa_explanation":"x","examples":["a","b"],"example_translations":["c","d"]}'))]
        mock_openai.chat.completions.create.return_value = mock_resp
        mock_openai.close = MagicMock()

        preset = {"name": "p", "base_url": "http://x", "model": "m", "timeout_seconds": 5, "temperature": 0.6, "max_output_tokens": 100}
        with patch("services.ai.ai._client", return_value=mock_openai):
            with patch("services.ai.ai._model", return_value="m"):
                # _request_json should close the client even on success
                ai_module._request_json("sys", "usr", preset=preset)
                mock_openai.close.assert_called()

    def test_no_credentials_leak_on_proxy_error(self):
        import services.ai.ai as ai_module
        import httpx

        with patch.object(ai_module, "AI_PROXY_URL", "socks5://user:secret@127.0.0.1:1080"):
            with patch("services.ai.ai.httpx", httpx):
                # Simulate socksio missing -> ImportError on client creation
                with patch.object(ai_module, "_HttpxClient", side_effect=ImportError("socksio not installed")):
                    preset = {"name": "p", "base_url": "http://x", "model": "m", "timeout_seconds": 5}
                    with patch("services.db.resolve_preset_key", return_value="sk"):
                        with patch.object(ai_module.log, "error") as mock_err:
                            client = ai_module.create_client(preset)
                            self.assertTrue(mock_err.called, "proxy error must be logged at error level")
                            args = " ".join(str(a) for a in mock_err.call_args[0])
                            self.assertNotIn("secret", args)
                            self.assertNotIn("user", args)
                            # redacted target scheme://host:port must be present
                            self.assertIn("socks5://127.0.0.1:1080", args)
                    client.close()


if __name__ == "__main__":
    unittest.main()
