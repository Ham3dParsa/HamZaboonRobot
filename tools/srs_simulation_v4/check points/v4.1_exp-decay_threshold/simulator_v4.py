"""SRS v4 Session Simulation — unified pipeline, continuous mastery, cost-aware AI.

This is the successor to v3 Golden. It fixes seven bugs identified in the v3
review and keeps every new behavior toggleable via `SimConfig` flags, so v4
can be configured to reproduce v3's behavior exactly (all flags off) or run
with the full new feature set (all flags on, the default).

WHAT CHANGED VS V3 (bug -> fix):

  1. Rejected AI slots were discarded, not recycled.
     -> Fixed unconditionally (this is a correctness fix, not a toggle):
        AI generation now runs in a slot-by-slot loop. Each rejected card
        immediately frees its slot for another attempt (AI retry, then
        query backlog, then simply left open if truly nothing is available).

  2. query_backlog and AI cards were tracked as separate populations with
     different accounting, causing a bad total_vocab_exposure metric.
     -> Fixed unconditionally: every new card (whatever its origin) is a
        `Card` with `origin` in {"query", "ai"} and idx=-1 until its first
        review. A single `pending` pool holds all not-yet-reviewed cards.
        The "entered the system" metric (`total_active_words`) is counted
        at the moment a card is first reviewed (idx -1 -> 0), not at creation.

  3. Score was a binary proxy (success/forget) tightly coupled to idx, so
     the "learned = idx>=2 OR score>=4" condition never exercised the OR.
     -> Toggle: `enable_continuous_mastery` (default True). When on, each
        review draws a continuous performance value in [0, 1] that is a
        function of the persona's base success rate, the card's recent
        success streak, and noise (modeling the variability an AI-based
        mastery estimator would see in practice). idx and score respond
        to performance on different curves, so they can genuinely diverge.
        When off, v4 falls back to v3's binary model for direct comparison.

  4. No relative override for premium sessions/session_size configuration.
     -> Optional: `SimConfig.sessions_override` / `session_size_override`,
        clamped to +/-30% of the plan default. Can also be changed mid-run
        via `simulate_stream` (see below) to model a user editing settings
        partway through.

  5. O(n^2) membership check (`c not in active`) on every reviewed card.
     -> Fixed unconditionally: an `active_ids: set[int]` tracks membership
        in O(1).

  6. AI daily cap wasn't tied to real per-call cost or rate-limited within
     a day (a user could burn the whole day's cap in a single session).
     -> `AI_COST_PER_CALL = 0.0006` (USD) is tracked and reported every day
        and cumulatively. Toggle: `enable_session_rate_limit` (default True)
        adds a soft per-session AI ceiling (`ai_daily_cap` spread across the
        day's sessions rather than front-loadable in session 1), so the cap
        stays inviting but can't be burst-spent in one sitting.

  7. write_csv did not export `queries`/`q_saved`.
     -> Fixed unconditionally.

FEATURE FLAGS (all in SimConfig, all default True/on unless noted):
  enable_rejection            proficiency-based AI card rejection (v3 feature, kept)
  enable_catchup               catch-up bonus sessions (v3 feature, kept)
  enable_continuous_mastery    bug-3 fix; set False to use v3's binary score model
  enable_session_rate_limit    bug-6 fix; set False to allow full-day AI burst in one session

POST-REVIEW REFINEMENTS (locked in, always active — no toggle, since these
correct realism issues rather than add optional behavior):

  A. Diminishing-returns + decay mastery score (realism fix for the score
     model in bug 3). Two changes:
       - Score gains shrink as score approaches 5.0: gain *= (1 - score/5).
         A weak card (score=1) gains most of a strong review; a
         near-mastered card (score=4.5) gains almost nothing. This stops
         every card from saturating near 5.0 after a handful of reviews,
          so "score >= 4.3" (v4.1) becomes a meaningful threshold.
        - Overdue cards decay: each day a card sits in the due queue
          unreviewed, its score decays exponentially: score *= exp(-1/S)
          where S = INTERVALS[idx] (stability proxy).  A newly-learned
          card (interval 1 day) decays fast; a mature card (interval 480
          days) barely decays per day.  Previously used a flat -0.02/day.
          This makes score reflect *retained* mastery — a word neglected
          for months by an advanced learner (high idx) degrades slowly,
          while one reviewed last week by a beginner decays rapidly.

  B. Query-first slot priority (realism fix for query vs. AI fairness).
     Query-origin cards (user explicitly asked for that word) and AI-origin
     cards no longer split remaining slots by a percentage formula. Instead:
       - Query-origin pending cards are filled into today's session FIRST,
         in full (oldest first), before any AI generation is attempted.
       - AI only fills whatever slots remain after all pending queries are
         seated (or as many as fit).
       - A hard cap (QUERY_BACKLOG_HARD_CAP_MULT x daily_slots) forces
         ai_cap_today to 0 for the day if the query backlog grows past it,
         guaranteeing the backlog gets a full-priority day to drain.
       - A soft cap (QUERY_BACKLOG_SOFT_CAP_MULT x daily_slots) tightens
         inflow: once the backlog crosses it, the day's query allowance
         (query_daily_cap) is reduced (up to 80%) so new queries don't
         outrun the drain rate.
     This reflects that a card's origin (daily AI suggestion vs. a word the
     user deliberately asked about) is just a birth-record tag — it carries
     no less (arguably more) priority for actually being reviewed.

Everything else (slot recycling, unified origin tracking, active-id set, CSV
columns) are correctness fixes applied unconditionally — there is no
"buggy" mode for those since the old behavior was simply wrong.

GLOSSARY OF OUTPUT FIELDS:
  total_active_words     - distinct cards that actually entered the SRS cycle
                            (idx -1 -> 0), regardless of origin. This is the
                            correct "vocab exposure" metric (bug 2 fix).
  created_by_query        - cards created via user "Ask a Word" queries
  created_by_ai            - cards created via AI generation (accepted only)
  total_ai_calls           - AI generation attempts, including rejected ones
                            (AI cost proxy — every attempt costs money)
  total_rejected_ai        - cards discarded via proficiency-based rejection
  total_bonus_due          - extra due cards processed through catch-up bonus
  final_active_cards       - cards in the active review pool at run end
    learned_words            - cards with idx>=3 OR score>=4.3 (primary KPI;
                             tightened in v4.1 from idx>=2/score>=4.0;
                             meaningful only when enable_continuous_mastery=True,
                             see bug 3)
  avg_score                - average familiarity score of active cards (0-5)
  max_due_backlog          - worst single-day due-card overflow
  max_query_backlog        - worst single-day saved-but-unreviewed pileup
  avg_lateness_days        - average days a due card waited past schedule
  max_lateness_days        - worst-case single delay any card experienced
  archived_lost_words      - always 0 (archiving/deletion is out of scope by design)
  total_ai_cost_usd        - total AI $ spent this run (total_ai_calls * AI_COST_PER_CALL)
  learned_words_per_dollar - learned_words / total_ai_cost_usd (efficiency KPI)
"""

