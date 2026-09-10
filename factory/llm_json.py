"""Shared Zen/LLM JSON helpers for factory runners (stdlib only).

- extract_json: first balanced ``{...}`` object via JSONDecoder scan.
  (The old greedy ``re.search(r"\\{.*\\}", text, re.S)`` grabbed first-``{``
  to last-``}`` and could swallow trailing prose into the parse.)
- AuthError + raise_for_auth: 401/403 aborts LOUDLY. An auth failure must
  never be retried into a silent deterministic fallback (that records
  unjudged data as judged).
- classify: shared (code, body, provider) error-action table (C4a). This
  module is the SOLE owner of provider error taxonomy — no provider-name
  branches or error-action literals anywhere else (guard-tested).
"""

import json
import urllib.error


class AuthError(RuntimeError):
    """Raised when the provider rejects our credentials (401/403)."""


# --- C4a error actions (single vocabulary; callers switch on these) ---
ROTATE = "rotate"  # 429/quota: rotate key, same provider
COOLDOWN_SWITCH = "cooldown_switch"  # location block: cool down + switch provider
ABORT = "abort"  # bad key/auth: stop loudly, no fallback
RETRY_ONCE = "retry_once"  # transient 5xx/timeout: one retry, then caller policy
FAIL_CLOSED = "fail_closed"  # unknown: stop this item, record, no silent data

# Code rules are provider-independent: (codes, action). 5xx range handled
# by range check in classify().
_CODE_RULES = (
    ((401, 403), ABORT),
    ((429,), ROTATE),
    ((408,), RETRY_ONCE),
)

# Per-provider body snippets: provider -> ≤3 (snippet, action). Snippets
# are matched case-insensitively as substrings of the error body.
_PROVIDER_SNIPPETS = {
    "zen": (
        ("rate limit exceeded", ROTATE),
        ("too many requests", ROTATE),
        ("quota exceeded", ROTATE),
    ),
    "google": (
        ("user location is not supported", COOLDOWN_SWITCH),
        # Location-gated only: a bare FAILED_PRECONDITION also covers
        # billing/API-disabled/quota, which must NOT cool down + switch.
        ("location is not supported", COOLDOWN_SWITCH),
    ),
    "openrouter": (
        ("rate limit", ROTATE),
        ("quota exceeded", ROTATE),
        ("temporarily unavailable", RETRY_ONCE),
    ),
    "avalai": (
        ("rate limit exceeded", ROTATE),
        ("service unavailable", RETRY_ONCE),
        ("overloaded", RETRY_ONCE),
    ),
}

# Provider snippets that beat even the code rules (checked first).
# Google RESOURCE_EXHAUSTED is project-level quota: a 429 carrying it
# must cool down + switch provider, NOT rotate keys on the same project.
_PROVIDER_PRECODE_SNIPPETS = {
    "google": (
        ("resource_exhausted", COOLDOWN_SWITCH),
    ),
}

# Provider-independent body snippets: (snippet, action).
_GENERIC_SNIPPETS = (
    ("invalid_api_key", ABORT),
    ("incorrect_api_key", ABORT),
    ("invalid api key", ABORT),
    ("timed out", RETRY_ONCE),
    ("timeout", RETRY_ONCE),
    ("deadline exceeded", RETRY_ONCE),
)


def classify(code, body, provider="generic"):
    """Map a provider failure to an error action (pure, no I/O).

    code: HTTP status int (or None for transport timeouts); body: raw
    error text/JSON (or None); provider: zen/google/openrouter/avalai
    (case-insensitive, anything else matches generic rows only).
    First match wins: pre-code provider snippets, then code rules, then
    provider snippets, then generic snippets, else FAIL_CLOSED.
    """
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = None
    text = "" if body is None else str(body).lower()
    prov = "" if provider is None else str(provider).strip().lower()
    for snippet, action in _PROVIDER_PRECODE_SNIPPETS.get(prov, ()):
        if snippet in text:
            return action
    if code is not None:
        for codes, action in _CODE_RULES:
            if code in codes:
                return action
        if 500 <= code <= 599:
            return RETRY_ONCE
    for snippet, action in _PROVIDER_SNIPPETS.get(prov, ()):
        if snippet in text:
            return action
    for snippet, action in _GENERIC_SNIPPETS:
        if snippet in text:
            return action
    return FAIL_CLOSED


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
