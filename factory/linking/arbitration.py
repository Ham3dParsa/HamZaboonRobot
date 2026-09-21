"""Arbitration provider port (R1-R5, deep module, stdlib only).

Single owner of the raw-arbitration provider boundary. No tally, no vote,
no gate logic anywhere in this file — the service carries the source sense
for identity/logging only and returns the port's raw text unchanged.
Parsing/tallying/gating into :class:`ArbitrationVerdict` is assembled by
the gate layer later, not here.

No I/O except :class:`LocalGemmaAdapter` (explicit local endpoint, never
reads env/config); no model calls at import time; imports outside
``typing`` / ``dataclasses`` / ``urllib`` / ``json`` are rejected.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Literal, Optional, Protocol


class ArbitrationTransportError(Exception):
    """Transport failure from :class:`LocalGemmaAdapter` (never swallowed)."""


class ArbitrationPayloadError(ValueError):
    """Malformed response envelope from :class:`LocalGemmaAdapter`.

    Raised for payload shape/key/content failures (invalid JSON, missing
    ``choices``/``message``/``content`` keys, non-``str`` content) — never
    for transport failures, so callers retrying on transport never
    pointlessly retry a shape bug.
    """


class ArbitrationProviderPort(Protocol):
    """Structural provider boundary (no inheritance required)."""

    def execute_arbitration(self, prompt: str) -> str:
        """Executes raw arbitration prompt and returns raw model text output."""
        ...


@dataclass
class SourceSense:
    """Source sense carried for identity/logging only (no logic)."""

    sense_id: str
    gloss: str
    example: str = ""


@dataclass
class ArbitrationVerdict:
    """Gate-layer verdict shape (assembled by the gate layer later, NOT by the service)."""

    sense_id: str
    status: Literal["auto-linked", "routed-to-human-review"]
    winner_synset_id: Optional[str] = None


class ArbitrationService:
    """Thin DI service: delegates to any structural port match."""

    def __init__(self, port: ArbitrationProviderPort) -> None:
        self._port = port

    def arbitrate(self, source: SourceSense, prompt: str) -> str:
        """Return the port's raw text unchanged (source is identity only)."""
        _ = source
        return self._port.execute_arbitration(prompt)


class LocalGemmaAdapter:
    """Local Gemma provider over OpenAI-compatible chat completions."""

    def __init__(
        self,
        endpoint: str = "http://localhost:1234/v1",
        timeout: int = 120,
        model: str = "google/gemma-4-e2b",
        opener=None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.model = model
        self._opener = opener if opener is not None else urllib.request.urlopen

    def execute_arbitration(self, prompt: str) -> str:
        """POST the prompt and return the raw model text output."""
        url = self.endpoint.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ArbitrationTransportError(f"{type(exc).__name__}: {exc}") from exc
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ArbitrationPayloadError(f"{type(exc).__name__}: {exc}") from exc
        if not isinstance(content, str):
            raise ArbitrationPayloadError(
                f"content is {type(content).__name__}, expected str"
            )
        return content
