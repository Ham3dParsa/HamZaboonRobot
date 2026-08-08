"""sim_runner.py — FSRS simulation with event recording for replay.

Imports the algorithmic core from v5.4_FSRS_full.py and runs simulation
while recording every card review as an event for step-by-step replay.

Supports:
- All 5 standard personas + "me" (manual grading, no persona effects)
- Session tracking, streak, lateness, easy rate monitoring
- Language filtering
- Engine feature toggles (rejection, catchup, session rate limit, etc.)

┌─────────────────────────────────────────────────────────────┐
│  TO SWITCH ENGINE VERSION:                                  │
│  1. Copy new engine .py file into this directory            │
│  2. Change _ENGINE_FILE below to the new filename           │
│  3. If public API changed, update the ENGINE SECTION below  │
└─────────────────────────────────────────────────────────────┘
"""

import importlib.util
import os
import sys
import json
import random
import statistics
from collections import Counter

# ═══════════════════════════════════════════════════════════════
# ENGINE IMPORT — change _ENGINE_FILE to switch engine version
# ═══════════════════════════════════════════════════════════════
_ENGINE_FILE = "v5.4_FSRS_full.py"
_ENGINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), _ENGINE_FILE)

_ENGINE_SPEC = importlib.util.spec_from_file_location("fsrs_engine", _ENGINE_PATH)
_engine = importlib.util.module_from_spec(_ENGINE_SPEC)
sys.modules["fsrs_engine"] = _engine
_ENGINE_SPEC.loader.exec_module(_engine)

# Monkey-patch _sample_grade on the engine to record each review's grade
_last_grade = [None]
_orig_sample_grade = _engine._sample_grade

def _rec_sample(persona, r, rng):
    g = _orig_sample_grade(persona, r, rng)
    _last_grade[0] = g
    return g

_engine._sample_grade = _rec_sample

# Pull all needed names from the engine
SimConfig = _engine.SimConfig
Card = _engine.Card
PLAN_DEFAULTS = _engine.PLAN_DEFAULTS
PERSONAS = _engine.PERSONAS
PERSONA_GRADE_PROBS = _engine.PERSONA_GRADE_PROBS
PROFICIENCY = _engine.PROFICIENCY
DSR_W = _engine.DSR_W
LEARNED_MIN_STABILITY_DAYS = _engine.LEARNED_MIN_STABILITY_DAYS
DSR_TIER_THRESHOLDS = _engine.DSR_TIER_THRESHOLDS
AI_COST_PER_CALL = _engine.AI_COST_PER_CALL
DESIRED_RETENTION_DEFAULT = _engine.DESIRED_RETENTION_DEFAULT
_attend_prob = _engine._attend_prob
_clamp_override = _engine._clamp_override
_dsr_retrievability = _engine._dsr_retrievability
_dsr_interval_days = _engine._dsr_interval_days
_dsr_s0 = _engine._dsr_s0
_dsr_d0 = _engine._dsr_d0
_dsr_update_difficulty = _engine._dsr_update_difficulty
_dsr_update_stability = _engine._dsr_update_stability
_dsr_tier = _engine._dsr_tier
_handle_first_exposure = _engine._handle_first_exposure
_review_outcome_dsr = _engine._review_outcome_dsr

# Augment engine with the Gamer persona (not present in stock v5.4)
_engine.PERSONAS["gamer"] = {
    "persona_key": "gamer", "attend": 0.98,
    "q_lo": 3, "q_hi": 8, "save_prob": 0.85, "forget": 0.05,
    "grade_probs": "gamer", "session_completion": 1.0,
    "response_time_sec": (1, 3),
}
_engine.PERSONA_GRADE_PROBS["gamer"] = [0.01, 0.04, 0.35, 0.60]
PERSONAS["gamer"] = _engine.PERSONAS["gamer"]
PERSONA_GRADE_PROBS["gamer"] = _engine.PERSONA_GRADE_PROBS["gamer"]

