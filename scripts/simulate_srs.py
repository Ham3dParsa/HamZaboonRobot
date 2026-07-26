#!/usr/bin/env python3
"""Simulate SRS v2.8 session-based review engine for N days.

Pure Python, no external dependencies, no AI, no database.
Run: python scripts/simulate_srs.py --plan free --days 30 --seed 42

All behavioral rules are locked per Plan_srs_core.md:
  Rule S1: Again on idx=-1 -> graduate (idx=0, next_review=today+1)
  Rule S2: Again on idx>=0  -> reset to idx=0, next_review=today+1
  Rule S3: Session fill priority: overdue due first, then backlog
  Rule S4: Overflow session processes only backlog cards
  Rule S5: Remembered -> idx = min(current+1, 4), next_review += INTERVAL_DAYS[new_idx]
"""

import argparse
import csv
import random
import sys
from dataclasses import dataclass, field
from typing import Optional

INTERVAL_DAYS = [1, 3, 7, 16, 30]

PLAN_DEFAULTS = {
    "free":   {"daily_cards": 3,  "word_query_cap": 3,  "session_cap": 1},
    "silver": {"daily_cards": 8,  "word_query_cap": 10, "session_cap": 4},
    "gold":   {"daily_cards": 12, "word_query_cap": 14, "session_cap": 10},
}


@dataclass
class Card:
    id: int
    interval_idx: int = -1
    next_review: Optional[int] = None


