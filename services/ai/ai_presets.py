"""Hardcoded AI provider presets with batch/RPM limits.

Built-in presets are defined here and seeded into the ai_presets table at init.
Custom presets can be created by admins and stored in the DB (is_custom=1).
"""

import os

BUILTIN_PRESETS = {
    "gapgpt": {
        "name": "gapgpt",
        "base_url": "https://api.gapgpt.app/v1",
        "default_model": "gapgpt-qwen-3.6",
        "api_key": "$GAPGPT_API_KEY",
        "daily_batch_size": 6,
        "max_concurrency": 2,
        "max_rpm": 30,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
    },
    "openai": {
        "name": "openai",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "api_key": "$OPENAI_API_KEY",
        "daily_batch_size": 6,
        "max_concurrency": 2,
        "max_rpm": 60,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
    },
    "anthropic": {
        "name": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-haiku-20240307",
        "api_key": "$ANTHROPIC_API_KEY",
        "daily_batch_size": 6,
        "max_concurrency": 2,
        "max_rpm": 50,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
    },
    "custom": {
        "name": "custom",
        "base_url": "",
        "default_model": "",
        "api_key": "",
        "daily_batch_size": 6,
        "max_concurrency": 2,
        "max_rpm": 30,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
    },
}


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

    return raw


def seed_presets():
    """Return list of built-in preset tuples for DB seeding.

    Returns list of tuples matching ai_presets table columns:
    (name, base_url, model, api_key, daily_batch_size, max_concurrency, max_rpm,
     timeout_seconds, temperature, max_output_tokens, is_custom)
    """
    return [
        (
            p["name"],
            p["base_url"],
            p["default_model"],
            p.get("api_key", ""),
            p["daily_batch_size"],
            p["max_concurrency"],
            p["max_rpm"],
            p["timeout_seconds"],
            p["temperature"],
            p["max_output_tokens"],
            p["is_custom"],
        )
        for p in BUILTIN_PRESETS.values()
    ]


def get_builtin_preset(name: str) -> dict | None:
    """Get a built-in preset by name (does not include DB custom presets)."""
    return BUILTIN_PRESETS.get(name)


def list_builtin_presets() -> list[dict]:
    """List all built-in presets."""
    return list(BUILTIN_PRESETS.values())