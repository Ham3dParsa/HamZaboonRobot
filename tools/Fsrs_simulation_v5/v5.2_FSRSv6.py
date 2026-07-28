"""SRS v5 DSRL-fixed Session Simulation — FSRS-6 inspired DSR model
with first-exposure grading, unified pipeline, cost-aware AI.

Three mastery models (set via SimConfig.mastery_model):
  "dsr"    — FSRS-6 DSR with 12 params, first-exposure grading (default)
  "lite"   — Simplified DSR-lite from v5 (kept for benchmark)
  "legacy" — Binary success/fail from v3 (kept for comparison)

Key differences from v5_dsr.py (lite) and v5_dsr_2.py (full FSRS-6):
  - Adds first-exposure grading: user sees 3 buttons on NEW cards
    and their grade determines initial stability/difficulty via FSRS-6 S0/D0
  - Uses core FSRS-6 formulas (w0-w15) without overkill (no w3, w16-w20)
  - Mean reversion to D0(3)=Good instead of D0(4)=Easy (3-button adaptation)
  - unified summary fields across all three models
"""

import math
import random
from collections import Counter
from dataclasses import dataclass
from typing import Optional, Literal

# ============ SRS Intervals ============
INTERVALS = [1, 3, 7, 15, 30, 60, 120, 240, 480, 960]

# ============ Plan Defaults ============
PLAN_DEFAULTS = {
    "free":     {"sessions": 1, "session_size": 4,  "ai_daily_cap": 3,  "query_daily_cap": 3,  "queue_cap_days": 2},
    "silver":   {"sessions": 3, "session_size": 5,  "ai_daily_cap": 5,  "query_daily_cap": 7,  "queue_cap_days": 3},
    "gold":     {"sessions": 4, "session_size": 7,  "ai_daily_cap": 12, "query_daily_cap": 10, "queue_cap_days": 4},
    "platinum": {"sessions": 5, "session_size": 10, "ai_daily_cap": 20, "query_daily_cap": 16, "queue_cap_days": 6},
}

