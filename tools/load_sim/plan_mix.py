"""Synthetic user arrival model for load simulation (locked R2; arrival-v2 T1).

Assigns each synthetic user a plan and a journey per the locked realistic
mix, deterministically per seed. Pure logic, no I/O, no Telegram, no AI.
Never imports services.db (stays pure and testable): DB-driven plan sizes
arrive as the ``plan_limits`` INPUT (the driver reads the live plans table).

Arrival-v2 (T1) additions, still pure:
- R1: ``plan_limits`` maps plan code to sessions-per-day and
  cards-per-session; each user spans its plan's sessions-per-day with
  per-session card counts from the limits.
- R2: each user gets a persona INDEPENDENT of plan (separate RNG stream so
  the legacy plan/journey draw sequence is bit-identical). Persona drives
  daily attendance, queries per day, and abandon probability; the
  fluctuating 21-day wave modulates abandon and resume timing. Sessions
  spread across the day; abandons resume hours later.
- R3: :func:`edge_scenarios` builds the three named edge workloads.
"""

from __future__ import annotations

import math
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

# R1 fallback when the caller passes no limits. Mirrors the DB seed in
# services/db/plans.py (_PLAN_LIMITS: sessions-per-day, cards-per-session):
# free 2x3, bronze 3x3, silver 3x5, gold 4x7, emerald 5x9. The driver always
# passes live table values; this fallback only keeps pure unit use testable.
_DEFAULT_PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free": {"sessions": 2, "cards": 3},
    "bronze": {"sessions": 3, "cards": 3},
    "silver": {"sessions": 3, "cards": 5},
    "gold": {"sessions": 4, "cards": 7},
    "emerald": {"sessions": 5, "cards": 9},
}

# R2 persona parameters. Mirrored (not invented) from
# tools/fsrs-replay/v5.4_FSRS_full.py PERSONAS (verified: identical values
# also archived at tools/Fsrs_simulation_v5/v5.4_FSRS_full.py; the fsrs-replay
# copy is the live engine imported by sim_runner.py): eager attend 0.92
# q 2-6, average 0.70 q 0-3, lazy 0.35 q 0-1, fluctuating base 0.55
# amplitude 0.30 period 21d q 0-3 (completion mirrors session_completion
# there: eager 1.0, average 0.85, lazy 0.40, fluctuating 0.60); gamer
# attend 0.98 q 3-8 completion 1.0 mirrored from
# tools/fsrs-replay/sim_runner.py (gamer augmentation, absent from v5.4).
_PERSONA_PARAMS: dict[str, dict[str, float]] = {
    "eager": {"attend": 0.92, "q_lo": 2, "q_hi": 6, "completion": 1.0},
    "average": {"attend": 0.70, "q_lo": 0, "q_hi": 3, "completion": 0.85},
    "lazy": {"attend": 0.35, "q_lo": 0, "q_hi": 1, "completion": 0.40},
    "fluctuating": {
        "attend_base": 0.55,
        "attend_amplitude": 0.30,
        "attend_period_days": 21,
        "q_lo": 0,
        "q_hi": 3,
        "completion": 0.60,
    },
    "gamer": {"attend": 0.98, "q_lo": 3, "q_hi": 8, "completion": 1.0},
}

# R2 global persona mix (percent weights, tunable): lazy 25, average 40,
# eager 20, fluctuating 10, gamer 5. Independent of plan by owner constraint.
PERSONA_MIX: list[tuple[str, int]] = [
    ("lazy", 25),
    ("average", 40),
    ("eager", 20),
    ("fluctuating", 10),
    ("gamer", 5),
]

# Simulated week span (days) over which user arrivals spread.
ARRIVAL_SPAN_DAYS = 7

# F3 night-owl spread (locked plan scale/plan-load-sim-60day round 2).
# Full-fidelity days spread each active user's sessions across all 24h:
# with persona-weighted probability the session lands in the midnight mass
# (00-05), otherwise uniformly across the daytime band (07-23); hour 06 is
# a quiet buffer crossed only by resume delays, never by starts. Global
# midnight mass stays small (~4-5% of starts: the mix-weighted mean of the
# per-persona probabilities below). Persona weights: night-owl gamers stay
# up latest (0.10), eager learners next (0.06), fluctuating with the wave
# (0.05), average (0.04), lazy earliest (0.03). Pure schedule construction —
# replay order is the ascending start hour; nothing here touches routers.
NIGHT_HOURS: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
DAY_HOURS: tuple[int, ...] = tuple(range(7, 24))
NIGHT_OWL_PROB: dict[str, float] = {
    "gamer": 0.10,
    "eager": 0.06,
    "fluctuating": 0.05,
    "average": 0.04,
    "lazy": 0.03,
}

