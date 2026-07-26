#!/usr/bin/env python3
"""Pure simulation logic for SRS v2.8 session-based review engine.

All behavioral rules are locked per Plan_srs_core.md:
  Rule S1: Again on idx=-1 -> graduate (idx=0, next_review=today+1)
  Rule S2: Again on idx>=0  -> reset to idx=0, next_review=today+1
  Rule S3: Session fill priority: overdue due first, then backlog
  Rule S4: Overflow session processes only backlog cards
  Rule S5: Remembered -> idx = min(current+1, 4), next_review += INTERVAL_DAYS[new_idx]

No external dependencies (pure Python).
"""

import csv
import random
from dataclasses import dataclass, field
from typing import Optional

INTERVAL_DAYS = [1, 3, 7, 16, 30]

PLAN_DEFAULTS = {
    "free":   {"daily_cards": 3,  "word_query_cap": 3,  "session_cap": 1},
    "silver": {"daily_cards": 8,  "word_query_cap": 10, "session_cap": 4},
    "gold":   {"daily_cards": 12, "word_query_cap": 14, "session_cap": 10},
}


@dataclass
class SimConfig:
    plan: str = "free"
    days: int = 30
    daily_cards: Optional[int] = None
    word_query_cap: Optional[int] = None
    word_query_save_prob: float = 0.5
    session_cap: Optional[int] = None
    session_size: int = 5
    backlog_ceiling: int = 50
    fail_review_prob: float = 0.15
    overflow_session_threshold: Optional[int] = None
    seed: Optional[int] = None
    report_every: int = 5

    def __post_init__(self):
        plan_caps = PLAN_DEFAULTS[self.plan]
        if self.daily_cards is None:
            self.daily_cards = plan_caps["daily_cards"]
        if self.word_query_cap is None:
            self.word_query_cap = plan_caps["word_query_cap"]
        if self.session_cap is None:
            self.session_cap = plan_caps["session_cap"]


@dataclass
class Card:
    id: int
    interval_idx: int = -1
    next_review: Optional[int] = None


@dataclass
class DailyRow:
    day: int
    backlog: int
    due_processed: int
    due_carried_over: int
    total_graduated: int
    rejected: int
    overflow: bool


@dataclass
class Summary:
    avg_backlog_last_7: float
    max_carry_streak: int
    rejection_pct: float
    overflow_count: int
    overflow_enabled: bool


def simulate(cfg: SimConfig):
    rng = random.Random(cfg.seed)
    words: list[Card] = []
    next_id = 0
    daily_rows: list[DailyRow] = []

    def backlog_size() -> int:
        return sum(1 for w in words if w.interval_idx == -1)

    def add_backlog_card() -> None:
        nonlocal next_id
        next_id += 1
        words.append(Card(id=next_id, interval_idx=-1, next_review=None))

    def get_due_cards(day: int) -> list[Card]:
        due = [
            w for w in words
            if w.interval_idx >= 0 and w.next_review is not None and w.next_review <= day
        ]
        due.sort(key=lambda w: w.next_review)
        return due

    def get_backlog_cards() -> list[Card]:
        return [w for w in words if w.interval_idx == -1]

    def process_card(card: Card, day: int) -> None:
        if card.interval_idx == -1:
            card.interval_idx = 0
            card.next_review = day + 1
        else:
            if rng.random() < cfg.fail_review_prob:
                card.interval_idx = 0
                card.next_review = day + 1
            else:
                new_idx = min(card.interval_idx + 1, len(INTERVAL_DAYS) - 1)
                card.interval_idx = new_idx
                card.next_review = day + INTERVAL_DAYS[new_idx]

    for day in range(cfg.days):
        rejected = 0
        due_processed = 0
        due_carried_over = 0
        overflow_triggered = False

        for _ in range(cfg.daily_cards):
            if backlog_size() < cfg.backlog_ceiling:
                add_backlog_card()
            else:
                rejected += 1

        for _ in range(cfg.word_query_cap):
            if rng.random() < cfg.word_query_save_prob:
                if backlog_size() < cfg.backlog_ceiling:
                    add_backlog_card()
                else:
                    rejected += 1

        total_slots = cfg.session_cap * cfg.session_size
        if total_slots > 0:
            due_cards = get_due_cards(day)
            due_before = len(due_cards)
            backlog_cards = get_backlog_cards()
            candidates = due_cards + backlog_cards
            selected = candidates[:total_slots]

            processed = 0
            for card in selected:
                process_card(card, day)
                processed += 1

            due_processed = min(due_before, processed)
            due_carried_over = due_before - due_processed

        if cfg.overflow_session_threshold is not None and backlog_size() > cfg.overflow_session_threshold:
            overflow_triggered = True
            overflow_cards = get_backlog_cards()[:cfg.session_size]
            for card in overflow_cards:
                process_card(card, day)

        total_graduated = sum(1 for w in words if w.interval_idx >= 0)
        daily_rows.append(DailyRow(
            day=day,
            backlog=backlog_size(),
            due_processed=due_processed,
            due_carried_over=due_carried_over,
            total_graduated=total_graduated,
            rejected=rejected,
            overflow=overflow_triggered,
        ))

    last_7 = daily_rows[-7:]
    avg_backlog_last_7 = sum(r.backlog for r in last_7) / max(len(last_7), 1)

    max_carry_streak = 0
    current_carry_streak = 0
    for row in daily_rows:
        if row.due_carried_over > 0:
            current_carry_streak += 1
            max_carry_streak = max(max_carry_streak, current_carry_streak)
        else:
            current_carry_streak = 0

    days_with_rejection = sum(1 for r in daily_rows if r.rejected > 0)
    rejection_pct = (days_with_rejection / max(len(daily_rows), 1)) * 100
    overflow_count = sum(1 for r in daily_rows if r.overflow)

    summary = Summary(
        avg_backlog_last_7=round(avg_backlog_last_7, 1),
        max_carry_streak=max_carry_streak,
        rejection_pct=round(rejection_pct, 1),
        overflow_count=overflow_count,
        overflow_enabled=cfg.overflow_session_threshold is not None,
    )

    return daily_rows, summary, cfg


