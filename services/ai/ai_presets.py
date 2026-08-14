"""AI provider preset API-key resolution helpers.

All preset configuration is stored in the ``ai_presets`` table (single source
of truth) and managed exclusively through the admin panel / AI preset manager.
There are no hardcoded built-in presets. This module only owns the shared
API-key resolution helper used by the DB layer and the benchmark tool.
"""

import logging
import os

log = logging.getLogger(__name__)


def resolve_api_key(preset_or_raw: dict | str) -> str:
    """Resolve API key from preset dict or raw string.

    Supports:
    - Literal key string
    - Environment variable reference: $ENV_VAR_NAME
    - Dict with 'api_key' field (same rules)

    Returns the resolved key string (empty if not found).
    """
    if isinstance(preset_or_raw, str):
        raw = preset_or_raw
    else:
        raw = preset_or_raw.get("api_key", "")

    if not raw:
        return ""

    if raw.startswith("$"):
        env_name = raw[1:]
        return os.getenv(env_name, "")

    # Defensive guard (R3B): a raw key that is neither a "$" env reference nor
    # a plausibly-valid literal key is almost certainly a mis-stored env-var
    # name (e.g. the historical "HpOF_API_KEY" without the "$" prefix). Log it
    # so the mistake surfaces instead of being silently sent to the provider.
    # We never throw here: callers' fallback chains may still try to use it.
    if not _looks_like_plausible_key(raw):
        log.warning(
            "resolve_api_key: api_key %r is not a '$ENV' reference nor a "
            "plausible literal key; check the preset's stored api_key",
            raw,
        )

    return raw


def _looks_like_plausible_key(raw: str) -> bool:
    """Heuristic: is ``raw`` a plausibly-valid literal API key?

    Real keys in this codebase are token-like — hyphenated/dotted (``sk-...``)
    or long (``ix_<long hex>``). A short bare ``[A-Za-z0-9_]+`` token is the
    shape of a mis-stored env-var name (e.g. ``HpOF_API_KEY`` without the
    leading ``$``), so it is treated as not-a-key and surfaced for review.
    """
    if not raw:
        return False
    if "-" in raw or "." in raw:
        return True
    if len(raw) >= 32:
        return True
    return False
