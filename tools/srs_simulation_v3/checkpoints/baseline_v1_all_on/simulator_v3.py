"""Pure simulation logic for SRS 'Hybrid Smart Session' Engine (v3, session-based).

New features (all toggleable via SimConfig):
- three_button_mode: 3-button review (LATER / NEUTRAL / SOONER) vs 2-button (Remembered / Again)
- score_enabled: per-card familiarity score (0.0-5.0) that adjusts intervals
- random_intervals: each card gets a randomized interval vector to spread due dates

All learner-facing content remains AI-generated. This is a pure offline simulator.
"""

import csv
import random
from dataclasses import dataclass
from typing import Optional

INTERVAL_SETS = [
    [1, 3, 7, 16, 30],
    [2, 4, 8, 14, 27],
    [1, 3, 6, 15, 28],
    [2, 5, 9, 17, 30],
]

DEFAULT_INTERVALS = [1, 3, 7, 16, 30]

PLAN_DEFAULTS = {
    "free":   {"session_size": 4, "sessions": 1, "ai_daily_cap": 3,  "query_daily_cap": 3},
    "silver": {"session_size": 6, "sessions": 3, "ai_daily_cap": 15, "query_daily_cap": 7},
    "gold":   {"session_size": 7, "sessions": 4, "ai_daily_cap": 20, "query_daily_cap": 10},
}

PLAN_RANGES = {
    "free":   {"session_size": (4, 4),  "sessions": (1, 1)},
    "silver": {"session_size": (4, 7),  "sessions": (2, 4)},
    "gold":   {"session_size": (4, 10), "sessions": (3, 6)},
}


@dataclass
class SimConfig:
    plan: str = "free"
    days: int = 30
    session_size: Optional[int] = None
    sessions: Optional[int] = None
    ai_daily_cap: Optional[int] = None
    query_daily_cap: Optional[int] = None
    save_gate_rate: float = 0.5
    forget_rate: float = 0.15
    seed: Optional[int] = None
    report_every: int = 5

    # Feature toggles
    three_button_mode: bool = True
    score_enabled: bool = True
    random_intervals: bool = True

    def __post_init__(self):
        d = PLAN_DEFAULTS[self.plan]
        if self.session_size is None:
            self.session_size = d["session_size"]
        if self.sessions is None:
            self.sessions = d["sessions"]
        if self.ai_daily_cap is None:
            self.ai_daily_cap = d["ai_daily_cap"]
        if self.query_daily_cap is None:
            self.query_daily_cap = d["query_daily_cap"]


@dataclass
class Card:
    card_id: int
    srs_stage: int = 0
    score: float = 3.0
    interval_set: list[int] = None
    next_review_day: Optional[int] = None


@dataclass
class DailyRow:
    day: int
    reviews_done: int
    backlog_count: int
    queries_made: int
    ai_cards_served: int
    total_ai_calls: int
    ai_daily_cap: int
    total_slots: int
    empty_slots: int
    total_cards: int


@dataclass
class Summary:
    avg_ai_per_day: float
    avg_ai_calls_per_day: float
    ai_cap: float
    ai_utilization_pct: float
    max_backlog: int
    avg_backlog_last7: float
    pct_days_empty_slots: float
    final_total_cards: int
    avg_final_score: float


def _score_multiplier(score: float) -> float:
    """Option A: direct multiplier based on score (0.0-5.0)."""
    mult = 1.0 + (score - 2.5) * 0.2
    return max(0.5, mult)