# "me" persona — manual grading, no persona effects
_engine.PERSONAS["me"] = {
    "persona_key": "me", "attend": 1.0,
    "q_lo": 0, "q_hi": 0, "save_prob": 0.0, "forget": 0.0,
    "grade_probs": "average", "session_completion": 1.0,
    "response_time_sec": (1, 2),
}
_engine.PERSONA_GRADE_PROBS["me"] = [0.0, 0.0, 1.0, 0.0]  # Always Good for scheduling
PERSONAS["me"] = _engine.PERSONAS["me"]
PERSONA_GRADE_PROBS["me"] = _engine.PERSONA_GRADE_PROBS["me"]
# ═══════════════════════════════════════════════════════════════

LEARNED_S = 21.0


def _resolve_plan(cfg):
    d = dict(PLAN_DEFAULTS[cfg.plan])
    d["sessions"] = _clamp_override(d["sessions"], cfg.sessions_override)
    d["session_size"] = _clamp_override(d["session_size"], cfg.session_size_override)
    return d


def _filter_pool_by_lang(pool, lang):
    if not lang or lang == "all":
        return list(pool)
    return [c for c in pool if c.get("lang", "en") == lang]


def _lang_counts(pool):
    counts = {}
    for c in pool:
        l = c.get("lang", "en")
        counts[l] = counts.get(l, 0) + 1
    return counts


