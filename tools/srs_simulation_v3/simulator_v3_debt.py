"""CHECKPOINT v3 — debt_metric (fix on top of v2)

BUG FOUND in v2: `active_queue_size()` counted every scheduled card,
including cards nicely spread 1-30 days into the future by the SRS
algorithm itself. A healthy spaced-repetition pool is SUPPOSED to hold
hundreds of cards that are not due today -- that is not backlog, that is
just "vocabulary the user already knows and is maintaining." Capping on
total scheduled count made the cap trigger constantly for eager users even
while their actual overdue backlog was ~0, stranding 300-800 cards in the
waiting room for good.

FIX: queue pressure is now measured as "review debt" only:
    debt = (cards due today or overdue) + (cards never reviewed even once)
Cards on a healthy future schedule (next_review_day in the future AND
already reviewed at least once) do NOT count against the cap. This is the
correct notion of "the user actually owes work"; it's what the earlier
`backlog_count` / `pregrad_pool` metrics were already measuring separately
-- this checkpoint just makes the admission/throttle logic use that
instead of raw pool size.

Everything else is unchanged from v2 (see that file's docstring for the
full rationale of the queue-cap + waiting-room + soft-throttle design).
"""

import math
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

# Active-queue cap = roughly N days worth of full plan capacity.
# This is the one new "dial" this checkpoint introduces.
QUEUE_CAP_DAYS = 3
THROTTLE_START_FRACTION = 0.70   # start scaling down Tier-3 past 70% of cap
THROTTLE_FLOOR = 0.15            # never fully cut new-word generation, just slow it
OVERDUE_DEMOTE_DAYS = 60
WASTE_THRESHOLD_DAYS = 45
CATCHUP_BONUS_FRACTION = 0.25    # up to +25% slots on heavy-overdue attend days


@dataclass
class Persona:
    name: str
    attendance_prob: float
    session_completion: float
    forget_rate: float
    query_lambda: float
    save_gate_rate: float
    fluctuating: bool = False

    def attendance_today(self, day: int, rng: random.Random) -> float:
        if not self.fluctuating:
            return self.attendance_prob
        wave = 0.5 + 0.4 * math.sin(2 * math.pi * day / 21.0)
        noise = rng.uniform(-0.1, 0.1)
        return max(0.15, min(0.95, wave + noise))

    def forget_today(self, day: int, rng: random.Random) -> float:
        if not self.fluctuating:
            return self.forget_rate
        wave = 0.18 + 0.10 * math.sin(2 * math.pi * (day + 10) / 21.0)
        return max(0.05, min(0.35, wave))


PERSONAS = {
    "lazy":        Persona("lazy", 0.40, 0.55, 0.25, 0.6, 0.30),
    "moderate":    Persona("moderate", 0.72, 0.85, 0.15, 1.6, 0.50),
    "eager":       Persona("eager", 0.92, 1.00, 0.08, 3.5, 0.65),
    "fluctuating": Persona("fluctuating", 0.6, 0.75, 0.15, 1.8, 0.45, fluctuating=True),
}


