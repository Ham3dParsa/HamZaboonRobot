"""Hardcoded AI provider presets with batch/RPM limits.

Built-in presets are defined here and seeded into the ai_presets table at init.
Custom presets can be created by admins and stored in the DB (is_custom=1).
"""

import os

BUILTIN_PRESETS = {
    # ── Google 3.6 Flash (newest, highest priority) ──
    "Gemini_36F_HP": {
        "name": "google_36_flash_hpof",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-3.6-flash",
        "api_key": "$HpOF_API_KEY",
        "daily_batch_size": 6,
        "max_concurrency": 2,
        "max_rpm": 5,
        "max_tpm": 250000,
        "max_daily_req": 20,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 0,
        "enabled": 1,
        "is_emergency": 0,
    },
    "Gemini_36F_eli": {
        "name": "google_36_flash_eliapi",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-3.6-flash",
        "api_key": "$ELIAPI_API_KEY",
        "daily_batch_size": 6,
        "max_concurrency": 2,
        "max_rpm": 5,
        "max_tpm": 250000,
        "max_daily_req": 20,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 1,
        "enabled": 1,
        "is_emergency": 0,
    },
    # ── Google 3.5 Flash (default primary) ──
    "Gemini_35F_HP": {
        "name": "google_35_flash_hpof",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-3.5-flash",
        "api_key": "$HpOF_API_KEY",
        "daily_batch_size": 6,
        "max_concurrency": 2,
        "max_rpm": 5,
        "max_tpm": 250000,
        "max_daily_req": 20,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 2,
        "enabled": 1,
        "is_emergency": 0,
    },
    "Gemini_35F_ELI": {
        "name": "google_35_flash_eliapi",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-3.5-flash",
        "api_key": "$ELIAPI_API_KEY",
        "daily_batch_size": 6,
        "max_concurrency": 2,
        "max_rpm": 5,
        "max_tpm": 250000,
        "max_daily_req": 20,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 3,
        "enabled": 1,
        "is_emergency": 0,
    },
    # ── Google 3.5 Flash Lite (newer lite) ──
    "Gemini_35F_lite_HP": {
        "name": "google_35_flash_lite_hpof",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-3.5-flash-lite",
        "api_key": "$HpOF_API_KEY",
        "daily_batch_size": 12,
        "max_concurrency": 3,
        "max_rpm": 15,
        "max_tpm": 250000,
        "max_daily_req": 500,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 4,
        "enabled": 1,
        "is_emergency": 0,
    },
    "Gemini_35F_lite_ELI": {
        "name": "google_35_flash_lite_eliapi",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-3.5-flash-lite",
        "api_key": "$ELIAPI_API_KEY",
        "daily_batch_size": 12,
        "max_concurrency": 3,
        "max_rpm": 15,
        "max_tpm": 250000,
        "max_daily_req": 500,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 5,
        "enabled": 1,
        "is_emergency": 0,
    },
    # ── Google Flash Lite (latest) ──
    "google_flash_lite_latest_hpof": {
        "name": "google_flash_lite_latest_hpof",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-flash-lite-latest",
        "api_key": "$HpOF_API_KEY",
        "daily_batch_size": 12,
        "max_concurrency": 3,
        "max_rpm": 15,
        "max_tpm": 250000,
        "max_daily_req": 500,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 6,
        "enabled": 1,
        "is_emergency": 0,
    },
    "google_flash_lite_latest_eliapi": {
        "name": "google_flash_lite_latest_eliapi",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-flash-lite-latest",
        "api_key": "$ELIAPI_API_KEY",
        "daily_batch_size": 12,
        "max_concurrency": 3,
        "max_rpm": 15,
        "max_tpm": 250000,
        "max_daily_req": 500,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 7,
        "enabled": 1,
        "is_emergency": 0,
    },
    # ── Google Gemma 4 31B IT ──
    "google_gemma_4_31b_hpof": {
        "name": "google_gemma_4_31b_hpof",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemma-4-31b-it",
        "api_key": "$HpOF_API_KEY",
        "daily_batch_size": 4,
        "max_concurrency": 2,
        "max_rpm": 30,
        "max_tpm": 16000,
        "max_daily_req": 14400,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 8,
        "enabled": 1,
        "is_emergency": 0,
    },
    "google_gemma_4_31b_eliapi": {
        "name": "google_gemma_4_31b_eliapi",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemma-4-31b-it",
        "api_key": "$ELIAPI_API_KEY",
        "daily_batch_size": 4,
        "max_concurrency": 2,
        "max_rpm": 30,
        "max_tpm": 16000,
        "max_daily_req": 14400,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 9,
        "enabled": 1,
        "is_emergency": 0,
    },
    # ── Google Gemma 4 26B-A4B IT ──
    "google_gemma_4_26b_hpof": {
        "name": "google_gemma_4_26b_hpof",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemma-4-26b-a4b-it",
        "api_key": "$HpOF_API_KEY",
        "daily_batch_size": 3,
        "max_concurrency": 2,
        "max_rpm": 30,
        "max_tpm": 16000,
        "max_daily_req": 14400,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 10,
        "enabled": 1,
        "is_emergency": 0,
    },
    "google_gemma_4_26b_eliapi": {
        "name": "google_gemma_4_26b_eliapi",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemma-4-26b-a4b-it",
        "api_key": "$ELIAPI_API_KEY",
        "daily_batch_size": 3,
        "max_concurrency": 2,
        "max_rpm": 30,
        "max_tpm": 16000,
        "max_daily_req": 14400,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 11,
        "enabled": 1,
        "is_emergency": 0,
    },
    # ── GapGPT Gemini Lite (emergency fallback) ──
    "gapgpt_gemini_lite": {
        "name": "gapgpt_gemini_lite",
        "base_url": "https://api.gapgpt.app/v1",
        "default_model": "gemini-3.1-flash-lite",
        "api_key": "$GAPGPT_API_KEY",
        "daily_batch_size": 6,
        "max_concurrency": 2,
        "max_rpm": 30,
        "max_tpm": 300000,
        "max_daily_req": 1000,
        "timeout_seconds": 30.0,
        "temperature": 0.6,
        "max_output_tokens": 4096,
        "is_custom": 0,
        "priority": 0,
        "enabled": 1,
        "is_emergency": 1,
    },
}


