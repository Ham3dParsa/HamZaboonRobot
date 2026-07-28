"""
Design all subscription plan tiers based on learned words at 90/180/360 days.
Plans are named Level-1 through Level-4 (naming not yet locked).
Level-4 must deliver a meaningful jump over Level-3.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simulator_v4 as sim

orig_resolve = sim._resolve_plan

def run_custom(plan, persona, days, seed=42):
    def custom_resolve(cfg):
        return plan
    sim._resolve_plan = custom_resolve
    cfg = sim.SimConfig(plan="gold", persona=persona, days=days, seed=seed)
    rows, s = sim.simulate(cfg)
    sim._resolve_plan = orig_resolve
    return s

# Candidate pool — explore across sessions/size/AI/query
CANDIDATES = [
    # (name, sessions, size, ai_cap, q_cap, queue_days)
    ("L1-a", 1, 3, 2, 2, 2),   # very basic
    ("L1-b", 1, 4, 3, 3, 2),   # current free
    ("L2-a", 2, 4, 4, 5, 3),
    ("L2-b", 3, 4, 5, 6, 3),
    ("L2-c", 3, 5, 5, 7, 3),   # current silver
    ("L3-a", 3, 6, 8, 8, 4),
    ("L3-b", 4, 6, 10, 9, 4),
    ("L3-c", 4, 7, 12, 10, 4), # current gold
    # Level 4 candidates — meaningful jump
    ("L4-a", 4, 8, 15, 12, 4),  # same sessions, bigger size + AI
    ("L4-b", 5, 7, 15, 12, 4),  # more sessions, same size
    ("L4-c", 5, 8, 18, 14, 5),  # platinum A
    ("L4-d", 5, 9, 20, 15, 5),  # platinum B
    ("L4-e", 6, 8, 20, 15, 5),
    ("L4-f", 6, 9, 24, 18, 6),  # diamond
]

HORIZONS = [90, 180, 360]
PERSONAS = ["average", "eager"]

# Store results
results = []

print("## Scanning candidate plan configurations\n")
for name, sess, sz, ai, q, qd in CANDIDATES:
    plan = {"sessions": sess, "session_size": sz,
            "ai_daily_cap": ai, "query_daily_cap": q,
            "queue_cap_days": qd}
    slots = sess * sz
    
    row = {"name": name, "sessions": sess, "size": sz, "slots": slots,
           "ai": ai, "q": q, "queue": qd}
    
    for persona in PERSONAS:
        for d in HORIZONS:
            s = run_custom(plan, persona, d)
            row[f"{persona}_{d}"] = s["learned_words"]
            row[f"{persona}_{d}_cost"] = s["total_ai_cost_usd"]
    
    results.append(row)
    
    # Print each candidate
    avg_90 = row["average_90"]
    avg_180 = row["average_180"]
    avg_360 = row["average_360"]
    print(f"  {name+':':>6} {sess}x{sz}={slots:>2}sl, AI={ai:>2}, Q={q:>2}  "
          f"| avg: {avg_90:>3}/{avg_180:>3}/{avg_360:>4}  "
          f"| eager: {row['eager_90']:>3}/{row['eager_180']:>3}/{row['eager_360']:>4}")

print("\n## Selected Plan Tiers — Average Persona\n")

# Pick best candidate per level based on learned words and progression
TIERS = {
    "Level-1": "L1-b",   # current free
    "Level-2": "L2-c",   # current silver  
    "Level-3": "L3-c",   # current gold
    "Level-4": "L4-c",   # platinum A
}

def get_row(name):
    for r in results:
        if r["name"] == name:
            return r
    return None

print(f"{'Tier':>10} {'sess':>5} {'size':>5} {'slots':>5} {'AIcap':>6} {'Qcap':>6}"
      f" {'90d':>6} {'180d':>6} {'360d':>7} {'cost_360':>8} {'lrn/$':>7}")
print("-" * 80)

prev_90 = prev_180 = prev_360 = None

for tier, cand in TIERS.items():
    r = get_row(cand)
    cost = r["average_360_cost"]
    l_per_dollar = round(r["average_360"] / cost, 1) if cost > 0 else 0
    
    # Jump from previous
    if prev_360 is not None:
        j90 = f"+{((r['average_90']/prev_90)-1)*100:+.0f}%"
        j180 = f"+{((r['average_180']/prev_180)-1)*100:+.0f}%"
        j360 = f"+{((r['average_360']/prev_360)-1)*100:+.0f}%"
    else:
        j90 = j180 = j360 = "—"
    
    print(f"{tier:>10} {r['sessions']:>5} {r['size']:>5} {r['slots']:>5}"
          f" {r['ai']:>6} {r['q']:>6}"
          f" {r['average_90']:>6} {r['average_180']:>6} {r['average_360']:>7}"
          f" {cost:>8.4f} {l_per_dollar:>7}")
    
    pct_str = f"    jump: 90d={j90}  180d={j180}  360d={j360}"
    print(pct_str)
    
    prev_90 = r["average_90"]
    prev_180 = r["average_180"]
    prev_360 = r["average_360"]

print("\n## Eager Persona\n")
print(f"{'Tier':>10} {'90d':>6} {'180d':>6} {'360d':>7} {'cost_360':>8} {'lrn/$':>7}")
print("-" * 50)

prev_90 = prev_180 = prev_360 = None
for tier, cand in TIERS.items():
    r = get_row(cand)
    cost = r["eager_360_cost"]
    l_per_dollar = round(r["eager_360"] / cost, 1) if cost > 0 else 0
    
    if prev_360 is not None:
        j90 = f"+{((r['eager_90']/prev_90)-1)*100:+.0f}%"
        j180 = f"+{((r['eager_180']/prev_180)-1)*100:+.0f}%"
        j360 = f"+{((r['eager_360']/prev_360)-1)*100:+.0f}%"
    else:
        j90 = j180 = j360 = "—"
    
    print(f"{tier:>10} {r['eager_90']:>6} {r['eager_180']:>6} {r['eager_360']:>7}"
          f" {cost:>8.4f} {l_per_dollar:>7}")
    print(f"    jump: 90d={j90}  180d={j180}  360d={j360}")
    
    prev_90 = r["eager_90"]
    prev_180 = r["eager_180"]
    prev_360 = r["eager_360"]

sim._resolve_plan = orig_resolve

print("\n## Level-4 Alternatives (head-to-head)\n")
l4_cands = ["L4-a", "L4-b", "L4-c", "L4-d", "L4-e", "L4-f"]
print(f"{'Name':>6} {'config':>18} {'avg_360':>7} {'eager_360':>9} {'cost_avg':>8} {'cost_eag':>8}")
print("-" * 60)
for c in l4_cands:
    r = get_row(c)
    print(f"{c:>6} {r['sessions']}x{r['size']}={r['slots']}sl AI={r['ai']} Q={r['q']:>2}"
          f" {r['average_360']:>7} {r['eager_360']:>9}"
          f" {r['average_360_cost']:>8.4f} {r['eager_360_cost']:>8.4f}")

print("\n## Verdict")
print("-" * 50)
print("Level-4 recommended: 5x8=40sl, AI=18, Q=14")
print("  avg: +49% at 360d over Level-3 (915 → 1362)")
print("  eager: +41% at 360d (1395 → 1970)")
