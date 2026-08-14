"""API-key encryption at rest (Phase 5, R11/F2).

A deep module: a small public interface hiding all Fernet crypto, master-key
loading, and fail-closed behavior. Every place that stores, resolves, or
displays an API key crosses this seam instead of duplicating crypto or
masking logic:

- ``encrypt_secret(plaintext)``  — encrypt a key before storing it. Returns
  ``''`` for empty input (keys are stored encrypted or not at all).
- ``decrypt_secret(token)``      — decrypt a stored key. Fail-closed: returns
  ``''`` and logs a warning (never the literal value) when the master key is
  missing/invalid or the value is not a ``v1:``-tagged token. Never raises.
- ``mask_key(plaintext)``        — render a key for display: ``—`` when empty,
  ``***`` when short, ``sk-abc…wxyz`` when long. Callers must pass the
  decrypted plaintext; this helper never decrypts on its own.
- ``encrypt_for_storage(value)`` — idempotent write seam. ``v1:``-tagged
  ciphertext is passed through unchanged; raw plaintext is encrypted and
  tagged. Fail-closed: raises ``MasterKeyRequiredError`` when a *new* key would
  have to be stored but no master key is configured, so a plain key is never
  written to the database.
- ``MasterKeyRequiredError``     — raised when a write needs a master key that
  is not configured.

Stored ciphertext always carries the explicit ``VERSION_PREFIX`` (``v1:``) so
the module never has to guess whether a value is encrypted by sniffing a
Fernet prefix. This distinguishes "already encrypted" from "a raw key" with
no ambiguity.

The master key comes from the ``AI_MASTER_KEY`` environment variable
(loaded in ``config``). It is read lazily on every call so a runtime config
change or test override takes effect without an import-time pin.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

VERSION_PREFIX = "v1:"


class MasterKeyRequiredError(Exception):
    """A key write needs a configured master key, but none is available.

    Raised (never silently swallowed) so callers can surface a clear error to
    the admin instead of persisting a plaintext key.
    """


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
    return VERSION_PREFIX + f.encrypt(plaintext.encode()).decode()


def decrypt_secret(value: str) -> str:
    """Decrypt a stored ``value``. Fail-closed: returns ``''`` on any problem.

    Only ``v1:``-tagged ciphertext is decrypted; any other value is not
    encrypted by this module and resolves to ``''``. Logs a warning that never
    includes the literal value (Rule 6). Never raises — callers' fallback
    chains can keep trying other presets.
    """
    if not value:
        return ""
    if not value.startswith(VERSION_PREFIX):
        log.warning("decrypt_secret: stored api_key is not tagged %s", VERSION_PREFIX)
        return ""
    f = _fernet()
    if f is None:
        return ""
    try:
        return f.decrypt(value[len(VERSION_PREFIX):].encode()).decode()
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


def encrypt_for_storage(value: str, *, fail_closed: bool = True) -> str:
    """Encrypt ``value`` for persistence, unless it is already ciphertext.

    Write APIs take the intended stored value. A user typing a new key passes
    plaintext; but an unchanged edit hands back the ``v1:``-tagged token that
    is already at rest, which must not be encrypted a second time.

    - ``v1:``-tagged ciphertext is returned unchanged (idempotent), whether it
      decrypts under the current key or is from a *previous* key after rotation
      (we preserve it; the resolver fails closed and the admin re-enters).
    - Raw plaintext (no tag) is encrypted and tagged ``v1:``.

    Fail-closed: empty input stays empty. When no master key is configured and
    the value is a *new* plaintext key, ``fail_closed`` (default True) raises
    ``MasterKeyRequiredError`` so a plain key is never written; the
    non-destructive migration path passes ``fail_closed=False`` to preserve
    existing values untouched (resolution fails closed later).
    """
    if not value:
        return ""
    f = _fernet()
    if f is None:
        # No master key configured: never invent a key. A tagged ciphertext is
        # preserved (unchanged edit / non-destructive migration). A raw
        # plaintext key must not be persisted, so fail closed by default.
        if value.startswith(VERSION_PREFIX):
            return value
        if fail_closed:
            raise MasterKeyRequiredError()
        return value
    if value.startswith(VERSION_PREFIX):
        # Already tagged ciphertext: idempotent, no re-encryption. If it does
        # not decrypt under the current key (rotation), preserve it untouched —
        # re-wrapping would hide the old ciphertext and make it undecryptable.
        return value
    return VERSION_PREFIX + f.encrypt(value.encode()).decode()