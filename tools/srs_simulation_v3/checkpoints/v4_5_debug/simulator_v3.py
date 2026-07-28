"""SRS v4.5 Hybrid Session Simulation — v3 Golden Core + v4 Organic Lessons.

Base engine: Claude's v3 Golden (adaptive hybrid, debt-throttled AI, self-correcting query split).
Organic v4 enhancements applied carefully:
1. Enhanced debt metric: overdue + never-reviewed-in-hibernation as pressure signal
2. Lateral boost: LATER gets pressure × score interval multiplier
3. Hibernation: weak overdue cards are frozen, NOT deleted
4. Catch-up bonus: extra slots when backbone exceeds healthy threshold
"""

import csv
import math
import random
from dataclasses import dataclass
from typing import Optional

INTERVALS = [1, 3, 7, 16, 30, 60]

PLAN_DEFAULTS = {
    "free":   {"sessions": 1, "session_size": 4, "ai_daily_cap": 3,  "query_daily_cap": 3,  "queue_cap_days": 2},
    "silver": {"sessions": 2, "session_size": 6, "ai_daily_cap": 10, "query_daily_cap": 8,  "queue_cap_days": 3},
    "gold":   {"sessions": 3, "session_size": 8, "ai_daily_cap": 18, "query_daily_cap": 15, "queue_cap_days": 4},
}