# ============ User Personas ============
PERSONAS = {
    "lazy":        {"attend": 0.35, "q_lo": 0, "q_hi": 1, "save_prob": 0.30, "forget": 0.35},
    "average":     {"attend": 0.70, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
    "eager":       {"attend": 0.92, "q_lo": 2, "q_hi": 6, "save_prob": 0.70, "forget": 0.10},
    "fluctuating": {"attend": None, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
}

# ============ Proficiency Levels ============
PROFICIENCY = {
    "beginner":     {"known_vocab": 500,  "target_pool": 2000, "ai_efficiency": 0.70, "reject_noise": 0.10},
    "intermediate": {"known_vocab": 2000, "target_pool": 4000, "ai_efficiency": 0.65, "reject_noise": 0.15},
    "advanced":     {"known_vocab": 4000, "target_pool": 7000, "ai_efficiency": 0.60, "reject_noise": 0.20},
}

# ============ AI Cost ============
AI_COST_PER_CALL = 0.0006

# ============ FSRS-6 DSR Parameters (3-button, no Easy) ============
DSR_W = {
    "w0": 0.212,      # S0(Again)
    "w1": 1.2931,     # S0(Hard)
    "w2": 2.3065,     # S0(Good)
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
}

DSR_FACTOR = 19.0 / 81.0
DSR_DECAY = -0.5
DESIRED_RETENTION_DEFAULT = 0.85

# Learned and tier thresholds (DSR model)
LEARNED_MIN_STABILITY_DAYS = 21.0
DSR_TIER_THRESHOLDS = [
    ("در حال یادگیری", 0.0),
    ("آشنا", 7.0),
    ("یادگرفته‌شده", 21.0),
    ("تثبیت‌شده", 60.0),
]

# Lite model constants (carried from v5_dsr.py)
STABILITY_INITIAL = 1.0
STABILITY_MIN = 0.5
DIFFICULTY_DEFAULT = 5.0
DIFFICULTY_MIN = 1.0
DIFFICULTY_MAX = 10.0
DIFFICULTY_DELTA_FORGET = 1.2
DIFFICULTY_DELTA_HOLD = 0.3
DIFFICULTY_DELTA_ADVANCE = -0.2
DIFFICULTY_MEAN_REVERSION = 0.05
GROWTH_BASE_HOLD = 1.15
GROWTH_SENSITIVITY_HOLD = 0.8
GROWTH_BASE_ADVANCE = 1.5
GROWTH_SENSITIVITY_ADVANCE = 2.0
LAPSE_STABILITY_BASE = 0.15
LAPSE_STABILITY_DIFF_SPAN = 0.35
LEARNED_MIN_STABILITY_DAYS_LITE = 30
LEARNED_MIN_REVIEWS = 4

# Performance draw (shared across models)
PERFORMANCE_NOISE = 0.15
PERFORMANCE_RETRIEVABILITY_WEIGHT = 0.5
PERFORMANCE_SUCCESS_THRESHOLD = 0.75
PERFORMANCE_PARTIAL_THRESHOLD = 0.40

# Query-first priority thresholds
QUERY_BACKLOG_SOFT_CAP_MULT = 1.0
QUERY_BACKLOG_HARD_CAP_MULT = 2.0
QUERY_INFLOW_MAX_REDUCTION = 0.80

# Premium override band
PLAN_OVERRIDE_BAND = 0.30

MasteryModel = Literal["legacy", "lite", "dsr"]
Origin = Literal["query", "ai"]

# ============================================================
# DSR HELPER FUNCTIONS
# ============================================================

def _dsr_retrievability(elapsed_days: float, stability: float) -> float:
    stability = max(0.1, stability)
    t = max(0.0, elapsed_days)
    return (1.0 + DSR_FACTOR * t / stability) ** DSR_DECAY

def _dsr_interval_days(stability: float, desired_retention: float = DESIRED_RETENTION_DEFAULT) -> float:
    stability = max(0.1, stability)
    inv = desired_retention ** (1.0 / DSR_DECAY) - 1.0
    return stability * inv / DSR_FACTOR

def _dsr_s0(grade: int) -> float:
    return {1: DSR_W["w0"], 2: DSR_W["w1"], 3: DSR_W["w2"]}[grade]

def _dsr_d0(grade: int) -> float:
    d0 = DSR_W["w4"] - math.exp(DSR_W["w5"] * (grade - 1)) + 1.0
    return max(1.0, min(10.0, d0))

def _dsr_update_difficulty(d: float, grade: int) -> float:
    delta_d = -DSR_W["w6"] * (grade - 3)
    d_damped = d + delta_d * (10.0 - d) / 9.0
    d0_good = _dsr_d0(3)
    d_reverted = DSR_W["w7"] * d0_good + (1.0 - DSR_W["w7"]) * d_damped
    return max(1.0, min(10.0, d_reverted))

def _dsr_update_stability(d: float, s: float, r: float, grade: int) -> float:
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
    s_inc = (
        1.0
        + math.exp(DSR_W["w8"])
        * (11.0 - d)
        * (s ** -DSR_W["w9"])
        * (math.exp(DSR_W["w10"] * (1.0 - r)) - 1.0)
        * hard_penalty
    )
    return s * max(1.0, s_inc)

def _dsr_tier(stability: float) -> str:
    tier = DSR_TIER_THRESHOLDS[0][0]
    for name, floor in DSR_TIER_THRESHOLDS:
        if stability >= floor:
            tier = name
    return tier

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

    idx: int = -1
    score: float = 2.0
    streak: int = 0
    next_review: Optional[int] = None
    due_since: Optional[int] = None
    ease: float = 1.0
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
    enable_continuous_mastery: bool = True

    mastery_model: MasteryModel = "dsr"
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
    if persona == "fluctuating":
        phase = (2 * math.pi * day) / 21.0
        prob = 0.60 + 0.30 * math.sin(phase)
        return rng.random() < prob
    return rng.random() < p["attend"]

# ============================================================
# REVIEW OUTCOME — LEGACY (binary)
# ============================================================

def _review_outcome_legacy(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    if rng.random() < persona["forget"]:
        card.stability = STABILITY_MIN
        card.next_review = day + 1
        card.last_review = day
        card.reviews += 1
        return "forget"
    card.stability *= 2.0
    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
    card.next_review = day + max(1, round(card.stability * jitter))
    card.last_review = day
    card.reviews += 1
    return "advance"

# ============================================================
# REVIEW OUTCOME — LITE (DSR-lite from v5)
# ============================================================

def _review_outcome_lite(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    elapsed = day - (card.last_review if card.last_review is not None else day)
    r = (1.0 + DSR_FACTOR * max(0.0, elapsed) / max(0.1, card.stability)) ** DSR_DECAY

    if not cfg.enable_continuous_mastery:
        if rng.random() < persona["forget"]:
            card.stability = STABILITY_MIN
            card.next_review = day + 1
            card.last_review = day
            card.reviews += 1
            return "forget"
        card.stability *= 2.0
        jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
        card.next_review = day + max(1, round(card.stability * jitter))
        card.last_review = day
        card.reviews += 1
        return "advance"

    base_success = 1.0 - persona["forget"]
    noise = rng.uniform(-PERFORMANCE_NOISE, PERFORMANCE_NOISE)
    performance = max(0.0, min(1.0,
        (1 - PERFORMANCE_RETRIEVABILITY_WEIGHT) * base_success
        + PERFORMANCE_RETRIEVABILITY_WEIGHT * r
        + noise))
    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
    D = card.difficulty

    def mean_revert(d):
        d = max(DIFFICULTY_MIN, min(DIFFICULTY_MAX, d))
        return d + (DIFFICULTY_DEFAULT - d) * DIFFICULTY_MEAN_REVERSION

    card.reviews += 1
    card.last_review = day
    card.due_since = None

    if performance >= PERFORMANCE_SUCCESS_THRESHOLD:
        growth = GROWTH_BASE_ADVANCE + GROWTH_SENSITIVITY_ADVANCE * (1 - r) * (10 - D) / 9
        card.stability *= growth
        card.difficulty = mean_revert(D + DIFFICULTY_DELTA_ADVANCE)
        card.next_review = day + max(1, round(card.stability * jitter))
        return "advance"
    elif performance >= PERFORMANCE_PARTIAL_THRESHOLD:
        growth = GROWTH_BASE_HOLD + GROWTH_SENSITIVITY_HOLD * (1 - r) * (10 - D) / 9
        card.stability *= growth
        card.difficulty = mean_revert(D + DIFFICULTY_DELTA_HOLD)
        card.next_review = day + max(1, round(card.stability * jitter))
        return "hold"
    lapse_factor = LAPSE_STABILITY_BASE + LAPSE_STABILITY_DIFF_SPAN * (1 - D / 10)
    card.stability = max(STABILITY_MIN, card.stability * lapse_factor)
    card.difficulty = mean_revert(D + DIFFICULTY_DELTA_FORGET)
    card.next_review = day + 1
    return "forget"

# ============================================================
# FIRST EXPOSURE — shared across all models
# ============================================================

def _handle_first_exposure(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    base_success = 1.0 - persona["forget"]
    r_at_first = 1.0
    noise = rng.uniform(-PERFORMANCE_NOISE, PERFORMANCE_NOISE)
    performance = max(0.0, min(1.0,
        (1 - PERFORMANCE_RETRIEVABILITY_WEIGHT) * base_success
        + PERFORMANCE_RETRIEVABILITY_WEIGHT * r_at_first
        + noise))

    if performance >= PERFORMANCE_SUCCESS_THRESHOLD:
        grade = 3
    elif performance >= PERFORMANCE_PARTIAL_THRESHOLD:
        grade = 2
    else:
        grade = 1

    if cfg.mastery_model == "dsr":
        card.stability = _dsr_s0(grade)
        card.difficulty = _dsr_d0(grade)
        interval = _dsr_interval_days(card.stability, cfg.desired_retention)
    else:
        card.stability = STABILITY_INITIAL
        card.difficulty = DIFFICULTY_DEFAULT
        interval = 1.0

    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
    card.next_review = day + max(1, round(interval * jitter))
    card.last_review = day
    card.reviews += 1
    card.first_exposure_done = True

    return {1: "forget", 2: "hold", 3: "advance"}[grade]

# ============================================================
# REVIEW OUTCOME — DSR (FSRS-6, subsequent reviews only)
# ============================================================

def _review_outcome_dsr(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    elapsed = day - (card.last_review if card.last_review is not None else day)
    r = _dsr_retrievability(elapsed, card.stability)

    base_success = 1.0 - persona["forget"]
    noise = rng.uniform(-PERFORMANCE_NOISE, PERFORMANCE_NOISE)
    performance = max(0.0, min(1.0,
        (1 - PERFORMANCE_RETRIEVABILITY_WEIGHT) * base_success
        + PERFORMANCE_RETRIEVABILITY_WEIGHT * r
        + noise))

    if performance >= PERFORMANCE_SUCCESS_THRESHOLD:
        grade = 3
    elif performance >= PERFORMANCE_PARTIAL_THRESHOLD:
        grade = 2
    else:
        grade = 1

    card.difficulty = _dsr_update_difficulty(card.difficulty, grade)
    card.stability = _dsr_update_stability(card.difficulty, card.stability, r, grade)
    card.last_review = day
    card.reviews += 1
    card.due_since = None

    interval = _dsr_interval_days(card.stability, cfg.desired_retention)
    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
    card.next_review = day + max(1, round(interval * jitter))

    return {1: "forget", 2: "hold", 3: "advance"}[grade]

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
            user_avg_difficulty = (sum(c.difficulty for c in active) / len(active)) if active else DIFFICULTY_DEFAULT
            candidates = tier1 + tier2 + tier3

            for c in candidates:
                was_due = c in tier1
                if was_due:
                    lateness_samples.append(day - c.due_since)

                if not c.first_exposure_done:
                    _handle_first_exposure(c, persona, cfg, day, rng)
                    if c.id not in active_ids:
                        active.append(c)
                        active_ids.add(c.id)
                        total_active_words += 1
                    if cfg.mastery_model != "dsr":
                        c.difficulty = user_avg_difficulty
                else:
                    if cfg.mastery_model == "dsr":
                        _review_outcome_dsr(c, persona, cfg, day, rng)
                    elif cfg.mastery_model == "lite":
                        _review_outcome_lite(c, persona, cfg, day, rng)
                    else:
                        _review_outcome_legacy(c, persona, cfg, day, rng)
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
                    if cfg.mastery_model == "dsr":
                        _review_outcome_dsr(c, persona, cfg, day, rng)
                    elif cfg.mastery_model == "lite":
                        _review_outcome_lite(c, persona, cfg, day, rng)
                    else:
                        _review_outcome_legacy(c, persona, cfg, day, rng)
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

    if cfg.mastery_model == "dsr":
        learned = sum(1 for c in active if c.stability >= LEARNED_MIN_STABILITY_DAYS)
        stabilities = [c.stability for c in active]
        difficulties = [c.difficulty for c in active if c.difficulty > 0]
        retrievabilities = [_dsr_retrievability(final_day - (c.last_review if c.last_review is not None else final_day), c.stability) for c in active]
        tier_counts = dict(Counter(_dsr_tier(c.stability) for c in active))
    else:
        if cfg.mastery_model == "lite":
            lrn_thresh = LEARNED_MIN_STABILITY_DAYS_LITE
        else:
            lrn_thresh = LEARNED_MIN_STABILITY_DAYS_LITE
        learned = sum(1 for c in active if c.stability >= lrn_thresh or c.reviews >= LEARNED_MIN_REVIEWS)
        stabilities = [c.stability for c in active]
        difficulties = [c.difficulty for c in active if c.difficulty > 0]
        retrievabilities = [max(0, min(1, 1.0 - (final_day - (c.last_review or final_day)) / max(c.stability, 1))) for c in active]
        tier_counts = None

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
        "mastery_model": cfg.mastery_model,
        "desired_retention": cfg.desired_retention if cfg.mastery_model == "dsr" else None,
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
    lines.append(f"SRS v5 (DSR-fixed) Simulation: plan={cfg.plan}, persona={cfg.persona}, "
                 f"proficiency={cfg.proficiency}, days={cfg.days}, seed={cfg.seed}")
    features = []
    if cfg.enable_rejection:
        features.append("rejection")
    if cfg.enable_catchup:
        features.append("catchup")
    if cfg.mastery_model == "dsr":
        features.append("DSR-fixed")
    elif cfg.mastery_model == "lite":
        features.append("Lite")
    else:
        features.append("Legacy")
    if cfg.enable_session_rate_limit:
        features.append("session-ratelimit")
    feat_str = "+".join(features)
    lines.append(f"Config: {summary['sessions_effective']} sessions x {summary['session_size_effective']} = "
                 f"{summary['sessions_effective'] * summary['session_size_effective']} slots/day  |  "
                 f"features: [{feat_str}]")
    if cfg.desired_retention and cfg.mastery_model == "dsr":
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
    if summary["mastery_model"] == "dsr":
        lines.append(f"  Avg Stability:           {summary['avg_stability_days']} days")
        lines.append(f"  Avg Difficulty:          {summary['avg_difficulty']} / 10")
        lines.append(f"  Avg Retrievability:      {summary['avg_retrievability']}")
        if summary.get("tier_counts"):
            tier_str = ", ".join(f"{k}={v}" for k, v in summary["tier_counts"].items())
            lines.append(f"  Tiers:                   {tier_str}")
    else:
        lines.append(f"  Avg Stability:           {summary['avg_stability_days']} days")
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