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
         so "score >= 4" becomes a real threshold, not a near-certainty.
       - Overdue cards decay on an Ebbinghaus curve, not linearly: the
         moment a card becomes overdue its score is snapshotted
         (score_at_due), then each further day it's recomputed as
         `score_at_due * exp(-days_late / stability)`, where stability is
         drawn from the card's current SRS rung (INTERVALS[idx]) — a card
         that has earned a long interval decays slowly if it's a bit late,
         while a young, low-idx card decays fast. This replaces a flat
         per-day subtraction (which under- and over-penalized lateness at
         the same rate regardless of how well-established the memory was)
         with the standard forgetting-curve shape from memory research.

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
  learned_words            - cards with idx>=2 OR score>=4.0 (primary KPI;
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

SCORE_DECAY_STABILITY_FLOOR = 1.0       # minimum days of "stability" even for idx=0 cards

# Learned-word thresholds (tightened per external review: idx>=2/score>=4
# were too lenient — idx>=2 matches Anki's "graduated" state, not mastery)
LEARNED_MIN_IDX = 3       # >=4 successful reviews, not 3
LEARNED_MIN_SCORE = 4.5   # was 4.0
# Bug found while auditing v4: with the diminishing-returns formula, score
# never actually reaches 4.5 even in the best 720-day scenario (max
# observed ~4.26), so the "OR score>=4.5" branch is dead code and
# `learned` silently degrades back to a pure idx threshold. This is the
# core motivation for the DSR model below: a mastery signal with a real
# physical unit (days of durable memory) instead of an unbounded 0-5 dial.

# ---------------------------------------------------------------------------
# DSR (Difficulty/Stability/Retrievability) mastery model — v5, `mastery_model="dsr"`
#
# A simplified, hand-parameterized port of the FSRS-6 memory model
# (https://github.com/open-spaced-repetition/awesome-fsrs/wiki/The-Algorithm),
# adapted to هم‌زبان's 3-button review UI (no "Easy" grade). Replaces
# idx/score/streak/ease entirely for cards reviewed under this model.
#
# WHY THIS FIXES THE v4 PROBLEM:
#   - Mastery is `Stability` (S), measured in *days*, not an arbitrary
#     0-5 dial. "learned" becomes S >= LEARNED_MIN_STABILITY_DAYS, a
#     threshold with an actual physical meaning (predicted retrievability
#     stays >= desired_retention for at least that many days without
#     review) rather than a magic number nobody can defend.
#   - Retrievability R(t, S) is a *continuous* function of elapsed time,
#     computed on demand. There is no separate `score_at_due` snapshot +
#     manual exponential decay hack (v4 refinement A) — R(t,S) already
#     *is* the correct decay curve, so late cards are handled for free.
#   - The next-review interval is derived directly from S and a target
#     retention rate, replacing the fixed 10-rung INTERVALS ladder with a
#     continuous, per-card, per-history interval.
#
# NO-EASY-BUTTON CAVEAT (explicitly asked about — answering here in code,
# not just chat, so the reasoning travels with the model):
#   FSRS-6 has 4 grades (Again/Hard/Good/Easy) and estimates 4 initial-
#   stability values (w0..w3) plus an Easy-specific bonus multiplier
#   (w16) inside the stability-growth formula. هم‌زبان only has 3 buttons
#   (🔴 یادم نبود / 🟡 سخت بود / 🟢 خوب یادمه), so this port:
#     - drops w3 (initial S for "Easy") and w16 (Easy growth bonus)
#       entirely — nothing downstream references them, so nothing
#       *breaks*, it's a clean subset, not a partial/dangling formula.
#     - repoints "mean reversion" (which pulls Difficulty back toward a
#       baseline over time) at the *Good*-grade default difficulty
#       (`_dsr_d0(3)`) instead of the Easy-grade default the original
#       formula uses, since Good is now the "ceiling" grade.
#   What you genuinely lose without Easy: less resolution on *how*
#   confidently a correct recall happened. In real FSRS, a card the user
#   found trivially easy grows Stability faster than one they barely got
#   right — Easy is a costless way to say "even more confident than
#   Good." Collapsing that into a single "correct" grade means every
#   confident recall and every barely-scraped-through recall gets the
#   same Good-sized stability bump, which will very slightly overstate
#   how fast well-known cards should mature and very slightly understate
#   it for genuinely easy ones. This is a real but small accuracy cost
#   (the published FSRS ablations suggest Easy/Hard mainly sharpen the
#   *tails* of the difficulty distribution, not the median behavior) —
#   not a structural break. If a 4th button gets added later, re-enable
#   w3/w16 and this reduces to full FSRS-6 with zero architecture change.
#
# PARAMETER SOURCE: FSRS-6 published defaults (fit on ~700M real Anki
# reviews), used as-is for now. These were tuned on generic front/back
# Anki cards, not هم‌زبان's richer cards (definition + 2 examples +
# grammar note + synonym/antonym reviewed as one unit), so treat them as
# a reasonable starting point, not gospel — re-fit via gradient descent
# on هم‌زبان's own review logs once a few thousand real reviews exist
# (see `_dsr_negloglik` stub below for the hook).
# ---------------------------------------------------------------------------
MasteryModel = Literal["legacy", "continuous", "dsr"]

DSR_W = {
    # initial stability (days) by first grade — w3 (Easy) intentionally omitted
    "S0_again": 0.212,
    "S0_hard": 1.2931,
    "S0_good": 2.3065,
    # initial difficulty formula: D0(G) = w4 - e^(w5*(G-1)) + 1
    "w4": 6.4133,
    "w5": 0.8334,
    # difficulty update: deltaD = -w6*(G-3); mean-reversion weight w7
    "w6": 3.0194,
    "w7": 0.001,
    # stability growth on success: SInc = 1 + e^w8*(11-D)*S^-w9*(e^(w10*(1-R))-1)*hard_penalty
    "w8": 1.8722,
    "w9": 0.1666,
    "w10": 0.796,
    "w15_hard_penalty": 0.6014,   # <1, dampens growth when grade=Hard
    # post-lapse stability: S' = w11 * D^-w12 * ((S+1)^w13 - 1) * e^(w14*(1-R)), capped at old S
    "w11": 1.4835,
    "w12": 0.0614,
    "w13": 0.2629,
    "w14": 1.6483,
}
DSR_FACTOR = 19.0 / 81.0
DSR_DECAY = -0.5
DSR_DESIRED_RETENTION = 0.85   # target recall probability used to schedule next review

# Mastery tiers by stability (days) — replaces the single learned/not-learned
# bool with a scale that actually means something operationally.
DSR_TIER_THRESHOLDS = [
    ("در حال یادگیری", 0.0),
    ("آشنا", 7.0),
    ("یادگرفته‌شده", 21.0),
    ("تثبیت‌شده", 60.0),
]
LEARNED_MIN_STABILITY_DAYS = 21.0  # "learned" cutoff for KPI parity with v4's `learned_words`

# Rough per-card time cost model (seconds), used only for reporting a
# minutes/day estimate — NOT calibrated on real telemetry yet. Swap in
# measured show->answer latencies once available; these are placeholders
# grounded in "a definition + 2 examples + grammar note takes noticeably
# longer to read than a 3-button re-review."
TIME_BASE_REVIEW_SEC = 8.0
TIME_PER_DIFFICULTY_SEC = 3.0      # scales with D (dsr) or a idx/score-derived proxy (legacy/continuous)
TIME_NEW_CARD_BASE_SEC = 40.0
TIME_NEW_CARD_PER_DIFFICULTY_SEC = 5.0
TIME_PRIOR_HOLD_PENALTY_SEC = 5.0  # small extra cost if the previous grade on this card was "hold"


def _dsr_retrievability(elapsed_days: float, stability: float) -> float:
    """R(t, S) — FSRS-6 power-law forgetting curve (global decay, no w20
    per-user personalization yet — see module docstring)."""
    stability = max(0.1, stability)
    t = max(0.0, elapsed_days)
    return (1.0 + DSR_FACTOR * t / stability) ** DSR_DECAY


def _dsr_interval_days(stability: float, desired_retention: float = DSR_DESIRED_RETENTION) -> float:
    """Invert R(t,S) for desired_retention to get the scheduling interval."""
    return stability * ((desired_retention ** (1.0 / DSR_DECAY) - 1.0) / DSR_FACTOR)


def _dsr_s0(grade: int) -> float:
    return {1: DSR_W["S0_again"], 2: DSR_W["S0_hard"], 3: DSR_W["S0_good"]}[grade]


def _dsr_d0(grade: int) -> float:
    d0 = DSR_W["w4"] - math.exp(DSR_W["w5"] * (grade - 1)) + 1.0
    return max(1.0, min(10.0, d0))


def _dsr_update_difficulty(d: float, grade: int) -> float:
    delta_d = -DSR_W["w6"] * (grade - 3)
    d_damped = d + (10.0 - d) * delta_d / 9.0
    # mean reversion toward the Good-grade default (no Easy grade to
    # revert toward, per the no-Easy caveat above)
    d_reverted = DSR_W["w7"] * _dsr_d0(3) + (1.0 - DSR_W["w7"]) * d_damped
    return max(1.0, min(10.0, d_reverted))


def _dsr_update_stability(d: float, s: float, r: float, grade: int) -> float:
    if grade == 1:  # forget / lapse
        s_new = (DSR_W["w11"] * (d ** -DSR_W["w12"]) * (((s + 1.0) ** DSR_W["w13"]) - 1.0)
                  * math.exp(DSR_W["w14"] * (1.0 - r)))
        return max(0.1, min(s_new, s))  # post-lapse stability can never exceed pre-lapse stability
    hard_penalty = DSR_W["w15_hard_penalty"] if grade == 2 else 1.0
    s_inc = 1.0 + (math.exp(DSR_W["w8"]) * (11.0 - d) * (s ** -DSR_W["w9"])
                    * (math.exp(DSR_W["w10"] * (1.0 - r)) - 1.0) * hard_penalty)
    return s * max(1.0, s_inc)  # SInc>=1: a passing grade can never shrink stability


def _dsr_tier(stability: float) -> str:
    tier = DSR_TIER_THRESHOLDS[0][0]
    for name, floor in DSR_TIER_THRESHOLDS:
        if stability >= floor:
            tier = name
    return tier


def _dsr_negloglik_stub():
    """Placeholder for the future per-deck refit: once هم‌زبان has a few
    thousand real (elapsed_days, stability_before, grade) review triples,
    fit DSR_W by gradient descent minimizing binary cross-entropy between
    predicted R(t,S) and observed pass/fail, exactly as FSRS's own
    optimizer does. Not implemented here — flagging the hook, not the
    training loop, since we have zero real review data to fit on yet.
    """
    raise NotImplementedError("no real review telemetry to fit against yet")

# ---------------------------------------------------------------------------
# Ease factor model (three-button Telegram UI: forget / hold / advance)
# Mirrors the "همزبان" bot's actual review buttons 1:1. `ease` is a
# per-card multiplier on the base SRS interval, nudged up/down by which
# button the user pressed, so two cards at the same idx can get different
# next-review spacing based on that card's (and the user's) real history.
# ---------------------------------------------------------------------------
EASE_DEFAULT = 1.0
EASE_MIN = 0.7
EASE_MAX = 1.5
EASE_DELTA_FORGET = -0.30   # 🔴 "یادم نبود"
EASE_DELTA_HOLD = -0.15     # 🟡 "سخت بود"
EASE_DELTA_ADVANCE = 0.05   # 🟢 "خوب یادمه"
HOLD_INTERVAL_FACTOR = 0.5  # 🟡 reschedules at half the current rung's interval, not zero

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
        score_at_due: Score snapshot taken the moment the card became
            overdue (due_since set). Used as the baseline for exponential
            decay while the card waits (see SCORE_DECAY docs).
        ease: Per-card interval multiplier (three-button model), starts at
            EASE_DEFAULT for the very first card a user ever gets, or at
            the user's current average ease afterward — so a user with a
            track record of "خوب یادمه" starts new cards with longer
            spacing than one who often taps "سخت بود".
        d: DSR model only — Difficulty, 1 (easiest) to 10 (hardest).
            None until the card's first real (graded) review.
        s: DSR model only — Stability, in days (time for predicted
            retrievability to fall from 100% to 90%). None until the
            card's first real (graded) review. This *is* the mastery
            signal for the DSR model — no separate `score` field.
        last_review_day: DSR model only — day index of the most recent
            review, used to compute elapsed time for R(t,S) at the next
            review (this replaces `due_since`/`score_at_due`'s manual
            decay bookkeeping — R(t,S) is continuous, so no snapshot is
            needed).
    """
    id: int
    origin: Origin = "ai"
    idx: int = -1
    score: float = 2.0
    streak: int = 0
    next_review: Optional[int] = None
    due_since: Optional[int] = None
    score_at_due: Optional[float] = None
    ease: float = EASE_DEFAULT
    d: Optional[float] = None
    s: Optional[float] = None
    last_review_day: Optional[int] = None
    last_grade: Optional[int] = None


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
        enable_session_rate_limit: If True, spread the daily AI cap across
            the day's sessions instead of allowing it to be burst-spent in a
            single session (bug 6 fix).
        sessions_override: Optional absolute sessions/day override, clamped
            to +/-30% of the plan default (bug 4). None = use plan default.
        session_size_override: Optional absolute cards/session override,
            clamped to +/-30% of the plan default. None = use plan default.
        mastery_model: "legacy" (v3 binary success/forget model), "continuous"
            (v4's streak/noise/diminishing-returns model, bug-3 fix), or
            "dsr" (v5's FSRS-6-derived Difficulty/Stability/Retrievability
            model — see the DSR constants block above). Replaces v4's
            `enable_continuous_mastery: bool` with a 3-way choice so all
            three can be benchmarked side by side.
    """
    plan: str = "free"
    persona: str = "average"
    proficiency: str = "advanced"
    days: int = 180
    seed: Optional[int] = 42
    jitter: float = 0.15
    enable_rejection: bool = True
    enable_catchup: bool = True
    enable_session_rate_limit: bool = True
    sessions_override: Optional[int] = None
    session_size_override: Optional[int] = None
    mastery_model: MasteryModel = "continuous"
    desired_retention: float = DSR_DESIRED_RETENTION


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


def _review_outcome(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> str:
    """Apply one review's outcome to `card` in place and return the outcome label.

    The three outcomes ("forget" / "hold" / "advance") map 1:1 onto the
    همزبان bot's three review buttons:
        🔴 "یادم نبود"   -> forget
        🟡 "سخت بود"     -> hold
        🟢 "خوب یادمه"   -> advance
    A simulated persona doesn't literally click a button; instead, which
    outcome occurs is drawn from a continuous performance signal (below),
    and the CONSEQUENCES of that outcome are exactly what pressing the
    corresponding button would do in the real bot: idx change, ease change,
    score change, and the resulting next_review date. This keeps the
    simulator's scoring logic identical to the product's actual review
    mechanics rather than a separate abstract model.

    Two models, selected by cfg.enable_continuous_mastery:

    Continuous mastery model (bug 3 fix, + diminishing-returns + ease):
        performance = base_success + streak_bonus + noise, where
        base_success = 1 - persona forget rate, streak_bonus rewards
        consecutive prior successes (capped), and noise models the
        variability a real AI-based mastery estimator would see.

          performance >= 0.75 -> 🟢 advance:
              idx += 1 (capped at top rung), streak += 1
              ease = min(EASE_MAX, ease + EASE_DELTA_ADVANCE)
              score += (0.3 + 0.5*performance) * (1 - score/5)   [diminishing returns]
              next_review = day + max(1, round(INTERVALS[idx] * ease * jitter))

          0.40 <= performance < 0.75 -> 🟡 hold:
              idx unchanged, streak unchanged
              ease = max(EASE_MIN, ease + EASE_DELTA_HOLD)
              score nudged by (performance-0.5)*0.4 * (1 - score/5)
              next_review = day + max(1, round(INTERVALS[idx] * ease * jitter * HOLD_INTERVAL_FACTOR))
              (half the current rung's interval, not zero — bug fix: the
              old model left next_review untouched on "hold", so a card
              could reappear as due on the very same day in an effective
              infinite loop. The max(1, ...) floor guarantees it never
              schedules for today or earlier.)

          performance < 0.40 -> 🔴 forget:
              idx = 0, streak = 0
              ease = max(EASE_MIN, ease + EASE_DELTA_FORGET)
              score -= 1.0
              next_review = day + 1 (always tomorrow, regardless of ease/jitter —
              a lapsed card gets the shortest possible gap, full stop)

        The (1 - score/5) factor makes score gains shrink as a card
        approaches mastery (diminishing returns), so score no longer
        saturates near 5.0 after a handful of reviews. `ease` lets two
        cards at the same idx diverge in spacing based on that card's
        (and implicitly the user's) real review history — a user who
        usually taps "خوب یادمه" earns longer intervals over time; one who
        often taps "سخت بود" gets tightened spacing even while still
        progressing.

    Legacy binary model (v3 behavior, for comparison — ignores ease):
        A single roll against persona forget rate: success advances idx
        and adds a fixed +0.5 to score; failure resets idx to 0 and
        subtracts 1.0 from score.
    """
    if cfg.mastery_model == "legacy":
        if rng.random() < persona["forget"]:
            card.idx = 0
            card.streak = 0
            card.score = max(0.0, card.score - 1.0)
            card.next_review = day + 1
            return "forget"
        else:
            card.idx = min(card.idx + 1, len(INTERVALS) - 1)
            card.streak += 1
            card.score = min(5.0, card.score + 0.5)
            jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
            card.next_review = day + max(1, round(INTERVALS[card.idx] * jitter))
            return "advance"

    base_success = 1.0 - persona["forget"]
    streak_bonus = min(MASTERY_STREAK_BONUS_CAP, card.streak * MASTERY_STREAK_BONUS_PER_STEP)
    noise = rng.uniform(-MASTERY_NOISE, MASTERY_NOISE)
    performance = max(0.0, min(1.0, base_success + streak_bonus + noise))
    headroom = 1.0 - card.score / 5.0  # diminishing returns as score -> 5.0
    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)

    if performance >= MASTERY_SUCCESS_THRESHOLD:
        card.idx = min(card.idx + 1, len(INTERVALS) - 1)
        card.streak += 1
        card.ease = min(EASE_MAX, card.ease + EASE_DELTA_ADVANCE)
        card.score = min(5.0, card.score + (0.3 + 0.5 * performance) * headroom)
        card.next_review = day + max(1, round(INTERVALS[card.idx] * card.ease * jitter))
        return "advance"
    elif performance >= MASTERY_PARTIAL_THRESHOLD:
        card.ease = max(EASE_MIN, card.ease + EASE_DELTA_HOLD)
        card.score = max(0.0, min(5.0, card.score + (performance - 0.5) * 0.4 * headroom))
        card.next_review = day + max(1, round(INTERVALS[card.idx] * card.ease * jitter * HOLD_INTERVAL_FACTOR))
        return "hold"
    else:
        card.idx = 0
        card.streak = 0
        card.ease = max(EASE_MIN, card.ease + EASE_DELTA_FORGET)
        card.score = max(0.0, card.score - 1.0)
        card.next_review = day + 1
        return "forget"


def _review_outcome_dsr(card: Card, persona: dict, cfg: SimConfig, day: int, rng: random.Random) -> tuple[str, float]:
    """Apply one review's outcome under the DSR model. Mirrors
    `_review_outcome`'s role but D/S replace idx/score/streak/ease.

    Key difference from `_review_outcome`'s continuous model: the
    persona's simulated performance is blended with the model's OWN
    retrievability prediction R(t,S) for this card, rather than being
    drawn independently of the scheduler. This closes the loop the same
    way a real user would: if the DSR scheduler is doing its job, R at
    review time should hover near `desired_retention` regardless of
    persona, and a mis-tuned scheduler (reviews too early/late) shows up
    directly as too-high or too-low simulated pass rates — a built-in
    sanity check that the ad-hoc v4 model didn't have.

    Returns (grade_label, r_at_review) — r_at_review is exposed so the
    caller can log it (useful for checking the scheduler is actually
    hitting its retention target across a run).
    """
    elapsed = day - (card.last_review_day if card.last_review_day is not None else day)
    r = _dsr_retrievability(elapsed, card.s if card.s is not None else 1.0)

    persona_skill = 1.0 - persona["forget"]
    noise = rng.uniform(-MASTERY_NOISE, MASTERY_NOISE)
    performance = max(0.0, min(1.0, 0.5 * r + 0.5 * persona_skill + noise))

    if performance < MASTERY_PARTIAL_THRESHOLD:
        grade = 1
        label = "forget"
    elif performance < MASTERY_SUCCESS_THRESHOLD:
        grade = 2
        label = "hold"
    else:
        grade = 3
        label = "advance"

    d_prev = card.d if card.d is not None else _dsr_d0(3)
    s_prev = card.s if card.s is not None else _dsr_s0(3)

    card.d = _dsr_update_difficulty(d_prev, grade)
    card.s = _dsr_update_stability(d_prev, s_prev, r, grade)
    card.last_grade = grade
    card.last_review_day = day

    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
    interval = _dsr_interval_days(card.s, cfg.desired_retention) * jitter
    if grade == 1:
        interval = 1.0  # a lapse always gets the shortest possible gap, same policy as v4
    card.next_review = day + max(1, round(interval))

    return label, r


def _estimate_review_seconds(card: Card, is_new: bool, cfg: SimConfig) -> float:
    """Rough per-review time cost (seconds), for the minutes/day reporting
    metric asked about explicitly (v4 had no time model at all). Uses D
    directly for the dsr model; falls back to an idx/score-derived
    difficulty proxy for legacy/continuous so all three models can be
    compared on the same estimated-minutes basis. NOT calibrated on real
    telemetry — see TIME_* constants docstring above.
    """
    if cfg.mastery_model == "dsr" and card.d is not None:
        difficulty = card.d
    else:
        # proxy: low idx / low score ~ "feels hard" ~ high difficulty
        difficulty = max(1.0, 10.0 - (card.idx * 1.5 + card.score * 1.2))
    seconds = TIME_BASE_REVIEW_SEC + TIME_PER_DIFFICULTY_SEC * difficulty
    if is_new:
        seconds += TIME_NEW_CARD_BASE_SEC + TIME_NEW_CARD_PER_DIFFICULTY_SEC * difficulty
    if card.last_grade == 2 or (card.last_grade is None and card.score < 2.0):
        seconds += TIME_PRIOR_HOLD_PENALTY_SEC
    return seconds


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

    total_estimated_seconds = 0.0

    for day in range(cfg.days):
        attended = _attend_prob(cfg.persona, day, rng)
        day_seconds_total = 0.0

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

        # =====================================================================
        # STEP 2 — DUE CARDS
        # =====================================================================
        due = [c for c in active if c.next_review is not None and c.next_review <= day]
        for c in due:
            if c.due_since is None:
                c.due_since = c.next_review
                c.score_at_due = c.score
            if cfg.mastery_model == "continuous":
                # Refinement A (v2): Ebbinghaus-style exponential decay,
                # R = e^(-t/S), instead of a flat per-day subtraction.
                # Stability S comes from the card's current rung — a card
                # that has earned a long interval represents a more
                # established memory and decays slower if it runs a bit
                # late; a young/low-idx card decays fast.
                days_late = day - c.due_since
                stability = max(SCORE_DECAY_STABILITY_FLOOR, INTERVALS[max(c.idx, 0)])
                retention = math.exp(-days_late / stability)
                c.score = c.score_at_due * retention
            # mastery_model=="dsr": no manual decay needed here — R(t,S) is
            # computed fresh at review time in _review_outcome_dsr from
            # `elapsed = day - last_review_day`, which already captures
            # any lateness. mastery_model=="legacy": no decay at all
            # (matches v3 behavior, unchanged).
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
            # User's current average ease across active cards — new cards'
            # starting ease is drawn from this (not a fixed 1.0), so a user
            # with a track record of "خوب یادمه" gives their new cards
            # longer spacing from day one; a user who often taps "سخت بود"
            # starts new cards tighter. Falls back to EASE_DEFAULT when the
            # user has no active cards yet (their very first-ever card).
            user_avg_ease = (sum(c.ease for c in active) / len(active)) if active else EASE_DEFAULT

            candidates = tier1 + tier2 + tier3
            for c in candidates:
                was_due = c in tier1
                if was_due:
                    lateness_samples.append(day - c.due_since)

                is_first_exposure = c.idx == -1
                day_seconds_total += _estimate_review_seconds(c, is_first_exposure, cfg)

                if is_first_exposure:
                    c.idx = 0
                    if cfg.mastery_model == "dsr":
                        # First exposure is a *presentation*, not a graded
                        # review (matches existing pipeline behavior: idx
                        # -1->0 with no performance draw). Seed D/S at the
                        # Good-grade defaults since there is no real first
                        # grade to estimate from, then schedule the first
                        # real (graded) review off S0(Good).
                        c.d = _dsr_d0(3)
                        c.s = _dsr_s0(3)
                        c.last_review_day = day
                        c.next_review = day + max(1, round(c.s))
                    else:
                        c.ease = user_avg_ease
                        c.next_review = day + INTERVALS[0]
                    c.due_since = None
                    c.score_at_due = None
                    if c.id not in active_ids:
                        active.append(c)
                        active_ids.add(c.id)
                        total_active_words += 1
                elif cfg.mastery_model == "dsr":
                    _review_outcome_dsr(c, persona, cfg, day, rng)
                    c.due_since = None
                else:
                    _review_outcome(c, persona, cfg, day, rng)
                    c.due_since = None
                    c.score_at_due = None

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
                    day_seconds_total += _estimate_review_seconds(c, False, cfg)
                    if cfg.mastery_model == "dsr":
                        _review_outcome_dsr(c, persona, cfg, day, rng)
                    else:
                        _review_outcome(c, persona, cfg, day, rng)
                    c.due_since = None
                    c.score_at_due = None
                bonus_processed = bonus_take
                total_bonus_processed += bonus_take
                due_slots_used += bonus_processed
                due_remaining = due_before - due_slots_used
        else:
            due_remaining = due_before

        total_estimated_seconds += day_seconds_total
        rows.append({
            "day": day, "attended": attended,
            "due_processed": due_slots_used, "due_remaining": due_remaining,
            "queries": queries_today, "q_saved": saved_today,
            "q_backlog": len([c for c in pending if c.origin == "query"]),
            "ai_gen": ai_generated, "ai_rejected": rejected_today,
            "ai_cost_today": round(ai_generated * AI_COST_PER_CALL, 4),
            "bonus_processed": bonus_processed,
            "active": len(active),
            "est_minutes_today": round(day_seconds_total / 60.0, 2),
        })

    if cfg.mastery_model == "dsr":
        learned = sum(1 for c in active if (c.s or 0.0) >= LEARNED_MIN_STABILITY_DAYS)
        avg_score = (sum(c.s for c in active if c.s is not None) / len(active)) if active else 0.0
        tier_counts = {name: 0 for name, _ in DSR_TIER_THRESHOLDS}
        for c in active:
            tier_counts[_dsr_tier(c.s or 0.0)] += 1
        avg_difficulty = (sum(c.d for c in active if c.d is not None) / len(active)) if active else 0.0
    else:
        learned = sum(1 for c in active if c.idx >= LEARNED_MIN_IDX or c.score >= LEARNED_MIN_SCORE)
        avg_score = (sum(c.score for c in active) / len(active)) if active else 0.0
        tier_counts = None
        avg_difficulty = None
    max_due_backlog = max(r["due_remaining"] for r in rows)
    max_query_backlog = max(r["q_backlog"] for r in rows)
    avg_lateness = (sum(lateness_samples) / len(lateness_samples)) if lateness_samples else 0.0
    max_lateness = max(lateness_samples) if lateness_samples else 0
    # Median/p90 alongside the mean — flagged in the previous review as
    # necessary because "lazy"/"fluctuating" personas produce a
    # right-skewed lateness distribution the mean alone understates.
    if lateness_samples:
        _lat_sorted = sorted(lateness_samples)
        _n = len(_lat_sorted)
        median_lateness = _lat_sorted[_n // 2]
        p90_lateness = _lat_sorted[min(_n - 1, int(_n * 0.9))]
    else:
        median_lateness = 0
        p90_lateness = 0
    avg_minutes_per_day = (sum(r["est_minutes_today"] for r in rows) / cfg.days) if cfg.days else 0.0

    effective_plan = plan
    summary = {
        "plan": cfg.plan,
        "persona": cfg.persona,
        "proficiency": cfg.proficiency,
        "enable_rejection": cfg.enable_rejection,
        "enable_catchup": cfg.enable_catchup,
        "mastery_model": cfg.mastery_model,
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
        "avg_score": round(avg_score, 2),  # dsr: this is avg stability in days, not a 0-5 dial
        "avg_difficulty": round(avg_difficulty, 2) if avg_difficulty is not None else None,
        "tier_counts": tier_counts,
        "max_due_backlog": max_due_backlog,
        "max_query_backlog": max_query_backlog,
        "avg_lateness_days": round(avg_lateness, 1),
        "median_lateness_days": median_lateness,
        "p90_lateness_days": p90_lateness,
        "max_lateness_days": max_lateness,
        "archived_lost_words": 0,
        "avg_ai_gen_per_day": round(total_ai_calls / cfg.days, 2) if cfg.days > 0 else 0,
        "total_ai_cost_usd": round(total_ai_cost, 4),
        "learned_words_per_dollar": round(learned / total_ai_cost, 1) if total_ai_cost > 0 else 0.0,
        "avg_minutes_per_day": round(avg_minutes_per_day, 1),
        "total_estimated_hours": round(total_estimated_seconds / 3600.0, 1),
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
    features.append(f"mastery={cfg.mastery_model}")
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
    if summary['mastery_model'] == "dsr":
        lines.append(f"  Avg Stability:           {summary['avg_score']} days")
        lines.append(f"  Avg Difficulty:          {summary['avg_difficulty']} / 10")
        if summary['tier_counts']:
            tier_str = ", ".join(f"{k}={v}" for k, v in summary['tier_counts'].items())
            lines.append(f"  Tiers:                   {tier_str}")
    else:
        lines.append(f"  Avg Score:               {summary['avg_score']} / 5.0")
    lines.append(f"  Max Due Backlog:         {summary['max_due_backlog']}")
    lines.append(f"  Max Query Backlog:       {summary['max_query_backlog']}")
    lines.append(f"  Avg Lateness:            {summary['avg_lateness_days']} days "
                 f"(median={summary['median_lateness_days']}, p90={summary['p90_lateness_days']})")
    lines.append(f"  Max Lateness:            {summary['max_lateness_days']} days")
    lines.append(f"  Avg Minutes / Day:       {summary['avg_minutes_per_day']} "
                 f"(est., total {summary['total_estimated_hours']}h over the run)")
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
