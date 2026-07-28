"""
Compare v3 (Claude's Golden) vs v4.2-sweet across 4 time horizons.
Now includes score-only learned words breakdown and query AI costs.

Run: python compare_v3_v4.py
"""
import sys, os
import textwrap, inspect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
    "srs_simulation_v3", "Claude's Version"))
sys.path.insert(0, os.path.dirname(__file__))

from simulator import SimConfig as V3Config, simulate as v3_simulate
from simulator_v4 import SimConfig as V4Config, simulate as v4_simulate
from simulator_v4 import PLAN_DEFAULTS as V4_PLANS
from simulator_v4 import PERSONAS as V4_PERSONAS

PERSONAS = ["lazy", "average", "eager", "fluctuating"]
PLANS = ["free", "silver", "gold"]
HORIZONS = [30, 120, 360, 720]
CHECKPOINT_DAYS = frozenset(HORIZONS)

report = []
def log(line):
    print(line)
    report.append(line)

# ------------------------------------------------------------------
# Instrumented v4 simulate that also captures score-vs-idx breakdown
# ------------------------------------------------------------------
def _make_instrumented():
    src = textwrap.dedent(inspect.getsource(v4_simulate))
    cap_marker = "    learned = sum(1 for c in active if c.idx >= 3 or c.score >= 3.75)"
    cap_code = textwrap.dedent("""\
        elapsed = day + 1
        if elapsed in CHECKPOINT_DAYS:
            learned_via_idx = sum(1 for c in active if c.idx >= 3)
            score_only = sum(1 for c in active if c.score >= 3.0 and c.idx < 3)
            both = sum(1 for c in active if c.idx >= 3 and c.score >= 3.0)
            learn_breakdown[elapsed] = {
                'learned_via_idx': learned_via_idx,
                'score_only': score_only,
                'both': both,
                'total': learned_via_idx + score_only,
            }
    """)
    cap_code = textwrap.indent(cap_code, "        ")
    src = src.replace(cap_marker, cap_code + "\n" + cap_marker)

    init_marker = "    total_ease_count = 0"
    init_code = "    learn_breakdown: dict = {}\n"
    idx = src.find(init_marker)
    idx = src.index("\n", idx) + 1
    src = src[:idx] + init_code + src[idx:]

    ret_marker = "return rows, summary"
    src = src.replace(ret_marker, "return rows, summary, learn_breakdown")

    ns = dict(__import__('simulator_v4').__dict__)
    ns["CHECKPOINT_DAYS"] = CHECKPOINT_DAYS
    exec(src, ns)
    return ns["simulate"]

_v4_sim_instr = _make_instrumented()

_v4_sim_instr = _make_instrumented()

def v4_sim_with_breakdown(**kw):
    cfg = V4Config(**kw)
    _, s, lb = _v4_sim_instr(cfg)
    return s, lb

# =====================================================================
# Section 1: Full comparison table (all plans x personas x horizons)
# =====================================================================
log("# v3 (Claude's Golden) vs v4.2-sweet — Side by Side\n")
log(f"Seed=42, personas across 3 plans, 4 time horizons.  "
     f"v4 threshold: idx>=3 OR score>=3.75 (gain=0.8*(1-s/7), hold=0.15*(1-s/7), start=2.5).\n")
log("KEY DIFFERENCES:")
log("  v3: intervals=[1,3,9,18,38,70,120,250,400,730], gold=5x9=45 slots")
log("  v4: intervals=[1,3,7,15,30,60,120,240,480,960], gold=4x7=28 slots")
log("  v3: binary score (+0.5/-1.0), NO decay, NO ease, NO rejection")
log("  v4: continuous mastery, exponential decay, ease [0.7-1.5], AI rejection")
log("  v3: learned=idx>=2; v4: learned=idx>=3 OR score>=3.0 (score-only column tracked)")
log("  v3: query split 50/50 → self-correcting; v4: query-first-full + AI leftover")
log("  v4: queries now count as AI calls (same $0.0006/cost as AI gen)")
log("")

HEADER = (
    f"{'days':>5} {'plan':7} {'persona':12} {'v':3}"
    f" {'active':>6} {'learned':>8} {'score':>6} {'due_bl':>7} {'q_bl':>6}"
    f" {'ai_gen':>7}"
    f" | v:4"
    f" {'active':>6} {'learned':>8} {'score':>6} {'due_bl':>7} {'q_bl':>6}"
    f" {'ai_gen':>7} {'ai_q':>7} {'ease':>6}"
)
SEP = "-" * len(HEADER)

