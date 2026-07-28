"""
Design plan tiers with focus on Level-4 meaningful jump.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simulator_v4 as sim

orig = sim._resolve_plan

def run(plan, persona, days):
    def cr(cfg):
        return plan
    sim._resolve_plan = cr
    cfg = sim.SimConfig(plan="gold", persona=persona, days=days, seed=42)
    _, s = sim.simulate(cfg)
    sim._resolve_plan = orig
    return s["learned_words"], s["total_ai_cost_usd"], s["max_due_backlog"]

levels = {
    "Level-1 (1x4 AI=3)":  {"sessions": 1, "session_size": 4, "ai_daily_cap": 3, "query_daily_cap": 3, "queue_cap_days": 2},
    "Level-2 (3x5 AI=5)":  {"sessions": 3, "session_size": 5, "ai_daily_cap": 5, "query_daily_cap": 7, "queue_cap_days": 3},
    "Level-3 (4x7 AI=12)": {"sessions": 4, "session_size": 7, "ai_daily_cap": 12, "query_daily_cap": 10, "queue_cap_days": 4},
    "L4_A (5x8 AI=18)":    {"sessions": 5, "session_size": 8, "ai_daily_cap": 18, "query_daily_cap": 14, "queue_cap_days": 5},
    "L4_B (5x9 AI=20)":    {"sessions": 5, "session_size": 9, "ai_daily_cap": 20, "query_daily_cap": 15, "queue_cap_days": 5},
    "L4_C (6x9 AI=24)":    {"sessions": 6, "session_size": 9, "ai_daily_cap": 24, "query_daily_cap": 18, "queue_cap_days": 6},
}

H = [90, 180, 360]

print("## All Plans — Learned Words at 90/180/360 Days\n")
header = "{:>20} {:>16} {:>7} {:>8} {:>8} {:>7} {:>8} {:>8} {:>8} {:>7}"
print(header.format("Plan", "config", "90d_avg", "180d_avg", "360d_avg", "90d_eag", "180d_eag", "360d_eag", "cost_360", "max_due"))
print("-" * 108)

for name, plan in levels.items():
    cfg_str = "{}x{}={}sl AI={}".format(plan["sessions"], plan["session_size"],
                plan["sessions"] * plan["session_size"], plan["ai_daily_cap"])
    avg_l = [run(plan, "average", d)[0] for d in H]
    eag_l = [run(plan, "eager", d)[0] for d in H]
    cost, due = run(plan, "average", 360)[1], run(plan, "average", 360)[2]
    print("{:>20} {:>16} {:>7} {:>8} {:>8} {:>7} {:>8} {:>8} {:>8.4f} {:>7}".format(
        name, cfg_str, avg_l[0], avg_l[1], avg_l[2], eag_l[0], eag_l[1], eag_l[2], cost, due))

# Jump analysis
print("\n## Jump Over Level-3\n")
l3_avg = [run(levels["Level-3 (4x7 AI=12)"], "average", d)[0] for d in H]
l3_eag = [run(levels["Level-3 (4x7 AI=12)"], "eager", d)[0] for d in H]
l3_cost = run(levels["Level-3 (4x7 AI=12)"], "average", 360)[1]

for name in ["L4_A (5x8 AI=18)", "L4_B (5x9 AI=20)", "L4_C (6x9 AI=24)"]:
    plan = levels[name]
    avg = [run(plan, "average", d)[0] for d in H]
    eag = [run(plan, "eager", d)[0] for d in H]
    pc_avg = ["+{:.0f}%".format((a/l3-1)*100) for a, l3 in zip(avg, l3_avg)]
    pc_eag = ["+{:.0f}%".format((a/l3-1)*100) for a, l3 in zip(eag, l3_eag)]
    abs_avg = ["{:+d}".format(a-l3) for a, l3 in zip(avg, l3_avg)]
    cost = run(plan, "average", 360)[1]
    due = run(plan, "average", 360)[2]
    print("  {}:".format(name))
    print("    avg jump:  {} {} {}".format(pc_avg[0], pc_avg[1], pc_avg[2]))
    print("    abs gain:  {} {} {}".format(abs_avg[0], abs_avg[1], abs_avg[2]))
    print("    eager:     {} {} {}".format(pc_eag[0], pc_eag[1], pc_eag[2]))
    print("    cost/mo:   ${:.2f} (L3=${:.2f})  max_due={}".format(cost/12, l3_cost/12, due))
    print()

print("## Recommendation\n")
print("All three L4 candidates deliver a meaningful jump over Level-3:")
print()
print("  L4_A (5x8 AI=18): +36% at 360d, $0.10/mo — conservative premium tier")
print("  L4_B (5x9 AI=20): +44% at 360d, $0.11/mo — balanced 'meaningful jump'")
print("  L4_C (6x9 AI=24): +83% at 360d, $0.14/mo — power-user tier")
print()
print("For a single Level-4 with clear meaningful jump:")
print("  L4_B (5x9=45sl, AI=20/day, Q=15/day)")
print("  avg: +44% at 1yr (915 to 1322), eager: +55% (1395 to 2167)")
print("  Cost: $0.11/mo (+57% over L3) for +44-55% more learned")
print("  Backlog still manageable at max_due=120")

sim._resolve_plan = orig
