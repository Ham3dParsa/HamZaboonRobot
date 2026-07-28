#!/usr/bin/env python3
"""
Three-model benchmark: legacy vs lite vs dsr

Runs the same 40 scenarios used in compare_v5_vs_v5_2.py:
  plans: silver, gold
  personas: eager, average, fluctuating, lazy
  time_buckets (days): 90, 180, 360, 540, 720

Outputs CSV with summary rows and a markdown table.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from v5_dsr_fixed import simulate, SimConfig, PLAN_DEFAULTS, PERSONAS
import csv

PLANS = ["silver", "gold"]
PERSONA_KEYS = ["eager", "average", "fluctuating", "lazy"]
TIME_BUCKETS = [90, 180, 360, 540, 720]
MODELS = ["legacy", "lite", "dsr"]

SEED = 42

def run_one(plan, persona, days, model):
    cfg = SimConfig(
        plan=plan,
        persona=persona,
        proficiency="intermediate",
        days=days,
        seed=SEED,
        mastery_model=model,
        enable_rejection=False,
    )
    _, summary = simulate(cfg)
    return summary

def main():
    print("Running 3-model benchmark (40 scenarios × 3 models = 120 runs)...")
    results = []

    for plan in PLANS:
        for persona in PERSONA_KEYS:
            for days in TIME_BUCKETS:
                row = {"plan": plan, "persona": persona, "days": days}
                for model in MODELS:
                    s = run_one(plan, persona, days, model)
                    prefix = f"{model}_"
                    row[f"{prefix}learned"] = s["learned_words"]
                    row[f"{prefix}active"] = s["total_active_words"]
                    row[f"{prefix}ai_calls"] = s["total_ai_calls"]
                    row[f"{prefix}cost"] = s["total_ai_cost_usd"]
                    row[f"{prefix}eff"] = s["learned_words_per_dollar"]
                    row[f"{prefix}max_due"] = s["max_due_backlog"]
                    row[f"{prefix}avg_late"] = s["avg_lateness_days"]
                    row[f"{prefix}rejected"] = s["total_rejected_ai"]
                results.append(row)

    # Write CSV
    csv_path = "benchmark_three_models.csv"
    fieldnames = ["plan", "persona", "days"] + \
        [f"{m}_{f}" for m in MODELS for f in
         ("learned", "active", "ai_calls", "cost", "eff", "max_due", "avg_late", "rejected")]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow(r)
    print(f"\nCSV saved to {csv_path}")

    # Print markdown table (learned words only, compact)
    print("\n### Learned words comparison")
    print("| plan | persona | days | legacy | lite | dsr | dsr/lite |")
    print("|------|---------|------|--------|------|-----|----------|")
    for r in results:
        l = r["legacy_learned"]
        li = r["lite_learned"]
        d = r["dsr_learned"]
        ratio = d / li if li else 0
        print(f"| {r['plan']} | {r['persona']} | {r['days']} | {l} | {li} | {d} | {ratio:.2f} |")

    # Summary by plan
    print("\n### Summary by plan (averaged over personas & time buckets)")
    for plan in PLANS:
        plan_rows = [r for r in results if r["plan"] == plan]
        for model in MODELS:
            learned_avg = sum(r[f"{model}_learned"] for r in plan_rows) / len(plan_rows)
            eff_avg = sum(r[f"{model}_eff"] for r in plan_rows) / len(plan_rows)
            max_due_avg = sum(r[f"{model}_max_due"] for r in plan_rows) / len(plan_rows)
            late_avg = sum(r[f"{model}_avg_late"] for r in plan_rows) / len(plan_rows)
            print(f"  {plan}/{model}: learned={learned_avg:.0f}, eff={eff_avg:.2f}, max_due={max_due_avg:.0f}, lateness={late_avg:.1f}")

    # Quality gate check
    print("\n### Quality gate check (DSR vs Lite)")
    all_ok = True
    for r in results:
        li = r["lite_learned"]
        d = r["dsr_learned"]
        if d < li * 0.9:
            print(f"  FAIL: {r['plan']}/{r['persona']}/{r['days']}d: dsr={d} < 90% of lite={li}")
            all_ok = False
    if all_ok:
        print("  All scenarios: DSR learned >= 90% of Lite ✓")

    eff_ok = True
    for r in results:
        li_eff = r["lite_eff"]
        d_eff = r["dsr_eff"]
        if d_eff < li_eff * 0.85:
            print(f"  FAIL efficiency: {r['plan']}/{r['persona']}/{r['days']}d: dsr_eff={d_eff:.2f} < 85% of lite_eff={li_eff:.2f}")
            eff_ok = False
    if eff_ok:
        print("  All scenarios: DSR efficiency >= 85% of Lite ✓")

if __name__ == "__main__":
    main()