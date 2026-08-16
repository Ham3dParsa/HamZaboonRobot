"""Settings accessors for the database layer."""

import json

from config import (
    LLM_INPUT_COST_USD_PER_MILLION,
    LLM_OUTPUT_COST_USD_PER_MILLION,
    USD_TO_TOMAN_RATE,
)
from config.catalog import DISPLAY_TOGGLE_DEFAULTS, DISPLAY_TOGGLE_FIELDS

from services.db.schema import get_conn, transaction

DISPLAY_TOGGLE_DEFAULTS_KEY = "display_toggle_defaults"


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_bool_setting(key: str, default: bool = False) -> bool:
    return get_setting(key, "true" if default else "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def set_bool_setting(key: str, value: bool):
    set_setting(key, "true" if value else "false")


def get_display_toggle_defaults() -> dict[str, bool]:
    """Admin-global display-toggle defaults (R10), always complete.

    Stored values are merged over the built-in catalog defaults so the result
    always carries every DISPLAY_TOGGLE_FIELD and unknown/stale keys are
    ignored.
    """
    effective = dict(DISPLAY_TOGGLE_DEFAULTS)
    raw = get_setting(DISPLAY_TOGGLE_DEFAULTS_KEY, "")
    if raw:
        try:
            stored = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            stored = None
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DISPLAY_TOGGLE_FIELDS:
                    effective[key] = bool(value)
    return effective


def set_display_toggle_defaults(values: dict[str, bool]):
    """Merge per-field admin-global display-toggle defaults (R10).

    Only known DISPLAY_TOGGLE_FIELDS are accepted; anything else raises so a
    mistyped admin edit can never silently no-op.
    """
    unknown = set(values) - set(DISPLAY_TOGGLE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown display-toggle field(s): {', '.join(sorted(unknown))}")
    merged = get_display_toggle_defaults()
    for key, value in values.items():
        merged[key] = bool(value)
    set_setting(DISPLAY_TOGGLE_DEFAULTS_KEY, json.dumps(merged))


def get_llm_cost_profile() -> dict[str, float]:
    return {
        "input_cost_usd_per_million": float(
            get_setting("llm_input_cost_usd_per_million", str(LLM_INPUT_COST_USD_PER_MILLION))
        ),
        "output_cost_usd_per_million": float(
            get_setting("llm_output_cost_usd_per_million", str(LLM_OUTPUT_COST_USD_PER_MILLION))
        ),
        "usd_to_toman_rate": float(get_setting("usd_to_toman_rate", str(USD_TO_TOMAN_RATE))),
    }


def set_llm_cost_profile(
    *,
    input_cost_usd_per_million: float,
    output_cost_usd_per_million: float,
    usd_to_toman_rate: float,
):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("llm_input_cost_usd_per_million", str(input_cost_usd_per_million)),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("llm_output_cost_usd_per_million", str(output_cost_usd_per_million)),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("usd_to_toman_rate", str(usd_to_toman_rate)),
        )
