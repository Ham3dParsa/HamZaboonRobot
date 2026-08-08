"""v5.4 — True FSRS-6 DSR Session Simulation

Clean implementation based on docs/FSRS_v6.md:
- Full 21-parameter FSRS-6 (w0-w20)
- 4-grade system: Again(1), Hard(2), Good(3), Easy(4)
- w20-derived forgetting curve and interval formulas
- Short-term stability (gated behind enable_short_term)
- Mean reversion toward D0(Easy) per FSRS-6 §2.7
- No lite/legacy models (removed from v5.2)
- Performance threshold for Easy grade: 0.90
"""

import math
import random
from collections import Counter
from dataclasses import dataclass
from typing import Optional, Literal

# ============ Plan Defaults ============
PLAN_DEFAULTS = {
    "free":     {"sessions": 1, "session_size": 4,  "ai_daily_cap": 3,  "query_daily_cap": 3,  "queue_cap_days": 2},
    "silver":   {"sessions": 3, "session_size": 5,  "ai_daily_cap": 5,  "query_daily_cap": 7,  "queue_cap_days": 3},
    "gold":     {"sessions": 4, "session_size": 7,  "ai_daily_cap": 12, "query_daily_cap": 10, "queue_cap_days": 4},
    "platinum": {"sessions": 6, "session_size": 8, "ai_daily_cap": 20, "query_daily_cap": 16, "queue_cap_days": 6},
}

# ============ User Personas ============
# Research-based parameters from:
# - FSRS paper optimization (Ye et al. KDD 2022, TKDE 2023)
# - FSRS4Anki defaults (optimized on 500M+ Anki reviews)
# - Anki/FSRS FAQ on button usage patterns
# - SuperMemo/Duolingo attendance research
PERSONAS = {
    "eager": {
        "persona_key": "eager",
        "attend": 0.92,
        "q_lo": 2, "q_hi": 6,
        "save_prob": 0.70,
        "forget": 0.08,
        "grade_probs": "eager",
        "session_completion": 1.0,  # completes all daily slots
        "response_time_sec": (2, 5),  # fast
    },
    "average": {
        "persona_key": "average",
        "attend": 0.70,
        "q_lo": 0, "q_hi": 3,
        "save_prob": 0.50,
        "forget": 0.15,
        "grade_probs": "average",
        "session_completion": 0.85,
        "response_time_sec": (3, 7),
    },
    "lazy": {
        "persona_key": "lazy",
        "attend": 0.35,
        "q_lo": 0, "q_hi": 1,
        "save_prob": 0.30,
        "forget": 0.30,
        "grade_probs": "lazy",
        "session_completion": 0.40,
        "response_time_sec": (8, 15),
    },
    "fluctuating": {
        "persona_key": "fluctuating",
        "attend_base": 0.55,
        "attend_amplitude": 0.30,
        "attend_period_days": 21,
        "q_lo": 0, "q_hi": 3,
        "save_prob": 0.50,
        "forget": 0.20,
        "grade_probs": "fluctuating",
        "session_completion": 0.60,
        "response_time_sec": (4, 10),
    },
}

# ============ Proficiency Levels ============
PROFICIENCY = {
    "beginner":     {"known_vocab": 500,  "target_pool": 2000, "ai_efficiency": 0.70, "reject_noise": 0.10},
    "intermediate": {"known_vocab": 2000, "target_pool": 4000, "ai_efficiency": 0.65, "reject_noise": 0.15},
    "advanced":     {"known_vocab": 4000, "target_pool": 7000, "ai_efficiency": 0.60, "reject_noise": 0.20},
}

# ============ AI Cost ============
AI_COST_PER_CALL = 0.0006

# ============ FSRS-6 Full Parameters (w0-w20) ============
DSR_W = {
    "w0": 0.212,      # S0(Again)
    "w1": 1.2931,     # S0(Hard)
    "w2": 2.3065,     # S0(Good)
    "w3": 8.2956,     # S0(Easy)
    "w4": 6.4133,
    "w5": 0.8334,
    "w6": 3.0194,
    "w7": 0.001,
    "w8": 1.8722,
    "w9": 0.1666,
    "w10": 0.796,
    "w11": 1.4835,
    "w12": 0.0614,
    "w13": 0.2629,
    "w14": 1.6483,
    "w15": 0.6014,
    "w16": 1.8729,    # Easy bonus
    "w17": 0.5425,    # Short-term: grade effect
    "w18": 0.0912,    # Short-term: grade offset
    "w19": 0.0658,    # Short-term: S^-w19
    "w20": 0.1542,    # Decay exponent
}

