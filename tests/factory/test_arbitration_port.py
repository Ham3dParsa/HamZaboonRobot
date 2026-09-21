"""Arbitration provider port (R1-R5): hermetic, stdlib only, no network.

Covers: Protocol structural match, service byte-identical passthrough,
adapter payload via injected fake urlopen, transport-error mapping,
dataclass fields. No sockets/ports touched — every adapter test injects
a fake opener; the real urllib.request.urlopen is never called.
"""

import json
import urllib.request

import pytest

from factory.linking import arbitration as arb


class _FakePort:
    """Structural match only — deliberately no Protocol inheritance."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.seen: list = []

    def execute_arbitration(self, prompt: str) -> str:
        self.seen.append(prompt)
        return self.text


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.closed = False

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        self.close()
        return False


def test_source_sense_fields_and_defaults():
    s = arb.SourceSense(sense_id="bank#1", gloss="financial institution")
    assert s.sense_id == "bank#1"
    assert s.gloss == "financial institution"
    assert s.example == ""
    s2 = arb.SourceSense(sense_id="bank#2", gloss="river edge", example="by the bank")
    assert s2.example == "by the bank"


def test_verdict_fields_and_defaults():
    v = arb.ArbitrationVerdict(sense_id="bank#1", status="auto-linked")
    assert v.sense_id == "bank#1"
    assert v.status == "auto-linked"
    assert v.winner_synset_id is None
    v2 = arb.ArbitrationVerdict(
        sense_id="bank#1",
        status="routed-to-human-review",
        winner_synset_id="eng-30-08420278-n",
    )
    assert v2.winner_synset_id == "eng-30-08420278-n"


def test_service_accepts_structural_port_without_inheritance():
    fake = _FakePort("raw-output")
    assert arb.ArbitrationProviderPort not in type(fake).__mro__  # no inheritance, structural only
    svc = arb.ArbitrationService(port=fake)
    out = svc.arbitrate(arb.SourceSense(sense_id="x#0", gloss="g"), "hello")
    assert out == "raw-output"
    assert fake.seen == ["hello"]


def test_service_returns_raw_text_byte_identical():
    raw = "line1\nline2 — فارسی ✓ \x00 tail"
    fake = _FakePort(raw)
    svc = arb.ArbitrationService(port=fake)
    src = arb.SourceSense(sense_id="s#9", gloss="g", example="e")
    out = svc.arbitrate(src, "prompt-text")
    assert out == raw
    assert out.encode("utf-8") == raw.encode("utf-8")


def test_adapter_posts_correct_payload_via_fake_opener():
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["method"] = request.get_method()
        body = json.dumps({"choices": [{"message": {"content": "RAW-MODEL-TEXT"}}]}).encode("utf-8")
        return _FakeResponse(body)

    adapter = arb.LocalGemmaAdapter(opener=fake_urlopen)
    assert adapter.endpoint == "http://localhost:1234/v1"
    assert adapter.timeout == 120
    assert adapter.model == "google/gemma-4-e2b"
    out = adapter.execute_arbitration("arbitrate this")
    assert out == "RAW-MODEL-TEXT"
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 120
    assert captured["body"]["model"] == "google/gemma-4-e2b"
    assert captured["body"]["temperature"] == 0
    assert captured["body"]["messages"] == [{"role": "user", "content": "arbitrate this"}]


def test_adapter_raises_transport_error_on_failure():
    def failing_opener(request, timeout=None):
        raise OSError("connection refused")

    adapter = arb.LocalGemmaAdapter(opener=failing_opener)
    with pytest.raises(arb.ArbitrationTransportError):
        adapter.execute_arbitration("prompt")


def test_adapter_raises_payload_error_on_malformed_json():
    def bad_json_opener(request, timeout=None):
        return _FakeResponse(b"not-json{{{:")

    adapter = arb.LocalGemmaAdapter(opener=bad_json_opener)
    with pytest.raises(arb.ArbitrationPayloadError):
        adapter.execute_arbitration("prompt")


@pytest.mark.parametrize(
    "envelope",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"no_message": {}}]},
    ],
)
def test_adapter_raises_payload_error_on_missing_keys(envelope):
    def opener(request, timeout=None):
        return _FakeResponse(json.dumps(envelope).encode("utf-8"))

    adapter = arb.LocalGemmaAdapter(opener=opener)
    with pytest.raises(arb.ArbitrationPayloadError):
        adapter.execute_arbitration("prompt")


@pytest.mark.parametrize("content", [None, 123, {"text": "x"}, ["x"], True])
def test_adapter_raises_payload_error_on_non_string_content(content):
    def opener(request, timeout=None):
        body = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
        return _FakeResponse(body)

    adapter = arb.LocalGemmaAdapter(opener=opener)
    with pytest.raises(arb.ArbitrationPayloadError):
        adapter.execute_arbitration("prompt")


def test_transport_error_is_not_payload_error():
    # Transport and payload failures route to distinct types.
    assert not issubclass(arb.ArbitrationTransportError, arb.ArbitrationPayloadError)
    assert not issubclass(arb.ArbitrationPayloadError, arb.ArbitrationTransportError)


def test_no_real_network_used():
    # Default wiring pins to urllib.request.urlopen without calling it.
    assert arb.LocalGemmaAdapter()._opener is urllib.request.urlopen
    # Injected opener is used behaviorally (not just stored).
    seen = {}

    def custom_opener(request, timeout=None):
        seen["called"] = True
        seen["timeout"] = timeout
        body = json.dumps({"choices": [{"message": {"content": "CUSTOM"}}]}).encode("utf-8")
        return _FakeResponse(body)

    adapter = arb.LocalGemmaAdapter(opener=custom_opener)
    assert adapter._opener is custom_opener
    assert adapter.execute_arbitration("hi") == "CUSTOM"
    assert seen.get("called") is True
    assert seen.get("timeout") == 120
