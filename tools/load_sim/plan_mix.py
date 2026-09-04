"""Synthetic user arrival model for load simulation (locked R2).

Assigns each synthetic user a plan and a journey per the locked realistic
mix, deterministically per seed. Pure logic, no I/O, no Telegram, no AI.
"""

from __future__ import annotations

import random

_PLAN_WEIGHTS: list[tuple[str, int]] = [
    ("free", 70),
    ("bronze", 15),
    ("silver", 8),
    ("gold", 5),
    ("emerald", 2),
]

_JOURNEY_WEIGHTS: list[tuple[str, int]] = [
    ("full_session", 70),
    ("partial", 10),
    ("word_query", 10),
    ("settings", 5),
    ("idle", 5),
]


def _pick(rng: random.Random, weights: list[tuple[str, int]]) -> str:
    total = sum(w for _, w in weights)
    roll = rng.randrange(total)
    acc = 0
    for name, w in weights:
        acc += w
        if roll < acc:
            return name
    return weights[-1][0]


def sample_workload(n: int, seed: int) -> list[dict]:
    """Return n synthetic users as {plan, journey} dicts, deterministic per seed."""
    rng = random.Random(seed)
    return [
        {"plan": _pick(rng, _PLAN_WEIGHTS), "journey": _pick(rng, _JOURNEY_WEIGHTS)}
        for _ in range(n)
    ]
