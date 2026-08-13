"""FSRS-6 Core Engine — pure DSR math, no side effects.

Full 21-parameter FSRS-6 (w0-w20) with:
- 4-grade system: Again(1), Hard(2), Good(3), Easy(4)
- First-exposure familiarity-based stability (separate weights)
- w20-derived forgetting curve and interval formulas
- FSRSConfig is a frozen dataclass (use MappingProxyType to prevent dict mutation)
- Config injection via optional parameter on every function
- Short-term stability (gated behind enable_short_term in config)

Reference: docs/FSRS_v6.md
Validation: tools/Fsrs_simulation_v5/v5.4_FSRS_full.py
Phase 0.7 verification: compute_retrievability(S=30, t=30) = 0.9, compute_interval(S=30, r=0.9) = 30.0
"""

import math
from dataclasses import dataclass, field
from types import MappingProxyType

# ============================================================
# Constants
# ============================================================

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


def _compute_factor(w20: float) -> float:
    """DSR factor from w20: F = r^(-1/w20) - 1 with r=0.9."""
    return 0.9 ** (-1.0 / w20) - 1.0

# First-exposure stability (familiarity-based grading)
# Question: "چقدر با محتوای این فلش کارت آشنایی داری؟"
# G=1: کاملاً ناآشنا ام, G=2: کمی آشنا ام, G=3: آشنایی خوب, G=4: کاملاً بلدمش
FIRST_EXPOSURE_STABILITY = MappingProxyType({1: 0.212, 2: 1.5, 3: 3.0, 4: 12.0})


# ============================================================
# FSRSConfig — frozen dataclass for parameter injection
# ============================================================

@dataclass(frozen=True)
class FSRSConfig:
    """Immutable config for FSRS-6 computation.

    All dict fields use MappingProxyType to prevent accidental mutation
    (a frozen dataclass doesn't freeze the objects it contains).
    Always construct a fresh config for overrides — never mutate the default:
        cfg = FSRSConfig(w={**DEFAULT_FSRS_CONFIG.w, 'w3': 20.0})
    """
    w: MappingProxyType = field(default_factory=lambda: MappingProxyType(dict(DSR_W)))
    first_exposure_stability: MappingProxyType = field(default_factory=lambda: FIRST_EXPOSURE_STABILITY)
    desired_retention: float = DESIRED_RETENTION_DEFAULT
    maximum_interval: int = 365
    enable_short_term: bool = True
    name: str = "default"


DEFAULT_FSRS_CONFIG = FSRSConfig()


# ============================================================
# DSR Functions
# ============================================================

def compute_retrievability(elapsed_days: float, stability: float, config: FSRSConfig = DEFAULT_FSRS_CONFIG) -> float:
    s = max(0.1, stability)
    t = max(0.0, elapsed_days)
    factor = _compute_factor(config.w["w20"])
    return (1.0 + factor * t / s) ** (-config.w["w20"])


def compute_interval(stability: float, desired_retention: float | None = None, config: FSRSConfig = DEFAULT_FSRS_CONFIG) -> float:
    s = max(0.1, stability)
    r = DESIRED_RETENTION_DEFAULT if desired_retention is None else desired_retention
    factor = _compute_factor(config.w["w20"])
    inv = r ** (-1.0 / config.w["w20"]) - 1.0
    interval = s * inv / factor
    return min(interval, float(config.maximum_interval))


def initial_stability(grade: int, config: FSRSConfig = DEFAULT_FSRS_CONFIG) -> float:
    """Recall-based: S0 = w_{G-1}. Grade in {1,2,3,4}."""
    return {1: config.w["w0"], 2: config.w["w1"], 3: config.w["w2"], 4: config.w["w3"]}[grade]


def initial_stability_first_exposure(grade: int, config: FSRSConfig = DEFAULT_FSRS_CONFIG) -> float:
    """Familiarity-based: uses FIRST_EXPOSURE_STABILITY weights.
    Separate wrapper, not a flag on initial_stability(), to prevent
    'if first_exposure' branching from spreading across the algorithm layer.
    """
    return config.first_exposure_stability[grade]


def initial_difficulty(grade: int, config: FSRSConfig = DEFAULT_FSRS_CONFIG) -> float:
    d0 = config.w["w4"] - math.exp(config.w["w5"] * (grade - 1)) + 1.0
    return max(1.0, min(10.0, d0))


def update_difficulty(d: float, grade: int, config: FSRSConfig = DEFAULT_FSRS_CONFIG) -> float:
    delta_d = -config.w["w6"] * (grade - 3)
    d_damped = d + delta_d * (10.0 - d) / 9.0
    d0_easy = initial_difficulty(4, config)
    d_reverted = config.w["w7"] * d0_easy + (1.0 - config.w["w7"]) * d_damped
    return max(1.0, min(10.0, d_reverted))


def update_stability(
    d: float, s: float, r: float, grade: int,
    config: FSRSConfig = DEFAULT_FSRS_CONFIG,
) -> float:
    s = max(0.1, s)
    if grade == 1:
        s_new = (
            config.w["w11"]
            * (d ** -config.w["w12"])
            * (((s + 1.0) ** config.w["w13"]) - 1.0)
            * math.exp(config.w["w14"] * (1.0 - r))
        )
        if config.enable_short_term:
            upper = s / math.exp(config.w["w17"] * config.w["w18"])
            return max(0.01, min(s_new, upper))
        return max(0.1, min(s_new, s))
    hard_penalty = config.w["w15"] if grade == 2 else 1.0
    easy_bonus = config.w["w16"] if grade == 4 else 1.0
    s_inc = (
        1.0
        + math.exp(config.w["w8"])
        * (11.0 - d)
        * (s ** -config.w["w9"])
        * (math.exp(config.w["w10"] * (1.0 - r)) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    return s * max(1.0, s_inc)


def short_term_stability(s: float, grade: int, config: FSRSConfig = DEFAULT_FSRS_CONFIG) -> float:
    s_inc = math.exp(config.w["w17"] * (grade - 3 + config.w["w18"])) * (s ** -config.w["w19"])
    if grade >= 3:
        s_inc = max(1.0, s_inc)
    return s * s_inc