@dataclass
class SimConfig:
    plan: str = "free"
    persona: str = "moderate"
    days: int = 90
    session_size: Optional[int] = None
    sessions: Optional[int] = None
    ai_daily_cap: Optional[int] = None
    query_daily_cap: Optional[int] = None
    seed: Optional[int] = None
    random_intervals: bool = True
    queue_cap_days: int = QUEUE_CAP_DAYS

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
    interval_set: list = None
    next_review_day: Optional[int] = None  # None while in waiting room
    created_day: int = 0
    ever_reviewed: bool = False
    origin: str = "ai"


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def simulate(cfg: SimConfig):
    rng = random.Random(cfg.seed)
    persona = PERSONAS[cfg.persona]
    active_cards: list[Card] = []
    waiting_room: list[Card] = []
    next_id = 0
    daily_log = []
    overdue_delays = []

    plan_slots_per_day = cfg.sessions * cfg.session_size
    queue_cap = max(plan_slots_per_day * cfg.queue_cap_days, plan_slots_per_day * 2)

    def active_queue_size(day):
        # "Review debt": cards due/overdue right now, or never reviewed even
        # once. Cards already reviewed at least once and sitting on a
        # healthy future schedule do NOT count -- that's normal SRS
        # steady-state pool, not backlog.
        debt = 0
        for c in active_cards:
            if not c.ever_reviewed:
                debt += 1
            elif c.next_review_day is not None and c.next_review_day <= day:
                debt += 1
        return debt

    def new_card(day, origin):
        nonlocal next_id
        next_id += 1
        iv_set = rng.choice(INTERVAL_SETS) if cfg.random_intervals else DEFAULT_INTERVALS
        return Card(card_id=next_id, interval_set=iv_set, created_day=day, origin=origin)

    def admit_or_wait(card, day):
        if active_queue_size(day) < queue_cap:
            card.next_review_day = day + 1
            active_cards.append(card)
        else:
            waiting_room.append(card)

    def admit_from_waiting_room(day):
        admitted = 0
        while waiting_room and active_queue_size(day) < queue_cap:
            c = waiting_room.pop(0)
            c.next_review_day = day + 1
            active_cards.append(c)
            admitted += 1
        return admitted

    def get_overdue(day):
        overdue = [c for c in active_cards if c.next_review_day is not None and c.next_review_day <= day]
        overdue.sort(key=lambda c: c.next_review_day)
        return overdue

    for day in range(cfg.days):
        for c in active_cards:
            if c.next_review_day is not None and (day - c.next_review_day) > OVERDUE_DEMOTE_DAYS:
                c.srs_stage = 0
                c.next_review_day = day + 1

        # Word-query desire vs quota -- quota is UNTOUCHED by backlog state.
        desired_queries = _poisson(rng, persona.query_lambda)
        served_queries = min(desired_queries, cfg.query_daily_cap)
        queries_blocked = max(0, desired_queries - served_queries)
        for _ in range(served_queries):
            if rng.random() < persona.save_gate_rate:
                admit_or_wait(new_card(day, origin="query"), day)

        # Daily admission from waiting room as headroom allows.
        admitted_today = admit_from_waiting_room(day)

        attend_p = persona.attendance_today(day, rng)
        attends = rng.random() < attend_p
        sessions_done = 0
        if attends:
            sessions_done = round(cfg.sessions * persona.session_completion)
            sessions_done = max(1, min(cfg.sessions, sessions_done))
        slots_today = sessions_done * cfg.session_size

        overdue = get_overdue(day)
        overdue_before = len(overdue)

        # Mild elastic catch-up: heavy overdue + user showed up -> bonus slots.
        if attends and overdue_before > slots_today:
            bonus = math.floor(slots_today * CATCHUP_BONUS_FRACTION)
            slots_today += bonus

        candidates = overdue[:slots_today]
        remaining = slots_today - len(candidates)

        # Tier-3 AI generation, soft-throttled by queue pressure.
        fill_fraction = active_queue_size(day) / queue_cap if queue_cap else 0
        if fill_fraction <= THROTTLE_START_FRACTION:
            throttle = 1.0
        else:
            # linearly scale from 1.0 down to THROTTLE_FLOOR as fill goes 0.7 -> 1.0
            span = 1.0 - THROTTLE_START_FRACTION
            over = min(fill_fraction - THROTTLE_START_FRACTION, span)
            throttle = 1.0 - (1.0 - THROTTLE_FLOOR) * (over / span)
        ai_budget = max(0, math.floor(cfg.ai_daily_cap * throttle))
        ai_take = min(remaining, ai_budget)
        for _ in range(ai_take):
            admit_or_wait(new_card(day, origin="ai"), day)

        forget_rate_today = persona.forget_today(day, rng)
        reviews_done = 0
        for card in candidates:
            overdue_delays.append(day - card.next_review_day)
            card.ever_reviewed = True
            if rng.random() < forget_rate_today:
                card.srs_stage = 0
                card.next_review_day = day + card.interval_set[0]
            else:
                new_stage = min(card.srs_stage + 1, 4)
                card.srs_stage = new_stage
                card.next_review_day = day + card.interval_set[new_stage]
            reviews_done += 1

        backlog_count = overdue_before - reviews_done
        pregrad_pool = sum(1 for c in active_cards if not c.ever_reviewed) + len(waiting_room)
        wasted_today = sum(
            1 for c in active_cards
            if not c.ever_reviewed and (day - c.created_day) > WASTE_THRESHOLD_DAYS
        )

        daily_log.append({
            "day": day, "attended": attends, "sessions_done": sessions_done,
            "reviews_done": reviews_done, "backlog_count": backlog_count,
            "desired_queries": desired_queries, "served_queries": served_queries,
            "queries_blocked": queries_blocked,
            "ai_cards_served": ai_take, "ai_throttle": round(throttle, 2),
            "total_cards": len(active_cards) + len(waiting_room),
            "waiting_room": len(waiting_room), "admitted_today": admitted_today,
            "pregrad_pool": pregrad_pool, "wasted_cards": wasted_today,
            "plan_slots": plan_slots_per_day, "slots_today": slots_today,
            "queue_cap": queue_cap,
        })

    total_generated = len(active_cards) + len(waiting_room)
    final_wasted = daily_log[-1]["wasted_cards"] if daily_log else 0
    total_queries_desired = sum(r["desired_queries"] for r in daily_log)
    total_queries_served = sum(r["served_queries"] for r in daily_log)
    total_queries_blocked = sum(r["queries_blocked"] for r in daily_log)
    summary = {
        "persona": cfg.persona, "plan": cfg.plan, "queue_cap": queue_cap,
        "final_total_cards": total_generated,
        "final_waiting_room": len(waiting_room),
        "final_wasted_cards": final_wasted,
        "wasted_pct": round(100 * final_wasted / max(1, total_generated), 1),
        "max_backlog": max((r["backlog_count"] for r in daily_log), default=0),
        "avg_backlog_last30": round(sum(r["backlog_count"] for r in daily_log[-30:]) /
                                     max(1, len(daily_log[-30:])), 1),
        "avg_overdue_delay": round(sum(overdue_delays) / max(1, len(overdue_delays)), 2),
        "max_overdue_delay": max(overdue_delays, default=0),
        "attendance_rate_pct": round(100 * sum(r["attended"] for r in daily_log) / max(1, len(daily_log)), 1),
        "query_fulfillment_pct": round(100 * total_queries_served / max(1, total_queries_desired), 1),
        "total_queries_blocked": total_queries_blocked,
        "avg_ai_throttle": round(sum(r["ai_throttle"] for r in daily_log) / max(1, len(daily_log)), 2),
    }
    return daily_log, summary


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="SRS v3 debt_metric simulation")
    parser.add_argument("--plan", choices=["free", "silver", "gold"], default="gold")
    parser.add_argument("--persona", choices=["lazy", "moderate", "eager", "fluctuating"], default="eager")
    parser.add_argument("--days", type=int, default=360)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--queue-cap-days", type=int, default=3)
    args = parser.parse_args()

    cfg = SimConfig(
        plan=args.plan,
        persona=args.persona,
        days=args.days,
        seed=args.seed,
        queue_cap_days=args.queue_cap_days,
    )

    daily_log, summary = simulate(cfg)

    print(f"SRS v3 debt_metric Simulation: plan={cfg.plan}, persona={cfg.persona}, days={cfg.days}, seed={cfg.seed}")
    print(f"Queue cap: {summary['queue_cap']} (plan slots/day: {cfg.sessions * cfg.session_size} * {args.queue_cap_days} days)")
    print()
    print("Final Summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")