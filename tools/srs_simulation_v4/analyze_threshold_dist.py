"""Analyze score distribution at each idx level across personas."""
import textwrap, inspect
import simulator_v4 as sim

CHECKPOINT_DAYS = frozenset({120, 360, 720})

def instrumented_simulate():
    src = textwrap.dedent(inspect.getsource(sim.simulate))
    # Inject checkpoint capture with score distribution per idx
    cap_marker = "    learned = sum(1 for c in active if c.idx >= 3 or c.score >= 4.3)"
    cap_code = textwrap.dedent("""\
        elapsed = day + 1
        if elapsed in CHECKPOINT_DAYS:
            # score distribution per idx
            score_by_idx = {}
            for c in active:
                score_by_idx.setdefault(c.idx, []).append(c.score)
            checkpoints[elapsed] = {
                'score_by_idx': {k: (min(v), max(v), round(sum(v)/len(v),2), len(v)) 
                                 for k, v in score_by_idx.items()},
                'learned': sum(1 for c in active if c.idx >= 3 or c.score >= 4.3),
            }
    """)
    cap_code = textwrap.indent(cap_code, "        ")
    src = src.replace(cap_marker, cap_code + "\n" + cap_marker)

    init_marker = "    total_ease_count = 0"
    init_code = "    checkpoints: dict = {}\n"
    idx = src.find(init_marker)
    idx = src.index("\n", idx) + 1
    src = src[:idx] + init_code + src[idx:]

    if "return rows, summary" not in src:
        raise RuntimeError("Cannot find return")
    src = src.replace("return rows, summary", "return rows, summary, checkpoints")

    ns = dict(sim.__dict__)
    ns["CHECKPOINT_DAYS"] = CHECKPOINT_DAYS
    exec(src, ns)
    return ns["simulate"]

sim_instr = instrumented_simulate()

configs = [
    ('gold', 'lazy', 'beginner'),
    ('gold', 'average', 'intermediate'),
    ('gold', 'eager', 'advanced'),
    ('silver', 'average', 'intermediate'),
]

for plan, persona, prof in configs:
    cfg = sim.SimConfig(plan=plan, persona=persona, days=720, seed=42, proficiency=prof)
    _, summary, cps = sim_instr(cfg)
    
    print(f"\n{'='*60}")
    print(f"{plan}/{persona}/{prof} — learned={summary['learned_words']}")
    print(f"{'='*60}")
    
    for d in sorted(cps):
        cp = cps[d]
        sbd = cp['score_by_idx']
        print(f"\n  Day {d}:")
        for idx in sorted(sbd):
            mn, mx, avg, cnt = sbd[idx]
            # How many at this idx would qualify for score>=4.3? score>=4.0? score>=3.5?
            mark = '✨' if mx >= 4.0 else '  '
            mark43 = '🔥' if mx >= 4.3 else '  '
            print(f"    idx={idx}: count={cnt:>4}, score range=[{mn:.2f}–{mx:.2f}], avg={avg:.2f} {mark43}")

    # Also check: what threshold would give a meaningful contribution?
    # We need to re-run for threshold analysis
