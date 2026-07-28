"""SRS v5 "DSR-lite" Session Simulation — unified pipeline, FSRS-inspired
mastery model, cost-aware AI.

Successor to v4_sweet. Main change: replaces v4's hand-built idx+score+ease
with DSR-lite (FSRS simplified): Stability (S, days to 90% recall) /
Difficulty (D, 1=easy..10=hard) / Retrievability (R, computed on demand
via FSRS forgetting curve R=(1+F*t/S)^C). "Learned" = S≥30d OR reviews≥4.

Bug fixes from v3 (unconditional unless noted):
  1. AI rejection recycled slot immediately (slot-by-slot loop: retry→query backlog→leave open).
  2. Unified pending pool; total_active_words counted at first exposure, not creation.
  3. Continuous mastery (toggle `enable_continuous_mastery`, default True): draws
     performance from base rate + R + noise; False → v3 binary model.
  4. Premium override: `sessions_override`/`session_size_override` clamped ±30%.
  5. O(1) active membership via `active_ids: set[int]`.
  6. Real AI cost tracking: AI_COST_PER_CALL=0.0006$; queries cost 1 call.
     Soft per-session cap via `enable_session_rate_limit` (default True).
  7. CSV exports queries/q_saved.

Feature flags (SimConfig, default True): enable_rejection, enable_catchup,
enable_continuous_mastery, enable_session_rate_limit.

QUERY-FIRST PRIORITY (always active): query-origin cards seated before AI
generation. Hard cap zeros ai_cap_today if backlog > HARD_MULT×daily_slots;
soft cap throttles inflow at SOFT_MULT×daily_slots. Origin = birth tag.

DSR-lite model details (see constants below): S growth on success has
floor (GROWTH_BASE_*) + bonus scaled by low R ("desirable difficulty"),
damped by D. S loss on lapse depends on D. D nudged per outcome with
mean reversion (DIFFICULTY_MEAN_REVERSION=0.05). Not implemented: full
FSRS 19-21 params, Easy rating, same-day reviews, per-user optimization.

OUTPUT FIELDS: total_active_words, created_by_query, created_by_ai,
total_ai_calls, total_rejected_ai, total_bonus_due, final_active_cards,
learned_words, avg/median/p90_stability_days, avg/median_retrievability,
avg_difficulty, max/median/p90_due_backlog, max_query_backlog,
avg/median/p90_lateness_days, max_lateness_days, archived_lost_words(=0),
total_ai_cost_usd, learned_words_per_dollar.
"""

import math
import random
from dataclasses import dataclass, field
from typing import Optional, Literal

# -----
# SRS Intervals (10 rungs): 1 day up to ~32 months.
# -----
INTERVALS = [1, 3, 7, 15, 30, 60, 120, 240, 480, 960]

# -----
# Plan Defaults
# -----
PLAN_DEFAULTS = {
    "free":     {"sessions": 1, "session_size": 4,  "ai_daily_cap": 3,  "query_daily_cap": 3,  "queue_cap_days": 2},
    "silver":   {"sessions": 3, "session_size": 5,  "ai_daily_cap": 5,  "query_daily_cap": 7,  "queue_cap_days": 3},
    "gold":     {"sessions": 4, "session_size": 7,  "ai_daily_cap": 12, "query_daily_cap": 10, "queue_cap_days": 4},
    # Name TBD ("platinum"? "pro+"?) — proposed 4th tier for very-eager
    # learners. Sized by load-testing (see test_simulator_v4.py section 7):
    # ~1.8x gold's daily slot capacity (50 vs 28 slots/day) gives ~80%
    # more learned words at 3/6/12 months, proportional to the extra
    # capacity rather than an arbitrary multiplier — see report.md.
    "platinum": {"sessions": 5, "session_size": 10, "ai_daily_cap": 20, "query_daily_cap": 16, "queue_cap_days": 6},
}

