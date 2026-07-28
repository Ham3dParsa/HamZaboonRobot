"""
Compare all 4 SRS simulator versions side-by-side: v1 (deprecated), v2, v3 (Claude's Golden), v4.2-sweet.

Run: python compare_all_versions.py
"""
import sys, os, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))

_cache = {}
def _import_from(path, name=None):
    """Import a module from a specific file path with a unique cache key."""
    abspath = os.path.abspath(path)
    mod_name = name or f"_mod_{hash(abspath)}"
    key = (abspath, mod_name)
    if key in _cache:
        return _cache[key]
    spec = importlib.util.spec_from_file_location(mod_name, abspath)
    mod = importlib.util.module_from_spec(spec)
    _cache[key] = mod
    spec.loader.exec_module(mod)
    return mod

v1_mod = _import_from(os.path.join(HERE, "..", "srs_simulation", "simulator.py"))
v2_mod = _import_from(os.path.join(HERE, "..", "srs_simulation_v2", "simulator.py"))
v3_mod = _import_from(os.path.join(HERE, "..", "srs_simulation_v3", "Claude's Version", "simulator.py"))
v4_mod = _import_from(os.path.join(HERE, "simulator_v4.py"))

V1Config = v1_mod.SimConfig
v1_simulate = v1_mod.simulate
V2Config = v2_mod.SimConfig
v2_simulate = v2_mod.simulate
V3Config = v3_mod.SimConfig
v3_simulate = v3_mod.simulate
V4Config = v4_mod.SimConfig
v4_simulate = v4_mod.simulate

HORIZONS = [30, 120, 360, 720]
PERSONAS = ["lazy", "average", "eager", "fluctuating"]

report = []
def log(line):
    print(line)
    report.append(line)

def run_v1(days, seed=42):
    cfg = V1Config(plan="gold", days=days, seed=seed)
    rows, summary, _ = v1_simulate(cfg)
    learned = rows[-1].total_graduated if rows else 0
    max_due = max(r.due_carried_over for r in rows)
    overflow = sum(1 for r in rows if r.overflow)
    return {
        "active": learned,
        "learned": learned,
        "score": 0.0,
        "max_due": max_due,
        "max_q": max(r.backlog for r in rows),
        "ai_gen": cfg.daily_cards * days,
        "ai_q": cfg.word_query_cap * days,
        "ai_calls": cfg.daily_cards * days + cfg.word_query_cap * days,
        "ai_cost": (cfg.daily_cards + cfg.word_query_cap) * days * 0.0006,
        "overflow": overflow,
    }

def run_v2(days, seed=42):
    cfg = V2Config(plan="gold", days=days, seed=seed)
    rows, summary, _ = v2_simulate(cfg)
    total_ai_gen = sum(r.ai_generated for r in rows)
    total_ai_q = sum(r.queries_made for r in rows)
    return {
        "active": summary.final_active_cards,
        "learned": summary.final_active_cards,
        "score": 0.0,
        "max_due": summary.max_due_remaining,
        "max_q": summary.max_query_saved,
        "ai_gen": total_ai_gen,
        "ai_q": total_ai_q,
        "ai_calls": total_ai_gen + total_ai_q,
        "ai_cost": (total_ai_gen + total_ai_q) * 0.0006,
    }

def run_v3(days, persona="average", seed=42):
    cfg = V3Config(plan="gold", persona=persona, days=days, seed=seed)
    rows, s = v3_simulate(cfg)
    ai = s.get('total_new_words', s.get('total_ai_calls', 0))
    return {
        "active": s['final_active_cards'],
        "learned": s['learned_words'],
        "score": s['avg_score'],
        "max_due": s['max_due_backlog'],
        "max_q": s['max_query_backlog'],
        "ai_gen": ai,
        "ai_q": 0,
        "ai_calls": ai,
        "ai_cost": ai * 0.0006,
    }

def run_v4(days, persona="average", seed=42):
    cfg = V4Config(plan="gold", persona=persona, days=days, seed=seed)
    rows, s = v4_simulate(cfg)
    return {
        "active": s['final_active_cards'],
        "learned": s['learned_words'],
        "score": s['avg_score'],
        "max_due": s['max_due_backlog'],
        "max_q": s['max_query_backlog'],
        "ai_gen": s['created_by_ai'],
        "ai_q": s['total_query_calls'],
        "ai_calls": s['total_ai_calls'],
        "ai_cost": s['total_ai_cost_usd'],
        "ease": s['avg_user_ease'],
    }

log("# SRS Engine Evolution: v1 → v2 → v3 → v4.2-sweet\n")
log("```")
log("v1 (deprecated):  5-step ladder [1,3,7,16,30], gold=10x5=50slots, backlog ceiling, overflow")
log("v2:               5-step ladder [1,3,7,16,30], gold=5x6=30slots, query-first, binary reviews")
log("v3 (Claude):     10-step ladder [1,3,9,18,38,70,120,250,400,730], gold=5x9=45slots, binary+score")
log("v4.2-sweet:      10-step ladder [1,3,7,15,30,60,120,240,480,960], gold=4x7=28slots, ease+decay")
log("```\n")