def simulate(cfg: SimConfig):
    rng = random.Random(cfg.seed)
    active_cards: list[Card] = []
    next_id = 0
    daily_log: list[DailyRow] = []

    def create_card() -> Card:
        nonlocal next_id
        next_id += 1
        iv_set = rng.choice(INTERVAL_SETS) if cfg.random_intervals else DEFAULT_INTERVALS
        return Card(card_id=next_id, interval_set=iv_set)

    def add_card(next_day: int) -> Card:
        card = create_card()
        card.srs_stage = 0
        card.score = 3.0
        card.next_review_day = next_day
        active_cards.append(card)
        return card

    def get_overdue_cards(day: int) -> list[Card]:
        overdue = [c for c in active_cards if c.next_review_day is not None and c.next_review_day <= day]
        overdue.sort(key=lambda c: c.next_review_day)
        return overdue

    slots_per_day = cfg.sessions * cfg.session_size

    for day in range(cfg.days):
        # Step 1: Word queries
        queries_today = rng.randint(0, cfg.query_daily_cap)
        for _ in range(queries_today):
            if rng.random() < cfg.save_gate_rate:
                add_card(next_day=day + 1)

        # Step 2: Overdue cards
        overdue = get_overdue_cards(day)
        overdue_before = len(overdue)
        candidates = overdue[:slots_per_day]
        overdue_candidate_ids = {c.card_id for c in candidates}

        remaining = slots_per_day - len(candidates)

        # Step 3: AI fills remaining slots
        ai_take = min(remaining, cfg.ai_daily_cap)
        for _ in range(ai_take):
            add_card(next_day=day + 1)
        new_cards = active_cards[-ai_take:] if ai_take > 0 else []
        candidates.extend(new_cards)

        empty_slots = slots_per_day - len(candidates)

        # Step 4: Process each candidate
        reviews_done = 0
        for card in candidates:
            was_overdue = card.card_id in overdue_candidate_ids
            if not was_overdue:
                # Brand-new cards pass through without review logic
                continue

            # This is an overdue card being reviewed
            if rng.random() < cfg.forget_rate:
                # FORGET (Again)
                card.srs_stage = 0
                card.next_review_day = day + card.interval_set[0]
                if cfg.score_enabled:
                    card.score = max(0.0, card.score - 0.2)
                reviews_done += 1
            else:
                # Non-forget: pick a button
                if cfg.three_button_mode:
                    # Distribution among non-forget: Sooner 10%, Neutral 75%, Later 15%
                    # This models realistic user behavior: most reviews are "normal",
                    # some confident pushes (Later), few deliberate pulls (Sooner)
                    roll = rng.random()
                    if roll < 0.10:  # SOONER (10% of non-forget)
                        if card.srs_stage == 0:
                            # Blocked at stage 0 -> treat as NEUTRAL
                            new_stage = 1
                            card.srs_stage = new_stage
                            card.next_review_day = day + card.interval_set[new_stage]
                            if cfg.score_enabled:
                                card.score = min(5.0, card.score + 0.1)
                        else:
                            new_stage = card.srs_stage - 1
                            card.srs_stage = new_stage
                            card.next_review_day = day + card.interval_set[new_stage]
                            if cfg.score_enabled:
                                card.score = max(0.0, card.score - 0.1)
                    elif roll < 0.85:  # NEUTRAL (75% of non-forget = 0.10 + 0.75 = 0.85)
                        new_stage = min(card.srs_stage + 1, 4)
                        card.srs_stage = new_stage
                        if new_stage == 4 and card.srs_stage == 4:
                            card.next_review_day = day + card.interval_set[4]
                        else:
                            card.next_review_day = day + card.interval_set[new_stage]
                        if cfg.score_enabled:
                            card.score = min(5.0, card.score + 0.1)
                    else:  # LATER (15% of non-forget)
                        if card.srs_stage == 4:
                            # Noisy "stage 5"
                            card.next_review_day = day + rng.randint(20, 45)
                        else:
                            new_stage = min(card.srs_stage + 1, 4)
                            prev_interval = card.interval_set[max(0, card.srs_stage - 1)]
                            next_interval = card.interval_set[new_stage]
                            base_interval = next_interval + prev_interval
                            if cfg.score_enabled:
                                mult = _score_multiplier(card.score)
                                final_interval = round(base_interval * mult)
                            else:
                                final_interval = base_interval
                            card.next_review_day = day + final_interval
                            card.srs_stage = new_stage
                        if cfg.score_enabled:
                            card.score = min(5.0, card.score + 0.2)
                else:
                    # Two-button mode: Remembered only (NEUTRAL equivalent)
                    new_stage = min(card.srs_stage + 1, 4)
                    card.srs_stage = new_stage
                    card.next_review_day = day + card.interval_set[new_stage]
                reviews_done += 1

        backlog_count = overdue_before - reviews_done
        total_ai_calls = queries_today + ai_take

        daily_log.append(DailyRow(
            day=day,
            reviews_done=reviews_done,
            backlog_count=backlog_count,
            queries_made=queries_today,
            ai_cards_served=ai_take,
            total_ai_calls=total_ai_calls,
            ai_daily_cap=cfg.ai_daily_cap,
            total_slots=slots_per_day,
            empty_slots=empty_slots,
            total_cards=len(active_cards),
        ))

    total_ai_gen = sum(r.ai_cards_served for r in daily_log)
    total_ai_calls = sum(r.total_ai_calls for r in daily_log)
    avg_ai = total_ai_gen / max(len(daily_log), 1)
    avg_calls = total_ai_calls / max(len(daily_log), 1)
    utilization = (avg_ai / cfg.ai_daily_cap) * 100 if cfg.ai_daily_cap > 0 else 0
    max_backlog = max(r.backlog_count for r in daily_log)
    last7 = daily_log[-7:]
    avg_backlog_last7 = sum(r.backlog_count for r in last7) / max(len(last7), 1)
    pct_empty = sum(1 for r in daily_log if r.empty_slots > 0) / max(len(daily_log), 1) * 100

    avg_final_score = 0.0
    if cfg.score_enabled and active_cards:
        avg_final_score = sum(c.score for c in active_cards) / len(active_cards)

    summary = Summary(
        avg_ai_per_day=round(avg_ai, 1),
        avg_ai_calls_per_day=round(avg_calls, 1),
        ai_cap=cfg.ai_daily_cap,
        ai_utilization_pct=round(utilization, 1),
        max_backlog=max_backlog,
        avg_backlog_last7=round(avg_backlog_last7, 1),
        pct_days_empty_slots=round(pct_empty, 1),
        final_total_cards=len(active_cards),
        avg_final_score=round(avg_final_score, 2),
    )
    return daily_log, summary, cfg


