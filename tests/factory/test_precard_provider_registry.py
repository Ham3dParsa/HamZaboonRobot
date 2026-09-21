"""RED (contract F1-F4): provider-as-data registry (TDD red).

Locked: F1 transport by PROTOCOL (openai_compat/gemini_rest), F2 route as
row field, F3 key refs by {PROVIDER}_API_KEY_{GROUP} convention (+ legacy
fallbacks), F4 CLI choices derived from the registry (no hardcoded tuple).
Adding a provider = one table row; zero logic edits. Secrets never appear:
tests assert NAMES only.

Every test here MUST FAIL until factory.precard.provider_registry exists.
"""

import unittest


class TestProviderRows(unittest.TestCase):
    def test_protocols(self):
        from factory.precard import provider_registry as reg
        self.assertEqual(reg.resolve_provider("groq")["protocol"],
                         "openai_compat")
        self.assertEqual(reg.resolve_provider("openrouter")["protocol"],
                         "openai_compat")
        self.assertEqual(reg.resolve_provider("google")["protocol"],
                         "gemini_rest")
        self.assertEqual(reg.resolve_provider("avalai")["protocol"],
                         "openai_compat")

    def test_routes_are_row_fields(self):
        from factory.precard import provider_registry as reg
        self.assertEqual(reg.resolve_provider("google")["route"], "tunnel")
        self.assertEqual(reg.resolve_provider("avalai")["route"], "direct")
        self.assertEqual(reg.resolve_provider("groq")["route"], "direct")
        self.assertEqual(reg.resolve_provider("openrouter")["route"],
                         "tunnel")

    def test_unknown_provider_fails_closed(self):
        from factory.precard import provider_registry as reg
        self.assertIsNone(reg.resolve_provider("nope"))

    def test_provider_names_cover_all_four(self):
        from factory.precard import provider_registry as reg
        self.assertTrue({"avalai", "google", "groq", "openrouter"} <= set(
            reg.provider_names()))


class TestKeyRefs(unittest.TestCase):
    def test_convention_first_then_legacy(self):
        from factory.precard import provider_registry as reg
        refs = reg.key_ref_for("groq", "G1")
        self.assertEqual(refs[0], "GROQ_API_KEY_G1")
        refs = reg.key_ref_for("google", "G1")
        self.assertEqual(refs[0], "GOOGLE_API_KEY_G1")
        self.assertIn("GOOGLE_AI_API_KEY", refs)

    def test_unknown_provider_has_no_refs(self):
        from factory.precard import provider_registry as reg
        self.assertEqual(reg.key_ref_for("nope", "G1"), [])

    def test_case_insensitive_and_group_edges(self):
        from factory.precard import provider_registry as reg
        self.assertIsNotNone(reg.resolve_provider("GROQ"))
        self.assertEqual(reg.key_ref_for("groq", "")[0],
                         "GROQ_API_KEY_G1")
        self.assertIn("GROQ_API_KEY", reg.key_ref_for("groq", "G1"))


class TestProtocolTransports(unittest.TestCase):
    def test_transport_for_protocol(self):
        from factory.precard import provider_registry as reg
        openai_fn = reg.transport_for("openai_compat")
        gemini_fn = reg.transport_for("gemini_rest")
        self.assertTrue(callable(openai_fn))
        self.assertTrue(callable(gemini_fn))
        self.assertIsNone(reg.transport_for("nope"))

    def test_openai_compat_post_shape(self):
        import io
        import json
        import urllib.request
        from factory.precard import provider_registry as reg

        seen = {}
        real_urlopen = urllib.request.urlopen

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps(
                    {"choices": [{"message": {"content": "hi"}}],
                     "usage": {}}).encode("utf-8")

        def _fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            body = json.loads(req.data.decode("utf-8"))
            seen["model"] = body.get("model")
            seen["temp"] = body.get("temperature")
            return _Resp()

        urllib.request.urlopen = _fake_urlopen
        try:
            text, usage = reg.transport_for("openai_compat")(
                "k", "m", "hi",
                base_url="https://example.invalid/v1/chat/completions")
        finally:
            urllib.request.urlopen = real_urlopen
        self.assertEqual(
            seen["url"], "https://example.invalid/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer k")
        self.assertEqual((seen["model"], seen["temp"]), ("m", 0))
        self.assertEqual(text, "hi")


if __name__ == "__main__":
    unittest.main()
