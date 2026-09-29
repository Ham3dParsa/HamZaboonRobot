"""Transport adapter tests (stub openers only — zero network).

LocalGemmaAdapter reuses its injected opener; GeminiRestAdapter takes
the same injection so both ride identical hermetic tests.
"""

from __future__ import annotations

import io
import json

from factory.linking import arbitration as _arb


def _fake_opener(payload, exc=None):
    def _open(request, timeout=None):
        if exc is not None:
            raise exc
        data = json.dumps(payload).encode()
        return io.BytesIO(data)
    _open.requests = []
    orig = _open

    def _spy(request, timeout=None):
        _spy.requests.append(request)
        return orig(request, timeout=timeout)
    _spy.requests = _open.requests
    return _spy


def _gemini_payload(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_gemini_adapter_posts_generate_and_returns_text():
    opener = _fake_opener(_gemini_payload("hello"))
    adapter = _arb.GeminiRestAdapter(model="gemini-2.5-flash",
                                     key_value="K",
                                     opener=opener)
    assert adapter.execute_arbitration("prompt") == "hello"
    req = opener.requests[0]
    assert "generateContent" in req.full_url
    assert "models/gemini-2.5-flash" in req.full_url
    assert "key=K" not in req.full_url  # key rides header, never the URL
    assert req.headers.get("X-goog-api-key") == "K"


def test_gemini_adapter_transport_error():
    import urllib.error

    opener = _fake_opener(None, urllib.error.URLError("down"))
    adapter = _arb.GeminiRestAdapter(model="m", key_value="K",
                                     opener=opener)
    try:
        adapter.execute_arbitration("prompt")
        raised = False
    except _arb.ArbitrationTransportError:
        raised = True
    assert raised is True


def test_gemini_adapter_bad_shape():
    opener = _fake_opener({"nope": 1})
    adapter = _arb.GeminiRestAdapter(model="m", key_value="K",
                                     opener=opener)
    try:
        adapter.execute_arbitration("prompt")
        raised = False
    except _arb.ArbitrationPayloadError:
        raised = True
    assert raised is True


def test_local_gemma_adapter_posts_completions():
    opener = _fake_opener({"choices": [{"message": {"content": "hi"}}]})
    adapter = _arb.LocalGemmaAdapter(endpoint="http://localhost:1/v1",
                                     model="m", opener=opener)
    assert adapter.execute_arbitration("prompt") == "hi"
    assert opener.requests[0].full_url.endswith("/chat/completions")


def test_local_gemma_adapter_bearer_only_with_key():
    opener = _fake_opener({"choices": [{"message": {"content": "hi"}}]})
    adapter = _arb.LocalGemmaAdapter(endpoint="http://localhost:1/v1",
                                     model="m", opener=opener,
                                     key_value="K")
    adapter.execute_arbitration("prompt")
    headers = opener.requests[0].headers
    assert headers.get("Authorization") == "Bearer K"