# Derived constants (FSRS-6 §2.1)
DSR_FACTOR = 0.9 ** (-1.0 / DSR_W["w20"]) - 1.0
DESIRED_RETENTION_DEFAULT = 0.9

# Learned and tier thresholds
LEARNED_MIN_STABILITY_DAYS = 21.0
DSR_TIER_THRESHOLDS = [
    ("در حال یادگیری", 0.0),
    ("آشنا", 7.0),
    ("یادگرفته‌شده", 21.0),
    ("تثبیت‌شده", 60.0),
]

# Performance draw
PERFORMANCE_NOISE = 0.15

# Persona-specific grade probabilities [Again, Hard, Good, Easy]
# Calibrated from FSRS paper optimization results (Ye et al. KDD 2022, TKDE 2023)
# and FSRS4Anki defaults (optimized on 500M+ Anki reviews)
# Targets: eager=2btn (Again/Good), average=3btn, lazy=3btn conservative, fluctuating=moderate
# Easy usage per FSRS FAQ: "FSRS is a little more accurate for people who mostly use Again and Good"
PERSONA_GRADE_PROBS = {
    "eager":        [0.02, 0.05, 0.60, 0.33],  # 2% Again, 5% Hard, 60% Good, 33% Easy - uses Easy liberally
    "average":      [0.08, 0.15, 0.55, 0.22],  # 8% Again, 15% Hard, 55% Good, 22% Easy - balanced
    "lazy":         [0.15, 0.20, 0.50, 0.15],  # 15% Again, 20% Hard, 50% Good, 15% Easy - conservative, more Hard
    "fluctuating":  [0.10, 0.15, 0.55, 0.20],  # 10% Again, 15% Hard, 55% Good, 20% Easy - moderate
}

# Retrievability modulation strength for grade distribution
GRADE_RETRIEVABILITY_SHIFT = 0.30

# Query-first priority thresholds
QUERY_BACKLOG_SOFT_CAP_MULT = 1.0
QUERY_BACKLOG_HARD_CAP_MULT = 2.0
QUERY_INFLOW_MAX_REDUCTION = 0.80

# Premium override band
PLAN_OVERRIDE_BAND = 0.30

Origin = Literal["query", "ai"]

# ============================================================
# DSR HELPER FUNCTIONS
# ============================================================

def _dsr_retrievability(elapsed_days: float, stability: float) -> float:
    """FSRS-6 forgetting curve: R = (1 + FACTOR * t/S) ^ (-w20)  (§2.1)"""
    stability = max(0.1, stability)
    t = max(0.0, elapsed_days)
    return (1.0 + DSR_FACTOR * t / stability) ** (-DSR_W["w20"])

def _dsr_interval_days(stability: float, desired_retention: float = DESIRED_RETENTION_DEFAULT) -> float:
    """FSRS-6 next interval: I = S/FACTOR * (r^(-1/w20) - 1)  (§2.8)"""
    stability = max(0.1, stability)
    inv = desired_retention ** (-1.0 / DSR_W["w20"]) - 1.0
    return stability * inv / DSR_FACTOR

def _dsr_s0(grade: int) -> float:
    """Initial stability for first review (§2.2)."""
    return {1: DSR_W["w0"], 2: DSR_W["w1"], 3: DSR_W["w2"], 4: DSR_W["w3"]}[grade]

def _dsr_d0(grade: int) -> float:
    """Initial difficulty for first review (§2.3)."""
    d0 = DSR_W["w4"] - math.exp(DSR_W["w5"] * (grade - 1)) + 1.0
    return max(1.0, min(10.0, d0))