def run_simulation(params):
    """Run full simulation with per-card event recording.

    Args:
        params: dict — see SimConfig fields + "cards" (list of card data dicts)

    Returns: {"rows": [...], "summary": {...}, "events": [...], "history": {...}}
    """
    cards_data = params.pop("cards", [])
    sim_cfg = {k: v for k, v in params.items() if hasattr(SimConfig, k)}
    cfg = SimConfig(**sim_cfg)

    # Language filter
    language = params.get("language", "all")
    pool = _filter_pool_by_lang(list(cards_data), language)
    lang_counts = _lang_counts(cards_data)

    plan = _resolve_plan(cfg)
    p_key = cfg.persona
    is_me_mode = (p_key == "me")
    persona = dict(PERSONAS[p_key])
    prof = dict(PROFICIENCY[cfg.proficiency])

    rng = random.Random(cfg.seed) if cfg.seed is not None else random.Random()

    sessions_per_day = plan["sessions"]
    session_size = plan["session_size"]
    ai_daily_cap = plan["ai_daily_cap"]
    query_daily_cap = plan["query_daily_cap"]
    queue_cap_days = plan["queue_cap_days"]

    daily_slots = sessions_per_day * session_size
    q_backlog_soft = int(daily_slots * 1.0)
    q_backlog_hard = int(daily_slots * 2.0)
    q_inflow_max_red = 0.80

    # Card pool
    rng.shuffle(pool)
    pool_size = len(pool)
    next_pool_idx = 0
    for i, c in enumerate(pool):
        c["_idx"] = i

    active = {}
    active_ids = set()
    pending = []
    next_card_id = 1
    total_ai_calls = 0
    total_rejected_ai = 0
    total_bonus_reviews = 0
    total_ai_cost = 0.0
    created_by_query = 0
    created_by_ai = 0
    lateness_samples = []
    total_reviews = 0
    successful_reviews = 0
    streak = 0
    best_streak = 0

    # Per-session easy rate tracking
    session_easy_count = 0
    session_total_count = 0
    session_easy_rates = []

    h_avg_S = []
    h_avg_D = []
    h_avg_R = []
    h_learned = []
    h_retention = []
    h_backlog = []
    h_ai_calls = []
    h_streak = []

    events = []
    card_idx_map = {}
    unique_cards_exposed = set()

    rows = []

    for day in range(cfg.days):
        attended = _attend_prob(cfg.persona, day, rng) if not is_me_mode else True

        if attended:
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0

        due_list = sorted(
            [c for c in active.values() if c.next_review is not None and c.next_review <= day],
            key=lambda c: c.next_review
        )
        due_count = len(due_list)

        # Mark due_since for lateness tracking
        for c in due_list:
            if c.due_since is None:
                c.due_since = c.next_review

        # Queries — disabled in ME mode (user uses AI Query button)
        n_q = 0
        q_saved = 0
        if not is_me_mode:
            q_lo = persona.get("q_lo", 0)
            q_hi = persona.get("q_hi", 3)
            n_q = rng.randint(q_lo, q_hi)

            pc = len(pending)
            if pc > q_backlog_soft:
                f = min(q_inflow_max_red, (pc - q_backlog_soft) / (q_backlog_hard - q_backlog_soft + 1))
                n_q = max(0, int(n_q * (1 - f)))

            for _ in range(n_q):
                if rng.random() < persona.get("save_prob", 0.5) and next_pool_idx < pool_size:
                    cdata = pool[next_pool_idx]
                    next_pool_idx += 1
                    card = Card(id=next_card_id)
                    next_card_id += 1
                    pending.append(card)
                    card_idx_map[card.id] = cdata["_idx"]
                    q_saved += 1
                    created_by_query += 1

        # AI generation
        if is_me_mode:
            ai_max = ai_daily_cap
        elif cfg.enable_session_rate_limit and len(pending) >= q_backlog_hard:
            ai_max = 0
        else:
            ai_max = ai_daily_cap

        ai_gen = 0
        ai_rejected = 0
        ai_cost_today = 0.0
        for _ in range(ai_max):
            if next_pool_idx >= pool_size:
                break
            total_ai_calls += 1
            ai_cost_today += AI_COST_PER_CALL
            total_ai_cost += AI_COST_PER_CALL
            cdata = pool[next_pool_idx]
            next_pool_idx += 1
            if not is_me_mode and cfg.enable_rejection and rng.random() < prof.get("reject_noise", 0.15):
                ai_rejected += 1
                total_rejected_ai += 1
            else:
                card = Card(id=next_card_id, origin="ai")
                next_card_id += 1
                pending.append(card)
                card_idx_map[card.id] = cdata["_idx"]
                ai_gen += 1
                created_by_ai += 1

        if not attended and not is_me_mode:
            rows.append({
                "day": day, "attended": False,
                "due_processed": 0, "due_remaining": due_count,
                "queries": 0, "q_saved": 0,
                "q_backlog": len(pending),
                "ai_gen": 0, "ai_rejected": 0,
                "ai_cost_today": 0.0,
                "bonus_processed": 0,
                "active": len(active),
                "easy_rate": 0,
            })
            h_avg_S.append(h_avg_S[-1] if h_avg_S else 0)
            h_avg_D.append(h_avg_D[-1] if h_avg_D else 0)
            h_avg_R.append(h_avg_R[-1] if h_avg_R else 0)
            h_learned.append(h_learned[-1] if h_learned else 0)
            h_retention.append(h_retention[-1] if h_retention else 0)
            h_backlog.append(due_count)
            h_ai_calls.append(total_ai_calls)
            h_streak.append(streak)
            continue

        # Session processing
        available = list(pending)
        if due_list:
            available = due_list + available
        rng.shuffle(available)

        due_processed = 0
        bonus_processed = 0
        today_session_easy = 0
        today_session_total = 0

        for sess in range(sessions_per_day):
            slots = session_size
            used = 0
            session_cards = []
            rest = []

            for c in available:
                if c.id in active_ids and c.next_review is not None and c.next_review > day:
                    continue
                if used < slots:
                    session_cards.append(c)
                    used += 1
                else:
                    rest.append(c)

            available = rest

            if cfg.enable_catchup and due_count > session_size * sessions_per_day:
                cap = slots - used
                if cap > 0:
                    extra = [c for c in due_list if c not in session_cards]
                    for c in extra[:cap]:
                        session_cards.append(c)
                        bonus_processed += 1
                        total_bonus_reviews += 1

            for card in session_cards:
                if card in pending:
                    pending.remove(card)
                if card.id not in active_ids:
                    active_ids.add(card.id)
                    active[card.id] = card
                    card.origin = getattr(card, "origin", "query")

                idx = card_idx_map.get(card.id, -1)
                cdata = cards_data[idx] if 0 <= idx < len(cards_data) else {}

                if not card.first_exposure_done:
                    sb, db = 0.0, 0.0
                    rb = None
                    if is_me_mode:
                        # ME mode: don't auto-grade, use grade=3 for scheduling
                        grade = 0
                        # Temporarily apply grade=3 for scheduling
                        tmp_s = _dsr_s0(3)
                        tmp_d = _dsr_d0(3)
                        card.stability = tmp_s
                        card.difficulty = tmp_d
                        card.first_exposure_done = True
                        card.reviews = 1
                        card.last_review = day
                        jitter = 1 + rng.uniform(-cfg.jitter, cfg.jitter)
                        card.next_review = day + max(1, round(_dsr_interval_days(tmp_s, cfg.desired_retention) * jitter))
                        outcome = "first_exposure"
                        sa, da = 0.0, 0.0  # Will be computed by UI
                        interval = _dsr_interval_days(tmp_s, cfg.desired_retention)
                        total_reviews += 1
                        unique_cards_exposed.add(card.id)
                        events.append({
                            "day": day, "session": sess, "card_id": card.id, "card_idx": idx,
                            "word": cdata.get("word", ""),
                            "type": "first_exposure", "grade": 0, "grade_required": True,
                            "S_before": sb, "S_after": 0.0,
                            "D_before": db, "D_after": 0.0,
                            "R_before": None,
                            "outcome": outcome, "interval_days": round(interval, 4),
                            "tier_before": "new", "tier_after": "new",
                            "default_grade": 3,
                        })
                    else:
                        outcome = _handle_first_exposure(card, persona, cfg, day, rng)
                        grade = _last_grade[0]
                        sa, da = card.stability, card.difficulty
                        interval = _dsr_interval_days(sa, cfg.desired_retention)
                        total_reviews += 1
                        if outcome == "success":
                            successful_reviews += 1
                        due_processed += 1
                        unique_cards_exposed.add(card.id)
                        today_session_total += 1
                        if grade == 4:
                            today_session_easy += 1
                        events.append({
                            "day": day, "session": sess, "card_id": card.id, "card_idx": idx,
                            "word": cdata.get("word", ""),
                            "type": "first_exposure", "grade": grade,
                            "S_before": sb, "S_after": round(sa, 4),
                            "D_before": db, "D_after": round(da, 4),
                            "R_before": None,
                            "outcome": outcome, "interval_days": round(interval, 4),
                            "tier_before": "new", "tier_after": _dsr_tier(sa),
                        })
                else:
                    sb, db = card.stability, card.difficulty
                    elapsed = day - card.last_review
                    rb = _dsr_retrievability(elapsed, sb)
                    if is_me_mode:
                        # ME mode: don't auto-grade, use grade=3 for scheduling
                        grade = 0
                        tmp_s = _dsr_update_stability(db, sb, rb, 3)
                        tmp_d = _dsr_update_difficulty(db, 3)
                        card.stability = tmp_s
                        card.difficulty = tmp_d
                        card.reviews += 1
                        card.last_review = day
                        card.next_review = day + max(1, round(_dsr_interval_days(tmp_s, cfg.desired_retention)))
                        outcome = "success" if 3 >= 3 else "forgot"
                        sa, da = 0.0, 0.0
                        interval = _dsr_interval_days(tmp_s, cfg.desired_retention)
                        total_reviews += 1
                        events.append({
                            "day": day, "session": sess, "card_id": card.id, "card_idx": idx,
                            "word": cdata.get("word", ""),
                            "type": "review", "grade": 0, "grade_required": True,
                            "S_before": round(sb, 4), "S_after": 0.0,
                            "D_before": round(db, 4), "D_after": 0.0,
                            "R_before": round(rb, 4),
                            "outcome": outcome, "interval_days": round(interval, 4),
                            "tier_before": _dsr_tier(sb), "tier_after": _dsr_tier(tmp_s),
                            "default_grade": 3,
                        })
                    else:
                        outcome = _review_outcome_dsr(card, persona, cfg, day, rng)
                        grade = _last_grade[0]
                        sa, da = card.stability, card.difficulty
                        interval = _dsr_interval_days(sa, cfg.desired_retention)
                        total_reviews += 1
                        if outcome == "success":
                            successful_reviews += 1
                        due_processed += 1
                        today_session_total += 1
                        if grade == 4:
                            today_session_easy += 1
                        events.append({
                            "day": day, "session": sess, "card_id": card.id, "card_idx": idx,
                            "word": cdata.get("word", ""),
                            "type": "review", "grade": grade,
                            "S_before": round(sb, 4), "S_after": round(sa, 4),
                            "D_before": round(db, 4), "D_after": round(da, 4),
                            "R_before": round(rb, 4),
                            "outcome": outcome, "interval_days": round(interval, 4),
                            "tier_before": _dsr_tier(sb), "tier_after": _dsr_tier(sa),
                        })

            if used == 0:
                break

        # Lateness tracking
        for c in active.values():
            if c.last_review is not None and c.due_since is not None and c.last_review > c.due_since:
                lateness_samples.append(c.last_review - c.due_since)

        session_easy_rate = today_session_easy / max(today_session_total, 1)
        session_easy_rates.append(session_easy_rate)

        rows.append({
            "day": day, "attended": True,
            "due_processed": due_processed,
            "due_remaining": max(0, due_count - due_processed),
            "queries": n_q, "q_saved": q_saved,
            "q_backlog": len(pending),
            "ai_gen": ai_gen, "ai_rejected": ai_rejected,
            "ai_cost_today": round(ai_cost_today, 4),
            "bonus_processed": bonus_processed,
            "active": len(active),
            "easy_rate": round(session_easy_rate, 4),
            "streak": streak,
            "best_streak": best_streak,
        })

        # History snapshots
        if active:
            ss = [c.stability for c in active.values()]
            dd = [c.difficulty for c in active.values()]
            rr = []
            for c in active.values():
                if c.last_review is not None and c.stability > 0:
                    rr.append(_dsr_retrievability(day - c.last_review, c.stability))
                elif c.stability > 0:
                    rr.append(1.0)
            h_avg_S.append(statistics.mean(ss))
            h_avg_D.append(statistics.mean(dd))
            h_avg_R.append(statistics.mean(rr) if rr else 0)
            h_learned.append(sum(1 for c in active.values() if c.stability >= LEARNED_S))
            h_retention.append(successful_reviews / max(total_reviews, 1) * 100)
        else:
            h_avg_S.append(0)
            h_avg_D.append(0)
            h_avg_R.append(0)
            h_learned.append(0)
            h_retention.append(0)
        h_backlog.append(max(0, due_count - due_processed))
        h_ai_calls.append(total_ai_calls)
        h_streak.append(streak)

    # Attach stats snapshots to events
    ev_idx = 0
    for day in range(cfg.days):
        d_learned = h_learned[day] if day < len(h_learned) else 0
        d_ret = h_retention[day] if day < len(h_retention) else 0
        d_streak = h_streak[day] if day < len(h_streak) else 0
        while ev_idx < len(events) and events[ev_idx]["day"] == day:
            events[ev_idx]["stats"] = {
                "active": rows[day]["active"] if day < len(rows) else 0,
                "avg_S": h_avg_S[day],
                "avg_D": h_avg_D[day],
                "due_today": rows[day]["due_remaining"] if day < len(rows) else 0,
                "learned": d_learned,
                "retention": round(d_ret, 1),
                "ai_cost": round(total_ai_cost * events[ev_idx]["day"] / max(cfg.days, 1), 4),
                "ai_calls": total_ai_calls,
                "streak": d_streak,
                "best_streak": best_streak,
            }
            ev_idx += 1

    # Summary
    learned_words = sum(1 for c in active.values() if c.stability >= LEARNED_S)
    stabilities = sorted([c.stability for c in active.values()])
    difficulties = [c.difficulty for c in active.values()]
    retrievabilities = []
    for c in active.values():
        if c.last_review is not None and c.stability > 0:
            retrievabilities.append(_dsr_retrievability(cfg.days - 1 - c.last_review, c.stability))
        elif c.stability > 0:
            retrievabilities.append(1.0)

    tier_counts = {}
    for label, th in reversed(DSR_TIER_THRESHOLDS):
        c = sum(1 for c in active.values() if c.stability >= th)
        if c:
            tier_counts[label] = c

    db_days = [r["due_remaining"] for r in rows]
    qb_days = [r["q_backlog"] for r in rows]

    # Available card indices for AI Query (ME mode)
    available_card_indices = [c["_idx"] for c in pool if c["_idx"] not in set(
        card_idx_map.get(cid, -1) for cid in active_ids
    ) and c["_idx"] < len(cards_data)]

    # Plan info for ME mode
    plan_info = {
        "sessions_per_day": sessions_per_day,
        "session_size": session_size,
        "ai_daily_cap": ai_daily_cap,
        "query_daily_cap": query_daily_cap,
        "total_cards_in_pool": pool_size,
        "lang_counts": lang_counts,
    }

    summary = {
        "plan": cfg.plan, "persona": cfg.persona,
        "proficiency": cfg.proficiency,
        "enable_rejection": cfg.enable_rejection,
        "enable_catchup": cfg.enable_catchup,
        "enable_session_rate_limit": cfg.enable_session_rate_limit,
        "desired_retention": cfg.desired_retention,
        "sessions_effective": sessions_per_day,
        "session_size_effective": session_size,
        "days": cfg.days,
        "total_active_words": len(active),
        "created_by_query": created_by_query,
        "created_by_ai": created_by_ai,
        "total_ai_calls": total_ai_calls,
        "total_rejected_ai": total_rejected_ai,
        "total_bonus_due": total_bonus_reviews,
        "final_active_cards": len(active),
        "learned_words": learned_words,
        "avg_stability_days": round(statistics.mean(stabilities), 2) if stabilities else 0,
        "median_stability_days": round(statistics.median(stabilities), 2) if stabilities else 0,
        "p90_stability_days": round(sorted(stabilities)[int(len(stabilities) * 0.9)], 2) if stabilities and len(stabilities) > 1 else 0,
        "avg_retrievability": round(statistics.mean(retrievabilities), 4) if retrievabilities else 0,
        "median_retrievability": round(statistics.median(retrievabilities), 4) if retrievabilities else 0,
        "avg_difficulty": round(statistics.mean(difficulties), 2) if difficulties else 0,
        "tier_counts": tier_counts,
        "max_due_backlog": max(db_days) if db_days else 0,
        "median_due_backlog": round(statistics.median(db_days), 1) if db_days else 0,
        "p90_due_backlog": round(sorted(db_days)[int(len(db_days) * 0.9)], 1) if db_days and len(db_days) > 1 else 0,
        "max_query_backlog": max(qb_days) if qb_days else 0,
        "avg_lateness_days": round(statistics.mean(lateness_samples), 1) if lateness_samples else 0,
        "median_lateness_days": round(statistics.median(lateness_samples), 1) if lateness_samples else 0,
        "p90_lateness_days": round(sorted(lateness_samples)[int(len(lateness_samples) * 0.9)], 1) if lateness_samples and len(lateness_samples) > 1 else 0,
        "max_lateness_days": max(lateness_samples) if lateness_samples else 0,
        "archived_lost_words": 0,
        "avg_ai_gen_per_day": round(total_ai_calls / max(cfg.days, 1), 2),
        "total_ai_cost_usd": round(total_ai_cost, 4),
        "learned_words_per_dollar": round(learned_words / max(total_ai_cost, 0.0001), 2) if total_ai_cost > 0 else 0,
        "total_cards_exposed": len(unique_cards_exposed),
        "best_streak": best_streak,
    }

    result = {
        "rows": rows,
        "summary": summary,
        "events": events,
        "history": {
            "avg_S": h_avg_S, "avg_D": h_avg_D, "avg_R": h_avg_R,
            "learned": h_learned, "retention": h_retention,
            "backlog": h_backlog, "ai_calls": h_ai_calls,
            "streak": h_streak,
        },
        "plan_info": plan_info,
        "available_card_indices": available_card_indices if is_me_mode else [],
        "language": language,
        "is_me_mode": is_me_mode,
    }

    return result


if __name__ == "__main__":
    import re
    cards_file = os.path.join(os.path.dirname(__file__), "archive", "simulator_cards.js")
    with open(cards_file, "r", encoding="utf-8") as f:
        js = f.read()
    match = re.search(r"var SIMULATOR_CARDS\s*=\s*(\[.*?\]);", js, re.DOTALL)
    cards = json.loads(match.group(1)) if match else []

    result = run_simulation({
        "plan": "gold", "persona": "eager", "days": 30,
        "seed": 42, "proficiency": "advanced", "cards": cards,
    })
    print(f"Events: {len(result['events'])}")
    print(f"Rows: {len(result['rows'])}")
    print(f"Active: {result['summary']['final_active_cards']}")
    print(f"Learned: {result['summary']['learned_words']}")
    print(f"AI Calls: {result['summary']['total_ai_calls']}")
    print(f"AI Cost: ${result['summary']['total_ai_cost_usd']}")
    print(f"Avg Stability: {result['summary']['avg_stability_days']}d")
    print(f"Cards Exposed: {result['summary']['total_cards_exposed']}")
    print(f"Best Streak: {result['summary']['best_streak']}")
    print("sim_runner.py OK")
