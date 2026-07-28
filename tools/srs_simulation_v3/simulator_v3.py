"""SRS v4.6+ Session Simulation — V3 Golden + 7 bugfixes + continuous mastery.

Core engine: Claude's v3 Golden (debt-throttled AI, self-correcting split).
Bugfixes applied:
  1. Rejected AI slots recycled to query backlog (no slot waste)
  2. Cards unified (query/AI both idx=-1); total_active_words counted at active entry
  3. Continuous performance model (streak + noise) — score/idx independent
  4. Session override (±30% clamp) for premium flexibility testing
  5. O(1) active membership via set[int]
  6. AI cost tracking ($0.0006/event) + per-session rate-limit
  7. Full CSV export (queries, q_saved)

Feature flags: enable_rejection, enable_catchup, enable_continuous_mastery (all optional).

GLOSSARY OF OUTPUT FIELDS:
  total_active_words      - cards that entered SRS active pool (first idx: -1 → 0)
  total_new_words         - AI generation attempts (including rejected) — AI cost proxy
  total_rejected_ai       - AI cards discarded by proficiency-based rejection
  total_queries_saved     - user queries that were saved to backlog
  total_ai_cost           - estimated USD cost (total_new_words × AI_COST_PER_CALL)
  bonus_due_processed     - extra due cards processed through catch-up bonus sessions
  final_active_cards      - cards currently in the active review pool at simulation end
  learned_words           - cards with idx >= 2 OR score >= 4.0
  avg_score               - average familiarity of active cards (0=weak .. 5=mastered)
  max_due_backlog         - worst single-day due card overflow
  max_query_backlog       - worst single-day saved-but-unreviewed query pileup
  avg_lateness_days       - average days a due card waited past scheduled date
"""

import math
import random
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# SRS Intervals (10 rungs, days between reviews)
# ---------------------------------------------------------------------------
INTERVALS = [1, 3, 7, 15, 30, 60, 120, 240, 480, 960]

# ---------------------------------------------------------------------------
# Plan Defaults (subscription tiers)
# ---------------------------------------------------------------------------
PLAN_DEFAULTS = {
    "free":   {"sessions": 1, "session_size": 4, "ai_daily_cap": 3,  "query_daily_cap": 3,  "queue_cap_days": 2},
    "silver": {"sessions": 3, "session_size": 6, "ai_daily_cap": 5, "query_daily_cap": 7,  "queue_cap_days": 3},
    "gold":   {"sessions": 5, "session_size": 8, "ai_daily_cap": 12, "query_daily_cap": 10, "queue_cap_days": 4},
}