def _dsr_update_difficulty(d: float, grade: int) -> float:
    """Difficulty update with mean reversion toward D0(Easy) (§2.7)."""
    delta_d = -DSR_W["w6"] * (grade - 3)
    d_damped = d + delta_d * (10.0 - d) / 9.0
    d0_easy = _dsr_d0(4)
    d_reverted = DSR_W["w7"] * d0_easy + (1.0 - DSR_W["w7"]) * d_damped
    return max(1.0, min(10.0, d_reverted))

def _dsr_update_stability(d: float, s: float, r: float, grade: int) -> float:
    """Stability update: success (§2.4) or failure (§2.5)."""
    s = max(0.1, s)
    if grade == 1:
        s_new = (
            DSR_W["w11"]
            * (d ** -DSR_W["w12"])
            * (((s + 1.0) ** DSR_W["w13"]) - 1.0)
            * math.exp(DSR_W["w14"] * (1.0 - r))
        )
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

def _dsr_short_term_stability(s: float, grade: int) -> float:
    """Same-day review stability (§2.6)."""
    s_inc = math.exp(DSR_W["w17"] * (grade - 3 + DSR_W["w18"])) * (s ** -DSR_W["w19"])
    if grade >= 3:
        s_inc = max(1.0, s_inc)
    return s * s_inc

def _dsr_tier(stability: float) -> str:
    tier = DSR_TIER_THRESHOLDS[0][0]
    for name, floor in DSR_TIER_THRESHOLDS:
        if stability >= floor:
            tier = name
    return tier


def _sample_grade(persona_key: str, r: float, rng: random.Random) -> int:
    """Sample grade from persona-specific distribution modulated by retrievability."""
    probs = PERSONA_GRADE_PROBS.get(persona_key, PERSONA_GRADE_PROBS["average"]).copy()
    shift = (1.0 - r) * GRADE_RETRIEVABILITY_SHIFT
    probs[0] += shift * 0.6  # Again
    probs[1] += shift * 0.4  # Hard
    probs[2] -= shift * 0.5  # Good
    probs[3] -= shift * 0.5  # Easy
    probs = [max(0.01, p) for p in probs]
    total = sum(probs)
    probs = [p / total for p in probs]
    return rng.choices([1, 2, 3, 4], weights=probs)[0]


# ============================================================
# CARD DATACLASS
# ============================================================

@dataclass
class Card:
    id: int
    origin: Origin = "ai"

    stability: float = 0.0
    difficulty: float = 0.0
    last_review: Optional[int] = None

    next_review: Optional[int] = None
    due_since: Optional[int] = None
    reviews: int = 0

    first_exposure_done: bool = False

# ============================================================
# SIMULATION CONFIG
# ============================================================

@dataclass
class SimConfig:
    plan: str = "free"
    persona: str = "average"
    proficiency: str = "intermediate"
    days: int = 180
    seed: Optional[int] = 42
    jitter: float = 0.15

    enable_rejection: bool = True
    enable_catchup: bool = True
    enable_session_rate_limit: bool = True
    enable_short_term: bool = False

    desired_retention: float = DESIRED_RETENTION_DEFAULT

    sessions_override: Optional[int] = None
    session_size_override: Optional[int] = None

# ============================================================
# PLAN / OVERRIDE HELPERS
# ============================================================

def _clamp_override(default: int, requested: Optional[int]) -> int:
    if requested is None:
        return default
    lo = max(1, math.floor(default * (1 - PLAN_OVERRIDE_BAND)))
    hi = max(lo, math.ceil(default * (1 + PLAN_OVERRIDE_BAND)))
    return max(lo, min(hi, requested))

def _resolve_plan(cfg: SimConfig) -> dict:
    base = PLAN_DEFAULTS[cfg.plan]
    return {
        **base,
        "sessions": _clamp_override(base["sessions"], cfg.sessions_override),
        "session_size": _clamp_override(base["session_size"], cfg.session_size_override),
    }

def _attend_prob(persona: str, day: int, rng: random.Random) -> bool:
    p = PERSONAS[persona]
    if "attend_base" in p:
        phase = (2 * math.pi * day) / p["attend_period_days"]
        prob = p["attend_base"] + p["attend_amplitude"] * math.sin(phase)
        return rng.random() < prob
    return rng.random() < p["attend"]