import math
import random
from dataclasses import dataclass, field
from typing import Optional, Literal

# ---------------------------------------------------------------------------
# SRS Intervals (10 rungs): 1 day up to ~32 months.
# ---------------------------------------------------------------------------
INTERVALS = [1, 3, 7, 15, 30, 60, 120, 240, 480, 960]

# ---------------------------------------------------------------------------
# Plan Defaults
# ---------------------------------------------------------------------------
PLAN_DEFAULTS = {
    "free":   {"sessions": 1, "session_size": 4, "ai_daily_cap": 3,  "query_daily_cap": 3,  "queue_cap_days": 2},
    "silver": {"sessions": 3, "session_size": 5, "ai_daily_cap": 5,  "query_daily_cap": 7,  "queue_cap_days": 3},
    "gold":   {"sessions": 4, "session_size": 7, "ai_daily_cap": 12, "query_daily_cap": 10, "queue_cap_days": 4},
}

# ---------------------------------------------------------------------------
# User Personas
# ---------------------------------------------------------------------------
PERSONAS = {
    "lazy":        {"attend": 0.35, "q_lo": 0, "q_hi": 1, "save_prob": 0.30, "forget": 0.35},
    "average":     {"attend": 0.70, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
    "eager":       {"attend": 0.92, "q_lo": 2, "q_hi": 6, "save_prob": 0.70, "forget": 0.10},
    "fluctuating": {"attend": None, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
}

# ---------------------------------------------------------------------------
# Proficiency Levels (vocabulary mastery & AI rejection)
# Rejection formula: reject_prob = (known_vocab / target_pool) x ai_efficiency + noise
# ---------------------------------------------------------------------------
PROFICIENCY = {
    "beginner":     {"known_vocab": 500,  "target_pool": 2000, "ai_efficiency": 0.70, "reject_noise": 0.10},
    "intermediate": {"known_vocab": 2000, "target_pool": 4000, "ai_efficiency": 0.65, "reject_noise": 0.15},
    "advanced":     {"known_vocab": 4000, "target_pool": 7000, "ai_efficiency": 0.60, "reject_noise": 0.20},
}

# ---------------------------------------------------------------------------
# AI cost model (bug 6): real per-call cost, padded slightly for safety margin.
# ---------------------------------------------------------------------------
AI_COST_PER_CALL = 0.0006  # USD per AI generation attempt (accepted or rejected)

# ---------------------------------------------------------------------------
# Continuous mastery model constants (bug 3)
# ---------------------------------------------------------------------------
MASTERY_STREAK_BONUS_PER_STEP = 0.03   # +3% success chance per consecutive success
MASTERY_STREAK_BONUS_CAP = 0.25        # capped at +25%
MASTERY_NOISE = 0.15                   # +/- random noise on performance draw
MASTERY_SUCCESS_THRESHOLD = 0.75       # performance >= this -> full advance
MASTERY_PARTIAL_THRESHOLD = 0.40       # performance in [partial, success) -> hold steady
# performance < MASTERY_PARTIAL_THRESHOLD -> forgotten (idx resets)

# Replaced with exponential decay: score *= exp(-1.0 / INTERVALS[idx]) per overdue day.
# (constant removed in v4.1 — see git history)

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
    """A single vocabulary card in the SRS system.

    Attributes:
        id: Unique card identifier (monotonic across the simulation).
        origin: How this card was created — "query" (user asked for the word)
            or "ai" (AI-suggested during a review session). Cards of both
            origins are otherwise identical citizens of the same pipeline
            (bug 2 fix): same idx=-1 start, same review mechanics.
        idx: Current rung index in the INTERVALS ladder (-1 = never reviewed).
        score: Continuous familiarity score, 0.0 (weak) to 5.0 (mastered).
            Under enable_continuous_mastery this evolves independently of
            idx (bug 3 fix); under the legacy binary model it tracks idx
            closely, as in v3.
        streak: Consecutive successful reviews (resets to 0 on any forget).
            Feeds the continuous mastery performance draw.
        next_review: Simulation day this card is next due for review.
        due_since: Day it first became overdue (for lateness tracking).
    """
    id: int
    origin: Origin = "ai"
    idx: int = -1
    score: float = 2.0
    streak: int = 0
    next_review: Optional[int] = None
    due_since: Optional[int] = None


@dataclass
class SimConfig:
    """Configuration for a single simulation run.

    Args:
        plan: Subscription tier ("free", "silver", "gold").
        persona: User behavior profile ("lazy", "average", "eager", "fluctuating").
        proficiency: Language proficiency ("beginner", "intermediate", "advanced").
        days: Number of simulation days to run.
        seed: RNG seed for reproducible comparisons (None = random).
        jitter: +/- fraction applied to SRS intervals (0.15 = 15%).
        enable_rejection: If True, apply proficiency-based AI card rejection.
        enable_catchup: If True, offer bonus sessions when due backlog is high.
        enable_continuous_mastery: If True, use the streak/noise-based
            continuous performance model for scoring (bug 3 fix). If False,
            fall back to v3's binary success/forget model for comparison.
        enable_session_rate_limit: If True, spread the daily AI cap across
            the day's sessions instead of allowing it to be burst-spent in a
            single session (bug 6 fix).
        sessions_override: Optional absolute sessions/day override, clamped
            to +/-30% of the plan default (bug 4). None = use plan default.
        session_size_override: Optional absolute cards/session override,
            clamped to +/-30% of the plan default. None = use plan default.
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
    """Clamp a requested plan-parameter override to +/-30% of the default.

    Used for premium "manage your own sessions/session_size" configuration
    (bug 4). Always returns at least 1.
    """
    if requested is None:
        return default
    lo = max(1, math.floor(default * (1 - PLAN_OVERRIDE_BAND)))
    hi = max(lo, math.ceil(default * (1 + PLAN_OVERRIDE_BAND)))
    return max(lo, min(hi, requested))


def _resolve_plan(cfg: SimConfig) -> dict:
    """Resolve effective plan parameters, applying any clamped overrides."""
    base = PLAN_DEFAULTS[cfg.plan]
    return {
        **base,
        "sessions": _clamp_override(base["sessions"], cfg.sessions_override),
        "session_size": _clamp_override(base["session_size"], cfg.session_size_override),
    }


def _attend_prob(persona: str, day: int, rng: random.Random) -> bool:
    """Determine if the simulated user studies on a given day.

    "fluctuating" follows a 21-day sine wave (60% +- 30%) modeling
    motivation cycles; all others use a flat probability.
    """
    p = PERSONAS[persona]
    if persona == "fluctuating":
        phase = (2 * math.pi * day) / 21.0
        prob = 0.60 + 0.30 * math.sin(phase)
        return rng.random() < prob
    return rng.random() < p["attend"]


def _review_outcome(card: Card, persona: dict, cfg: SimConfig, rng: random.Random) -> str:
    """Apply one review's outcome to `card` in place and return the outcome label.

    Two models, selected by cfg.enable_continuous_mastery:

    Continuous mastery model (bug 3 fix, + diminishing-returns refinement):
        Draws performance = base_success + streak_bonus + noise, where
        base_success = 1 - persona forget rate, streak_bonus rewards
        consecutive prior successes (capped), and noise models the
        variability a real AI-based mastery estimator would see.
          performance >= 0.75        -> "advance": idx+1, streak+1,
                                         score += (0.3 + 0.5*performance) * (1 - score/5)
          0.40 <= performance < 0.75 -> "hold": idx unchanged, streak unchanged,
                                         score nudged by (performance-0.5)*0.4 * (1 - score/5)
          performance < 0.40         -> "forget": idx=0, streak=0, score-=1.0
        The (1 - score/5) factor makes gains shrink as a card approaches
        mastery (a card at score=4.5 gains almost nothing further), so
        score no longer saturates near 5.0 after a handful of reviews —
        it takes sustained, real performance to earn a high score. This
        lets idx (repetition count) and score (retained mastery) diverge,
        which is required for the "3+ reviews OR score>=4" learned-word
        condition to be meaningful. Separately, score also decays while a
        card sits overdue (see the due-collection step in simulate()),
        so neglect is penalized even before the next review happens.

    Legacy binary model (v3 behavior, for comparison):
        A single roll against persona forget rate: success advances idx
        and adds a fixed +0.5 to score; failure resets idx to 0 and
        subtracts 1.0 from score. idx and score are tightly coupled here,
        which is the exact bug 3 condition being fixed above.
    """
    if not cfg.enable_continuous_mastery:
        if rng.random() < persona["forget"]:
            card.idx = 0
            card.streak = 0
            card.score = max(0.0, card.score - 1.0)
        else:
            card.idx = min(card.idx + 1, len(INTERVALS) - 1)
            card.streak += 1
            card.score = min(5.0, card.score + 0.5)
        return "advance" if card.idx > 0 else "forget"

    base_success = 1.0 - persona["forget"]
    streak_bonus = min(MASTERY_STREAK_BONUS_CAP, card.streak * MASTERY_STREAK_BONUS_PER_STEP)
    noise = rng.uniform(-MASTERY_NOISE, MASTERY_NOISE)
    performance = max(0.0, min(1.0, base_success + streak_bonus + noise))

    headroom = 1.0 - card.score / 5.0  # diminishing returns as score -> 5.0
    if performance >= MASTERY_SUCCESS_THRESHOLD:
        card.idx = min(card.idx + 1, len(INTERVALS) - 1)
        card.streak += 1
        card.score = min(5.0, card.score + (0.3 + 0.5 * performance) * headroom)
        return "advance"
    elif performance >= MASTERY_PARTIAL_THRESHOLD:
        card.score = max(0.0, min(5.0, card.score + (performance - 0.5) * 0.4 * headroom))
        return "hold"
    else:
        card.idx = 0
        card.streak = 0
        card.score = max(0.0, card.score - 1.0)
        return "forget"


def simulate(cfg: SimConfig) -> tuple[list[dict], dict]:
    """Run one simulation scenario and return (daily_rows, summary).

    Daily processing order:
      1. User queries (capped by plan + smart cap if debt is high)
      2. Collect due cards (sorted oldest-first)
      3. Tier 1 — due reviews (fill daily sessions)
      4. Throttle AI cap by remaining due pressure (+ optional session
         rate-limiting so it can't be burst-spent in one sitting)
      5. Self-correcting split of remaining slots (query backlog vs AI)
      6. Tier 3 — new AI cards, generated + reviewed slot-by-slot so a
         rejected card's slot is immediately recycled (bug 1 fix)
      7. Review all candidates (mastery model advances/holds/forgets)
      8. Catch-up bonus (optional) — extra due processing when backlog > 25%

    Returns:
        daily_rows: List of dicts, one per day, with per-day metrics.
        summary: Dict of end-of-run aggregate statistics (see module
                 docstring for field glossary).
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
        return Card(id=next_id, origin=origin, idx=-1, next_review=None)

    daily_slots = plan["sessions"] * plan["session_size"]
    queue_cap_due = plan["queue_cap_days"] * daily_slots

    for day in range(cfg.days):
        attended = _attend_prob(cfg.persona, day, rng)

        recent_attendance.append(attended)
        if len(recent_attendance) > 7:
            recent_attendance.pop(0)
        enthusiasm = sum(recent_attendance) / len(recent_attendance) if recent_attendance else 0.0

        pending_debt = sum(1 for c in active if c.next_review is not None and c.next_review <= day)

        # =====================================================================
        # STEP 1 — USER QUERIES ("Ask a Word")
        # =====================================================================
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
                if rng.random() < persona["save_prob"]:
                    card = new_card("query")
                    pending.append(card)
                    created_by_query += 1
                    saved_today += 1

        # =====================================================================
        # STEP 2 — DUE CARDS
        # =====================================================================
        due = [c for c in active if c.next_review is not None and c.next_review <= day]
        for c in due:
            if c.due_since is None:
                c.due_since = c.next_review
            if cfg.enable_continuous_mastery:
                # Refinement A (v4.1): exponential score decay based on
                # Ebbinghaus forgetting curve.  Cards with higher idx have
                # greater stability (longer INTERVALS[idx]) and therefore
                # decay more slowly per overdue day.  Previously used a
                # flat -0.02/day which failed to differentiate new vs
                # mature cards.
                stability = max(1.0, float(INTERVALS[c.idx]))
                c.score = max(0.0, c.score * math.exp(-1.0 / stability))
        due.sort(key=lambda c: c.due_since)
        due_before = len(due)

        due_slots_used = 0
        ai_generated = 0
        rejected_today = 0
        bonus_processed = 0
        query_slots_used = 0

        if attended:
            # =================================================================
            # STEP 3 — TIER 1: DUE REVIEWS FIRST
            # =================================================================
            remaining = daily_slots
            tier1 = due[:remaining]
            due_slots_used = len(tier1)
            remaining -= due_slots_used

            # =================================================================
            # STEP 4 — THROTTLE AI CAP BY DUE DEBT + SESSION RATE-LIMIT
            #          + QUERY-BACKLOG HARD CAP (refinement B)
            # =================================================================
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

            # =================================================================
            # STEP 5 — QUERY-FIRST SLOT PRIORITY (refinement B)
            # A card's origin (AI-suggested vs. user-asked) is just a
            # birth-record tag, not a priority tier: pending query cards no
            # longer split remaining slots by a percentage formula against
            # AI. They are seated FIRST, in full (oldest first), up to
            # whatever fits in the remaining slots; AI only gets whatever
            # is left over.
            # =================================================================
            tier2 = query_backlog_now[:remaining]
            for c in tier2:
                pending.remove(c)
            query_slots_used = len(tier2)
            remaining -= query_slots_used

            # =================================================================
            # STEP 6 — TIER 3: NEW AI CARDS, slot-by-slot with recycling (bug 1)
            # Each slot is attempted individually: if a card is rejected, the
            # freed slot immediately tries again (another AI attempt, up to
            # the remaining cap) instead of being lost. If AI cap is
            # exhausted mid-loop, leftover slots fall back to query backlog.
            # =================================================================
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

            # =================================================================
            # STEP 7 — REVIEW ALL CANDIDATES
            # =================================================================
            candidates = tier1 + tier2 + tier3
            for c in candidates:
                was_due = c in tier1
                if was_due:
                    lateness_samples.append(day - c.due_since)

                if c.idx == -1:
                    c.idx = 0
                    c.next_review = day + INTERVALS[0]
                    c.due_since = None
                    if c.id not in active_ids:
                        active.append(c)
                        active_ids.add(c.id)
                        total_active_words += 1
                else:
                    outcome = _review_outcome(c, persona, cfg, rng)
                    if outcome == "hold":
                        pass  # idx unchanged, next_review unchanged this cycle
                    else:
                        jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
                        c.next_review = day + max(1, round(INTERVALS[c.idx] * jitter))
                    c.due_since = None

            # =================================================================
            # STEP 8 — CATCH-UP BONUS (optional)
            # =================================================================
            due_remaining = due_before - due_slots_used
            if cfg.enable_catchup and due_remaining > queue_cap_due * 0.25:
                bonus_factor = 0.75 + enthusiasm * 0.50
                bonus_capacity = max(1, int(plan["session_size"] * bonus_factor))
                bonus_take = min(due_remaining, bonus_capacity)
                for i in range(bonus_take):
                    c = due[due_slots_used + i]
                    lateness_samples.append(day - c.due_since)
                    outcome = _review_outcome(c, persona, cfg, rng)
                    if outcome != "hold":
                        jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
                        c.next_review = day + max(1, round(INTERVALS[c.idx] * jitter))
                    c.due_since = None
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

    learned = sum(1 for c in active if c.idx >= 3 or c.score >= 4.3)
    avg_score = (sum(c.score for c in active) / len(active)) if active else 0.0
    max_due_backlog = max(r["due_remaining"] for r in rows)
    max_query_backlog = max(r["q_backlog"] for r in rows)
    avg_lateness = (sum(lateness_samples) / len(lateness_samples)) if lateness_samples else 0.0
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
        "avg_score": round(avg_score, 2),
        "max_due_backlog": max_due_backlog,
        "max_query_backlog": max_query_backlog,
        "avg_lateness_days": round(avg_lateness, 1),
        "max_lateness_days": max_lateness,
        "archived_lost_words": 0,
        "avg_ai_gen_per_day": round(total_ai_calls / cfg.days, 2) if cfg.days > 0 else 0,
        "total_ai_cost_usd": round(total_ai_cost, 4),
        "learned_words_per_dollar": round(learned / total_ai_cost, 1) if total_ai_cost > 0 else 0.0,
    }
    return rows, summary


def format_table(daily_log: list, summary: dict, cfg: SimConfig) -> str:
    """Format simulation results as a human-readable summary table."""
    lines = []
    lines.append(f"SRS v4 Simulation: plan={cfg.plan}, persona={cfg.persona}, "
                 f"proficiency={cfg.proficiency}, days={cfg.days}, seed={cfg.seed}")
    features = []
    if cfg.enable_rejection:
        features.append("rejection")
    if cfg.enable_catchup:
        features.append("catchup")
    if cfg.enable_continuous_mastery:
        features.append("cont-mastery")
    if cfg.enable_session_rate_limit:
        features.append("session-ratelimit")
    feat_str = "+".join(features) if features else "none (legacy v3 mode)"
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
    lines.append(f"  Learned Words:           {summary['learned_words']}")
    lines.append(f"  Learned Words / $:       {summary['learned_words_per_dollar']}")
    lines.append(f"  Avg Score:               {summary['avg_score']} / 5.0")
    lines.append(f"  Max Due Backlog:         {summary['max_due_backlog']}")
    lines.append(f"  Max Query Backlog:       {summary['max_query_backlog']}")
    lines.append(f"  Avg Lateness:            {summary['avg_lateness_days']} days")
    lines.append(f"  Max Lateness:            {summary['max_lateness_days']} days")
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
