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

#: Seed rows only (first-run seed for the dynamic manifest). The FILE
#: owned by factory.precard.provider_manifest is authoritative after
#: seeding: adding/removing a provider is a data write, never a Python
#: edit here.
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
        "route": "direct",
        "key_vars": ("GROQ_API_KEY",),
        "request_extras": {},
    },
}


def _manifest():
    """Shared manifest manager (fresh instance per call: no stale reads)."""
    from factory.precard import provider_manifest as _manifest_mod
    return _manifest_mod.ProviderManifestManager()


def provider_names():
    """Canonical provider names: merged active manifest (removed stay gone).

    The manifest file is authoritative; the in-code PROVIDERS seed only
    fills a fresh store. A provider deleted via the manifest never
    reappears here, and manifest-added rows (kilo, local-studio, ...)
    appear with no code change.
    """
    try:
        return _manifest().provider_names()
    except Exception:
        return list(PROVIDERS)


def resolve_provider(name):
    """Copy of the provider row, or None (fail-closed on unknown).

    Removed providers stay gone: an explicit manifest deletion pins the
    name even though the in-code seed still carries the default row.
    """
    if not isinstance(name, str):
        return None
    try:
        mgr = _manifest()
    except Exception:
        mgr = None
    hit = None
    if mgr is not None:
        try:
            if mgr.is_removed(name):
                return None
            hit = mgr.get(name)
        except Exception:
            hit = None
    if isinstance(hit, dict):
        return dict(hit, key_vars=tuple(hit.get("key_vars", ())))
    try:
        if mgr is not None and mgr.is_removed(name):
            return None
    except Exception:
        pass
    row = PROVIDERS.get(lease_policy.norm_provider(name))
    if not isinstance(row, dict):
        return None
    return dict(row, key_vars=tuple(row.get("key_vars", ())))


def key_ref_for(provider, group="G1"):
    """Key variable NAMES for (provider, group): convention first, legacy
    explicit vars as fallback. Names only — values never resolved here.

    Indexed pattern: ``{PROVIDER}_API_KEY_{N}`` (1-based); legacy group
    labels map G1 -> 1, G2 -> 2. The manifest's full ordered slot list
    always leads, so N-key providers resolve beyond the old pair.
    """
    from factory.precard import provider_manifest as _manifest_mod
    row = resolve_provider(provider)
    if row is None:
        return []
    try:
        index = _manifest_mod.legacy_group_to_index(group)
    except Exception:
        index = 1
    convention = _manifest_mod.indexed_key_var(provider, index)
    # Legacy G-style alias for the same slot (G1 <-> _1 compatibility).
    stem = str(provider or "").strip().upper()
    legacy_alias = ""
    if stem and index in (1, 2):
        legacy_alias = "%s_API_KEY_G%d" % (
            __import__("re").sub(r"[^A-Z0-9]+", "_", stem).strip("_"), index)
    refs = []
    try:
        for var in _manifest().key_vars(provider):
            if var and var not in refs:
                refs.append(var)
    except Exception:
        pass
    # Manifest slots lead (keeps the seeded G-style default first for
    # backward compatibility); the numeric convention + G alias follow
    # so old and new spellings both resolve for the same slot.
    ordered = []
    for var in refs + ([convention] if convention else []) + (
            [legacy_alias] if legacy_alias else []):
        if var and var not in ordered:
            ordered.append(var)
    for var in row.get("key_vars", ()):
        if var and var not in ordered:
            ordered.append(var)
    return ordered


def ordered_key_vars(provider):
    """Full ordered key-var NAME list for a provider (names only)."""
    try:
        names = _manifest().key_vars(provider)
    except Exception:
        names = []
    if names:
        return list(names)
    row = resolve_provider(provider)
    if isinstance(row, dict):
        return [str(v) for v in (row.get("key_vars") or []) if str(v or "")]
    return []


def key_count(provider):
    """Exact active key-slot count for a provider (data row length)."""
    try:
        return int(_manifest().key_count(provider))
    except Exception:
        return len(ordered_key_vars(provider))


def create_provider(name, row):
    """Create a provider data row (validation only — no code edit)."""
    return _manifest().create(name, row)


def delete_provider(name):
    """Delete a provider, even defaults (removed stay gone)."""
    return _manifest().delete(name)


def add_provider_key(name, index=None, key_var=""):
    """Add a key slot at 1-based index (append when None)."""
    return _manifest().add_key(name, index=index, key_var=key_var)


def delete_provider_key(name, index):
    """Delete the key at 1-based index (higher indexes shift down)."""
    return _manifest().delete_key(name, index)


def transport_for(protocol):
    """Adapter function for a protocol, or None (fail-closed on unknown)."""
    if protocol == "openai_compat":
        return transports.openai_compat_transport
    if protocol == "gemini_rest":
        return transports._google_chat_transport
    return None
