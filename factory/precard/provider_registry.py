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


def _seed_providers():
    """First-run seed rows from the single owner (provider_manifest).

    The manifest FILE is authoritative after seeding; this dict only
    fills paths that cannot reach the file. Never a second diverging
    copy: protocol/route/base_url/key_vars match the manifest seed by
    construction (rows normalize key_vars to tuples at use sites).
    """
    try:
        from factory.precard import provider_manifest as _manifest_mod
        seed = _manifest_mod.SEED_PROVIDERS
    except Exception:
        return {}
    return seed if isinstance(seed, dict) else {}


def _manifest():
    """Shared manifest manager (fresh instance per call: no stale reads)."""
    from factory.precard import provider_manifest as _manifest_mod
    return _manifest_mod.ProviderManifestManager()


def fresh_manager():
    """One manifest manager for a request (single disk load via its cache).

    Single seam for request-scoped sharing: callers that make several
    registry calls per request build this once and pass
    ``_manager=...`` through. Tests patch ``_manifest`` beneath it.
    """
    return _manifest()


def provider_names(_manager=None):
    """Canonical provider names: merged active manifest (removed stay gone).

    The manifest file is authoritative; the manifest-owned seed only
    fills a fresh store. A provider deleted via the manifest never
    reappears here, and manifest-added rows (kilo, local-studio, ...)
    appear with no code change. ``_manager`` shares one manifest read
    across a request.
    """
    try:
        mgr = _manager if _manager is not None else _manifest()
    except Exception:
        return list(_seed_providers())
    try:
        return mgr.provider_names()
    except Exception:
        return list(_seed_providers())


def resolve_provider(name, _manager=None):
    """Copy of the provider row, or None (fail-closed on unknown).

    Removed providers stay gone: an explicit manifest deletion pins the
    name even though the manifest-owned seed still carries the default
    row. ``_manager`` shares one manifest read across a request (None
    builds a single fresh instance for this call).
    """
    if not isinstance(name, str):
        return None
    try:
        mgr = _manager if _manager is not None else _manifest()
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
    row = _seed_providers().get(lease_policy.norm_provider(name))
    if not isinstance(row, dict):
        return None
    return dict(row, key_vars=tuple(row.get("key_vars", ())))


def key_ref_for(provider, group="G1", _manager=None):
    """Key variable NAMES for (provider, group): convention first, legacy
    explicit vars as fallback. Names only — values never resolved here.

    Indexed pattern: ``{PROVIDER}_API_KEY_{N}`` (1-based); legacy group
    labels map G1 -> 1, G2 -> 2. The manifest's full ordered slot list
    always leads, so N-key providers resolve beyond the old pair.
    ``_manager`` shares one manifest read across a request.
    """
    from factory.precard import provider_manifest as _manifest_mod
    try:
        mgr = _manager if _manager is not None else _manifest()
    except Exception:
        mgr = None
    row = resolve_provider(provider, _manager=mgr)
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
    if mgr is not None:
        try:
            for var in mgr.key_vars(provider):
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


def ordered_key_vars(provider, _manager=None):
    """Full ordered key-var NAME list for a provider (names only)."""
    try:
        mgr = _manager if _manager is not None else _manifest()
    except Exception:
        mgr = None
    try:
        names = mgr.key_vars(provider) if mgr is not None else []
    except Exception:
        names = []
    if names:
        return list(names)
    row = resolve_provider(provider, _manager=mgr)
    if isinstance(row, dict):
        return [str(v) for v in (row.get("key_vars") or []) if str(v or "")]
    return []


def key_count(provider, _manager=None):
    """Exact active key-slot count for a provider (data row length)."""
    try:
        mgr = _manager if _manager is not None else _manifest()
    except Exception:
        mgr = None
    try:
        if mgr is not None:
            return int(mgr.key_count(provider))
    except Exception:
        pass
    return len(ordered_key_vars(provider, _manager=mgr))


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