def format_table(daily_log: list[DailyRow], summary: Summary, cfg: SimConfig) -> str:
    lines = []
    lines.append(f"SRS v3 Hybrid Session Simulation: plan={cfg.plan}, days={cfg.days}, seed={cfg.seed}")
    lines.append(f"Config: {cfg.sessions} sessions x {cfg.session_size} cards = {cfg.sessions*cfg.session_size} slots/day, "
                 f"ai_cap={cfg.ai_daily_cap}, query_cap={cfg.query_daily_cap}, "
                 f"save_gate={cfg.save_gate_rate}, forget={cfg.forget_rate}")
    if cfg.three_button_mode:
        lines.append("Mode: 3-button (Later / Neutral / Sooner)")
    else:
        lines.append("Mode: 2-button (Remembered / Again)")
    if cfg.score_enabled:
        lines.append("Score tracking: ON")
    if cfg.random_intervals:
        lines.append("Random interval sets: ON")
    lines.append("")

    header = (f"{'Day':>4} {'Review':>7} {'Backlog':>8} {'Slots':>6} {'Empty':>6} "
              f"{'AIServ':>7} {'AICall':>7} {'AICap':>6} {'Total':>7}")
    sep = "-" * len(header)
    lines.append(header)
    lines.append(sep)
    for row in daily_log:
        if cfg.report_every > 0 and row.day % cfg.report_every == 0:
            lines.append(f"{row.day:>4} {row.reviews_done:>7} {row.backlog_count:>8} "
                         f"{row.total_slots:>6} {row.empty_slots:>6} {row.ai_cards_served:>7} "
                         f"{row.total_ai_calls:>7} {row.ai_daily_cap:>6} {row.total_cards:>7}")
    lines.append(sep)
    last = daily_log[-1]
    lines.append(f"{last.day:>4} {last.reviews_done:>7} {last.backlog_count:>8} "
                 f"{last.total_slots:>6} {last.empty_slots:>6} {last.ai_cards_served:>7} "
                 f"{last.total_ai_calls:>7} {last.ai_daily_cap:>6} {last.total_cards:>7}")
    lines.append("")
    savings = 100 - summary.ai_utilization_pct
    lines.append("Final Summary:")
    lines.append(f"  Avg AI cards served per day:   {summary.avg_ai_per_day} / {summary.ai_cap} cap "
                 f"-> {summary.ai_utilization_pct}% utilization ({savings}% AI cost savings)")
    lines.append(f"  Avg Total AI Calls per day:    {summary.avg_ai_calls_per_day}")
    lines.append(f"  Max Backlog (any day):         {summary.max_backlog}")
    lines.append(f"  Avg Backlog (last 7 days):     {summary.avg_backlog_last7}")
    lines.append(f"  Days with empty slots (%):     {summary.pct_days_empty_slots}%")
    lines.append(f"  Final Active Cards in SRS:     {summary.final_total_cards}")
    if cfg.score_enabled:
        lines.append(f"  Avg Final Score (0-5):         {summary.avg_final_score}")
    return "\n".join(lines)


def write_csv(daily_log, summary, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "reviews_done", "backlog_count", "queries_made",
                    "ai_cards_served", "total_ai_calls", "ai_daily_cap",
                    "total_slots", "empty_slots", "total_cards"])
        for r in daily_log:
            w.writerow([r.day, r.reviews_done, r.backlog_count, r.queries_made,
                        r.ai_cards_served, r.total_ai_calls, r.ai_daily_cap,
                        r.total_slots, r.empty_slots, r.total_cards])