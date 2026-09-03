"""Shared Zen/LLM JSON helpers for factory runners (stdlib only).

- extract_json: first balanced ``{...}`` object via JSONDecoder scan.
  (The old greedy ``re.search(r"\\{.*\\}", text, re.S)`` grabbed first-``{``
  to last-``}`` and could swallow trailing prose into the parse.)
- AuthError + raise_for_auth: 401/403 aborts LOUDLY. An auth failure must
  never be retried into a silent deterministic fallback (that records
  unjudged data as judged).
"""

import json
import urllib.error


class AuthError(RuntimeError):
    """Raised when the provider rejects our credentials (401/403)."""


def extract_json(text):
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text, i)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("no JSON object in model reply")


def raise_for_auth(exc):
    """Re-raise HTTP 401/403 as AuthError (loud abort); pass through else."""
    code = getattr(exc, "code", None)
    if isinstance(exc, urllib.error.HTTPError) and code in (401, 403):
        raise AuthError(
            "provider auth failed (HTTP %s): check keys in factory/.env — "
            "aborting with no silent fallback" % code)
    raise exc
