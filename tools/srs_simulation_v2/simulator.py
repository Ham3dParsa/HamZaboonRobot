#!/usr/bin/env python3
"""Pure simulation logic for SRS Session Engine v3 (Pull-Based).

Core philosophy: AI cards are only generated when review sessions have
empty slots AFTER accommodating due cards and query backlog. No forced
daily card push, no backlog ceiling, no overflow sessions needed.

Rules:
  R1: First interaction (idx=-1) always graduates to idx=0, next_review=today+1
  R2: Again on idx>=0  -> reset to idx=0, next_review=today+1
  R3: Session fill: Due -> Query Backlog -> AI Generation (up to daily cap)
  R4: Remembered -> idx = min(idx+1, 4), next_review += INTERVAL_DAYS[new_idx]
  R5: AI budget is use-it-or-lose-it (resets daily, no rollover)

No external dependencies (pure Python).
"""

import csv
import random
from dataclasses import dataclass, field
from typing import Optional

INTERVAL_DAYS = [1, 3, 7, 16, 30]

PLAN_DEFAULTS = {
    "free":   {"ai_daily_cap": 3,  "query_daily_cap": 3,  "sessions": 1, "session_size": 4},
    "silver": {"ai_daily_cap": 8,  "query_daily_cap": 10, "sessions": 3, "session_size": 6},
    "gold":   {"ai_daily_cap": 12, "query_daily_cap": 14, "sessions": 5, "session_size": 6},
}


@dataclass
class SimConfig:
    plan: str = "free"
    days: int = 30
    ai_daily_cap: Optional[int] = None
    query_daily_cap: Optional[int] = None
    query_save_prob: float = 0.5
    sessions: Optional[int] = None
    session_size: Optional[int] = None
    fail_prob: float = 0.15
    seed: Optional[int] = None
    report_every: int = 5

    def __post_init__(self):
        plan_caps = PLAN_DEFAULTS[self.plan]
        if self.ai_daily_cap is None:
            self.ai_daily_cap = plan_caps["ai_daily_cap"]
        if self.query_daily_cap is None:
            self.query_daily_cap = plan_caps["query_daily_cap"]
        if self.sessions is None:
            self.sessions = plan_caps["sessions"]
        if self.session_size is None:
            self.session_size = plan_caps["session_size"]


@dataclass
class Card:
    id: int
    interval_idx: int = -1
    next_review: Optional[int] = None


@dataclass
class DailyRow:
    day: int
    due_processed: int
    due_remaining: int
    query_backlog: int
    ai_generated: int
    ai_cap: int
    active_cards: int


@dataclass
class Summary:
    avg_ai_per_day: float
    ai_cap: float
    ai_utilization_pct: float
    max_due_remaining: int
    max_query_backlog: int
    final_active_cards: int


def simulate(cfg: SimConfig):
    rng = random.Random(cfg.seed)
    active_cards: list[Card] = []
    query_backlog: list[Card] = []
    next_id = 0
    daily_rows: list[DailyRow] = []

    def add_card(interval_idx: int = -1, next_review: Optional[int] = None) -> Card:
        nonlocal next_id
        next_id += 1
        card = Card(id=next_id, interval_idx=interval_idx, next_review=next_review)
        return card

    def get_due_cards(day: int) -> list[Card]:
        due = [
            c for c in active_cards
            if c.next_review is not None and c.next_review <= day
        ]
        due.sort(key=lambda c: c.next_review)
        return due

    total_slots_per_day = cfg.sessions * cfg.session_size

    for day in range(cfg.days):
        # Step 1: User queries -> query_backlog
        for _ in range(cfg.query_daily_cap):
            if rng.random() < cfg.query_save_prob:
                card = add_card(interval_idx=-1, next_review=None)
                query_backlog.append(card)

        # Step 2: Collect due cards
        due_cards = get_due_cards(day)
        due_before = len(due_cards)
        ai_used_today = 0

        # Step 3: Build candidate list (bulk daily slots)
        candidates: list[Card] = []
        due_candidate_ids: set[int] = set()

        # Priority 1: Due cards (up to total slots)
        for card in due_cards[:total_slots_per_day]:
            candidates.append(card)
            due_candidate_ids.add(card.id)

        remaining = total_slots_per_day - len(candidates)

        # Priority 2: Query backlog (FIFO)
        backlog_take = query_backlog[:remaining]
        candidates.extend(backlog_take)
        query_backlog = query_backlog[remaining:]
        remaining -= len(backlog_take)

        # Priority 3: AI generation (up to daily cap)
        ai_take = min(remaining, cfg.ai_daily_cap)
        for _ in range(ai_take):
            card = add_card(interval_idx=-1, next_review=None)
            candidates.append(card)
            ai_used_today += 1

        # Step 4: Process each candidate card
        due_processed = 0

        for card in candidates:
            was_due = card.id in due_candidate_ids

            if card.interval_idx == -1:
                card.interval_idx = 0
                card.next_review = day + 1
                if card not in active_cards:
                    active_cards.append(card)
            else:
                if rng.random() < cfg.fail_prob:
                    card.interval_idx = 0
                    card.next_review = day + 1
                else:
                    new_idx = min(card.interval_idx + 1, len(INTERVAL_DAYS) - 1)
                    card.interval_idx = new_idx
                    card.next_review = day + INTERVAL_DAYS[new_idx]

            if was_due:
                due_processed += 1

        due_remaining = due_before - due_processed

        daily_rows.append(DailyRow(
            day=day,
            due_processed=due_processed,
            due_remaining=due_remaining,
            query_backlog=len(query_backlog),
            ai_generated=ai_used_today,
            ai_cap=cfg.ai_daily_cap,
            active_cards=len(active_cards),
        ))

    # ── Summary ──
    total_ai = sum(r.ai_generated for r in daily_rows)
    avg_ai = total_ai / max(len(daily_rows), 1)
    utilization = (avg_ai / cfg.ai_daily_cap) * 100 if cfg.ai_daily_cap > 0 else 0
    max_due_remain = max(r.due_remaining for r in daily_rows)
    max_q_backlog = max(r.query_backlog for r in daily_rows)

    summary = Summary(
        avg_ai_per_day=round(avg_ai, 1),
        ai_cap=cfg.ai_daily_cap,
        ai_utilization_pct=round(utilization, 1),
        max_due_remaining=max_due_remain,
        max_query_backlog=max_q_backlog,
        final_active_cards=len(active_cards),
    )

    return daily_rows, summary, cfg


