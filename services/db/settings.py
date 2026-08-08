"""Settings accessors for the database layer."""

from config import (
    DEFAULT_PHONETIC_SHOW_IPA,
    LLM_INPUT_COST_USD_PER_MILLION,
    LLM_OUTPUT_COST_USD_PER_MILLION,
    USD_TO_TOMAN_RATE,
)

from services.db.schema import get_conn


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


def get_bool_setting(key: str, default: bool = False) -> bool:
    return get_setting(key, "true" if default else "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def set_bool_setting(key: str, value: bool):
    set_setting(key, "true" if value else "false")


def get_phonetic_display_settings() -> dict[str, bool]:
    return {
        "ipa": get_bool_setting("phonetic_show_ipa", DEFAULT_PHONETIC_SHOW_IPA),
    }


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
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
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
        conn.commit()