EDGE_SCENARIOS: tuple[str, ...] = (
    "gamer_herd",
    "mass_resume",
    "hour_boundary_thunder",
)


def _pick(rng: random.Random, weights: list[tuple[str, int]]) -> str:
    total = sum(w for _, w in weights)
    roll = rng.randrange(total)
    acc = 0
    for name, w in weights:
        acc += w
        if roll < acc:
            return name
    return weights[-1][0]


def resolve_plan_limits(plan_limits: dict | None) -> dict[str, dict[str, int]]:
    """Normalize the R1 ``plan_limits`` input to code -> sessions/cards.

    Accepts per-code ``{"sessions": s, "cards": c}`` dicts (also
    ``sessions_per_day``/``cards_per_session`` keys) or ``(sessions, cards)``
    tuples. Unknown/missing codes fall back to the free entry; a ``None``
    input returns the module-default mirror of the DB seed.
    """
    if plan_limits is None:
        return {k: dict(v) for k, v in _DEFAULT_PLAN_LIMITS.items()}
    resolved: dict[str, dict[str, int]] = {}
    fallback = _DEFAULT_PLAN_LIMITS["free"]
    for code in _DEFAULT_PLAN_LIMITS:
        raw = plan_limits.get(code) if isinstance(plan_limits, dict) else None
        if isinstance(raw, (tuple, list)) and len(raw) >= 2:
            resolved[code] = {"sessions": int(raw[0]), "cards": int(raw[1])}
        elif isinstance(raw, dict):
            sessions = raw.get("sessions", raw.get("sessions_per_day"))
            cards = raw.get("cards", raw.get("cards_per_session"))
            try:
                resolved[code] = {
                    "sessions": int(sessions),
                    "cards": int(cards),
                }
            except (TypeError, ValueError):
                resolved[code] = dict(fallback)
        else:
            resolved[code] = dict(fallback)
    for code in resolved:
        resolved[code]["sessions"] = max(1, resolved[code]["sessions"])
        resolved[code]["cards"] = max(1, resolved[code]["cards"])
    return resolved


def _wave(day: int) -> float:
    """Fluctuating 21-day enthusiasm wave, mirrored from v5.4 _attend_prob."""
    period = _PERSONA_PARAMS["fluctuating"]["attend_period_days"]
    return math.sin((2 * math.pi * day) / period)


def attend_prob(persona: str, day: int) -> float:
    """Daily attendance probability for one persona on simulated ``day``.

    Flat ``attend`` rate per persona, except fluctuating which rides the
    21-day enthusiasm wave (peak days attend near ``base + amplitude``,
    trough days near ``base - amplitude``, clamped) — the attendance twin
    of :func:`abandon_prob`, mirrored from v5.4 ``_attend_prob``.
    """
    params = _PERSONA_PARAMS[persona]
    if "attend_base" in params:
        prob = params["attend_base"] + params["attend_amplitude"] * _wave(day)
        return max(0.05, min(0.98, prob))
    return float(params["attend"])


def abandon_prob(persona: str, day: int) -> float:
    """Mid-session abandon probability: 1 - completion, wave-modulated.

    Fluctuating enthusiasm runs inverse to abandon: peak-wave days abandon
    near ``1 - completion - amplitude``, trough days near
    ``1 - completion + amplitude`` (clamped). Other personas use their flat
    ``1 - completion`` rate.
    """
    params = _PERSONA_PARAMS[persona]
    base = 1.0 - params["completion"]
    if "attend_base" in params:
        base -= params["attend_amplitude"] * _wave(day)
    return max(0.05, min(0.90, base))


def sample_session_outcome(
    persona: str, day: int, rng: random.Random
) -> tuple[bool, float | None]:
    """Draw ``(abandoned, resume_hours_later)`` for one session.

    Resume lands hours later the same day (1-6h uniform); fluctuating trough
    days resume later (up to +1.5h), peak days sooner, via the 21-day wave.
    """
    if rng.random() >= abandon_prob(persona, day):
        return False, None
    delay = rng.uniform(1.0, 6.0)
    if "attend_base" in _PERSONA_PARAMS[persona]:
        delay -= 1.5 * _wave(day)
    return True, round(max(0.5, min(9.0, delay)), 1)


def _sample_schedule(
    persona: str, sessions: int, prng: random.Random
) -> dict:
    """Sample one user's arrival schedule: day, hours, queries, abandon."""
    params = _PERSONA_PARAMS[persona]
    day = prng.randrange(ARRIVAL_SPAN_DAYS)
    hours = sorted(prng.sample(range(7, 23), min(sessions, 16)))
    while len(hours) < sessions:  # sessions-per-day above 16: reuse peak hours
        hours.append(prng.choice(range(9, 21)))
        hours.sort()
    queries = prng.randint(int(params["q_lo"]), int(params["q_hi"]))
    abandoned, resume = sample_session_outcome(persona, day, prng)
    return {
        "day": day,
        "start_hours": hours,
        "queries": queries,
        "abandoned": abandoned,
        "resume_hours_later": resume,
    }


