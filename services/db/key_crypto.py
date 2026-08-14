"""API-key encryption at rest (Phase 5, R11/F2).

A deep module: a small public interface hiding all Fernet crypto, master-key
loading, and fail-closed behavior. Every place that stores, resolves, or
displays an API key crosses this seam instead of duplicating crypto or
masking logic:

- ``encrypt_secret(plaintext)``  — encrypt a key before storing it. Returns
  ``''`` for empty input (keys are stored encrypted or not at all).
- ``decrypt_secret(token)``      — decrypt a stored key. Fail-closed: returns
  ``''`` and logs a warning (never the literal value) when the master key is
  missing/invalid or the token is not a valid Fernet token. Never raises.
- ``mask_key(plaintext)``        — render a key for display: ``—`` when empty,
  ``***`` when short, ``sk-abc…wxyz`` when long. Callers must pass the
  decrypted plaintext; this helper never decrypts on its own.

The master key comes from the ``AI_MASTER_KEY`` environment variable
(loaded in ``config``). It is read lazily on every call so a runtime config
change or test override takes effect without an import-time pin.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)


def _fernet() -> Fernet | None:
    """Return a Fernet cipher for the configured master key, or None.

    None means no usable master key is configured (missing or invalid). Callers
    treat None as fail-closed: encryption produces nothing and decryption
    produces nothing, so a missing key can never turn into plaintext leaking
    into storage or a decrypt error escaping into a caller.
    """
    from config import AI_MASTER_KEY

    key = AI_MASTER_KEY.strip()
    if not key:
        log.warning("AI_MASTER_KEY is not set; cannot encrypt/decrypt API keys")
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        log.warning("AI_MASTER_KEY is invalid; cannot encrypt/decrypt API keys")
        return None


def encrypt_secret(plaintext: str) -> str:
    """Encrypt ``plaintext`` for storage. Empty input stays empty.

    When no master key is configured, returns ``''`` (fail-closed) so a plain
    key is never written to the database.
    """
    if not plaintext:
        return ""
    f = _fernet()
    if f is None:
        return ""
    return f.encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a stored ``token``. Fail-closed: returns ``''`` on any problem.

    Logs a warning that never includes the literal token (Rule 6). Never
    raises — callers' fallback chains can keep trying other presets.
    """
    if not token:
        return ""
    f = _fernet()
    if f is None:
        return ""
    try:
        return f.decrypt(token.encode()).decode()
    except InvalidToken:
        log.warning("decrypt_secret: stored api_key is not valid ciphertext")
        return ""
    except Exception:
        log.warning("decrypt_secret: unexpected error decrypting api_key")
        return ""


def mask_key(plaintext: str) -> str:
    """Render an API key for display: ``—`` empty, ``***`` short, ends when long.

    Short keys (< 12 chars) are shown fully masked because their first+last
    fragments would still expose the whole value. Longer keys reveal only the
    first 6 and last 4 characters.
    """
    if not plaintext:
        return "—"
    if len(plaintext) > 12:
        return plaintext[:6] + "…" + plaintext[-4:]
    return "***"


def encrypt_for_storage(value: str) -> str:
    """Encrypt ``value`` for persistence, unless it is already ciphertext.

    Write APIs take the intended stored value. A user typing a new key passes
    plaintext; but an unchanged edit hands back the token that is already at
    rest (Fernet tokens always begin with ``gAAAA``), which must not be
    encrypted a second time. Treating an existing Fernet token as already-stored
    makes writes idempotent and safe. Fail-closed like ``encrypt_secret``:
    empty input stays empty, and a plaintext key is never stored when no master
    key is configured.
    """
    if not value:
        return ""
    if value.startswith("gAAAA"):
        return value
    return encrypt_secret(value)