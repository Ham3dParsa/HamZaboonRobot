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
- PROVIDER_COOLDOWN_S + cooldown_for: shared per-provider post-429
  pause/exile seconds (sole owner — no literals elsewhere).
"""

import json
import urllib.error


class AuthError(RuntimeError):
    """Raised when the provider rejects our credentials (401/403)."""


# --- C4a error actions (single vocabulary; callers switch on these) ---
ROTATE = "rotate"  # 429/quota: rotate key, same provider
COOLDOWN_SWITCH = "cooldown_switch"  # project quota: cool down + switch
LOCATION_BLOCK = "location_block"  # geo/sanction: key kept, cool + switch
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
    "google": (),
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
# The Google location markers live here too (not below): a geo 403
# must cool + switch with the key kept, never ABORT on the code rule.
# Location-gated only: a bare FAILED_PRECONDITION also covers
# billing/API-disabled/quota, which must NOT cool down + switch.
_PROVIDER_PRECODE_SNIPPETS = {
    "google": (
        ("user location is not supported", LOCATION_BLOCK),
        ("location is not supported", LOCATION_BLOCK),
        ("resource_exhausted", COOLDOWN_SWITCH),
    ),
}

# Provider-independent pre-code snippets: (snippet, action). Checked
# before the code rules like the provider rows above, so a sanctioned
# egress 403 cools + switches instead of aborting. Deliberately narrow:
# the Google location marker stays provider-scoped, so other providers
# keep their scope isolation (see test_provider_scope_isolation).
_GENERIC_PRECODE_SNIPPETS = (
    ("sanction", LOCATION_BLOCK),
    ("unsupported country", LOCATION_BLOCK),
)

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
    First match wins: pre-code provider snippets, generic pre-code
    snippets, then code rules, then provider snippets, then generic
    snippets, else FAIL_CLOSED.
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
    for snippet, action in _GENERIC_PRECODE_SNIPPETS:
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


# --- Per-provider cooldowns (R1/R2/R6): post-429 pause/exile seconds.
# Sole owner: every ROTATE pause, cool() default, and tunnel-fetch
# backoff resolves through cooldown_for below — no literals elsewhere.
PROVIDER_COOLDOWN_S = {
    "kilo": 18.0,
    "google": 4.0,
    "zen": 300.0,
    "openrouter": 300.0,
    "avalai": 300.0,
    "generic": 300.0,
    "tunnel_fetch": 300.0,
}


def cooldown_for(provider, override=None):
    """Seconds to pause/exile provider after a 429 (pure, no I/O).

    An explicit finite positive override (e.g. --cooldown-secs) wins
    over the table; garbage overrides (non-finite, non-positive)
    fall back to the table instead of poisoning arithmetics.
    Unknown providers fall back to the generic exile default.
    """
    if override is not None:
        try:
            wait = float(override)
        except (TypeError, ValueError):
            wait = None
        if (wait is not None and wait > 0
                and wait < float("inf")):
            return wait
    prov = "" if provider is None else str(provider).strip().lower()
    return float(PROVIDER_COOLDOWN_S.get(
        prov, PROVIDER_COOLDOWN_S["generic"]))


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