def format_table(daily_rows: list[DailyRow], summary: Summary, cfg: SimConfig) -> str:
    lines: list[str] = []

    lines.append(f"SRS v3 Pull Simulation: plan={cfg.plan}, days={cfg.days}, seed={cfg.seed}")
    lines.append(f"Config: {cfg.sessions} sessions x {cfg.session_size} cards = {cfg.sessions * cfg.session_size} slots/day")
    lines.append(f"        ai_cap={cfg.ai_daily_cap}, queries={cfg.query_daily_cap}, save_prob={cfg.query_save_prob}, fail_prob={cfg.fail_prob}")
    lines.append("")

    header = (f"{'Day':>4} {'DueProc':>8} {'DueRem':>8} {'QBacklog':>9} "
              f"{'AIGen':>6} {'AICap':>6} {'Active':>7}")
    sep = "-" * len(header)
    lines.append(header)
    lines.append(sep)

    for row in daily_rows:
        if cfg.report_every > 0 and row.day % cfg.report_every == 0:
            lines.append(
                f"{row.day:>4} {row.due_processed:>8} {row.due_remaining:>8} "
                f"{row.query_backlog:>9} {row.ai_generated:>6} "
                f"{row.ai_cap:>6} {row.active_cards:>7}"
            )

    lines.append(sep)
    last = daily_rows[-1]
    lines.append(
        f"{last.day:>4} {last.due_processed:>8} {last.due_remaining:>8} "
        f"{last.query_backlog:>9} {last.ai_generated:>6} "
        f"{last.ai_cap:>6} {last.active_cards:>7}"
    )
    lines.append("")

    savings = 100 - summary.ai_utilization_pct
    lines.append("Final Summary:")
    lines.append(f"  Avg AI cards generated per day:  {summary.avg_ai_per_day} / {summary.ai_cap} cap "
                 f"-> {summary.ai_utilization_pct}% utilization ({savings}% AI cost savings)")
    lines.append(f"  Max Due Remaining (any day):     {summary.max_due_remaining}")
    lines.append(f"  Max Query Backlog (any day):     {summary.max_query_backlog}")
    lines.append(f"  Final Active Cards in SRS:       {summary.final_active_cards}")

    return "\n".join(lines)


def write_csv(daily_rows: list[DailyRow], summary: Summary, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "day", "due_processed", "due_remaining", "query_backlog",
            "ai_generated", "ai_cap", "active_cards",
        ])
        for row in daily_rows:
            writer.writerow([
                row.day, row.due_processed, row.due_remaining,
                row.query_backlog, row.ai_generated, row.ai_cap,
                row.active_cards,
            ])
        writer.writerow([])
        writer.writerow(["summary", "value"])
        writer.writerow(["avg_ai_per_day", summary.avg_ai_per_day])
        writer.writerow(["ai_cap", summary.ai_cap])
        writer.writerow(["ai_utilization_pct", summary.ai_utilization_pct])
        writer.writerow(["max_due_remaining", summary.max_due_remaining])
        writer.writerow(["max_query_backlog", summary.max_query_backlog])
        writer.writerow(["final_active_cards", summary.final_active_cards])