# Apply default cost fields to all presets.
# Uses real model-specific pricing so the cost dashboard reflects per-model costs.
# These values are overridden by whatever the admin sets in the DB (pricing is
# preserved across init_db() — see _init_ai_presets_table in db/__init__.py).
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-3.6-flash": (1.5, 7.5),
    "gemini-3.5-flash": (1.5, 9.0),
    "gemini-3.5-flash-lite": (0.3, 2.5),
    "gemini-flash-lite-latest": (0.25, 1.5),
    "gemini-3.1-flash-lite": (0.25, 1.5),
    "gemma-4-31b-it": (0.15, 0.6),
    "gemma-4-26b-a4b-it": (0.15, 0.6),
}
for _p in BUILTIN_PRESETS.values():
    _model_key = _p.get("default_model", "")
    if _model_key in _MODEL_PRICING:
        _inp, _out = _MODEL_PRICING[_model_key]
        _p["input_cost_per_million"] = _inp
        _p["output_cost_per_million"] = _out
    else:
        _p.setdefault("input_cost_per_million", None)
        _p.setdefault("output_cost_per_million", None)


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
     max_tpm, max_daily_req, timeout_seconds, temperature, max_output_tokens,
     is_custom, priority, enabled, is_emergency,
     input_cost_per_million, output_cost_per_million, group_label, in_fallback_chain)
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
            p.get("max_tpm", 0),
            p.get("max_daily_req", 0),
            p["timeout_seconds"],
            p["temperature"],
            p["max_output_tokens"],
            p["is_custom"],
            p.get("priority", 0),
            p.get("enabled", 1),
            p.get("is_emergency", 0),
            p.get("input_cost_per_million"),
            p.get("output_cost_per_million"),
            p.get("group_label", ""),
            p.get("in_fallback_chain", 1),
        )
        for p in BUILTIN_PRESETS.values()
    ]


def get_builtin_preset(name: str) -> dict | None:
    """Get a built-in preset by name (does not include DB custom presets)."""
    return BUILTIN_PRESETS.get(name)


def list_builtin_presets() -> list[dict]:
    """List all built-in presets."""
    return list(BUILTIN_PRESETS.values())