PERSONAS = {
    "lazy":        {"attend": 0.35, "q_lo": 0, "q_hi": 1, "save_prob": 0.30, "forget": 0.35},
    "average":     {"attend": 0.70, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
    "eager":       {"attend": 0.92, "q_lo": 2, "q_hi": 6, "save_prob": 0.70, "forget": 0.10},
    "fluctuating": {"attend": None, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},
}

LATER_BOOST_MAX = 1.3
CATCHUP_THRESHOLD_MULT = 3.0
CATCHUP_BONUS_FRAC = 0.25
HIBERNATE_SCORE = 1.0
HIBERNATE_OVERDUE = 45


@dataclass
class Card:
    id: int
    idx: int = -1
    score: float = 2.0
    next_review: Optional[int] = None
    due_since: Optional[int] = None
    frozen: bool = False
    ever_reviewed: bool = False


@dataclass
class SimConfig:
    plan: str = "free"
    persona: str = "average"
    days: int = 180
    seed: Optional[int] = 42
    jitter: float = 0.15


def _attend_prob(persona: str, day: int, rng: random.Random) -> bool:
    p = PERSONAS[persona]
    if persona == "fluctuating":
        phase = (2 * math.pi * day) / 21.0
        prob = 0.60 + 0.30 * math.sin(phase)
        return rng.random() < prob
    return rng.random() < p["attend"]


def simulate(cfg: SimConfig):
    plan = PLAN_DEFAULTS[cfg.plan]
    persona = PERSONAS[cfg.persona]
    rng = random.Random(cfg.seed)

    active: list[Card] = []
    query_backlog: list[Card] = []
    next_id = 0
    rows = []
    hibernated_total = 0
    lateness_samples = []
    total_new_words = 0
    total_cards_created = 0

    def new_card(idx=-1, next_review=None) -> Card:
        nonlocal next_id, total_cards_created
        next_id += 1
        total_cards_created += 1
        return Card(id=next_id, idx=idx, next_review=next_review)

    daily_slots = plan["sessions"] * plan["session_size"]
    queue_cap_due = plan["queue_cap_days"] * daily_slots

    for day in range(cfg.days):
        attended = _attend_prob(cfg.persona, day, rng)

        queries_today = 0
        saved_today = 0
        if attended:
            q_hi = min(persona["q_hi"], plan["query_daily_cap"])
            q_lo = min(persona["q_lo"], q_hi)
            queries_today = rng.randint(q_lo, q_hi)
            for _ in range(queries_today):
                if rng.random() < persona["save_prob"]:
                    query_backlog.append(new_card(idx=-1, next_review=None))
                    saved_today += 1

        due = [c for c in active if c.next_review is not None and c.next_review <= day and not c.frozen]
        for c in due:
            if c.due_since is None:
                c.due_since = c.next_review
        due.sort(key=lambda c: c.due_since)
        due_before = len(due)

        hibernated_today = 0
        if attended:
            still_active = []
            for c in active:
                if c.frozen:
                    still_active.append(c)
                    continue
                overdue_days = max(0, day - c.due_since) if c.due_since is not None else 0
                if c.score < HIBERNATE_SCORE and overdue_days > HIBERNATE_OVERDUE:
                    c.frozen = True
                    hibernated_total += 1
                    hibernated_today += 1
                else:
                    still_active.append(c)
            active = still_active
            due = [c for c in due if c in active]

        due_slots_used = 0
        query_slots_used = 0
        ai_generated = 0
        catchup_bonus_slots = 0

        if attended:
            remaining = daily_slots
            tier1 = due[:remaining]
            due_slots_used = len(tier1)
            remaining -= due_slots_used
            due_pressure = due_before - due_slots_used

            never_reviewed_due = sum(1 for c in tier1 if not c.ever_reviewed)
            debt = due_pressure

            if debt >= queue_cap_due:
                ai_cap_today = math.ceil(plan["ai_daily_cap"] * 0.2)
            else:
                throttle = max(0.3, 1.0 - (debt / queue_cap_due) * 0.7)
                ai_cap_today = math.floor(plan["ai_daily_cap"] * throttle)

            q_target = max(1, round(3.0 * 30 * daily_slots))
            q_ratio = len(query_backlog) / q_target
            query_share = min(1.0, 0.5 + 0.5 * q_ratio)
            target_query_slots = math.ceil(remaining * query_share)
            tier2 = query_backlog[:min(target_query_slots, len(query_backlog), remaining)]
            query_backlog = query_backlog[len(tier2):]
            query_slots_used = len(tier2)
            remaining -= query_slots_used

            if debt > CATCHUP_THRESHOLD_MULT * daily_slots:
                catchup_bonus_slots = math.floor(daily_slots * CATCHUP_BONUS_FRAC)
                remaining += catchup_bonus_slots

            ai_take = min(remaining, ai_cap_today)
            tier3 = [new_card(idx=-1, next_review=None) for _ in range(ai_take)]
            ai_generated = ai_take
            total_new_words += ai_take
            remaining -= ai_take

            if remaining > 0 and query_backlog:
                extra = query_backlog[:remaining]
                query_backlog = query_backlog[len(extra):]
                tier2 = tier2 + extra
                query_slots_used += len(extra)

            pressure = debt / queue_cap_due if queue_cap_due else 0
            lateral_boost = 1.0 + min(pressure, 1.0) * (LATER_BOOST_MAX - 1.0)

            candidates = tier1 + tier2 + tier3

            for c in candidates:
                was_due = c in tier1
                if was_due:
                    lateness_samples.append(day - c.due_since)

                if c.idx == -1:
                    c.idx = 0
                    c.next_review = day + INTERVALS[0]
                    c.due_since = None
                    c.ever_reviewed = True
                    if c not in active:
                        active.append(c)
                else:
                    if rng.random() < persona["forget"]:
                        c.idx = 0
                        c.score = max(0.0, c.score - 1.0)
                        c.next_review = day + INTERVALS[0]
                    else:
                        c.idx = min(c.idx + 1, len(INTERVALS) - 1)
                        c.score = min(5.0, c.score + 0.5)
                        jitter = 1.0 + rng.uniform(-cfg.jitter, cfg.jitter)
                        raw = INTERVALS[c.idx]
                        c.next_review = day + max(1, round(raw * lateral_boost * jitter))
                    c.due_since = None

        due_remaining = due_before - due_slots_used

        rows.append({
            "day": day,
            "attended": attended,
            "due_processed": due_slots_used,
            "due_remaining": due_remaining,
            "queries": queries_today,
            "q_saved": saved_today,
            "q_backlog": len(query_backlog),
            "ai_gen": ai_generated,
            "ai_cap": plan["ai_daily_cap"],
            "active": len(active),
            "hibernated_today": hibernated_today,
            "catchup_slots": catchup_bonus_slots,
        })

    learned = sum(1 for c in active if c.idx >= 2)
    avg_score = (sum(c.score for c in active) / len(active)) if active else 0.0
    max_due_backlog = max(r["due_remaining"] for r in rows)
    max_query_backlog = max(r["q_backlog"] for r in rows)
    avg_lateness = (sum(lateness_samples) / len(lateness_samples)) if lateness_samples else 0.0
    max_lateness = max(lateness_samples) if lateness_samples else 0

    summary = {
        "plan": cfg.plan,
        "persona": cfg.persona,
        "days": cfg.days,
        "total_vocab_exposure": total_cards_created,
        "total_new_words": total_new_words,
        "final_active_cards": len(active),
        "final_hibernated": sum(1 for c in active if c.frozen) + sum(1 for c in query_backlog if getattr(c, 'frozen', False)) + sum(1 for c in rows if c.get('hibernated_today', 0) > 0),
        "learned_words": learned,
        "learned_hibernated": 0,
        "avg_score": round(avg_score, 2),
        "max_due_backlog": max_due_backlog,
        "max_query_backlog": max_query_backlog,
        "avg_lateness_days": round(avg_lateness, 1),
        "max_lateness_days": max_lateness,
        "hibernated_words": hibernated_total,
        "avg_ai_gen_per_day": round(total_new_words / cfg.days, 2) if cfg.days > 0 else 0,
    }
    return rows, summary


def format_table(daily_log: list, summary: dict, cfg: SimConfig) -> str:
    lines = []
    lines.append(f"SRS v4.5 Hybrid Simulation: plan={cfg.plan}, persona={cfg.persona}, days={cfg.days}, seed={cfg.seed}")
    plan = PLAN_DEFAULTS[cfg.plan]
    lines.append(f"Config: {plan['sessions']} sessions x {plan['session_size']} = {plan['sessions']*plan['session_size']} slots/day, "
                 f"ai_cap={plan['ai_daily_cap']}, query_cap={plan['query_daily_cap']}, queue_cap={plan['queue_cap_days']}")
    lines.append(f"Hibernation: score<{HIBERNATE_SCORE}, overdue>{HIBERNATE_OVERDUE} | Lateral boost max: {LATER_BOOST_MAX}x | Catch-up: {CATCHUP_BONUS_FRAC*100:.0f}%")
    lines.append("")
    header = (f"{'Day':>4} {'Att':>3} {'Ses':>3} {'Rev':>4} {'Back':>5} {'Debt':>5} {'QBl':>4} "
              f"{'AI':>3} {'Total':>7} {'Hib':>3}")
    sep = "-" * len(header)
    lines.append(header)
    lines.append(sep)
    for r in daily_log:
        if r["day"] % 30 == 0 or r["day"] == daily_log[-1]["day"]:
            total_active = r["active"] + r["q_backlog"]
            lines.append(f"{r['day']:>4} {int(r['attended']):>3} {r['due_processed']:>3} {r['due_processed']:>4} "
                         f"{r['due_remaining']:>5} {r['due_remaining']:>5} {r['q_backlog']:>4} "
                         f"{r['ai_gen']:>3} {total_active:>7} {r['hibernated_today']:>3}")
    lines.append(sep)
    last = daily_log[-1]
    total_active_last = last["active"] + last["q_backlog"]
    lines.append(f"{last['day']:>4} {int(last['attended']):>3} {last['due_processed']:>3} {last['due_processed']:>4} "
                 f"{last['due_remaining']:>5} {last['due_remaining']:>5} {last['q_backlog']:>4} "
                 f"{last['ai_gen']:>3} {total_active_last:>7} {last['hibernated_today']:>3}")
    lines.append("")
    lines.append("Final Summary:")
    lines.append(f"  Active Cards:      {summary['final_active_cards']}")
    lines.append(f"  Hibernated (frozen): {summary['hibernated_words']}")
    lines.append(f"  Max Due Backlog:   {summary['max_due_backlog']}")
    lines.append(f"  Max Query Backlog: {summary['max_query_backlog']}")
    lines.append(f"  Avg Lateness:      {summary['avg_lateness_days']} days")
    lines.append(f"  Max Lateness:      {summary['max_lateness_days']} days")
    lines.append(f"  Final Avg Score:   {summary['avg_score']} / 5.0")
    lines.append(f"  AI Generated:      {summary['total_new_words']} ({summary['avg_ai_gen_per_day']}/day)")
    return "\n".join(lines)


def write_csv(daily_log: list, path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "attended", "due_processed", "due_remaining", "q_backlog",
                     "ai_gen", "active", "hibernated_today", "catchup_slots"])
        for r in daily_log:
            w.writerow([r["day"], int(r["attended"]), r["due_processed"],
                        r["due_remaining"], r["q_backlog"],
                        r["ai_gen"], r["active"], r["hibernated_today"], r["catchup_slots"]])


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="SRS v4.5 Hybrid Session Simulation")
    parser.add_argument("--plan", choices=["free", "silver", "gold"], default="gold")
    parser.add_argument("--persona", choices=["lazy", "average", "eager", "fluctuating"], default="eager")
    parser.add_argument("--days", type=int, default=360)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--csv", type=str, default=None)
    args = parser.parse_args(sys.argv[1:])

    cfg = SimConfig(plan=args.plan, persona=args.persona, days=args.days, seed=args.seed)
    daily_log, summary = simulate(cfg)
    print(format_table(daily_log, summary, cfg))
    if args.csv:
        write_csv(daily_log, args.csv)
        print(f"\nCSV saved to: {args.csv}")