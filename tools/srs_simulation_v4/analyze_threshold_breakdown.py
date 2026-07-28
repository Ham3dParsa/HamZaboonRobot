"""Analyze threshold breakdown at checkpoints during SRS v4 simulation.

At each checkpoint (30, 120, 360, 720 days), inspects all cards in the
active pool and breaks down "learned" words by threshold path.

Usage:
    python analyze_threshold_breakdown.py
"""

import textwrap
import inspect

import simulator_v4 as sim

CHECKPOINT_DAYS = frozenset({30, 120, 360, 720})


def _make_simulate_with_checkpoints():
    """Dynamically create a simulate variant that captures checkpoint snapshots.

    Uses exec with the original source code and the module's namespace,
    injecting checkpoint tracking at two points:
      1. After variable initialization (creates checkpoints dict)
      2. At the end of each day loop (captures checkpoint data)
    Then changes the return to include checkpoints.
    """
    src = textwrap.dedent(inspect.getsource(sim.simulate))

    # --- Injection 1: initialize checkpoints dict ---
    init_marker = "    total_ease_count = 0"
    init_code = "    checkpoints: dict = {}\n"
    idx = src.find(init_marker)
    if idx == -1:
        raise RuntimeError("Cannot find init marker in simulate source")
    idx = src.index("\n", idx) + 1
    src = src[:idx] + init_code + src[idx:]

    # --- Injection 2: capture checkpoint data at end of each day ---
    capture_marker = "    learned = sum(1 for c in active if c.idx >= 3 or c.score >= 4.3)"
    capture_code = textwrap.dedent("""\
        elapsed = day + 1
        if elapsed in CHECKPOINT_DAYS:
            learned_via_idx = sum(1 for c in active if c.idx >= 3)
            learned_via_score_only = sum(1 for c in active if c.score >= 4.3 and c.idx < 3)
            learned_via_both = sum(1 for c in active if c.idx >= 3 and c.score >= 4.3)
            checkpoints[elapsed] = {
                "learned_via_idx": learned_via_idx,
                "learned_via_score_only": learned_via_score_only,
                "learned_via_both": learned_via_both,
                "total": learned_via_idx + learned_via_score_only,
            }
    """)
    capture_code = textwrap.indent(capture_code, "        ")
    if capture_marker not in src:
        raise RuntimeError("Cannot find capture marker in simulate source")
    src = src.replace(capture_marker, capture_code + "\n" + capture_marker)

    # --- Injection 3: return checkpoints alongside rows and summary ---
    if "return rows, summary" not in src:
        raise RuntimeError("Cannot find return statement in simulate source")
    src = src.replace("return rows, summary", "return rows, summary, checkpoints")

    # Execute in the module's namespace with CHECKPOINT_DAYS injected
    namespace = dict(sim.__dict__)
    namespace["CHECKPOINT_DAYS"] = CHECKPOINT_DAYS
    exec(src, namespace)
    return namespace["simulate"]


simulate_with_checkpoints = _make_simulate_with_checkpoints()


def run_analysis():
    cfg = sim.SimConfig(
        plan="gold",
        persona="average",
        proficiency="advanced",
        days=720,
        seed=42,
    )
    rows, summary, checkpoints = simulate_with_checkpoints(cfg)

    print("Threshold Breakdown at Checkpoints")
    print("Scenario: gold/average/advanced, 720 days, seed=42")
    print()
    header = (
        f"{'Day':>6} | {'learned_via_idx':>14} | {'score_only':>11} | "
        f"{'both':>5} | {'total':>6} | {'%score_only':>11}"
    )
    print(header)
    print("-" * len(header))
    for d in sorted(checkpoints):
        cp = checkpoints[d]
        total = cp["total"]
        pct = 100.0 * cp["learned_via_score_only"] / total if total > 0 else 0.0
        print(
            f"{d:>6} | {cp['learned_via_idx']:>14} | {cp['learned_via_score_only']:>11} | "
            f"{cp['learned_via_both']:>5} | {total:>6} | {pct:>10.1f}%"
        )
    print("-" * len(header))

    # Cross-check: final checkpoint total vs summary.learned_words
    final_cp = checkpoints.get(720)
    match = (final_cp is not None and final_cp["total"] == summary["learned_words"])
    print()
    print(f"Cross-check: checkpoint[720].total == summary.learned_words ? "
          f"{'YES' if match else 'NO'}")
    if not match:
        print(f"  checkpoint[720].total = {final_cp['total'] if final_cp else 'N/A'}")
        print(f"  summary.learned_words = {summary['learned_words']}")

    print()
    print("Final Summary stats:")
    for key in ["total_active_words", "learned_words", "avg_score", "avg_user_ease",
                "max_due_backlog", "max_query_backlog", "avg_lateness_days",
                "total_ai_calls", "total_ai_cost_usd"]:
        print(f"  {key}: {summary[key]}")


if __name__ == "__main__":
    run_analysis()
