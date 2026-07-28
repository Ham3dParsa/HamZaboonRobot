"""Compare v5_dsr.py (DSR-lite) vs v5_dsr_2.py (Full DSR / FSRS-6).

Scenarios: silver + gold x 4 personas x 5 time buckets (3/6/12/18/24 months)
proficiency=intermediate, enable_rejection=False, learned threshold = S >= 45 days (both).
"""
import importlib.util
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

v5 = _load("v5_dsr", os.path.join(DIR, "v5_dsr.py"))
v5_2 = _load("v5_dsr_2", os.path.join(DIR, "v5_dsr_2.py"))

# Normalise thresholds: both use S >= 45 days, suppress reviews fallback in v5
v5.LEARNED_MIN_STABILITY_DAYS = 45
v5.LEARNED_MIN_REVIEWS = 9999
v5_2.LEARNED_MIN_STABILITY_DAYS = 45

PLANS = ["silver", "gold"]
PERSONAS = ["lazy", "average", "eager", "fluctuating"]
DAYS_AND_MONTHS = [(90, 3), (180, 6), (360, 12), (540, 18), (720, 24)]

def _pctl(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(p * len(s)))]

results = []
for plan in PLANS:
    for persona in PERSONAS:
        for days, months in DAYS_AND_MONTHS:
            cfg = v5.SimConfig(
                plan=plan, persona=persona, proficiency="intermediate",
                days=days, seed=42, enable_rejection=False,
            )
            cfg2 = v5_2.SimConfig(
                plan=plan, persona=persona, proficiency="intermediate",
                days=days, seed=42, enable_rejection=False,
                mastery_model="dsr",
            )

            _, s = v5.simulate(cfg)
            _, s2 = v5_2.simulate(cfg2)

            results.append({
                "plan": plan, "persona": persona, "days": days, "months": months,
                # v5 (DSR-lite)
                "v5_learned": s["learned_words"],
                "v5_ai_calls": s["total_ai_calls"],
                "v5_ai_cost": s["total_ai_cost_usd"],
                "v5_per_dollar": s["learned_words_per_dollar"],
                "v5_active": s["total_active_words"],
                "v5_stability": s["avg_stability_days"],
                "v5_retrievability": s["avg_retrievability"],
                "v5_difficulty": s["avg_difficulty"],
                "v5_max_due": s["max_due_backlog"],
                "v5_median_due": s["median_due_backlog"],
                "v5_avg_late": s["avg_lateness_days"],
                "v5_max_late": s["max_lateness_days"],
                # v5_2 (Full DSR)
                "v2_learned": s2["learned_words"],
                "v2_ai_calls": s2["total_ai_calls"],
                "v2_ai_cost": s2["total_ai_cost_usd"],
                "v2_per_dollar": s2["learned_words_per_dollar"],
                "v2_active": s2["total_active_words"],
                "v2_stability": s2["avg_score"],  # dsr mode: avg_score = avg stability
                "v2_difficulty": s2["avg_difficulty"],
                "v2_max_due": s2["max_due_backlog"],
                "v2_avg_late": s2["avg_lateness_days"],
                "v2_max_late": s2["max_lateness_days"],
            })

# ---- Report ----
lines = []

def h(text):
    lines.append("")
    lines.append(f"=== {text} ===")
    lines.append("")

h("SCENARIO LEGEND")
lines.append("Every row: plan=plan, persona=persona, months=months, enable_rejection=False, proficiency=intermediate")
lines.append("learned threshold: S >= 45 days (both versions)")
lines.append("")

h("FULL COMPARISON TABLE")
lines.append(f"{'plan':<7} {'persona':<11} {'mo':>3} | "
             f"{'v5_lrn':>6} {'v2_lrn':>6} {'d_lrn%':>7} | "
             f"{'v5_/$':>7} {'v2_/$':>7} {'d_$%':>7} | "
             f"{'v5_ai$':>7} {'v2_ai$':>7} | "
             f"{'v5_stb':>6} {'v2_stb':>6} | "
             f"{'v5_mdue':>6} {'v2_mdue':>6} | "
             f"{'v5_mlate':>6} {'v2_mlate':>6}")
lines.append("-" * 120)

