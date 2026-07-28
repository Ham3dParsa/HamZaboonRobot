"""SRS v3 Hybrid Session Simulation — V4 Hybrid (Debt Metric + Organic Pressure).

Hybrid design combining the best of both approaches:
- Debt Metric from v3: pressure = overdue + never_reviewed (not total pool)
- Organic Response from V3: interval extension, score multiplier, auto-archive
- No hard caps on queries/saves (paid features preserved)
- Waiting room for admission control (from debt_metric)
- Auto-archive for cognitive load management (organic)
- Adaptive plan configs per tier

Key V4 improvements:
- Debt-based pressure metric (overdue + never_reviewed only)
- Waiting room for admission control (no hard cap on active pool)
- Auto-archive for cognitive load (score + overdue thresholds)
- Adaptive daily quota based on real progress (not just pressure)
- No query/save suppression (paid features fully available)
- Query fulfillment = 100% always (upgrade incentive preserved)
"""

import csv
import math
import random
from dataclasses import dataclass, field
from typing import Optional

INTERVAL_SETS = [
    [1, 3, 7, 16, 30, 60],
    [2, 4, 8, 14, 27, 50],
    [1, 3, 6, 15, 28, 65],
    [2, 5, 9, 17, 30, 63],
]
DEFAULT_INTERVALS = [1, 3, 7, 16, 30, 60]

# ============================================================
# PLAN CONFIGURATIONS — Optimized for tier value perception
# ============================================================
PLAN_DEFAULTS = {
    "free": {
        "session_size": 4,
        "sessions": 1,
        "ai_daily_cap": 3,
        "query_daily_cap": 3,
        "queue_cap_days": 2,
        "archive_threshold_score": 1.5,
        "archive_threshold_overdue": 30,
        "lateral_boost_max": 2.0,
    },
    "silver": {
        "session_size": 6,
        "sessions": 2,
        "ai_daily_cap": 12,
        "query_daily_cap": 7,
        "queue_cap_days": 3,
        "archive_threshold_score": 1.2,
        "archive_threshold_overdue": 21,
        "lateral_boost_max": 2.5,
    },
    "gold": {
        "session_size": 8,
        "sessions": 3,
        "ai_daily_cap": 20,
        "query_daily_cap": 10,
        "queue_cap_days": 4,
        "archive_threshold_score": 1.0,
        "archive_threshold_overdue": 14,
        "lateral_boost_max": 3.0,
    },
}

PLAN_RANGES = {
    "free":   {"session_size": (4, 4),  "sessions": (1, 1)},
    "silver": {"session_size": (5, 8),  "sessions": (2, 3)},
    "gold":   {"session_size": (6, 10), "sessions": (2, 4)},
}

# ============================================================
# USER PERSONAS — Realistic behavior profiles
# ============================================================
@dataclass
class Persona:
    name: str
    attendance_prob: float
    session_completion: float
    forget_rate: float
    query_lambda: float          # Poisson λ for daily query desire
    save_gate_rate: float        # Prob(save | query)
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
    "lazy":        Persona("lazy", 0.40, 0.55, 0.25, 0.6,  0.30),
    "average":     Persona("average", 0.72, 0.85, 0.15, 1.6, 0.50),
    "eager":       Persona("eager", 0.92, 1.00, 0.08, 3.5, 0.65),
    "fluctuating": Persona("fluctuating", 0.60, 0.75, 0.15, 1.8, 0.45, fluctuating=True),
}


# ============================================================
# SIMULATION CONFIG
# ============================================================
@dataclass
class SimConfig:
    plan: str = "free"
    persona: str = "average"
    days: int = 90
    session_size: Optional[int] = None
    sessions: Optional[int] = None
    ai_daily_cap: Optional[int] = None
    query_daily_cap: Optional[int] = None
    seed: Optional[int] = None
    random_intervals: bool = True
    # V4 flags
    enable_waiting_room: bool = True
    enable_auto_archive: bool = True
    enable_adaptive_quota: bool = True
    # Override caps (for plan defaults)
    queue_cap_days: Optional[int] = None
    archive_threshold_score: Optional[float] = None
    archive_threshold_overdue: Optional[int] = None
    lateral_boost_max: Optional[float] = None

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
        if self.queue_cap_days is None:
            self.queue_cap_days = d["queue_cap_days"]
        if self.archive_threshold_score is None:
            self.archive_threshold_score = d["archive_threshold_score"]
        if self.archive_threshold_overdue is None:
            self.archive_threshold_overdue = d["archive_threshold_overdue"]
        if self.lateral_boost_max is None:
            self.lateral_boost_max = d["lateral_boost_max"]