for days in HORIZONS:
    log(f"\n## {days}-day Comparison\n")
    log(HEADER)
    log(SEP)
    for plan in PLANS:
        for persona in PERSONAS:
            cfg3 = V3Config(plan=plan, persona=persona, days=days, seed=42)
            _, s3 = v3_simulate(cfg3)
            s4, lb = v4_sim_with_breakdown(plan=plan, persona=persona, days=days, seed=42)

            log(
                f"{days:>5} {plan:7} {persona:12} {3:>1}"
                f" {s3['final_active_cards']:>6} {s3['learned_words']:>8}"
                f" {s3['avg_score']:>6} {s3['max_due_backlog']:>7}"
                f" {s3['max_query_backlog']:>6} {s3.get('total_new_words', s3.get('total_ai_calls', 0)):>7}"
                f" | {4:>1}"
                f" {s4['final_active_cards']:>6} {s4['learned_words']:>8}"
                f" {s4['avg_score']:>6} {s4['max_due_backlog']:>7}"
                f" {s4['max_query_backlog']:>6}"
                f" {s4.get('created_by_ai', s4.get('total_ai_calls', 0)):>7}"
                f" {s4.get('total_query_calls', 0):>7}"
                f" {s4.get('avg_user_ease', 1.0):>6.2f}"
            )
    log("")

# =====================================================================
# Section 2: Normalized: gold only, including score-only breakdown
# =====================================================================
log("\n## Normalized: gold only, all personas — with score threshold breakdown\n")
log(f"{'days':>5} {'persona':12} {'v3_learn':>9} {'v4_learn':>9} {'delta':>7}"
     f" {'v3_score':>9} {'v4_score':>9} {'v4_ai_gen':>9} {'v4_ai_q':>9}"
     f" {'v4_ease':>6} {'score_only':>10} {'idx_only':>10} {'both':>6}")
log("-" * 130)
for days in HORIZONS:
    for persona in PERSONAS:
        cfg3 = V3Config(plan="gold", persona=persona, days=days, seed=42)
        _, s3 = v3_simulate(cfg3)
        s4, lb = v4_sim_with_breakdown(plan="gold", persona=persona, days=days, seed=42)

        ld = s4['learned_words'] - s3['learned_words']
        ld_str = f"+{ld}" if ld >= 0 else str(ld)

        cp = lb.get(days, {})
        so = cp.get('score_only', 0)
        io = cp.get('learned_via_idx', 0)
        bt = cp.get('both', 0)

        log(f"{days:>5} {persona:12}"
            f" {s3['learned_words']:>9} {s4['learned_words']:>9} {ld_str:>7}"
            f" {s3['avg_score']:>9} {s4['avg_score']:>9}"
            f" {s4.get('created_by_ai', 0):>9}"
            f" {s4.get('total_query_calls', 0):>9}"
            f" {s4.get('avg_user_ease', 1.0):>6.2f}"
            f" {so:>10} {io:>10} {bt:>6}"
        )

# =====================================================================
# Section 3: Aggregate summary (averaged across all personas, gold only)
# =====================================================================
log("\n## Aggregate Summary (gold, avg across 4 personas)\n")
log(f"{'days':>5} {'v3_learned':>11} {'v4_learned':>11} {'delta%':>9}"
     f" {'v3_ai':>9} {'v4_ai':>9} {'v4_cost':>9} {'v4_learned/$':>13}")
log("-" * 80)

for days in HORIZONS:
    v3_l = 0; v4_l = 0; v3_a = 0; v4_a = 0; v4_c = 0.0
    for persona in PERSONAS:
        cfg3 = V3Config(plan="gold", persona=persona, days=days, seed=42)
        _, s3 = v3_simulate(cfg3)
        s4, _ = v4_sim_with_breakdown(plan="gold", persona=persona, days=days, seed=42)
        v3_l += s3['learned_words']
        v4_l += s4['learned_words']
        v3_a += s3.get('total_new_words', s3.get('total_ai_calls', 0))
        v4_a += s4['total_ai_calls']
        v4_c += s4['total_ai_cost_usd']

    delta_pct = (v4_l - v3_l) / v3_l * 100 if v3_l else 0
    eff = round(v4_l / v4_c, 1) if v4_c else 0
    log(f"{days:>5} {v3_l:>11} {v4_l:>11} {delta_pct:>+8.1f}%"
        f" {v3_a:>9} {v4_a:>9} {v4_c:>9.4f} {eff:>13}")

with open(os.path.join(os.path.dirname(__file__), "v3_vs_v4_comparison.md"),
          "w", encoding="utf-8") as f:
    f.write("\n".join(report))
print(f"\n(report written to v3_vs_v4_comparison.md)")