def format_table(daily_rows: list[DailyRow], summary: Summary, cfg: SimConfig) -> str:
    lines: list[str] = []

    lines.append(f"SRS Simulation: plan={cfg.plan}, days={cfg.days}, seed={cfg.seed}")
    lines.append(f"Config: daily_cards={cfg.daily_cards}, queries={cfg.word_query_cap}, "
                 f"sessions={cfg.session_cap}*{cfg.session_size}")
    lines.append(f"        backlog_ceil={cfg.backlog_ceiling}, fail_prob={cfg.fail_review_prob}, "
                 f"save_prob={cfg.word_query_save_prob}")
    if cfg.overflow_session_threshold is not None:
        lines.append(f"        overflow_threshold={cfg.overflow_session_threshold}")
    lines.append("")

    header = (f"{'Day':>4} {'Backlog':>8} {'DueProc':>8} {'DueCarry':>8} "
              f"{'Grad':>8} {'Rej':>6} {'Ovrflw':>6}")
    sep = "-" * len(header)
    lines.append(header)
    lines.append(sep)

    for row in daily_rows:
        if cfg.report_every > 0 and row.day % cfg.report_every == 0:
            lines.append(
                f"{row.day:>4} {row.backlog:>8} {row.due_processed:>8} "
                f"{row.due_carried_over:>8} {row.total_graduated:>8} "
                f"{row.rejected:>6} {'Yes' if row.overflow else '':>6}"
            )

    lines.append(sep)
    last = daily_rows[-1]
    lines.append(
        f"{last.day:>4} {last.backlog:>8} {last.due_processed:>8} "
        f"{last.due_carried_over:>8} {last.total_graduated:>8} "
        f"{last.rejected:>6} {'Yes' if last.overflow else '':>6}"
    )
    lines.append("")

    lines.append("Final Summary:")
    lines.append(f"  Average backlog (last 7 days):    {summary.avg_backlog_last_7}")
    lines.append(f"  Max carry streak (days):          {summary.max_carry_streak}")
    lines.append(f"  Days with rejection (%):          {summary.rejection_pct}%")
    if summary.overflow_enabled:
        lines.append(f"  Overflow sessions triggered:      {summary.overflow_count}")

    return "\n".join(lines)


def write_csv(daily_rows: list[DailyRow], summary: Summary, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "day", "backlog", "due_processed", "due_carried_over",
            "total_graduated", "rejected", "overflow",
        ])
        for row in daily_rows:
            writer.writerow([
                row.day, row.backlog, row.due_processed,
                row.due_carried_over, row.total_graduated,
                row.rejected, "Yes" if row.overflow else "",
            ])
        writer.writerow([])
        writer.writerow(["summary", "value"])
        writer.writerow(["avg_backlog_last_7", summary.avg_backlog_last_7])
        writer.writerow(["max_carry_streak", summary.max_carry_streak])
        writer.writerow(["rejection_pct", summary.rejection_pct])
        if summary.overflow_enabled:
            writer.writerow(["overflow_count", summary.overflow_count])
