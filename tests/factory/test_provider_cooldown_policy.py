"""Per-provider cooldown policy (R1/R2/R6): table + override precedence.

factory.core.llm_json is the sole taxonomy owner: PROVIDER_COOLDOWN_S
maps provider -> post-429 pause/exile seconds; cooldown_for(provider,
override=None) resolves with an explicit override winning over the
table (preserves --cooldown-secs behavior; no new env vars).
Pure stdlib, no network, no clock.
"""

from factory.core import llm_json as LJ


def test_table_values():
    assert LJ.PROVIDER_COOLDOWN_S["kilo"] == 18.0
    assert LJ.PROVIDER_COOLDOWN_S["google"] == 4.0
    for provider in ("zen", "openrouter", "avalai", "generic"):
        assert LJ.PROVIDER_COOLDOWN_S[provider] == 300.0
    assert LJ.PROVIDER_COOLDOWN_S["tunnel_fetch"] == 300.0


def test_cooldown_for_table_lookup():
    assert LJ.cooldown_for("google") == 4.0
    assert LJ.cooldown_for("kilo") == 18.0
    assert LJ.cooldown_for("zen") == 300.0
    assert LJ.cooldown_for("tunnel_fetch") == 300.0


def test_cooldown_for_override_wins():
    # Explicit override (--cooldown-secs) beats the table, any provider.
    assert LJ.cooldown_for("google", override=99.0) == 99.0
    assert LJ.cooldown_for("kilo", override=45.5) == 45.5
    assert LJ.cooldown_for("zen", override=1.0) == 1.0


def test_cooldown_for_unknown_provider_falls_back():
    assert LJ.cooldown_for("nope") == LJ.PROVIDER_COOLDOWN_S["generic"]
    assert LJ.cooldown_for("") == LJ.PROVIDER_COOLDOWN_S["generic"]
    assert LJ.cooldown_for(None) == LJ.PROVIDER_COOLDOWN_S["generic"]


def test_cooldown_for_normalizes_provider():
    assert LJ.cooldown_for(" Google ") == 4.0
    assert LJ.cooldown_for("KILO") == 18.0


def test_cooldown_for_garbage_override_falls_back():
    # Non-finite / non-positive / non-numeric overrides must not
    # poison arithmetics: the table decides instead.
    assert LJ.cooldown_for("google", override=float("nan")) == 4.0
    assert LJ.cooldown_for("google", override=float("inf")) == 4.0
    assert LJ.cooldown_for("google", override=0) == 4.0
    assert LJ.cooldown_for("google", override=-5) == 4.0
    assert LJ.cooldown_for("google", override="junk") == 4.0