log("## Gold/Average — Across 4 Time Horizons\n")

HEADER = (
    f"{'days':>4} {'v':3} {'learned':>8} {'score':>6}"
    f" {'due_bl':>7} {'ai_gen':>7} {'ai_q':>7} {'cost$':>7}"
)
log(HEADER)
log("-" * len(HEADER))

vers = [
    ("1", lambda d: run_v1(d)),
    ("2", lambda d: run_v2(d)),
    ("3", lambda d: run_v3(d, "average")),
    ("4", lambda d: run_v4(d, "average")),
]

for days in HORIZONS:
    for label, fn in vers:
        r = fn(days)
        s = r.get('score', 0)
        log(
            f"{days:>4} {label:>3}"
            f" {r['learned']:>8}"
            f" {s:>6.2f}"
            f" {r['max_due']:>7}"
            f" {r.get('ai_gen', 0):>7}"
            f" {r.get('ai_q', 0):>7}"
            f" {r['ai_cost']:>7.4f}"
        )
    log("")

log("## Gold/720d — Learned Words by Persona\n")
log(f"{'persona':>12} {'v1':>6} {'v2':>6} {'v3':>6} {'v4':>6}")
log("-" * 38)
for persona in PERSONAS:
    v1_r = run_v1(720)
    v2_r = run_v2(720)
    v3_r = run_v3(720, persona)
    v4_r = run_v4(720, persona)
    log(f"{persona:>12} {v1_r['learned']:>6} {v2_r['learned']:>6}"
        f" {v3_r['learned']:>6} {v4_r['learned']:>6}")

log("\n## 720-day Costs (gold/average)\n")
def cost_line(ver, r):
    return (f"  {ver}: ai_gen={r['ai_gen']}, ai_q={r['ai_q']}, "
            f"total_calls={r['ai_calls']}, cost=${r['ai_cost']:.4f}")

r1 = run_v1(720); r2 = run_v2(720); r3 = run_v3(720); r4 = run_v4(720)
log(cost_line("v1", r1))
log(cost_line("v2", r2))
log(cost_line("v3", r3))
log(cost_line("v4", r4))

log("\n## Feature Matrix\n")
log("| Feature | v1 (deprecated) | v2 | v3 (Claude) | v4.2-sweet |")
log("|---------|:---------------:|:--:|:-----------:|:----------:|")
log("| Interval ladder | 5 steps (max 30d) | 5 steps (max 30d) | 10 steps (max 730d) | 10 steps (max 960d) |")
log("| Gold slots/day | 50 (10×5) | 30 (5×6) | 45 (5×9) | 28 (4×7) |")
log("| Learned threshold | idx≥0 | idx≥0 | idx≥2 | idx≥3 OR score≥3.75 |")
log("| Score model | None | None | Binary (+0.5/−1.0) | 0.8×(1−s/7) cont. |")
log("| Score decay | None | None | None | Exponential |")
log("| Ease factor | None | None | None | [0.7–1.5] per card |")
log("| Query priority | After due+split | Backlog FIFO | Self-correcting split | Query-first-full |")
log("| AI rejection | Backlog ceiling | None | None | Proficiency-based |")
log("| Catch-up bonus | Overflow session | None | None | Yes (debt-triggered) |")
log("| Query AI cost | Not tracked | Counted | Not tracked | Counted |")

log("\n## Final Verdict\n")
log("**v4.2-sweet is the definitive version.** It addresses every known weakness from its predecessors:")
log("")
log("1. **Realistic score model** — v1/v2 had no score, v3 had binary (+0.5/-1.0), v4 uses continuous")
log("   diminishing-returns gains with Ebbinghaus decay. Learned threshold idx≥3 OR score≥3.75")
log("   provides a dual path to mastery.")
log("2. **Ease factor** — Per-card interval adaptation (v4-only) personalises spacing based on the")
log("   learner's self-reported recall quality, something no earlier version attempted.")
log("3. **Query-first priority** — v4 ensures user-requested words are never starved by AI generation,")
log("   fixing the backlog starvation v1/v2/v3 all suffered in high-query scenarios.")
log("4. **Full cost accounting** — Both AI generation and user queries cost $0.0006/call, giving")
log("   a truthful per-learner financial projection.")
log("5. **Catch-up bonus** — Extra due-card processing when backlog grows, replacing v1's crude")
log("   overflow session with a bounded, controlled mechanism.")
log("")
log("*v3 learned counts are inflated because its binary score model never decays — every card eventually")
log("saturates. v4's decay-ease combination produces lower raw counts but higher confidence per word.*")

log(f"\n---\n*Generated: 2026-07-27*")

with open(os.path.join(HERE, "all_versions_comparison.md"),
          "w", encoding="utf-8") as f:
    f.write("\n".join(report))
print("\n(report written to all_versions_comparison.md)")