@dataclass
class SimState:
    words: list = field(default_factory=list)
    next_id: int = 0
    rejected_backlog_full: int = 0
    due_processed: int = 0
    due_carried_over: int = 0
    overflow_triggered: bool = False


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Simulate SRS v2.8 session engine")
    p.add_argument("--plan", choices=list(PLAN_DEFAULTS), default="free")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--daily-cards", type=int, default=None)
    p.add_argument("--word-query-cap", type=int, default=None)
    p.add_argument("--word-query-save-prob", type=float, default=0.5)
    p.add_argument("--session-cap", type=int, default=None)
    p.add_argument("--session-size", type=int, default=5)
    p.add_argument("--backlog-ceiling", type=int, default=50)
    p.add_argument("--fail-review-prob", type=float, default=0.15)
    p.add_argument("--overflow-session-threshold", type=int, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--report-every", type=int, default=5)
    p.add_argument("--csv", type=str, default=None)
    args = p.parse_args(argv)

    plan_caps = PLAN_DEFAULTS[args.plan]
    if args.daily_cards is None:
        args.daily_cards = plan_caps["daily_cards"]
    if args.word_query_cap is None:
        args.word_query_cap = plan_caps["word_query_cap"]
    if args.session_cap is None:
        args.session_cap = plan_caps["session_cap"]

    return args


def simulate(args: argparse.Namespace):
    rng = random.Random(args.seed)
    state = SimState()
    daily_rows: list[dict] = []

    def backlog_size() -> int:
        return sum(1 for w in state.words if w.interval_idx == -1)

    def add_backlog_card() -> None:
        state.next_id += 1
        state.words.append(Card(id=state.next_id, interval_idx=-1, next_review=None))

    def get_due_cards(day: int) -> list[Card]:
        due = [
            w for w in state.words
            if w.interval_idx >= 0 and w.next_review is not None and w.next_review <= day
        ]
        due.sort(key=lambda w: w.next_review)
        return due

    def get_backlog_cards() -> list[Card]:
        return [w for w in state.words if w.interval_idx == -1]

    def process_card(card: Card, day: int) -> None:
        if card.interval_idx == -1:
            card.interval_idx = 0
            card.next_review = day + 1
        else:
            if rng.random() < args.fail_review_prob:
                card.interval_idx = 0
                card.next_review = day + 1
            else:
                new_idx = min(card.interval_idx + 1, len(INTERVAL_DAYS) - 1)
                card.interval_idx = new_idx
                card.next_review = day + INTERVAL_DAYS[new_idx]

    for day in range(args.days):
        state.rejected_backlog_full = 0
        state.due_processed = 0
        state.due_carried_over = 0
        state.overflow_triggered = False

        for _ in range(args.daily_cards):
            if backlog_size() < args.backlog_ceiling:
                add_backlog_card()
            else:
                state.rejected_backlog_full += 1

        for _ in range(args.word_query_cap):
            if rng.random() < args.word_query_save_prob:
                if backlog_size() < args.backlog_ceiling:
                    add_backlog_card()
                else:
                    state.rejected_backlog_full += 1

        total_slots = args.session_cap * args.session_size
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

            state.due_processed = min(due_before, processed)
            state.due_carried_over = due_before - state.due_processed

        if args.overflow_session_threshold is not None and backlog_size() > args.overflow_session_threshold:
            state.overflow_triggered = True
            overflow_cards = get_backlog_cards()[:args.session_size]
            for card in overflow_cards:
                process_card(card, day)

        total_graduated = sum(1 for w in state.words if w.interval_idx >= 0)
        daily_rows.append({
            "day": day,
            "backlog": backlog_size(),
            "due_processed": state.due_processed,
            "due_carried_over": state.due_carried_over,
            "total_graduated": total_graduated,
            "rejected": state.rejected_backlog_full,
            "overflow": state.overflow_triggered,
        })

    last_7 = daily_rows[-7:]
    avg_backlog_last_7 = sum(r["backlog"] for r in last_7) / max(len(last_7), 1)

    max_carry_streak = 0
    current_carry_streak = 0
    for row in daily_rows:
        if row["due_carried_over"] > 0:
            current_carry_streak += 1
            max_carry_streak = max(max_carry_streak, current_carry_streak)
        else:
            current_carry_streak = 0

    days_with_rejection = sum(1 for r in daily_rows if r["rejected"] > 0)
    rejection_pct = (days_with_rejection / max(len(daily_rows), 1)) * 100
    overflow_count = sum(1 for r in daily_rows if r["overflow"])

    summary = {
        "avg_backlog_last_7": round(avg_backlog_last_7, 1),
        "max_carry_streak": max_carry_streak,
        "rejection_pct": round(rejection_pct, 1),
        "overflow_count": overflow_count,
        "overflow_enabled": args.overflow_session_threshold is not None,
    }

    return daily_rows, summary, args


def format_table(daily_rows: list[dict], summary: dict, args: argparse.Namespace) -> str:
    lines: list[str] = []

    lines.append(f"SRS Simulation: plan={args.plan}, days={args.days}, seed={args.seed}")
    lines.append(f"Config: daily_cards={args.daily_cards}, queries={args.word_query_cap}, "
                 f"sessions={args.session_cap}*{args.session_size}")
    lines.append(f"        backlog_ceil={args.backlog_ceiling}, fail_prob={args.fail_review_prob}, "
                 f"save_prob={args.word_query_save_prob}")
    if args.overflow_session_threshold is not None:
        lines.append(f"        overflow_threshold={args.overflow_session_threshold}")
    lines.append("")

    header = (f"{'Day':>4} {'Backlog':>8} {'DueProc':>8} {'DueCarry':>8} "
              f"{'Grad':>8} {'Rej':>6} {'Ovrflw':>6}")
    sep = "-" * len(header)
    lines.append(header)
    lines.append(sep)

    for row in daily_rows:
        if args.report_every > 0 and row["day"] % args.report_every == 0:
            lines.append(
                f"{row['day']:>4} {row['backlog']:>8} {row['due_processed']:>8} "
                f"{row['due_carried_over']:>8} {row['total_graduated']:>8} "
                f"{row['rejected']:>6} {'Yes' if row['overflow'] else '':>6}"
            )

    lines.append(sep)
    last = daily_rows[-1]
    lines.append(
        f"{last['day']:>4} {last['backlog']:>8} {last['due_processed']:>8} "
        f"{last['due_carried_over']:>8} {last['total_graduated']:>8} "
        f"{last['rejected']:>6} {'Yes' if last['overflow'] else '':>6}"
    )
    lines.append("")

    lines.append("Final Summary:")
    lines.append(f"  Average backlog (last 7 days):    {summary['avg_backlog_last_7']}")
    lines.append(f"  Max carry streak (days):          {summary['max_carry_streak']}")
    lines.append(f"  Days with rejection (%):          {summary['rejection_pct']}%")
    if summary["overflow_enabled"]:
        lines.append(f"  Overflow sessions triggered:      {summary['overflow_count']}")

    return "\n".join(lines)


def write_csv(daily_rows: list[dict], summary: dict, args: argparse.Namespace, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "day", "backlog", "due_processed", "due_carried_over",
            "total_graduated", "rejected", "overflow",
        ])
        for row in daily_rows:
            writer.writerow([
                row["day"], row["backlog"], row["due_processed"],
                row["due_carried_over"], row["total_graduated"],
                row["rejected"], "Yes" if row["overflow"] else "",
            ])
        writer.writerow([])
        writer.writerow(["summary", "value"])
        writer.writerow(["avg_backlog_last_7", summary["avg_backlog_last_7"]])
        writer.writerow(["max_carry_streak", summary["max_carry_streak"]])
        writer.writerow(["rejection_pct", summary["rejection_pct"]])
        if summary["overflow_enabled"]:
            writer.writerow(["overflow_count", summary["overflow_count"]])


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    daily_rows, summary, _ = simulate(args)
    output = format_table(daily_rows, summary, args)
    print(output)
    if args.csv:
        write_csv(daily_rows, summary, args, args.csv)
        print(f"CSV written to: {args.csv}")


if __name__ == "__main__":
    main()
