"""Settings accessors for the database layer."""

from config import (
    LLM_INPUT_COST_USD_PER_MILLION,
    LLM_OUTPUT_COST_USD_PER_MILLION,
    USD_TO_TOMAN_RATE,
)
from config.catalog import settings_key

from services.db.schema import get_conn, transaction

# Sourced from the canonical settings-key registry (J0.2) so the literal key
# string has exactly one definition; consumers should prefer settings_key().
DISPLAY_TOGGLE_DEFAULTS_KEY = settings_key("display_toggle_defaults")["key"]


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
    """Admin-global display-toggle defaults (R10).

    Thin delegate to ``services.db.display_toggles`` (R3) — the single owner of
    display-toggle state and precedence resolution.
    """
    from services.db.display_toggles import get_global_defaults
    return get_global_defaults()


def set_display_toggle_defaults(values: dict[str, bool]):
    """Merge per-field admin-global display-toggle defaults (R10).

    Thin delegate to ``services.db.display_toggles`` (R3).
    """
    from services.db.display_toggles import set_global_defaults
    return set_global_defaults(values)


_MAINTENANCE_MODE_KEY = settings_key("maintenance_mode")["key"]
_MAINTENANCE_MESSAGE_KEY = settings_key("maintenance_message")["key"]

# Canonical default learner-facing maintenance message (single source of truth,
# shared by the admin status panel and the user-facing block in bot.py).
DEFAULT_MAINTENANCE_MESSAGE = "ربات در حال تعمیر است؛ لطفاً بعداً مراجعه کنید."


def is_maintenance_mode() -> bool:
    """True while admin maintenance mode is active (blocks normal user ops)."""
    return get_bool_setting(_MAINTENANCE_MODE_KEY, False)


def set_maintenance_mode(active: bool):
    set_bool_setting(_MAINTENANCE_MODE_KEY, active)


def get_maintenance_message() -> str:
    """Return the editable maintenance message, falling back to the canonical
    default when unset or explicitly cleared."""
    return get_setting(_MAINTENANCE_MESSAGE_KEY, DEFAULT_MAINTENANCE_MESSAGE) or DEFAULT_MAINTENANCE_MESSAGE


def set_maintenance_message(message: str):
    set_setting(_MAINTENANCE_MESSAGE_KEY, message)


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