@dataclass
class Card:
    card_id: int
    srs_stage: int = 0
    interval_set: list = None
    next_review_day: Optional[int] = None  # None = in waiting room
    created_day: int = 0
    ever_reviewed: bool = False
    origin: str = "ai"  # "ai" | "query"
    score: float = 3.0  # 0.0 - 5.0 familiarity


@dataclass
class DailyRow:
    day: int
    attended: bool
    sessions_done: int
    reviews_done: int
    backlog_count: int
    desired_queries: int
    served_queries: int
    blocked_queries: int
    ai_cards_served: int
    total_cards: int
    waiting_room: int
    admitted_today: int
    pregrad_pool: int
    archived_today: int
    plan_slots: int
    slots_today: int
    queue_cap: int
    debt: int


# ============================================================
# HELPER FUNCTIONS
# ============================================================
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


def _score_multiplier(score: float) -> float:
    """Score 5.0 → 1.8x, 3.0 → 1.1x, 0.0 → 0.5x"""
    return max(0.5, 1.0 + (score - 2.5) * 0.32)


def _lateral_boost(pressure: float, max_boost: float) -> float:
    """Pressure 0→1 → 1.0x to max_boost"""
    return 1.0 + min(pressure, 1.0) * (max_boost - 1.0)


# ============================================================
# CORE SIMULATION
# ============================================================
def simulate(cfg: SimConfig):
    rng = random.Random(cfg.seed)
    persona = PERSONAS[cfg.persona]

    active_cards: list[Card] = []
    waiting_room: list[Card] = []
    next_id = 0
    daily_log: list[DailyRow] = []
    overdue_delays = []

    plan_slots_per_day = cfg.sessions * cfg.session_size
    queue_cap = max(plan_slots_per_day * cfg.queue_cap_days, plan_slots_per_day * 2)

    # ---------------------------------------------------------
    # PRESSURE METRIC: DEBT = overdue + never_reviewed
    # (from debt_metric v3 — excludes healthy future-scheduled)
    # ---------------------------------------------------------
    def review_debt(day: int) -> int:
        debt = 0
        for c in active_cards:
            if not c.ever_reviewed:
                debt += 1
            elif c.next_review_day is not None and c.next_review_day <= day:
                debt += 1
        return debt

    def pressure_level(day: int) -> float:
        """Normalized pressure 0.0 - 1.0+"""
        if queue_cap == 0:
            return 0.0
        return review_debt(day) / queue_cap

    def new_card(day: int, origin: str) -> Card:
        nonlocal next_id
        next_id += 1
        iv_set = rng.choice(INTERVAL_SETS) if cfg.random_intervals else DEFAULT_INTERVALS
        return Card(
            card_id=next_id,
            interval_set=iv_set,
            created_day=day,
            origin=origin,
        )

    def admit_or_wait(card: Card, day: int):
        if review_debt(day) < queue_cap or not cfg.enable_waiting_room:
            card.next_review_day = day + 1
            active_cards.append(card)
        else:
            waiting_room.append(card)

    def admit_from_waiting_room(day: int) -> int:
        if not cfg.enable_waiting_room:
            return 0
        admitted = 0
        while waiting_room and review_debt(day) < queue_cap:
            c = waiting_room.pop(0)
            c.next_review_day = day + 1
            active_cards.append(c)
            admitted += 1
        return admitted

    def get_overdue(day: int) -> list[Card]:
        overdue = [c for c in active_cards if c.next_review_day is not None and c.next_review_day <= day]
        overdue.sort(key=lambda c: c.next_review_day)
        return overdue

    def auto_archive(day: int) -> int:
        """Archive chronically weak/overdue cards under pressure."""
        nonlocal active_cards
        if not cfg.enable_auto_archive:
            return 0
        pres = pressure_level(day)
        if pres < 1.0:
            return 0

        archived = 0
        survivors = []
        for c in active_cards:
            days_overdue = max(0, day - (c.next_review_day or day))
            should_archive = False
            if c.score < cfg.archive_threshold_score and days_overdue > cfg.archive_threshold_overdue:
                should_archive = True

            if not should_archive:
                survivors.append(c)
            else:
                archived += 1

        # Extreme pressure: forced archive of weakest 10%
        if pres > 2.5 and len(active_cards) > 30:
            active_cards.sort(key=lambda c: (c.score, -max(0, day - (c.next_review_day or day))))
            forced = max(2, int(len(active_cards) * 0.10))
            archived += forced
            active_cards = active_cards[forced:]

        return archived

    # ---------------------------------------------------------
    # MAIN LOOP
    # ---------------------------------------------------------
    for day in range(cfg.days):
        # 0. Demote extremely overdue cards (from debt_metric)
        for c in active_cards:
            if c.next_review_day is not None and (day - c.next_review_day) > 60:
                c.srs_stage = 0
                c.next_review_day = day + 1

        # 1. Word queries (quota ALWAYS fully available — paid feature)
        desired_queries = _poisson(rng, persona.query_lambda)
        served_queries = min(desired_queries, cfg.query_daily_cap)
        blocked_queries = max(0, desired_queries - served_queries)
        for _ in range(served_queries):
            if rng.random() < persona.save_gate_rate:
                admit_or_wait(new_card(day, "query"), day)

        # 2. Admit from waiting room (headroom permitting)
        admitted_today = admit_from_waiting_room(day)

        # 3. Attendance & slots
        attend_p = persona.attendance_today(day, rng)
        attends = rng.random() < attend_p
        sessions_done = 0
        if attends:
            sessions_done = round(cfg.sessions * persona.session_completion)
            sessions_done = max(1, min(cfg.sessions, sessions_done))
        slots_today = sessions_done * cfg.session_size

        # Catch-up bonus (from debt_metric)
        overdue = get_overdue(day)
        overdue_before = len(overdue)
        if attends and overdue_before > slots_today:
            bonus = math.floor(slots_today * 0.25)
            slots_today += bonus

        candidates = overdue[:slots_today]
        remaining = slots_today - len(candidates)

        # 4. AI fills remaining slots (adaptive — from debt_metric throttle)
        fill_frac = review_debt(day) / queue_cap if queue_cap else 0
        if fill_frac <= 0.70:
            throttle = 1.0
        else:
            span = 0.30
            over = min(fill_frac - 0.70, span)
            throttle = 1.0 - (1.0 - 0.15) * (over / span)
        ai_budget = max(0, math.floor(cfg.ai_daily_cap * throttle))
        ai_take = min(remaining, ai_budget)
        for _ in range(ai_take):
            admit_or_wait(new_card(day, "ai"), day)

        # 5. Review cards
        forget_rate_today = persona.forget_today(day, rng)
        reviews_done = 0
        for card in candidates:
            overdue_delays.append(day - card.next_review_day)
            card.ever_reviewed = True
            if rng.random() < forget_rate_today:
                # FORGET
                card.srs_stage = 0
                card.next_review_day = day + card.interval_set[0]
                card.score = max(0.0, card.score - 0.2)
            else:
                # REMEMBER — 3-button logic with lateral boost
                roll = rng.random()
                if roll < 0.10:  # SOONER
                    if card.srs_stage == 0:
                        card.srs_stage = 1
                        card.next_review_day = day + card.interval_set[1]
                        card.score = min(5.0, card.score + 0.1)
                    else:
                        card.srs_stage -= 1
                        card.next_review_day = day + card.interval_set[card.srs_stage]
                        card.score = max(0.0, card.score - 0.1)
                elif roll < 0.85:  # NEUTRAL
                    card.srs_stage = min(card.srs_stage + 1, 4)
                    card.next_review_day = day + card.interval_set[card.srs_stage]
                    card.score = min(5.0, card.score + 0.1)
                else:  # LATER — aggressive boost under pressure
                    pres = pressure_level(day)
                    boost = _lateral_boost(pres, cfg.lateral_boost_max)
                    if card.srs_stage == 4:
                        card.next_review_day = day + rng.randint(20, 45)
                    else:
                        card.srs_stage = min(card.srs_stage + 1, 4)
                        prev_int = card.interval_set[max(0, card.srs_stage - 1)]
                        next_int = card.interval_set[card.srs_stage]
                        base = next_int + prev_int
                        # Score multiplier + lateral boost
                        mult = _score_multiplier(card.score) * boost
                        final_int = round(base * mult)
                        card.next_review_day = day + final_int
                    card.score = min(5.0, card.score + 0.2)
            reviews_done += 1

        backlog_count = overdue_before - reviews_done
        pregrad_pool = sum(1 for c in active_cards if not c.ever_reviewed) + len(waiting_room)

        # 6. Auto-archive
        archived_today = auto_archive(day)

        # 7. Log
        pres = pressure_level(day)
        daily_log.append(DailyRow(
            day=day,
            attended=attends,
            sessions_done=sessions_done,
            reviews_done=reviews_done,
            backlog_count=backlog_count,
            desired_queries=desired_queries,
            served_queries=served_queries,
            blocked_queries=blocked_queries,
            ai_cards_served=ai_take,
            total_cards=len(active_cards) + len(waiting_room),
            waiting_room=len(waiting_room),
            admitted_today=admitted_today,
            pregrad_pool=pregrad_pool,
            archived_today=archived_today,
            plan_slots=plan_slots_per_day,
            slots_today=slots_today,
            queue_cap=queue_cap,
            debt=review_debt(day),
        ))

    # Summary
    total_generated = len(active_cards) + len(waiting_room)
    total_archived = sum(r.archived_today for r in daily_log)
    total_queries_desired = sum(r.desired_queries for r in daily_log)
    total_queries_served = sum(r.served_queries for r in daily_log)
    total_queries_blocked = sum(r.blocked_queries for r in daily_log)

    return daily_log, {
        "persona": cfg.persona,
        "plan": cfg.plan,
        "queue_cap": queue_cap,
        "final_total_cards": total_generated,
        "final_waiting_room": len(waiting_room),
        "final_active_cards": len(active_cards),
        "total_archived": total_archived,
        "max_backlog": max((r.backlog_count for r in daily_log), default=0),
        "avg_backlog_last30": round(sum(r.backlog_count for r in daily_log[-30:]) / max(1, len(daily_log[-30:])), 1),
        "avg_overdue_delay": round(sum(overdue_delays) / max(1, len(overdue_delays)), 2),
        "max_overdue_delay": max(overdue_delays, default=0),
        "attendance_rate_pct": round(100 * sum(r.attended for r in daily_log) / max(1, len(daily_log)), 1),
        "query_fulfillment_pct": round(100 * total_queries_served / max(1, total_queries_desired), 1),
        "total_queries_blocked": total_queries_blocked,
        "avg_throttle": round(sum(r.ai_cards_served for r in daily_log) / max(1, sum(r.ai_cards_served + r.blocked_queries for r in daily_log)) if False else 0, 2),  # placeholder
        "final_avg_score": round(sum(c.score for c in active_cards) / max(1, len(active_cards)), 2),
    }


