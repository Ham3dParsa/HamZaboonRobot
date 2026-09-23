"""Provider-as-data registry (contract F1-F4): adding a provider = one row.

Deep module: small interface, all provider knowledge behind it. Transports
are chosen by PROTOCOL (openai_compat / gemini_rest), never by provider-name
branches — a new provider needs zero logic edits. Route lives on the row
(F2). Key refs follow the {PROVIDER}_API_KEY_{GROUP} convention with legacy
explicit vars as fallback (F3). CLI choices derive from provider_names()
(F4). Secrets never appear here: rows carry key variable NAMES only.
"""

from __future__ import annotations

from factory.precard import provider_lease_policy as lease_policy
from factory.precard import provider_transport as transports

PROTOCOLS = ("openai_compat", "gemini_rest")

PROVIDERS = {
    "avalai": {
        "protocol": "openai_compat",
        "base_url": lease_policy.AVALAI_CHAT_URL,
        "route": "direct",
        "key_vars": ("AVALAI_API_KEY",),
        "request_extras": {
            "reasoning_effort": "low",
            "extra_body": {"reasoning_effort": "low"},
        },
    },
    "google": {
        "protocol": "gemini_rest",
        "base_url": None,
        "route": "tunnel",
        "key_vars": ("GOOGLE_AI_API_KEY",),
        "request_extras": {},
    },
    "openrouter": {
        "protocol": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "route": "tunnel",
        # OPENROUTER_API_KEY_2 is the older numbered style (same
        # meaning as the _G2 group slot); kept as a legacy fallback.
        "key_vars": ("OPENROUTER_API_KEY", "OPENROUTER_API_KEY_2"),
        "request_extras": {},
    },
    "groq": {
        "protocol": "openai_compat",
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "route": "tunnel",
        "key_vars": ("GROQ_API_KEY",),
        "request_extras": {},
    },
}


def provider_names():
    """Canonical provider names (drives CLI choices — never hardcoded)."""
    return list(PROVIDERS)


def resolve_provider(name):
    """Copy of the provider row, or None (fail-closed on unknown)."""
    if not isinstance(name, str):
        return None
    row = PROVIDERS.get(lease_policy.norm_provider(name))
    if not isinstance(row, dict):
        return None
    return dict(row, key_vars=tuple(row.get("key_vars", ())))


def key_ref_for(provider, group="G1"):
    """Key variable NAMES for (provider, group): convention first, legacy
    explicit vars as fallback. Names only — values never resolved here."""
    row = resolve_provider(provider)
    if row is None:
        return []
    convention = "%s_API_KEY_%s" % (
        str(provider).strip().upper(),
        str(group or "G1").strip().upper() or "G1")
    refs = [convention]
    for var in row.get("key_vars", ()):
        if var and var not in refs:
            refs.append(var)
    return refs


def transport_for(protocol):
    """Adapter function for a protocol, or None (fail-closed on unknown)."""
    if protocol == "openai_compat":
        return transports.openai_compat_transport
    if protocol == "gemini_rest":
        return transports._google_chat_transport
    return None
