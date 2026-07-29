"""FSRS-6 Core Engine — pure DSR math, no side effects.

Full 21-parameter FSRS-6 (w0-w20) with:
- 4-grade system: Again(1), Hard(2), Good(3), Easy(4)
- w20-derived forgetting curve and interval formulas
- Short-term stability (gated behind enable_short_term)
- Mean reversion toward D0(Easy) per FSRS-6 §2.7

Reference: docs/FSRS_v6.md
Validation: tools/Fsrs_simulation_v5/v5.4_FSRS_full.py
"""

import math

DSR_W = {
    "w0": 0.212,      # S0(Again)
    "w1": 1.2931,     # S0(Hard)
    "w2": 2.3065,     # S0(Good)
    "w3": 8.2956,     # S0(Easy)
    "w4": 6.4133,     # D0 base
    "w5": 0.8334,     # D0 multiplier
    "w6": 3.0194,     # Delta D multiplier
    "w7": 0.001,      # Mean reversion weight
    "w8": 1.8722,     # Scale factor
    "w9": 0.1666,     # Stability decay exponent
    "w10": 0.796,     # Retrievability exponent
    "w11": 1.4835,    # Fail stability multiplier
    "w12": 0.0614,    # Fail difficulty exponent
    "w13": 0.2629,    # Fail stability exponent
    "w14": 1.6483,    # Fail retrievability exponent
    "w15": 0.6014,    # Hard penalty
    "w16": 1.8729,    # Easy bonus
    "w17": 0.5425,    # Short-term exponent
    "w18": 0.0912,    # Short-term offset
    "w19": 0.0658,    # Short-term S decay
    "w20": 0.1542,    # Decay exponent (trainable)
}

DSR_FACTOR = 0.9 ** (-1.0 / DSR_W["w20"]) - 1.0
DESIRED_RETENTION_DEFAULT = 0.9


def compute_retrievability(elapsed_days: float, stability: float) -> float:
    s = max(0.1, stability)
    t = max(0.0, elapsed_days)
    return (1.0 + DSR_FACTOR * t / s) ** (-DSR_W["w20"])


def compute_interval(stability: float, desired_retention: float = DESIRED_RETENTION_DEFAULT) -> float:
    s = max(0.1, stability)
    inv = desired_retention ** (-1.0 / DSR_W["w20"]) - 1.0
    return s * inv / DSR_FACTOR


def initial_stability(grade: int) -> float:
    return {1: DSR_W["w0"], 2: DSR_W["w1"], 3: DSR_W["w2"], 4: DSR_W["w3"]}[grade]


def initial_difficulty(grade: int) -> float:
    d0 = DSR_W["w4"] - math.exp(DSR_W["w5"] * (grade - 1)) + 1.0
    return max(1.0, min(10.0, d0))


def update_difficulty(d: float, grade: int) -> float:
    delta_d = -DSR_W["w6"] * (grade - 3)
    d_damped = d + delta_d * (10.0 - d) / 9.0
    d0_easy = initial_difficulty(4)
    d_reverted = DSR_W["w7"] * d0_easy + (1.0 - DSR_W["w7"]) * d_damped
    return max(1.0, min(10.0, d_reverted))


def update_stability(
    d: float, s: float, r: float, grade: int,
    enable_short_term: bool = False,
) -> float:
    s = max(0.1, s)
    if grade == 1:
        s_new = (
            DSR_W["w11"]
            * (d ** -DSR_W["w12"])
            * (((s + 1.0) ** DSR_W["w13"]) - 1.0)
            * math.exp(DSR_W["w14"] * (1.0 - r))
        )
        if enable_short_term:
            upper = s / math.exp(DSR_W["w17"] * DSR_W["w18"])
            return max(0.01, min(s_new, upper))
        return max(0.1, min(s_new, s))
    hard_penalty = DSR_W["w15"] if grade == 2 else 1.0
    easy_bonus = DSR_W["w16"] if grade == 4 else 1.0
    s_inc = (
        1.0
        + math.exp(DSR_W["w8"])
        * (11.0 - d)
        * (s ** -DSR_W["w9"])
        * (math.exp(DSR_W["w10"] * (1.0 - r)) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    return s * max(1.0, s_inc)


def short_term_stability(s: float, grade: int) -> float:
    s_inc = math.exp(DSR_W["w17"] * (grade - 3 + DSR_W["w18"])) * (s ** -DSR_W["w19"])
    if grade >= 3:
        s_inc = max(1.0, s_inc)
    return s * s_inc