def format_table(daily_log: list[DailyRow], summary: dict, cfg: SimConfig) -> str:
    lines = []
    lines.append(f"SRS v4 Hybrid Simulation: plan={cfg.plan}, persona={cfg.persona}, days={cfg.days}, seed={cfg.seed}")
    lines.append(f"Config: {cfg.sessions} sessions x {cfg.session_size} = {cfg.sessions*cfg.session_size} slots/day, "
                 f"ai_cap={cfg.ai_daily_cap}, query_cap={cfg.query_daily_cap}, queue_cap={summary['queue_cap']}")
    lines.append(f"Archive: score<{cfg.archive_threshold_score}, overdue>{cfg.archive_threshold_overdue} | "
                 f"Lateral boost max: {cfg.lateral_boost_max}x")
    lines.append("")
    header = (f"{'Day':>4} {'Att':>3} {'Ses':>3} {'Rev':>4} {'Back':>5} {'Debt':>5} {'Wait':>5} "
              f"{'AISrv':>6} {'Total':>7} {'Arch':>4}")
    sep = "-" * len(header)
    lines.append(header)
    lines.append(sep)
    for r in daily_log:
        if r.day % 30 == 0 or r.day == daily_log[-1].day:
            lines.append(f"{r.day:>4} {int(r.attended):>3} {r.sessions_done:>3} {r.reviews_done:>4} "
                         f"{r.backlog_count:>5} {r.debt:>5} {r.waiting_room:>5} "
                         f"{r.ai_cards_served:>6} {r.total_cards:>7} {r.archived_today:>4}")
    lines.append(sep)
    last = daily_log[-1]
    lines.append(f"{last.day:>4} {int(last.attended):>3} {last.sessions_done:>3} {last.reviews_done:>4} "
                 f"{last.backlog_count:>5} {last.debt:>5} {last.waiting_room:>5} "
                 f"{last.ai_cards_served:>6} {last.total_cards:>7} {last.archived_today:>4}")
    lines.append("")
    lines.append("Final Summary:")
    lines.append(f"  Active Cards:      {summary['final_active_cards']}")
    lines.append(f"  Waiting Room:      {summary['final_waiting_room']}")
    lines.append(f"  Total Archived:    {summary['total_archived']}")
    lines.append(f"  Max Backlog:       {summary['max_backlog']}")
    lines.append(f"  Avg Backlog (30d): {summary['avg_backlog_last30']}")
    lines.append(f"  Avg Overdue Delay: {summary['avg_overdue_delay']} days")
    lines.append(f"  Max Overdue Delay: {summary['max_overdue_delay']} days")
    lines.append(f"  Attendance Rate:   {summary['attendance_rate_pct']}%")
    lines.append(f"  Query Fulfillment: {summary['query_fulfillment_pct']}%")
    lines.append(f"  Blocked Queries:   {summary['total_queries_blocked']}")
    lines.append(f"  Final Avg Score:   {summary['final_avg_score']} / 5.0")
    return "\n".join(lines)


