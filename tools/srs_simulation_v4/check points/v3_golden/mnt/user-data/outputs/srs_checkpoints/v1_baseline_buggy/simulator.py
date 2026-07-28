"""SRS v1 (lab) — Adaptive Hybrid engine with debt-throttled generation,
a waiting-room ceiling, and lateness-triggered archiving.

Pure Python, no deps.
"""
import math
import random
from dataclasses import dataclass, field
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
    "fluctuating": {"attend": None, "q_lo": 0, "q_hi": 3, "save_prob": 0.50, "forget": 0.20},  # attend computed per-day
}

ARCHIVE_SCORE_THRESHOLD = 1.0
ARCHIVE_OVERDUE_DAYS = 45


@dataclass
class Card:
    id: int
    idx: int = -1
    score: float = 2.0
    next_review: Optional[int] = None
    due_since: Optional[int] = None  # day it first became due (for lateness tracking)


@dataclass
class SimConfig:
    plan: str = "free"
    persona: str = "average"
    days: int = 180
    seed: Optional[int] = 42
    jitter: float = 0.15  # +/- interval randomization to avoid clumping


def _attend_prob(persona: str, day: int, rng: random.Random) -> bool:
    p = PERSONAS[persona]
    if persona == "fluctuating":
        # 21-day motivation cycle oscillating between 0.30 and 0.90
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
    archived_count = 0
    total_new_words = 0
    lateness_samples = []

    def new_card(idx=-1, next_review=None, due_since=None) -> Card:
        nonlocal next_id
        next_id += 1
        return Card(id=next_id, idx=idx, next_review=next_review, due_since=due_since)

    daily_slots = plan["sessions"] * plan["session_size"]
    queue_cap = plan["queue_cap_days"] * daily_slots

    for day in range(cfg.days):
        attended = _attend_prob(cfg.persona, day, rng)

        # ---- Queries (user-pulled, NOT throttled by backlog pressure) ----
        queries_today = 0
        saved_today = 0
        if attended:
            q_hi = min(persona["q_hi"], plan["query_daily_cap"])
            q_lo = min(persona["q_lo"], q_hi)
            queries_today = rng.randint(q_lo, q_hi)
            for _ in range(queries_today):
                if rng.random() < persona["save_prob"]:
                    c = new_card(idx=-1, next_review=None)
                    query_backlog.append(c)
                    saved_today += 1

        # ---- Due cards ----
        due = [c for c in active if c.next_review is not None and c.next_review <= day]
        for c in due:
            if c.due_since is None:
                c.due_since = c.next_review
        due.sort(key=lambda c: c.due_since)
        due_before = len(due)

        # ---- Archive rot: overdue + weak cards not attended to for too long ----
        archived_today = 0
        if attended:
            still_active = []
            for c in active:
                if (c.next_review is not None and c.due_since is not None
                        and (day - c.due_since) > ARCHIVE_OVERDUE_DAYS and c.score < ARCHIVE_SCORE_THRESHOLD):
                    archived_today += 1
                    archived_count += 1
                else:
                    still_active.append(c)
            active = still_active
            due = [c for c in due if c in active]

        due_slots_used = 0
        query_slots_used = 0
        ai_generated = 0

        if attended:
            remaining = daily_slots
            tier1 = due[:remaining]
            due_slots_used = len(tier1)
            remaining -= due_slots_used

            tier2 = query_backlog[:remaining]
            query_backlog = query_backlog[len(tier2):]
            query_slots_used = len(tier2)
            remaining -= query_slots_used

            # ---- Debt-based throttle for Tier 3 (new AI cards) ----
            backlog_pressure = (due_before - due_slots_used) + len(query_backlog)
            if backlog_pressure >= queue_cap:
                ai_cap_today = 0  # waiting room: pause generation entirely
            else:
                throttle = max(0.25, 1.0 - (backlog_pressure / queue_cap) * 0.75)
                ai_cap_today = math.floor(plan["ai_daily_cap"] * throttle)

            ai_take = min(remaining, ai_cap_today)
            tier3 = [new_card(idx=-1, next_review=None) for _ in range(ai_take)]
            ai_generated = ai_take
            total_new_words += ai_take

            candidates = tier1 + tier2 + tier3

            for c in candidates:
                was_due = c in tier1
                if was_due:
                    lateness_samples.append(day - c.due_since)

                if c.idx == -1:
                    c.idx = 0
                    c.next_review = day + INTERVALS[0]
                    c.due_since = None
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
                        c.next_review = day + max(1, round(INTERVALS[c.idx] * jitter))
                    c.due_since = None

        due_remaining = due_before - due_slots_used

        rows.append({
            "day": day, "attended": attended,
            "due_processed": due_slots_used, "due_remaining": due_remaining,
            "queries": queries_today, "q_saved": saved_today, "q_backlog": len(query_backlog),
            "ai_gen": ai_generated, "ai_cap": plan["ai_daily_cap"],
            "active": len(active), "archived_today": archived_today,
        })

    learned = sum(1 for c in active if c.idx >= 2)  # idx>=2 == survived 2+ reviews
    avg_score = (sum(c.score for c in active) / len(active)) if active else 0.0
    max_backlog = max(r["due_remaining"] + r["q_backlog"] for r in rows)
    avg_lateness = (sum(lateness_samples) / len(lateness_samples)) if lateness_samples else 0.0
    max_lateness = max(lateness_samples) if lateness_samples else 0

    summary = {
        "plan": cfg.plan, "persona": cfg.persona, "days": cfg.days,
        "total_new_words": total_new_words,
        "final_active_cards": len(active),
        "learned_words": learned,
        "avg_score": round(avg_score, 2),
        "max_backlog": max_backlog,
        "avg_lateness_days": round(avg_lateness, 1),
        "max_lateness_days": max_lateness,
        "archived_lost_words": archived_count,
        "avg_ai_gen_per_day": round(total_new_words / cfg.days, 2),
    }
    return rows, summary