# ---------------------------------------------------------------------------
# User Personas (attendance & learning behavior)
# ---------------------------------------------------------------------------
PERSONAS = {
    "lazy":        {"attend": 0.35, "q_lo": 0, "q_hi": 1, "save_prob": 0.30, "forget": 0.35},
    "average":     {"attend": 0.70, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
    "eager":       {"attend": 0.92, "q_lo": 2, "q_hi": 6, "save_prob": 0.70, "forget": 0.10},
    "fluctuating": {"attend": None, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
}

# ---------------------------------------------------------------------------
# Proficiency Levels (vocabulary mastery & AI rejection)
# ---------------------------------------------------------------------------
PROFICIENCY = {
    "beginner":     {"known_vocab": 750,  "target_pool": 2500, "ai_efficiency": 0.50, "reject_noise": 0.10},
    "intermediate": {"known_vocab": 2000, "target_pool": 4000, "ai_efficiency": 0.60, "reject_noise": 0.15},
    "advanced":     {"known_vocab": 4000, "target_pool": 7000, "ai_efficiency": 0.70, "reject_noise": 0.20},
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
QUERY_TARGET_MONTHS = 3.0
AI_COST_PER_CALL = 0.0006          # $ per AI generation attempt
SESSION_OVERRIDE_MIN = 0.70        # clamp floor (70%)
SESSION_OVERRIDE_MAX = 1.30        # clamp ceiling (130%)


@dataclass
class Card:
    """A single vocabulary card.

    Attributes:
        id: Unique card identifier.
        origin: "ai" (AI-generated) or "query" (user-saved).
        idx: Current rung in INTERVALS ladder (-1 = never reviewed).
        score: Familiarity (0.0 .. 5.0).
        consecutive_successes: Successful reviews since last forget.
        next_review: Day this card is next due.
        due_since: Day it first became overdue (for lateness).
    """
    id: int
    origin: str = "ai"
    idx: int = -1
    score: float = 2.0
    consecutive_successes: int = 0
    next_review: Optional[int] = None
    due_since: Optional[int] = None


@dataclass
class SimConfig:
    """Configuration for one simulation run.

    Args:
        plan: Subscription tier.
        persona: User behavior profile.
        proficiency: Language proficiency.
        days: Simulation duration.
        seed: RNG seed (None = random).
        jitter: +/- jitter on intervals (0.15 = 15%).
        sessions_override: Optional % override of plan sessions (0.7–1.3).
        session_size_override: Optional % override of plan session_size.
        enable_rejection: Apply proficiency-based AI card rejection.
        enable_catchup: Offer bonus sessions when due backlog is high.
        enable_continuous_mastery: Use continuous performance model for score/idx.
    """
    plan: str = "free"
    persona: str = "average"
    proficiency: str = "advanced"
    days: int = 180
    seed: Optional[int] = 42
    jitter: float = 0.15
    sessions_override: Optional[float] = None
    session_size_override: Optional[float] = None
    enable_rejection: bool = True
    enable_catchup: bool = True
    enable_continuous_mastery: bool = True


def _apply_override(default: int, override_pct: Optional[float]) -> int:
    """Apply a clamped percentage override to a plan default value."""
    if override_pct is None:
        return default
    clamped = max(SESSION_OVERRIDE_MIN, min(SESSION_OVERRIDE_MAX, override_pct))
    return max(1, round(default * clamped))


def _attend_prob(persona: str, day: int, rng: random.Random) -> bool:
    """Determine if the user studies on a given day."""
    p = PERSONAS[persona]
    if persona == "fluctuating":
        phase = (2 * math.pi * day) / 21.0
        prob = 0.60 + 0.30 * math.sin(phase)
        return rng.random() < prob
    return rng.random() < p["attend"]


def _compute_performance(persona: dict, card: Card, rng: random.Random) -> float:
    """Continuous performance [0,1] based on base retention + streak + noise.

    Higher for eager users with long streak; lower after forget or lazy users.
    """
    base = 1.0 - persona["forget"]           # eager: 0.9, lazy: 0.65
    streak_bonus = min(card.consecutive_successes * 0.05, 0.20)
    noise = rng.uniform(-0.15, 0.15)
    return max(0.0, min(1.0, base + streak_bonus + noise))


def simulate(cfg: SimConfig) -> tuple[list[dict], dict]:
    """Run one simulation scenario and return (daily_rows, summary)."""
    plan = PLAN_DEFAULTS[cfg.plan]
    persona = PERSONAS[cfg.persona]
    rng = random.Random(cfg.seed)

    # Effective plan values with optional override
    eff_sessions = _apply_override(plan["sessions"], cfg.sessions_override)
    eff_session_size = _apply_override(plan["session_size"], cfg.session_size_override)
    daily_slots = eff_sessions * eff_session_size
    queue_cap_due = plan["queue_cap_days"] * daily_slots

    active: list[Card] = []
    active_ids: set[int] = set()
    query_backlog: list[Card] = []
    next_id = 0
    rows = []

    # Counters
    total_ai_attempts = 0
    total_rejected = 0
    total_queries_saved = 0
    total_active_words = 0
    total_bonus_processed = 0
    lateness_samples = []
    recent_attendance: list[bool] = []
    total_ai_cost = 0.0

    # Per-session rate-limit: prevent burst consumption of AI cap
    ai_per_session_max = max(1, round(plan["ai_daily_cap"] / eff_sessions))

    # Pre-compute proficiency rejection base
    prof_cfg = PROFICIENCY[cfg.proficiency]
    reject_base = (prof_cfg["known_vocab"] / prof_cfg["target_pool"]) * prof_cfg["ai_efficiency"]
    reject_noise = prof_cfg["reject_noise"]

    def new_card(origin="ai", idx=-1, next_review=None) -> Card:
        nonlocal next_id
        next_id += 1
        return Card(id=next_id, origin=origin, idx=idx, next_review=next_review)

    for day in range(cfg.days):
        attended = _attend_prob(cfg.persona, day, rng)

        # Rolling 7-day enthusiasm
        recent_attendance.append(attended)
        if len(recent_attendance) > 7:
            recent_attendance.pop(0)
        enthusiasm = sum(recent_attendance) / len(recent_attendance) if recent_attendance else 0.0

        # Current overdue debt for smart query capping
        pending_debt = sum(1 for c in active if c.next_review is not None and c.next_review <= day)

        # =====================================================================
        # STEP 1 — USER QUERIES with Smart Capping
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
            q_lo = min(persona["q_lo"], q_hi)
            queries_today = rng.randint(q_lo, q_hi)
            for _ in range(queries_today):
                if rng.random() < persona["save_prob"]:
                    query_backlog.append(new_card(origin="query", idx=-1, next_review=None))
                    saved_today += 1
                    total_queries_saved += 1

        # =====================================================================
        # STEP 2 — DUE CARDS
        # =====================================================================
        due = [c for c in active if c.next_review is not None and c.next_review <= day]
        for c in due:
            if c.due_since is None:
                c.due_since = c.next_review
        due.sort(key=lambda c: c.due_since)
        due_before = len(due)

        due_slots_used = 0
        query_slots_used = 0
        ai_generated = 0
        rejected_today = 0
        bonus_processed = 0

        if attended:
            # =================================================================
            # STEP 3 — TIER 1: DUE REVIEWS FIRST
            # =================================================================
            remaining = daily_slots
            tier1 = due[:remaining]
            due_slots_used = len(tier1)
            remaining -= due_slots_used

            # =================================================================
            # STEP 4 — THROTTLE AI BY DUE DEBT
            # =================================================================
            due_pressure = due_before - due_slots_used
            if due_pressure >= queue_cap_due:
                ai_cap_today = 0
            else:
                throttle = max(0.3, 1.0 - (due_pressure / queue_cap_due) * 0.7)
                ai_cap_today = math.floor(plan["ai_daily_cap"] * throttle)

            if day <= 2 and plan["ai_daily_cap"] > 0:
                ai_cap_today = min(ai_cap_today * 2, remaining)

            # =================================================================
            # STEP 5 — FILL REMAINING SLOTS (AI first, then query backlog)
            # Each slot tries AI first (if cap left + per-session limit).
            # If AI is rejected, the same slot is immediately offered to query.
            # Zero slot waste. (Bugfix #1)
            # =================================================================
            tier2 = []
            tier3 = []
            ai_this_session = 0

            for _ in range(remaining):
                placed = False

                # Try AI
                if ai_generated < ai_cap_today and ai_this_session < ai_per_session_max:
                    total_ai_attempts += 1
                    reject_prob = 0.0
                    if cfg.enable_rejection:
                        reject_prob = reject_base + rng.uniform(-reject_noise, reject_noise)
                        reject_prob = max(0.0, min(0.9, reject_prob))

                    if rng.random() < reject_prob:
                        rejected_today += 1
                        total_rejected += 1
                        # Slot recycled: fall through to try query
                    else:
                        tier3.append(new_card(origin="ai", idx=-1, next_review=None))
                        ai_generated += 1
                        ai_this_session += 1
                        placed = True

                # Fallback to query backlog (even if AI was rejected)
                if not placed and query_backlog:
                    tier2.append(query_backlog.pop(0))
                    query_slots_used += 1
                    placed = True

                if not placed:
                    # Truly nothing to fill — stop early
                    break

            # =================================================================
            # STEP 6 — REVIEW ALL CANDIDATES
            # =================================================================
            candidates = tier1 + tier2 + tier3
            for c in candidates:
                was_due = c in tier1
                if was_due:
                    lateness_samples.append(day - c.due_since)

                if c.idx == -1:
                    # First review: enter active pool
                    c.idx = 0
                    c.next_review = day + INTERVALS[0]
                    c.due_since = None
                    if c.id not in active_ids:
                        active.append(c)
                        active_ids.add(c.id)
                        total_active_words += 1
                else:
                    # Existing card — apply recall model
                    if cfg.enable_continuous_mastery:
                        perf = _compute_performance(persona, c, rng)
                        if perf >= 0.75:
                            c.idx = min(c.idx + 1, len(INTERVALS) - 1)
                            c.score = min(5.0, c.score + 0.7 + perf * 0.3)
                            c.consecutive_successes += 1
                        elif perf >= 0.4:
                            c.score = min(5.0, max(0.0, c.score + (perf - 0.5) * 0.4))
                            c.consecutive_successes = 0
                        else:
                            c.idx = 0
                            c.score = max(0.0, c.score - 1.5)
                            c.consecutive_successes = 0
                    else:
                        # Legacy binary model
                        if rng.random() < persona["forget"]:
                            c.idx = 0
                            c.score = max(0.0, c.score - 1.0)
                        else:
                            c.idx = min(c.idx + 1, len(INTERVALS) - 1)
                            c.score = min(5.0, c.score + 0.5)
                    c.due_since = None

                    # Set next review based on idx (always uses intervals + jitter)
                    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
                    c.next_review = day + max(1, round(INTERVALS[c.idx] * jitter))

            # =================================================================
            # STEP 7 — CATCH-UP BONUS (optional)
            # =================================================================
            due_remaining = due_before - due_slots_used
            if cfg.enable_catchup and due_remaining > queue_cap_due * 0.25:
                bonus_factor = 0.75 + enthusiasm * 0.50
                bonus_capacity = max(1, int(eff_session_size * bonus_factor))
                bonus_take = min(due_remaining, bonus_capacity)
                for i in range(bonus_take):
                    c = due[due_slots_used + i]
                    lateness_samples.append(day - c.due_since)
                    if cfg.enable_continuous_mastery:
                        perf = _compute_performance(persona, c, rng)
                        if perf >= 0.75:
                            c.idx = min(c.idx + 1, len(INTERVALS) - 1)
                            c.score = min(5.0, c.score + 0.7 + perf * 0.3)
                            c.consecutive_successes += 1
                        elif perf >= 0.4:
                            c.score = min(5.0, max(0.0, c.score + (perf - 0.5) * 0.4))
                            c.consecutive_successes = 0
                        else:
                            c.idx = 0
                            c.score = max(0.0, c.score - 1.5)
                            c.consecutive_successes = 0
                    else:
                        if rng.random() < persona["forget"]:
                            c.idx = 0
                            c.score = max(0.0, c.score - 1.0)
                        else:
                            c.idx = min(c.idx + 1, len(INTERVALS) - 1)
                            c.score = min(5.0, c.score + 0.5)
                    c.due_since = None
                    jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
                    c.next_review = day + max(1, round(INTERVALS[c.idx] * jitter))
                bonus_processed = bonus_take
                total_bonus_processed += bonus_take
                due_slots_used += bonus_processed
                due_remaining = due_before - due_slots_used
        else:
            due_remaining = due_before

        # Track AI cost
        total_ai_cost = total_ai_attempts * AI_COST_PER_CALL

        rows.append({
            "day": day, "attended": attended,
            "due_processed": due_slots_used, "due_remaining": due_remaining,
            "queries": queries_today, "q_saved": saved_today, "q_backlog": len(query_backlog),
            "ai_gen": ai_generated, "ai_rejected": rejected_today,
            "bonus_processed": bonus_processed,
            "active": len(active),
            "ai_cost_today": round(ai_generated * AI_COST_PER_CALL, 6),
        })

    # End-of-run aggregates
    learned = sum(1 for c in active if c.idx >= 2 or c.score >= 4.0)
    avg_score = (sum(c.score for c in active) / len(active)) if active else 0.0
    max_due_backlog = max(r["due_remaining"] for r in rows)
    max_query_backlog = max(r["q_backlog"] for r in rows)
    avg_lateness = (sum(lateness_samples) / len(lateness_samples)) if lateness_samples else 0.0
    max_lateness = max(lateness_samples) if lateness_samples else 0

    summary = {
        "plan": cfg.plan, "persona": cfg.persona, "proficiency": cfg.proficiency,
        "enable_rejection": cfg.enable_rejection, "enable_catchup": cfg.enable_catchup,
        "enable_continuous_mastery": cfg.enable_continuous_mastery,
        "days": cfg.days,
        "total_active_words": total_active_words,
        "total_new_words": total_ai_attempts,
        "total_rejected_ai": total_rejected,
        "total_queries_saved": total_queries_saved,
        "total_ai_cost": round(total_ai_cost, 4),
        "total_bonus_due": total_bonus_processed,
        "final_active_cards": len(active),
        "learned_words": learned,
        "avg_score": round(avg_score, 2),
        "max_due_backlog": max_due_backlog,
        "max_query_backlog": max_query_backlog,
        "avg_lateness_days": round(avg_lateness, 1),
        "max_lateness_days": max_lateness,
        "archived_lost_words": 0,
        "avg_ai_gen_per_day": round(total_ai_attempts / cfg.days, 2) if cfg.days > 0 else 0,
        "eff_sessions": eff_sessions,
        "eff_session_size": eff_session_size,
    }
    return rows, summary


def format_table(daily_log: list, summary: dict, cfg: SimConfig) -> str:
    """Format simulation results as a human-readable summary table."""
    lines = []
    lines.append(f"SRS v4.6+ Bugfix: plan={cfg.plan}, persona={cfg.persona}, "
                 f"proficiency={cfg.proficiency}, days={cfg.days}, seed={cfg.seed}")
    es = summary.get("eff_sessions", 0)
    ess = summary.get("eff_session_size", 0)
    lines.append(f"Effective: {es} sessions x {ess} = {es * ess} slots/day")
    features = []
    if cfg.enable_rejection:
        features.append("rejection")
    if cfg.enable_catchup:
        features.append("catchup")
    if cfg.enable_continuous_mastery:
        features.append("mastery")
    lines.append(f"Features: [{','.join(features) if features else 'none'}]")
    lines.append("")

    max_q = summary.get("max_query_backlog", 0)
    max_d = summary.get("max_due_backlog", 0)

    lines.append("Final Summary:")
    lines.append(f"  Total Active Words:    {summary['total_active_words']}")
    lines.append(f"  AI Attempts:           {summary['total_new_words']} ({summary['avg_ai_gen_per_day']}/d)")
    lines.append(f"  AI Cost (est):         ${summary['total_ai_cost']}")
    lines.append(f"  AI Rejected:           {summary['total_rejected_ai']}")
    lines.append(f"  Queries Saved:         {summary['total_queries_saved']}")
    lines.append(f"  Bonus Due Processed:   {summary['total_bonus_due']}")
    lines.append(f"  Final Active Cards:    {summary['final_active_cards']}")
    lines.append(f"  Learned Words:         {summary['learned_words']}")
    lines.append(f"  Avg Score:             {summary['avg_score']} / 5.0")
    lines.append(f"  Max Due Backlog:       {max_d}")
    lines.append(f"  Max Query Backlog:     {max_q}")
    lines.append(f"  Avg Lateness:          {summary['avg_lateness_days']} days")
    lines.append(f"  Max Lateness:          {summary['max_lateness_days']} days")
    lines.append(f"  Archived:              {summary['archived_lost_words']}")
    return "\n".join(lines)


def write_csv(daily_log: list, path: str):
    """Write daily simulation log to a CSV file."""
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "attended", "due_processed", "due_remaining",
                     "queries", "q_saved", "q_backlog",
                     "ai_gen", "ai_rejected", "bonus_processed", "active",
                     "ai_cost_today"])
        for r in daily_log:
            w.writerow([r["day"], int(r["attended"]), r["due_processed"],
                        r["due_remaining"],
                        r["queries"], r["q_saved"], r["q_backlog"],
                        r["ai_gen"], r["ai_rejected"],
                        r["bonus_processed"], r["active"],
                        r["ai_cost_today"]])


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="SRS v4.6+ Bugfix Simulation")
    parser.add_argument("--plan", choices=["free", "silver", "gold"], default="gold")
    parser.add_argument("--persona", choices=["lazy", "average", "eager", "fluctuating"], default="eager")
    parser.add_argument("--proficiency", choices=["beginner", "intermediate", "advanced"], default="advanced")
    parser.add_argument("--days", type=int, default=360)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-rejection", action="store_true")
    parser.add_argument("--no-catchup", action="store_true")
    parser.add_argument("--no-mastery", action="store_true")
    parser.add_argument("--sessions-override", type=float, default=None,
                        help="Session count % override (0.7–1.3)")
    parser.add_argument("--session-size-override", type=float, default=None,
                        help="Session size % override (0.7–1.3)")
    parser.add_argument("--csv", type=str, default=None)
    args = parser.parse_args(sys.argv[1:])

    cfg = SimConfig(
        plan=args.plan, persona=args.persona, proficiency=args.proficiency,
        days=args.days, seed=args.seed,
        enable_rejection=not args.no_rejection,
        enable_catchup=not args.no_catchup,
        enable_continuous_mastery=not args.no_mastery,
        sessions_override=args.sessions_override,
        session_size_override=args.session_size_override,
    )
    daily_log, summary = simulate(cfg)
    print(format_table(daily_log, summary, cfg))
    if args.csv:
        write_csv(daily_log, args.csv)