for r in results:
    d_learned_pct = ((r["v2_learned"] - r["v5_learned"]) / max(r["v5_learned"], 1)) * 100
    d_dollar_pct = ((r["v2_per_dollar"] - r["v5_per_dollar"]) / max(r["v5_per_dollar"], 1)) * 100
    lines.append(f'{r["plan"]:<7} {r["persona"]:<11} {r["months"]:>3} | '
                 f'{r["v5_learned"]:>6} {r["v2_learned"]:>6} {d_learned_pct:>+6.1f}% | '
                 f'{r["v5_per_dollar"]:>7.1f} {r["v2_per_dollar"]:>7.1f} {d_dollar_pct:>+6.1f}% | '
                 f'{r["v5_ai_cost"]:>7.4f} {r["v2_ai_cost"]:>7.4f} | '
                 f'{r["v5_stability"]:>6.1f} {r["v2_stability"]:>6.1f} | '
                 f'{r["v5_max_due"]:>6} {r["v2_max_due"]:>6} | '
                 f'{r["v5_avg_late"]:>6.1f} {r["v2_avg_late"]:>6.1f}')
lines.append("")

# ---- Per-plan aggregation ----
for plan in PLANS:
    h(f"AGGREGATE: {plan.upper()} (avg across personas & months)")
    rp = [r for r in results if r["plan"] == plan]
    n = len(rp)
    keys = [
        ("v5_learned", "v2_learned", "learned_words"),
        ("v5_per_dollar", "v2_per_dollar", "learned/$"),
        ("v5_ai_cost", "v2_ai_cost", "AI cost ($)"),
        ("v5_stability", "v2_stability", "avg_stability"),
        ("v5_max_due", "v2_max_due", "max_due_backlog"),
        ("v5_avg_late", "v2_avg_late", "avg_lateness"),
    ]
    lines.append(f"{'metric':<20} {'DSR-lite':>10} {'Full DSR':>10} {'diff%':>8}")
    lines.append("-" * 50)
    for k1, k2, label in keys:
        a1 = sum(r[k1] for r in rp) / n
        a2 = sum(r[k2] for r in rp) / n
        d = ((a2 - a1) / max(abs(a1), 0.001)) * 100
        lines.append(f"{label:<20} {a1:>10.2f} {a2:>10.2f} {d:>+7.1f}%")

# ---- Worst-case backlog analysis ----
h("WORST-CASE: LERNED WORDS GAP > 20%")
lines.append(f"{'plan':<7} {'persona':<11} {'mo':>3} | "
             f"v5_lrn={6} v2_lrn={6} diff%={8} | "
             f"v5_mdue={6} v2_mdue={6} | "
             f"v5_stb={6} v2_stb={6}")
for r in results:
    d_learned_pct = ((r["v2_learned"] - r["v5_learned"]) / max(r["v5_learned"], 1)) * 100
    if abs(d_learned_pct) > 20:
        lines.append(f'{r["plan"]:<7} {r["persona"]:<11} {r["months"]:>3} | '
                     f'{r["v5_learned"]:>6} {r["v2_learned"]:>6} {d_learned_pct:>+7.1f}% | '
                     f'{r["v5_max_due"]:>6} {r["v2_max_due"]:>6} | '
                     f'{r["v5_stability"]:>6.1f} {r["v2_stability"]:>6.1f}')

has_worst = any(abs(((r["v2_learned"] - r["v5_learned"]) / max(r["v5_learned"], 1)) * 100) > 20 for r in results)
if not has_worst:
    lines.append("  (none — all within ±20%)")

h("V5 vs FULL DSR SUMMARY")
total_learned_v5 = sum(r["v5_learned"] for r in results)
total_learned_v2 = sum(r["v2_learned"] for r in results)
total_cost_v5 = sum(r["v5_ai_cost"] for r in results)
total_cost_v2 = sum(r["v2_ai_cost"] for r in results)
avg_eff_v5 = sum(r["v5_per_dollar"] for r in results) / len(results)
avg_eff_v2 = sum(r["v2_per_dollar"] for r in results) / len(results)
avg_stab_v5 = sum(r["v5_stability"] for r in results) / len(results)
avg_stab_v2 = sum(r["v2_stability"] for r in results) / len(results)

lines.append(f"Total learned words — DSR-lite: {total_learned_v5}, Full DSR: {total_learned_v2}")
lines.append(f"Total AI cost      — DSR-lite: ${total_cost_v5:.4f}, Full DSR: ${total_cost_v2:.4f}")
lines.append(f"Avg learned/$      — DSR-lite: {avg_eff_v5:.1f}, Full DSR: {avg_eff_v2:.1f}")
lines.append(f"Avg stability      — DSR-lite: {avg_stab_v5:.1f}d, Full DSR: {avg_stab_v2:.1f}d")

# Print to console
print("\n".join(lines))

# Write report
with open(os.path.join(DIR, "compare_v5_v2_report.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print(f"\nReport written to {os.path.join(DIR, 'compare_v5_v2_report.md')}")