def sample_workload(
    n: int, seed: int, plan_limits: dict | None = None
) -> list[dict]:
    """Return n synthetic users, deterministic per seed.

    Legacy ``plan``/``journey`` draws keep their exact historical RNG
    sequence (same ``seed`` stream as before arrival-v2, so the locked
    distribution gates cannot shift); persona and schedule draws consume a
    SEPARATE stream, which is what keeps persona independent of plan.
    Each user spans its plan's sessions-per-day with per-session card
    counts from ``plan_limits``.
    """
    limits = resolve_plan_limits(plan_limits)
    rng = random.Random(seed)
    # Independent stream: persona/schedule never perturb plan/journey draws.
    prng = random.Random((seed * 2654435761 + 0xA53A5EED) & 0xFFFFFFFF)
    users = []
    for _ in range(n):
        plan = _pick(rng, _PLAN_WEIGHTS)
        journey = _pick(rng, _JOURNEY_WEIGHTS)
        persona = _pick(prng, PERSONA_MIX)
        spec = limits.get(plan, limits["free"])
        sessions = spec["sessions"]
        cards = spec["cards"]
        sched = _sample_schedule(persona, sessions, prng)
        users.append(
            {
                "plan": plan,
                "journey": journey,
                "persona": persona,
                "sessions": sessions,
                "cards_per_session": cards,
                "session_cards": [cards] * sessions,
                **sched,
            }
        )
    return users


def night_owl_prob(persona: str) -> float:
    """Midnight-mass probability for one session start (pure, F3).

    Returns the persona-weighted share of session starts landing in
    00-05 (see ``NIGHT_OWL_PROB``); unknown personas fall back to the
    mix-weighted mean (0.05).
    """
    return float(NIGHT_OWL_PROB.get(persona, 0.05))


def sample_day_start_hours(
    persona: str, sessions: int, rng: random.Random
) -> list[int]:
    """Sample one user's session start hours across the full 24h (pure, F3).

    Each of the ``sessions`` starts lands in the midnight mass (uniform
    over 00-05) with probability :func:`night_owl_prob`, else uniformly
    over the daytime band (07-23). Returned sorted ascending — the replay
    order for the day. Deterministic per RNG state; consumes exactly
    ``sessions`` uniform draws plus ``sessions`` choice draws.
    """
    hours: list[int] = []
    for _ in range(max(0, int(sessions))):
        if rng.random() < night_owl_prob(persona):
            hours.append(rng.choice(NIGHT_HOURS))
        else:
            hours.append(rng.choice(DAY_HOURS))
    hours.sort()
    return hours


def build_day_replay_order(
    user_hours: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Order one simulated day's session starts for replay (pure, F3).

    Input is ``[(user_id, start_hour)]`` (one entry per session start);
    output is the same entries sorted by ``(start_hour, user_id)`` so the
    fidelity replay walks the day chronologically with a deterministic
    tie-break. No I/O, no router calls.
    """
    return sorted(user_hours, key=lambda item: (item[1], item[0]))


def edge_scenarios(
    name: str, n: int, seed: int, plan_limits: dict | None = None
) -> list[dict]:
    """Build one of the three named R3 edge workloads (pure, deterministic).

    - ``gamer_herd``: every user is a gamer arriving at once (hour 18) on a
      session/query journey.
    - ``mass_resume``: every user abandoned mid-session and resumes together
      (same start hour, same +3h resume delay).
    - ``hour_boundary_thunder``: every session starts at the same hour (09).
    """
    if name not in EDGE_SCENARIOS:
        raise ValueError(f"unknown edge scenario {name!r}; want one of {EDGE_SCENARIOS}")
    workload = sample_workload(n=n, seed=seed, plan_limits=plan_limits)
    if name == "gamer_herd":
        for i, user in enumerate(workload):
            user["persona"] = "gamer"
            user["journey"] = "full_session" if i % 2 == 0 else "word_query"
            user["day"] = 0
            user["start_hours"] = [18] * user["sessions"]
            user["abandoned"] = False
            user["resume_hours_later"] = None
    elif name == "mass_resume":
        for user in workload:
            user["journey"] = "partial"
            user["day"] = 0
            user["start_hours"] = [12] * user["sessions"]
            user["abandoned"] = True
            user["resume_hours_later"] = 3.0
    else:  # hour_boundary_thunder
        for user in workload:
            user["day"] = 0
            user["start_hours"] = [9] * user["sessions"]
    return workload