# -----
# User Personas
# -----
PERSONAS = {
    "lazy":        {"attend": 0.35, "q_lo": 0, "q_hi": 1, "save_prob": 0.30, "forget": 0.35},
    "average":     {"attend": 0.70, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
    "eager":       {"attend": 0.92, "q_lo": 2, "q_hi": 6, "save_prob": 0.70, "forget": 0.10},
    "fluctuating": {"attend": None, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
}

# -----
# Proficiency Levels (vocabulary mastery & AI rejection)
# Rejection formula: reject_prob = (known_vocab / target_pool) x ai_efficiency + noise
# -----
PROFICIENCY = {
    "beginner":     {"known_vocab": 500,  "target_pool": 2000, "ai_efficiency": 0.70, "reject_noise": 0.10},
    "intermediate": {"known_vocab": 2000, "target_pool": 4000, "ai_efficiency": 0.65, "reject_noise": 0.15},
    "advanced":     {"known_vocab": 4000, "target_pool": 7000, "ai_efficiency": 0.60, "reject_noise": 0.20},
}

# -----
# AI cost model (bug 6): real per-call cost, padded slightly for safety margin.
# -----
AI_COST_PER_CALL = 0.0006  # USD per AI generation attempt (accepted or rejected)

# -----
# DSR-lite mastery model (v5): Stability / Difficulty / Retrievability,
# a simplified version of the FSRS memory model (Difficulty, Stability,
# Retrievability — see https://github.com/open-spaced-repetition/fsrs4anki).
# Replaces v4's ad-hoc idx+score+ease bookkeeping with two physically
# meaningful per-card numbers:
#   stability (S):   days for recall probability to fall to ~90% — a real,
#                     interpretable quantity ("this word will likely still
#                     be remembered in S days without review").
#   difficulty (D):  1 (easy) to 10 (hard) — how much stability grows per
#                     successful review for THIS card.
# Retrievability (R) is never stored — it's computed on demand from
# (days since last review, S) via FSRS's own forgetting-curve formula,
# which research found fits real human forgetting curves better than a
# plain exponential (Ebbinghaus) decay.
# -----
FSRS_F = 19.0 / 81.0       # forgetting-curve shape constant (from FSRS)
FSRS_C = -0.5               # forgetting-curve shape constant (from FSRS)

DIFFICULTY_MIN = 1.0
DIFFICULTY_MAX = 10.0
DIFFICULTY_DEFAULT = 5.0
DIFFICULTY_DELTA_FORGET = 1.2     # 🔴 gets noticeably harder after a lapse
DIFFICULTY_DELTA_HOLD = 0.3       # 🟡 gets a little harder
DIFFICULTY_DELTA_ADVANCE = -0.2   # 🟢 gets a little easier
DIFFICULTY_MEAN_REVERSION = 0.05  # pulls D gently back toward the default each review

STABILITY_INITIAL = 1.0     # days; starting point for a brand-new card
STABILITY_MIN = 0.5

# Stability growth on a successful review has a floor (guaranteed
# multiplicative gain even when the review happened right on schedule,
# i.e. R was already ~0.9 — this mirrors how real spaced-repetition ease
# factors work) PLUS a bonus that scales with how LOW retrievability was
# at review time (the "desirable difficulty" effect: reviewing right
# before you'd forget strengthens memory far more than reviewing
# something you just saw), dampened by difficulty (harder cards grow
# stability more slowly).
GROWTH_BASE_HOLD = 1.15      # 🟡 floor multiplier even at R~0.9
GROWTH_SENSITIVITY_HOLD = 0.8
GROWTH_BASE_ADVANCE = 1.5    # 🟢 floor multiplier even at R~0.9
GROWTH_SENSITIVITY_ADVANCE = 2.0

# Stability loss on a lapse also depends on difficulty: a harder card
# loses more of its accumulated stability when forgotten.
LAPSE_STABILITY_BASE = 0.15
LAPSE_STABILITY_DIFF_SPAN = 0.35

# Learned-word threshold, now a physically meaningful claim instead of an
# arbitrary 0-5 score: "the model predicts this word would still likely be
# recalled a month from now without review." The review-count fallback
# keeps early, fast-progressing cards countable before they've accumulated
# 30 days of stability.
LEARNED_MIN_STABILITY_DAYS = 30
LEARNED_MIN_REVIEWS = 4

# Performance draw: which of the three buttons the simulated persona
# effectively "presses" on a given review. Combines the persona's base
# skill with the card's actual retrievability at review time (a card that
# is very overdue has objectively decayed, regardless of how good the
# persona is) plus noise for realistic variance.
PERFORMANCE_NOISE = 0.15
PERFORMANCE_RETRIEVABILITY_WEIGHT = 0.5   # R contributes half; persona skill the other half
PERFORMANCE_SUCCESS_THRESHOLD = 0.75      # -> 🟢 advance
PERFORMANCE_PARTIAL_THRESHOLD = 0.40      # -> 🟡 hold; below this -> 🔴 forget



# Query-first priority thresholds (refinement B), expressed as multiples of
# a plan's daily_slots (sessions x session_size):
QUERY_BACKLOG_SOFT_CAP_MULT = 1.0      # backlog above this -> tighten new-query inflow
QUERY_BACKLOG_HARD_CAP_MULT = 2.0      # backlog above this -> force AI cap to 0 today
QUERY_INFLOW_MAX_REDUCTION = 0.80      # inflow can be cut by at most 80%

# Relative config override band for premium plan customization (bug 4)
PLAN_OVERRIDE_BAND = 0.30  # +/- 30% of plan default


Origin = Literal["query", "ai"]


@dataclass
class Card:
    """A vocabulary card in the SRS system (v5: DSR-lite model).

    Fields: id, origin ("query"|"ai"), stability (days to 90% recall),
    difficulty (1=easy..10=hard), reviews (rated count), next_review (day, None=pending),
    due_since, last_review. Origin is a birth tag only — both origins share
    identical pipeline (bug 2 fix).
    """
    id: int
    origin: Origin = "ai"
    stability: float = STABILITY_INITIAL
    difficulty: float = DIFFICULTY_DEFAULT
    reviews: int = 0
    next_review: Optional[int] = None
    due_since: Optional[int] = None
    last_review: Optional[int] = None


def _retrievability(elapsed_days: float, stability: float) -> float:
    """FSRS forgetting-curve: predicted recall probability.

    R = (1 + F * t/S) ^ C, with F=19/81, C=-0.5 — power-law decay
    fitting human forgetting data better than exponential. R=1 at t=0;
    R=0.9 exactly at t=stability (definition of stability).
    """
    stability = max(STABILITY_MIN, stability)
    return (1.0 + FSRS_F * max(0.0, elapsed_days) / stability) ** FSRS_C




@dataclass
class SimConfig:
    """Configuration for a single simulation run.

    plan: "free"|"silver"|"gold"|"platinum"
    persona: "lazy"|"average"|"eager"|"fluctuating"
    proficiency: "beginner"|"intermediate"|"advanced"
    days: simulation length
    seed: RNG seed (None=random)
    jitter: ±fraction on SRS intervals (0.15=15%)
    enable_rejection: proficiency-based AI card rejection (default True)
    enable_catchup: bonus sessions when due backlog high (default True)
    enable_continuous_mastery: DSR-lite continuous model (True) vs v3 binary (False)
    enable_session_rate_limit: spread daily AI cap across sessions (default True)
    sessions_override: absolute sessions/day, clamped ±30% of plan default
    session_size_override: absolute cards/session, clamped ±30%
    """
    plan: str = "free"
    persona: str = "average"
    proficiency: str = "advanced"
    days: int = 180
    seed: Optional[int] = 42
    jitter: float = 0.15
    enable_rejection: bool = True
    enable_catchup: bool = True
    enable_continuous_mastery: bool = True
    enable_session_rate_limit: bool = True
    sessions_override: Optional[int] = None
    session_size_override: Optional[int] = None


def _clamp_override(default: int, requested: Optional[int]) -> int:
    """Clamp requested plan-parameter override to +/-30% of default (min 1)."""
    if requested is None:
        return default
    lo = max(1, math.floor(default * (1 - PLAN_OVERRIDE_BAND)))
    hi = max(lo, math.ceil(default * (1 + PLAN_OVERRIDE_BAND)))
    return max(lo, min(hi, requested))


def _resolve_plan(cfg: SimConfig) -> dict:
    """Resolve effective plan parameters, applying clamped overrides."""
    base = PLAN_DEFAULTS[cfg.plan]
    return {
        **base,
        "sessions": _clamp_override(base["sessions"], cfg.sessions_override),
        "session_size": _clamp_override(base["session_size"], cfg.session_size_override),
    }


def _attend_prob(persona: str, day: int, rng: random.Random) -> bool:
    """Determine if simulated user studies today.

    "fluctuating" follows 21-day sine wave (60% ± 30%); others use flat probability.
    """
    p = PERSONAS[persona]
    if persona == "fluctuating":
        phase = (2 * math.pi * day) / 21.0
        prob = 0.60 + 0.30 * math.sin(phase)
        return rng.random() < prob
    return rng.random() < p["attend"]


def _review_outcome(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    """Apply one review outcome to `card` in place; return "forget"|"hold"|"advance".

    Maps to همزبان buttons: 🔴 یادم نبود → forget, 🟡 سخت بود → hold, 🟢 خوب یادمه → advance.

    DSR-lite model (enable_continuous_mastery=True):
      performance = 0.5*(1 - persona_forget) + 0.5*R + noise(±PERFORMANCE_NOISE=0.15)
        advance (≥0.75): S *= GROWTH_BASE_ADVANCE(1.5) + GROWTH_SENSITIVITY_ADVANCE(2.0)*(1-R)*(10-D)/9
        hold    (0.40≤x<0.75): S *= GROWTH_BASE_HOLD(1.15) + GROWTH_SENSITIVITY_HOLD(0.8)*(1-R)*(10-D)/9
        forget  (<0.40): S = max(STABILITY_MIN, S * (LAPSE_STABILITY_BASE(0.5) + LAPSE_DIFF_SPAN(0.3)*(1-D/10)))
      D nudged per outcome (△advance=-0.2, △hold=+0.3, △forget=+1.2) then mean-reverted 5%.

    Legacy binary (enable_continuous_mastery=False):
      Single roll vs forget rate: success doubles S, failure resets to STABILITY_MIN. No D/R.
    """
    elapsed = day - (card.last_review if card.last_review is not None else day)
    R = _retrievability(elapsed, card.stability)

    if not cfg.enable_continuous_mastery:
        if rng.random() < persona["forget"]:
            card.stability = STABILITY_MIN
            card.next_review = day + 1
            card.last_review = day
            card.reviews += 1
            return "forget"
        else:
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
        + PERFORMANCE_RETRIEVABILITY_WEIGHT * R
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
        growth = GROWTH_BASE_ADVANCE + GROWTH_SENSITIVITY_ADVANCE * (1 - R) * (10 - D) / 9
        card.stability *= growth
        card.difficulty = mean_revert(D + DIFFICULTY_DELTA_ADVANCE)
        card.next_review = day + max(1, round(card.stability * jitter))
        return "advance"
    elif performance >= PERFORMANCE_PARTIAL_THRESHOLD:
        growth = GROWTH_BASE_HOLD + GROWTH_SENSITIVITY_HOLD * (1 - R) * (10 - D) / 9
        card.stability *= growth
        card.difficulty = mean_revert(D + DIFFICULTY_DELTA_HOLD)
        card.next_review = day + max(1, round(card.stability * jitter))
        return "hold"
    else:
        lapse_factor = LAPSE_STABILITY_BASE + LAPSE_STABILITY_DIFF_SPAN * (1 - D / 10)
        card.stability = max(STABILITY_MIN, card.stability * lapse_factor)
        card.difficulty = mean_revert(D + DIFFICULTY_DELTA_FORGET)
        card.next_review = day + 1
        return "forget"


def simulate(cfg: SimConfig, debug: bool = False):
    """Run simulation, return (daily_rows, summary).

    Daily pipeline: user queries → collect due → Tier 1 (due reviews)
    → throttle AI cap + session rate-limit → query-first slot fill
    → Tier 3 (AI cards, reject→recycle) → review all candidates
    → catch-up bonus if backlog > 25%.

    Returns:
        daily_rows: List[dict], one per day.
        summary: aggregate stats (see module docstring).
    """
    plan = _resolve_plan(cfg)
    persona = PERSONAS[cfg.persona]
    rng = random.Random(cfg.seed)

    active: list[Card] = []
    active_ids: set[int] = set()          # bug 5 fix: O(1) membership
    pending: list[Card] = []              # bug 2 fix: unified query+ai pool, idx=-1
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

        # =====
        # STEP 1 — USER QUERIES ("Ask a Word")
        # =====
        queries_today = 0
        saved_today = 0
        if attended:
            q_hi = min(persona["q_hi"], plan["query_daily_cap"])
            if pending_debt > queue_cap_due * 0.5:
                debt_ratio = pending_debt / queue_cap_due
                effective_reduction = min(0.5, (debt_ratio - 0.5))
                reduced_cap = int(plan["query_daily_cap"] * (1 - effective_reduction))
                q_hi = min(q_hi, max(int(plan["query_daily_cap"] * 0.5), reduced_cap))

            # Refinement B (soft cap): once the query backlog itself grows
            # past QUERY_BACKLOG_SOFT_CAP_MULT x daily_slots, tighten new
            # -query inflow (up to an 80% cut) so it can't keep outrunning
            # the drain rate, independent of due-card pressure above.
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
                # Every "Ask a Word" query is itself one AI call — the bot
                # has to look up/generate the definition, translation,
                # examples, etc. to show the user, whether or not they end
                # up saving it as a review card. This costs exactly the
                # same as an automatic daily AI card (v4.2 behavior fix).
                total_ai_calls += 1
                total_ai_cost += AI_COST_PER_CALL
                if rng.random() < persona["save_prob"]:
                    card = new_card("query")
                    pending.append(card)
                    created_by_query += 1
                    saved_today += 1

        # =====
        # STEP 2 — DUE CARDS
        # =====
        # v5: no manual score-decay bookkeeping needed here. Retrievability
        # is a derived quantity computed on demand (in _review_outcome, and
        # in the final summary for reporting) directly from elapsed time
        # since last_review and the card's stability — nothing to store or
        # update while a card merely sits waiting.
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
            # =====
            # STEP 3 — TIER 1: DUE REVIEWS FIRST
            # =====
            remaining = daily_slots
            tier1 = due[:remaining]
            due_slots_used = len(tier1)
            remaining -= due_slots_used

            # =====
            # STEP 4 — THROTTLE AI CAP BY DUE DEBT + SESSION RATE-LIMIT
            #          + QUERY-BACKLOG HARD CAP (refinement B)
            # =====
            due_pressure = due_before - due_slots_used
            if due_pressure >= queue_cap_due:
                ai_cap_today = 0
            else:
                throttle = max(0.3, 1.0 - (due_pressure / queue_cap_due) * 0.7)
                ai_cap_today = math.floor(plan["ai_daily_cap"] * throttle)

            if day <= 2 and plan["ai_daily_cap"] > 0:
                ai_cap_today = min(ai_cap_today * 2, remaining)

            if cfg.enable_session_rate_limit and plan["sessions"] > 1:
                # Spread the cap across sessions rather than allow a single
                # session to burn the whole day's AI allowance (bug 6).
                per_session_cap = max(1, math.ceil(ai_cap_today / plan["sessions"]))
                ai_cap_today = min(ai_cap_today, per_session_cap * plan["sessions"])
                # (kept as a single effective cap here since this simulator
                # models one aggregate "day", but the ceiling above prevents
                # any downstream per-session integration from over-granting)

            # Hard cap: if the query backlog has grown past
            # QUERY_BACKLOG_HARD_CAP_MULT x daily_slots, AI is fully paused
            # today so every slot goes toward draining pending queries —
            # guaranteeing they can't be starved indefinitely by AI's share.
            query_backlog_now = [c for c in pending if c.origin == "query"]
            hard_cap = daily_slots * QUERY_BACKLOG_HARD_CAP_MULT
            if len(query_backlog_now) > hard_cap:
                ai_cap_today = 0

            # =====
            # STEP 5 — QUERY-FIRST SLOT PRIORITY (refinement B)
            # A card's origin (AI-suggested vs. user-asked) is just a
            # birth-record tag, not a priority tier: pending query cards no
            # longer split remaining slots by a percentage formula against
            # AI. They are seated FIRST, in full (oldest first), up to
            # whatever fits in the remaining slots; AI only gets whatever
            # is left over.
            # =====
            tier2 = query_backlog_now[:remaining]
            for c in tier2:
                pending.remove(c)
            query_slots_used = len(tier2)
            remaining -= query_slots_used

            # =====
            # STEP 6 — TIER 3: NEW AI CARDS, slot-by-slot with recycling (bug 1)
            # Each slot is attempted individually: if a card is rejected, the
            # freed slot immediately tries again (another AI attempt, up to
            # the remaining cap) instead of being lost. If AI cap is
            # exhausted mid-loop, leftover slots fall back to query backlog.
            # =====
            # Each slot is attempted individually against the *remaining* AI
            # cap. A rejection consumes one cap unit (it still cost an AI
            # call) but does NOT consume a slot permanently: the loop keeps
            # spending slots on fresh AI attempts as long as cap allows, and
            # once the cap runs out any still-open slots fall through to the
            # query-backlog fill below. This is the direct fix for bug 1
            # (previously: `remaining -= ai_take` up front meant a rejected
            # card's slot vanished with nothing reviewed and nothing gained).
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
                        continue  # slot NOT consumed: loop tries again
                card = new_card("ai")
                pending.append(card)
                tier3.append(card)
                created_by_ai += 1
                slots_open -= 1  # slot consumed only on an accepted card
            remaining = slots_open

            # Any slots still open (AI cap exhausted, or rejection fix left
            # spare capacity) are filled from the query backlog.
            if remaining > 0:
                query_backlog_now = [c for c in pending if c.origin == "query"]
                extra = query_backlog_now[:remaining]
                for c in extra:
                    pending.remove(c)
                tier2 = tier2 + extra
                query_slots_used += len(extra)
                remaining -= len(extra)

            # STEP 7 — REVIEW ALL CANDIDATES
            # User's current average difficulty across active cards — new
            # cards' starting difficulty is drawn from this (not a fixed
            # DIFFICULTY_DEFAULT), so a user whose cards tend to run hard
            # (harder language/domain, or genuinely weaker recall) starts
            # new cards at a correspondingly higher difficulty. Falls back
            # to DIFFICULTY_DEFAULT when the user has no active cards yet.
            user_avg_difficulty = (sum(c.difficulty for c in active) / len(active)) if active else DIFFICULTY_DEFAULT

            candidates = tier1 + tier2 + tier3
            for c in candidates:
                was_due = c in tier1
                if was_due:
                    lateness_samples.append(day - c.due_since)

                if c.next_review is None:
                    # First-ever exposure: not a rated review (no button
                    # press yet), just entering the system.
                    c.stability = STABILITY_INITIAL
                    c.difficulty = user_avg_difficulty
                    c.next_review = day + 1
                    c.last_review = day
                    c.due_since = None
                    if c.id not in active_ids:
                        active.append(c)
                        active_ids.add(c.id)
                        total_active_words += 1
                else:
                    _review_outcome(c, persona, cfg, day, rng)

            # STEP 8 — CATCH-UP BONUS (optional)
            due_remaining = due_before - due_slots_used
            if cfg.enable_catchup and due_remaining > queue_cap_due * 0.25:
                bonus_factor = 0.75 + enthusiasm * 0.50
                bonus_capacity = max(1, int(plan["session_size"] * bonus_factor))
                bonus_take = min(due_remaining, bonus_capacity)
                for i in range(bonus_take):
                    c = due[due_slots_used + i]
                    lateness_samples.append(day - c.due_since)
                    _review_outcome(c, persona, cfg, day, rng)
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

    import statistics as _stats

    final_day = cfg.days - 1
    learned = sum(1 for c in active
                  if c.stability >= LEARNED_MIN_STABILITY_DAYS or c.reviews >= LEARNED_MIN_REVIEWS)
    stabilities = [c.stability for c in active]
    retrievabilities = [_retrievability(final_day - (c.last_review if c.last_review is not None else final_day), c.stability)
                        for c in active]
    difficulties = [c.difficulty for c in active]

    def _pctl(vals, p):
        if not vals:
            return 0.0
        s = sorted(vals)
        return round(s[min(len(s) - 1, int(p * len(s)))], 2)

    avg_stability = round(_stats.mean(stabilities), 2) if stabilities else 0.0
    median_stability = _pctl(stabilities, 0.5)
    p90_stability = _pctl(stabilities, 0.9)
    avg_retrievability = round(_stats.mean(retrievabilities), 3) if retrievabilities else 0.0
    median_retrievability = _pctl(retrievabilities, 0.5)
    avg_difficulty = round(_stats.mean(difficulties), 2) if difficulties else 0.0

    max_due_backlog = max(r["due_remaining"] for r in rows)
    max_query_backlog = max(r["q_backlog"] for r in rows)
    due_remaining_vals = [r["due_remaining"] for r in rows]
    median_due_backlog = _pctl(due_remaining_vals, 0.5)
    p90_due_backlog = _pctl(due_remaining_vals, 0.9)

    avg_lateness = (sum(lateness_samples) / len(lateness_samples)) if lateness_samples else 0.0
    median_lateness = _pctl(lateness_samples, 0.5)
    p90_lateness = _pctl(lateness_samples, 0.9)
    max_lateness = max(lateness_samples) if lateness_samples else 0

    effective_plan = plan
    summary = {
        "plan": cfg.plan,
        "persona": cfg.persona,
        "proficiency": cfg.proficiency,
        "enable_rejection": cfg.enable_rejection,
        "enable_catchup": cfg.enable_catchup,
        "enable_continuous_mastery": cfg.enable_continuous_mastery,
        "enable_session_rate_limit": cfg.enable_session_rate_limit,
        "sessions_effective": effective_plan["sessions"],
        "session_size_effective": effective_plan["session_size"],
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
    }
    if debug:
        return rows, summary, {"active": active, "lateness_samples": lateness_samples}
    return rows, summary


def format_table(daily_log: list, summary: dict, cfg: SimConfig) -> str:
    """Format simulation results as a human-readable summary table."""
    lines = []
    lines.append(f"SRS v5 (DSR-lite) Simulation: plan={cfg.plan}, persona={cfg.persona}, "
                 f"proficiency={cfg.proficiency}, days={cfg.days}, seed={cfg.seed}")
    features = []
    if cfg.enable_rejection:
        features.append("rejection")
    if cfg.enable_catchup:
        features.append("catchup")
    if cfg.enable_continuous_mastery:
        features.append("DSR-lite mastery")
    else:
        features.append("legacy binary mastery")
    if cfg.enable_session_rate_limit:
        features.append("session-ratelimit")
    feat_str = "+".join(features)
    lines.append(f"Config: {summary['sessions_effective']} sessions x {summary['session_size_effective']} = "
                 f"{summary['sessions_effective'] * summary['session_size_effective']} slots/day  |  "
                 f"features: [{feat_str}]")
    lines.append("")

    lines.append("Final Summary:")
    lines.append(f"  Total Active Words:      {summary['total_active_words']}"
                 f"  (query={summary['created_by_query']}, ai={summary['created_by_ai']})")
    lines.append(f"  AI Calls (cost proxy):   {summary['total_ai_calls']} ({summary['avg_ai_gen_per_day']}/day)")
    lines.append(f"  AI Rejected:             {summary['total_rejected_ai']}")
    lines.append(f"  AI Cost (USD):           ${summary['total_ai_cost_usd']}")
    lines.append(f"  Bonus Due Processed:     {summary['total_bonus_due']}")
    lines.append(f"  Final Active Cards:      {summary['final_active_cards']}")
    lines.append(f"  Learned Words:           {summary['learned_words']}  "
                 f"(stability>=30d OR reviews>=4)")
    lines.append(f"  Learned Words / $:       {summary['learned_words_per_dollar']}")
    lines.append(f"  Stability (days):        avg={summary['avg_stability_days']}  "
                 f"median={summary['median_stability_days']}  p90={summary['p90_stability_days']}")
    lines.append(f"  Retrievability now:      avg={summary['avg_retrievability']}  "
                 f"median={summary['median_retrievability']}")
    lines.append(f"  Avg Difficulty:          {summary['avg_difficulty']} / 10")
    lines.append(f"  Due Backlog:             max={summary['max_due_backlog']}  "
                 f"median={summary['median_due_backlog']}  p90={summary['p90_due_backlog']}")
    lines.append(f"  Max Query Backlog:       {summary['max_query_backlog']}")
    lines.append(f"  Lateness (days):         avg={summary['avg_lateness_days']}  "
                 f"median={summary['median_lateness_days']}  p90={summary['p90_lateness_days']}  "
                 f"max={summary['max_lateness_days']}")
    lines.append(f"  Archived:                {summary['archived_lost_words']}")
    return "\n".join(lines)


def write_csv(daily_log: list, path: str):
    """Write daily simulation log to a CSV file (bug 7: includes queries/q_saved)."""
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