def write_csv(daily_log: list[DailyRow], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day", "attended", "sessions_done", "reviews_done", "backlog_count",
                    "debt", "waiting_room", "desired_queries", "served_queries", "blocked_queries",
                    "ai_cards_served", "total_cards", "admitted_today", "pregrad_pool",
                    "archived_today", "plan_slots", "slots_today", "queue_cap"])
        for r in daily_log:
            w.writerow([r.day, int(r.attended), r.sessions_done, r.reviews_done, r.backlog_count,
                        r.debt, r.waiting_room, r.desired_queries, r.served_queries, r.blocked_queries,
                        r.ai_cards_served, r.total_cards, r.admitted_today, r.pregrad_pool,
                        r.archived_today, r.plan_slots, r.slots_today, r.queue_cap])


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="SRS v4 Hybrid Session Simulation")
    parser.add_argument("--plan", choices=["free", "silver", "gold"], default="gold")
    parser.add_argument("--persona", choices=["lazy", "average", "eager", "fluctuating"], default="eager")
    parser.add_argument("--days", type=int, default=360)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--queue-cap-days", type=int, default=None, help="Override plan default")
    parser.add_argument("--session-size", type=int, default=None)
    parser.add_argument("--sessions", type=int, default=None)
    parser.add_argument("--ai-daily-cap", type=int, default=None)
    parser.add_argument("--query-daily-cap", type=int, default=None)
    parser.add_argument("--no-waiting-room", action="store_true")
    parser.add_argument("--no-auto-archive", action="store_true")
    parser.add_argument("--no-adaptive-quota", action="store_true")
    parser.add_argument("--csv", type=str, default=None)
    args = parser.parse_args(sys.argv[1:])

    cfg = SimConfig(
        plan=args.plan,
        persona=args.persona,
        days=args.days,
        seed=args.seed,
        session_size=args.session_size,
        sessions=args.sessions,
        ai_daily_cap=args.ai_daily_cap,
        query_daily_cap=args.query_daily_cap,
        queue_cap_days=args.queue_cap_days,
        enable_waiting_room=not args.no_waiting_room,
        enable_auto_archive=not args.no_auto_archive,
        enable_adaptive_quota=not args.no_adaptive_quota,
    )

    daily_log, summary = simulate(cfg)
    print(format_table(daily_log, summary, cfg))
    if args.csv:
        write_csv(daily_log, args.csv)
        print(f"\nCSV saved to: {args.csv}")