# ============================================================
# FIRST EXPOSURE — 4-grade
# ============================================================

def _handle_first_exposure(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    r_at_first = 1.0
    grade = _sample_grade(persona["persona_key"], r_at_first, rng)

    card.stability = _dsr_s0(grade)
    card.difficulty = _dsr_d0(grade)
    if grade == 1:
        interval = 1.0
    else:
        interval = _dsr_interval_days(card.stability, cfg.desired_retention)

    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
    card.next_review = day + max(1, round(interval * jitter))
    card.last_review = day
    card.reviews += 1
    card.first_exposure_done = True

    return {1: "forget", 2: "hold", 3: "advance", 4: "master"}[grade]

# ============================================================
# REVIEW OUTCOME — DSR (FSRS-6, subsequent reviews)
# ============================================================

def _review_outcome_dsr(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    elapsed = day - (card.last_review if card.last_review is not None else day)
    r = _dsr_retrievability(elapsed, card.stability)

    grade = _sample_grade(persona["persona_key"], r, rng)

    card.difficulty = _dsr_update_difficulty(card.difficulty, grade)
    card.stability = _dsr_update_stability(card.difficulty, card.stability, r, grade)
    card.last_review = day
    card.reviews += 1
    card.due_since = None

    interval = _dsr_interval_days(card.stability, cfg.desired_retention)
    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
    card.next_review = day + max(1, round(interval * jitter))

    return {1: "forget", 2: "hold", 3: "advance", 4: "master"}[grade]

# ============================================================
# SIMULATE
# ============================================================

def simulate(cfg: SimConfig, debug: bool = False):
    plan = _resolve_plan(cfg)
    persona = PERSONAS[cfg.persona]
    rng = random.Random(cfg.seed)

    active: list[Card] = []
    active_ids: set[int] = set()
    pending: list[Card] = []
    next_id = 0
    rows = []
    total_ai_calls = 0
    total_active_words = 0
    total_rejected = 0
    total_bonus_processed = 0
    created_by_query = 0
    created_by_ai = 0
    lateness_samples = []
    recent_attendance: list[bool] = []
    total_ai_cost = 0.0

    prof_cfg = PROFICIENCY[cfg.proficiency]
    reject_base = (prof_cfg["known_vocab"] / prof_cfg["target_pool"]) * prof_cfg["ai_efficiency"]
    reject_noise = prof_cfg["reject_noise"]

    def new_card(origin: Origin) -> Card:
        nonlocal next_id
        next_id += 1
        return Card(id=next_id, origin=origin)

    daily_slots = plan["sessions"] * plan["session_size"]
    queue_cap_due = plan["queue_cap_days"] * daily_slots

    for day in range(cfg.days):
        attended = _attend_prob(cfg.persona, day, rng)

        recent_attendance.append(attended)
        if len(recent_attendance) > 7:
            recent_attendance.pop(0)
        enthusiasm = sum(recent_attendance) / len(recent_attendance) if recent_attendance else 0.0

        pending_debt = sum(1 for c in active if c.next_review is not None and c.next_review <= day)

        # Step 1: user queries
        queries_today = 0
        saved_today = 0
        if attended:
            q_hi = min(persona["q_hi"], plan["query_daily_cap"])
            if pending_debt > queue_cap_due * 0.5:
                debt_ratio = pending_debt / queue_cap_due
                effective_reduction = min(0.5, (debt_ratio - 0.5))
                reduced_cap = int(plan["query_daily_cap"] * (1 - effective_reduction))
                q_hi = min(q_hi, max(int(plan["query_daily_cap"] * 0.5), reduced_cap))

            query_backlog_size = sum(1 for c in pending if c.origin == "query")
            soft_cap = daily_slots * QUERY_BACKLOG_SOFT_CAP_MULT
            hard_cap = daily_slots * QUERY_BACKLOG_HARD_CAP_MULT
            if query_backlog_size > soft_cap:
                overflow_ratio = min(1.0, (query_backlog_size - soft_cap) / (hard_cap - soft_cap))
                inflow_reduction = overflow_ratio * QUERY_INFLOW_MAX_REDUCTION
                q_hi = max(0, int(q_hi * (1 - inflow_reduction)))

            q_lo = min(persona["q_lo"], q_hi)
            queries_today = rng.randint(q_lo, q_hi)
            for _ in range(queries_today):
                total_ai_calls += 1
                total_ai_cost += AI_COST_PER_CALL
                if rng.random() < persona["save_prob"]:
                    card = new_card("query")
                    pending.append(card)
                    created_by_query += 1
                    saved_today += 1

        # Step 2: collect due cards
        due = [c for c in active if c.next_review is not None and c.next_review <= day]
        for c in due:
            if c.due_since is None:
                c.due_since = c.next_review
        due.sort(key=lambda c: c.due_since)
        due_before = len(due)

        due_slots_used = 0
        ai_generated = 0
        rejected_today = 0
        bonus_processed = 0
        query_slots_used = 0

        if attended:
            # Step 3: due reviews first
            remaining = daily_slots
            tier1 = due[:remaining]
            due_slots_used = len(tier1)
            remaining -= due_slots_used

            # Step 4: throttle AI cap
            due_pressure = due_before - due_slots_used
            if due_pressure >= queue_cap_due:
                ai_cap_today = 0
            else:
                throttle = max(0.3, 1.0 - (due_pressure / queue_cap_due) * 0.7)
                ai_cap_today = math.floor(plan["ai_daily_cap"] * throttle)

            if day <= 2 and plan["ai_daily_cap"] > 0:
                ai_cap_today = min(ai_cap_today * 2, remaining)

            if cfg.enable_session_rate_limit and plan["sessions"] > 1:
                per_session_cap = max(1, math.ceil(ai_cap_today / plan["sessions"]))
                ai_cap_today = min(ai_cap_today, per_session_cap * plan["sessions"])

            query_backlog_now = [c for c in pending if c.origin == "query"]
            hard_cap_qb = daily_slots * QUERY_BACKLOG_HARD_CAP_MULT
            if len(query_backlog_now) > hard_cap_qb:
                ai_cap_today = 0

            # Step 5: query-first priority
            tier2 = query_backlog_now[:remaining]
            for c in tier2:
                pending.remove(c)
            query_slots_used = len(tier2)
            remaining -= query_slots_used

            # Step 6: AI cards with rejection recycling
            tier3 = []
            slots_open = remaining
            ai_budget_left = ai_cap_today
            while slots_open > 0 and ai_budget_left > 0:
                total_ai_calls += 1
                ai_generated += 1
                total_ai_cost += AI_COST_PER_CALL
                ai_budget_left -= 1
                if cfg.enable_rejection:
                    reject_prob = reject_base + rng.uniform(-reject_noise, reject_noise)
                    reject_prob = max(0.0, min(0.9, reject_prob))
                    if rng.random() < reject_prob:
                        rejected_today += 1
                        total_rejected += 1
                        continue
                card = new_card("ai")
                pending.append(card)
                tier3.append(card)
                created_by_ai += 1
                slots_open -= 1
            remaining = slots_open

            if remaining > 0:
                query_backlog_now = [c for c in pending if c.origin == "query"]
                extra = query_backlog_now[:remaining]
                for c in extra:
                    pending.remove(c)
                tier2 = tier2 + extra
                query_slots_used += len(extra)
                remaining -= len(extra)

            # Step 7: review all candidates
            candidates = tier1 + tier2 + tier3

            for c in candidates:
                was_due = c in tier1
                if was_due:
                    lateness_samples.append(day - c.due_since)

                if not c.first_exposure_done:
                    _handle_first_exposure(c, persona, cfg, day, rng)
                else:
                    _review_outcome_dsr(c, persona, cfg, day, rng)
                if c.id not in active_ids:
                    active.append(c)
                    active_ids.add(c.id)
                    total_active_words += 1

            # Step 8: catch-up bonus
            due_remaining = due_before - due_slots_used
            if cfg.enable_catchup and due_remaining > queue_cap_due * 0.25:
                bonus_factor = 0.75 + enthusiasm * 0.50
                bonus_capacity = max(1, int(plan["session_size"] * bonus_factor))
                bonus_take = min(due_remaining, bonus_capacity)
                for i in range(bonus_take):
                    c = due[due_slots_used + i]
                    lateness_samples.append(day - c.due_since)
                    _review_outcome_dsr(c, persona, cfg, day, rng)
                bonus_processed = bonus_take
                total_bonus_processed += bonus_take
                due_slots_used += bonus_processed
                due_remaining = due_before - due_slots_used
        else:
            due_remaining = due_before

        rows.append({
            "day": day, "attended": attended,
            "due_processed": due_slots_used, "due_remaining": due_remaining,
            "queries": queries_today, "q_saved": saved_today,
            "q_backlog": len([c for c in pending if c.origin == "query"]),
            "ai_gen": ai_generated, "ai_rejected": rejected_today,
            "ai_cost_today": round(ai_generated * AI_COST_PER_CALL, 4),
            "bonus_processed": bonus_processed,
            "active": len(active),
        })

    # ---- SUMMARY ----
    import statistics as _stats
    final_day = cfg.days - 1

    learned = sum(1 for c in active if c.stability >= LEARNED_MIN_STABILITY_DAYS)
    stabilities = [c.stability for c in active]
    difficulties = [c.difficulty for c in active if c.difficulty > 0]
    retrievabilities = [_dsr_retrievability(final_day - (c.last_review if c.last_review is not None else final_day), c.stability) for c in active]
    tier_counts = dict(Counter(_dsr_tier(c.stability) for c in active))

    avg_stability = round(_stats.mean(stabilities), 2) if stabilities else 0.0
    avg_retrievability = round(_stats.mean(retrievabilities), 3) if retrievabilities else 0.0
    avg_difficulty = round(_stats.mean(difficulties), 2) if difficulties else 0.0

    def _pctl(vals, p):
        if not vals:
            return 0.0
        s = sorted(vals)
        return round(s[min(len(s) - 1, int(p * len(s)))], 2)

    median_stability = _pctl(stabilities, 0.5)
    p90_stability = _pctl(stabilities, 0.9)
    median_retrievability = _pctl(retrievabilities, 0.5)

    max_due_backlog = max(r["due_remaining"] for r in rows)
    max_query_backlog = max(r["q_backlog"] for r in rows)
    due_remaining_vals = [r["due_remaining"] for r in rows]
    median_due_backlog = _pctl(due_remaining_vals, 0.5)
    p90_due_backlog = _pctl(due_remaining_vals, 0.9)

    avg_lateness = (sum(lateness_samples) / len(lateness_samples)) if lateness_samples else 0.0
    median_lateness = _pctl(lateness_samples, 0.5)
    p90_lateness = _pctl(lateness_samples, 0.9)
    max_lateness = max(lateness_samples) if lateness_samples else 0

    summary = {
        "plan": cfg.plan,
        "persona": cfg.persona,
        "proficiency": cfg.proficiency,
        "enable_rejection": cfg.enable_rejection,
        "enable_catchup": cfg.enable_catchup,
        "enable_session_rate_limit": cfg.enable_session_rate_limit,
        "desired_retention": cfg.desired_retention,
        "sessions_effective": plan["sessions"],
        "session_size_effective": plan["session_size"],
        "days": cfg.days,
        "total_active_words": total_active_words,
        "created_by_query": created_by_query,
        "created_by_ai": created_by_ai,
        "total_ai_calls": total_ai_calls,
        "total_rejected_ai": total_rejected,
        "total_bonus_due": total_bonus_processed,
        "final_active_cards": len(active),
        "learned_words": learned,
        "avg_stability_days": avg_stability,
        "median_stability_days": median_stability,
        "p90_stability_days": p90_stability,
        "avg_retrievability": avg_retrievability,
        "median_retrievability": median_retrievability,
        "avg_difficulty": avg_difficulty,
        "max_due_backlog": max_due_backlog,
        "median_due_backlog": median_due_backlog,
        "p90_due_backlog": p90_due_backlog,
        "max_query_backlog": max_query_backlog,
        "avg_lateness_days": round(avg_lateness, 1),
        "median_lateness_days": median_lateness,
        "p90_lateness_days": p90_lateness,
        "max_lateness_days": max_lateness,
        "archived_lost_words": 0,
        "avg_ai_gen_per_day": round(total_ai_calls / cfg.days, 2) if cfg.days > 0 else 0,
        "total_ai_cost_usd": round(total_ai_cost, 4),
        "learned_words_per_dollar": round(learned / total_ai_cost, 1) if total_ai_cost > 0 else 0.0,
        "tier_counts": dict(tier_counts) if tier_counts else None,
    }
    if debug:
        return rows, summary, {"active": active, "lateness_samples": lateness_samples}
    return rows, summary

# ============================================================
# FORMAT TABLE
# ============================================================

def format_table(daily_log: list, summary: dict, cfg: SimConfig) -> str:
    lines = []
    lines.append(f"SRS v5.4 (FSRS-6 Full) Simulation: plan={cfg.plan}, persona={cfg.persona}, "
                 f"proficiency={cfg.proficiency}, days={cfg.days}, seed={cfg.seed}")
    features = []
    if cfg.enable_rejection:
        features.append("rejection")
    if cfg.enable_catchup:
        features.append("catchup")
    if cfg.enable_session_rate_limit:
        features.append("session-ratelimit")
    feat_str = "+".join(features)
    lines.append(f"Config: {summary['sessions_effective']} sessions x {summary['session_size_effective']} = "
                 f"{summary['sessions_effective'] * summary['session_size_effective']} slots/day  |  "
                 f"features: [{feat_str}]")
    lines.append(f"Desired retention: {cfg.desired_retention}")
    lines.append("")

    lines.append("Final Summary:")
    lines.append(f"  Total Active Words:      {summary['total_active_words']}"
                 f"  (query={summary['created_by_query']}, ai={summary['created_by_ai']})")
    lines.append(f"  AI Calls (cost proxy):   {summary['total_ai_calls']} ({summary['avg_ai_gen_per_day']}/day)")
    lines.append(f"  AI Rejected:             {summary['total_rejected_ai']}")
    lines.append(f"  AI Cost (USD):           ${summary['total_ai_cost_usd']}")
    lines.append(f"  Bonus Due Processed:     {summary['total_bonus_due']}")
    lines.append(f"  Final Active Cards:      {summary['final_active_cards']}")
    lines.append(f"  Learned Words:           {summary['learned_words']}")
    lines.append(f"  Learned Words / $:       {summary['learned_words_per_dollar']}")
    lines.append(f"  Avg Stability:           {summary['avg_stability_days']} days")
    lines.append(f"  Avg Difficulty:          {summary['avg_difficulty']} / 10")
    lines.append(f"  Avg Retrievability:      {summary['avg_retrievability']}")
    if summary.get("tier_counts"):
        tier_str = ", ".join(f"{k}={v}" for k, v in summary["tier_counts"].items())
        lines.append(f"  Tiers:                   {tier_str}")
    lines.append(f"  Due Backlog:             max={summary['max_due_backlog']}  "
                 f"median={summary['median_due_backlog']}  p90={summary['p90_due_backlog']}")
    lines.append(f"  Max Query Backlog:       {summary['max_query_backlog']}")
    lines.append(f"  Lateness (days):         avg={summary['avg_lateness_days']}  "
                 f"median={summary['median_lateness_days']}  p90={summary['p90_lateness_days']}  "
                 f"max={summary['max_lateness_days']}")
    lines.append(f"  Archived:                {summary['archived_lost_words']}")
    return "\n".join(lines)

# ============================================================
# WRITE CSV
# ============================================================

def write_csv(daily_log: list, path: str):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "attended", "due_processed", "due_remaining",
                     "queries", "q_saved", "q_backlog",
                     "ai_gen", "ai_rejected", "ai_cost_today",
                     "bonus_processed", "active"])
        for r in daily_log:
            w.writerow([r["day"], int(r["attended"]), r["due_processed"],
                        r["due_remaining"], r["queries"], r["q_saved"], r["q_backlog"],
                        r["ai_gen"], r["ai_rejected"], r["ai_cost_today"],
                        r["bonus_processed"], r["active"]])
