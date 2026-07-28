"""
Design and evaluate eager-learner plan tiers beyond current gold.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simulator_v4 as sim

PLANS = {
    "gold (current)":   {"sessions": 4, "session_size": 7, "ai_daily_cap": 12, "query_daily_cap": 10, "queue_cap_days": 4},
    "platinum A":       {"sessions": 5, "session_size": 8, "ai_daily_cap": 18, "query_daily_cap": 14, "queue_cap_days": 5},
    "platinum B":       {"sessions": 5, "session_size": 9, "ai_daily_cap": 20, "query_daily_cap": 15, "queue_cap_days": 5},
    "diamond":          {"sessions": 6, "session_size": 9, "ai_daily_cap": 24, "query_daily_cap": 18, "queue_cap_days": 6},
}

orig_resolve = sim._resolve_plan

def run_custom(plan, persona, days=720, seed=42):
    def custom_resolve(cfg):
        return plan
    sim._resolve_plan = custom_resolve
    cfg = sim.SimConfig(plan="gold", persona=persona, days=days, seed=seed)
    rows, s = sim.simulate(cfg)
    sim._resolve_plan = orig_resolve
    return s

print("## Eager-Learner Plan Tiers (persona=eager, 720 days)\n")

header = f"{'Plan':>14} {'sess':>5} {'size':>5} {'slots':>6} {'ai_cap':>7} {'q_cap':>7} {'learned':>8} {'cost$':>8} {'lrn/$':>7} {'max_due':>7} {'ease':>5}"
print(header)
print("-" * len(header))

for name, plan in PLANS.items():
    s = run_custom(plan, "eager")
    slots = plan["sessions"] * plan["session_size"]
    cost = s["total_ai_cost_usd"]
    eff = round(s["learned_words"] / cost, 1) if cost > 0 else 0
    print(f"{name:>14} {plan['sessions']:>5} {plan['session_size']:>5} {slots:>6}"
          f" {plan['ai_daily_cap']:>7} {plan['query_daily_cap']:>7}"
          f" {s['learned_words']:>8} {cost:>8.4f} {eff:>7}"
          f" {s['max_due_backlog']:>7} {s['avg_user_ease']:>5.2f}")

print("\n## Cost Breakdown & Productivity\n")
for name, plan in PLANS.items():
    s = run_custom(plan, "eager")
    c = s["total_ai_cost_usd"]
    l = s["learned_words"]
    print(f"  {name:>14}: {l:>4} words, ${c:.2f} total = ${c/l:.5f}/word (gold baseline: ${0.0021:.5f}/word hypothetical)")

print("\n## For average persona (less query volume, more realistic)\n")
print(f"{'Plan':>14} {'learned':>8} {'cost$':>8} {'lrn/$':>7} {'max_due':>7}")
print("-" * 55)
for name, plan in PLANS.items():
    s = run_custom(plan, "average")
    cost = s["total_ai_cost_usd"]
    eff = round(s["learned_words"] / cost, 1) if cost > 0 else 0
    print(f"{name:>14} {s['learned_words']:>8} {cost:>8.4f} {eff:>7} {s['max_due_backlog']:>7}")

print("\n## Recommendation")
print("-" * 55)
print("Platinum A (5x8=40 slots, AI=18, Q=14) best balance:")
print("  - 30% more slots than gold (40 vs 28)")
print("  - 50% more AI budget (18 vs 12)")
print("  - 40% more query capacity (14 vs 10)")
print("  - Cost at eager persona ~${:.4f} total/720d = ${:.2f}/month".format(
    run_custom(PLANS["platinum A"], "eager")["total_ai_cost_usd"],
    run_custom(PLANS["platinum A"], "eager")["total_ai_cost_usd"] / 24))
print("  - Cost at average persona ~${:.4f} total = ${:.2f}/month".format(
    run_custom(PLANS["platinum A"], "average")["total_ai_cost_usd"],
    run_custom(PLANS["platinum A"], "average")["total_ai_cost_usd"] / 24))
print()
print("Diamond (6x9=54 slots) has diminishing returns: more backlog, not proportionally more learned.")

sim._resolve_plan = orig_resolve
