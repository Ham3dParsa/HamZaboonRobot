#!/usr/bin/env python3
"""
Two-version comparison: v5.2 (fixed/v5.3) vs v5.4 (FSRS-6 Full 4-grade)
Generates enhanced HTML report with per-row coloring and percentile metrics.

Scenarios:
- Plans: free, silver, gold
- Personas: eager, average  
- Periods: 1, 3, 6, 12, 24 months (30, 90, 180, 360, 720 days)
"""

import importlib.util
import json
import os
import sys
import statistics
import inspect
from datetime import datetime
from collections import Counter

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

# ---- Load both modules ----
def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(THIS_DIR, filename))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

mod_v52 = load_module("v5_2", "v5.2_FSRSv6.py")
mod_v54 = load_module("v5_4", "v5.4_FSRS_full.py")

VERSIONS = [
    ("v5.2 FSRS-6 (fixed)", mod_v52, "dsr"),
    ("v5.4 FSRS-6 Full (4-grade)", mod_v54, "dsr"),
]

# ---- Scenario Definitions ----
PLANS = ["free", "silver", "gold"]
PERSONAS = ["eager", "average"]
MONTHS = [1, 3, 6, 12, 24]
DAYS_MAP = {1: 30, 3: 90, 6: 180, 12: 360, 24: 720}
SEED = 42

BASE_SCENARIOS = [(plan, persona, months) for plan in PLANS for persona in PERSONAS for months in MONTHS]

# ---- Helpers ----
def make_cfg(mod, plan, persona, days, mastery):
    params = inspect.signature(mod.SimConfig.__init__).parameters
    kwargs = dict(
        plan=plan, persona=persona, proficiency="intermediate",
        days=days, seed=SEED, enable_rejection=False, enable_catchup=True,
        enable_session_rate_limit=True,
    )
    if "mastery_model" in params:
        kwargs["mastery_model"] = mastery
    if "desired_retention" in params:
        kwargs["desired_retention"] = 0.9 if "v5.4" in mod.__file__ else 0.85
    if "enable_continuous_mastery" in params:
        kwargs["enable_continuous_mastery"] = True
    if "enable_short_term" in params:
        kwargs["enable_short_term"] = False
    if "jitter" in params:
        kwargs["jitter"] = False
    return mod.SimConfig(**kwargs)

def supports_debug(mod):
    return "debug" in inspect.signature(mod.simulate).parameters

def percentile(data, p):
    if not data:
        return 0
    sorted_data = sorted(data)
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    idx = (p / 100) * (n - 1)
    if idx == int(idx):
        return sorted_data[int(idx)]
    lo = int(idx)
    hi = lo + 1
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac

def compute_percentiles(data, percentiles=(50, 90, 95, 99)):
    if not data:
        return {f"p{p}": 0 for p in percentiles} | {"max": 0}
    result = {f"p{p}": round(percentile(data, p), 2) for p in percentiles}
    result["max"] = max(data)
    return result

# ---- Main Data Collection ----
def run_all_simulations():
    print(f"Running {len(BASE_SCENARIOS)} scenarios × {len(VERSIONS)} versions = {len(BASE_SCENARIOS)*len(VERSIONS)} simulations...")
    
    all_runs = []
    
    for vlabel, mod, mastery in VERSIONS:
        debug_supported = supports_debug(mod)
        print(f"\n=== {vlabel} (debug={'yes' if debug_supported else 'no'}) ===")
        
        for plan, persona, months in BASE_SCENARIOS:
            days = DAYS_MAP[months]
            cfg = make_cfg(mod, plan, persona, days, mastery)
            
            if debug_supported:
                daily_log, summary, debug = mod.simulate(cfg, debug=True)
                active_cards = debug["active"]
                lateness_samples = debug["lateness_samples"]
            else:
                daily_log, summary = mod.simulate(cfg)
                active_cards = []
                lateness_samples = []
            
            final_day = cfg.days - 1
            card_lateness = []
            card_stability = []
            card_difficulty = []
            card_retrievability = []
            card_tier = []
            
            for c in active_cards:
                if c.last_review is not None:
                    if c.next_review is not None and c.next_review <= final_day:
                        card_lateness.append(final_day - c.next_review)
                    else:
                        card_lateness.append(0)
                card_stability.append(c.stability)
                if c.difficulty > 0:
                    card_difficulty.append(c.difficulty)
            
            if mastery == "dsr" and active_cards:
                for c in active_cards:
                    if c.last_review is not None:
                        elapsed = final_day - c.last_review
                        r = mod._dsr_retrievability(elapsed, c.stability)
                        card_retrievability.append(r)
                    if c.stability > 0:
                        card_tier.append(mod._dsr_tier(c.stability))
            
            daily_active = [r["active"] for r in daily_log]
            daily_due_remaining = [r["due_remaining"] for r in daily_log]
            daily_q_backlog = [r["q_backlog"] for r in daily_log]
            daily_reviews = [r.get("due_processed", 0) + r.get("bonus_processed", 0) for r in daily_log]
            
            lateness_pct = compute_percentiles(lateness_samples)
            card_late_pct = compute_percentiles(card_lateness)
            due_backlog_pct = compute_percentiles(daily_due_remaining)
            q_backlog_pct = compute_percentiles(daily_q_backlog)
            active_pct = compute_percentiles(daily_active)
            
            run_data = {
                "version": vlabel,
                "plan": plan,
                "persona": persona,
                "months": months,
                "days": days,
                "summary": summary,
                "daily_log": daily_log,
                "percentiles": {
                    "lateness_samples": lateness_pct,
                    "card_lateness_final": card_late_pct,
                    "due_backlog_daily": due_backlog_pct,
                    "query_backlog_daily": q_backlog_pct,
                    "active_cards_daily": active_pct,
                },
                "card_stats": {
                    "count": len(active_cards),
                    "stability_pct": compute_percentiles(card_stability) if card_stability else {},
                    "difficulty_pct": compute_percentiles(card_difficulty) if card_difficulty else {},
                    "retrievability_pct": compute_percentiles(card_retrievability) if card_retrievability else {},
                    "tier_counts": dict(Counter(card_tier)) if card_tier else {},
                },
                "has_debug_data": debug_supported,
            }
            all_runs.append(run_data)
            
            print(f"  {vlabel} | {plan}/{persona}/{months}m -> learned={summary['learned_words']}, "
                  f"avg_late={summary.get('avg_lateness_days', 0):.1f}, max_late={summary.get('max_lateness_days', 0)}")
    
    return all_runs

def save_raw_data(all_runs):
    output_path = os.path.join(THIS_DIR, "compare_v52_v54_data.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_runs, f, ensure_ascii=False, indent=2)
    print(f"\nRaw data saved to {output_path}")

if __name__ == "__main__":
    all_runs = run_all_simulations()
    save_raw_data(all_runs)
    print("\n=== Data collection complete ===")
    print(f"Total runs: {len(all_runs)}")