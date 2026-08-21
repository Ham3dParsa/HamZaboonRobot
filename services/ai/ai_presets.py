"""AI provider preset API-key resolution helpers.

All preset configuration is stored in the ``ai_presets`` table (single source
of truth) and managed exclusively through the admin panel / AI preset manager.
There are no hardcoded built-in presets.

Since Phase 5 every stored API key is Fernet ciphertext (see
``services.db.key_crypto``); a ``$ENV`` reference can only remain when the
Phase 5 migration was skipped (no master key, BUG-B1) and is resolved at
runtime via ``key_crypto._resolve_env`` to the same value as the migration.
This module owns the thin resolution adapter used by the DB layer:
``resolve_api_key`` decrypts (or resolves ``$ENV``) via the deep
``decrypt_secret`` helper and is fail-closed (returns ``''`` on any problem,
never raises, never logs the literal value).
"""

from services.db.key_crypto import decrypt_secret


def resolve_api_key(preset_or_raw: dict | str) -> str:
    """Resolve a preset's stored API key to its plaintext value.

    Accepts either a preset dict with an ``api_key`` field or a raw stored
    token. The stored value is always Fernet ciphertext, so this simply
    decrypts it. Fail-closed: returns ``''`` when the master key is missing or
    invalid or the token is not decryptable; never raises and never logs the
    literal key.
    """
    if isinstance(preset_or_raw, str):
        raw = preset_or_raw
    else:
        raw = preset_or_raw.get("api_key", "")
    return decrypt_secret(raw)
