import importlib.util
import random
import sys

spec = importlib.util.spec_from_file_location(
    'v5_4',
    r'C:\Python_Programming\#T-Bot\HamZaban\tools\Fsrs_simulation_v5\v5.4_FSRS_full.py'
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

PERSONA_KEYS = ["eager", "average", "lazy", "fluctuating"]
SIM_DAYS = 360
RUNS = 200
SEED_BASE = 42
SUMMARY_FILE = r'C:\Python_Programming\#T-Bot\HamZaban\tools\Fsrs_simulation_v5\v54_validation_report.txt'

GRADE_TARGETS = {
    "eager":        [0.02, 0.05, 0.60, 0.33],
    "average":      [0.08, 0.15, 0.55, 0.22],
    "lazy":         [0.15, 0.20, 0.50, 0.15],
    "fluctuating":  [0.10, 0.15, 0.55, 0.20],
}
GRADE_NAMES = ["Again", "Hard", "Good", "Easy"]
TOLERANCE = 0.02


def run_simulation(persona_key, run_idx):
    seed = SEED_BASE * 1000 + run_idx
    cfg = m.SimConfig(
        plan="gold",
        persona=persona_key,
        days=SIM_DAYS,
        seed=seed,
        enable_rejection=False,
        enable_catchup=True,
        enable_session_rate_limit=True,
        jitter=0.15,
    )
    _, s = m.simulate(cfg)
    return s


def check_first_exposure_grade_dist(persona_key):
    """Check grade distribution at R=1.0 (first exposure) against targets."""
    target = GRADE_TARGETS[persona_key]
    rng = random.Random(persona_key + "_first_exp")
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    n = 5000
    for _ in range(n):
        grade = m._sample_grade(persona_key, 1.0, rng)
        counts[grade] += 1
    dist = [counts[i] / n for i in [1, 2, 3, 4]]
    ok = True
    details = []
    for i in range(4):
        diff = abs(dist[i] - target[i])
        status = "OK" if diff <= TOLERANCE else "FAIL"
        if diff > TOLERANCE:
            ok = False
        details.append("  {}: target={:.2f} actual={:.2f} diff={:.3f} {}".format(
            GRADE_NAMES[i], target[i], dist[i], diff, status
        ))
    return ok, details


def check_difficulty_degradation(persona_key):
    """Check that difficulty mean reverts properly after lapses (no Ease Hell)."""
    rng = random.Random(persona_key + "_degrade")
    diffs_after_10_reviews = []
    for _ in range(1000):
        d = m._dsr_d0(4)  # start at Easy
        s = m._dsr_s0(4)
        for review in range(10):
            r = 0.5  # low retrievability → more lapses
            grade = m._sample_grade(persona_key, r, rng)
            d = m._dsr_update_difficulty(d, grade)
            s = m._dsr_update_stability(d, s, r, grade)
        diffs_after_10_reviews.append(d)
    mean_d = sum(diffs_after_10_reviews) / len(diffs_after_10_reviews)
    pct_below_2 = sum(1 for d in diffs_after_10_reviews if d < 2.0) / len(diffs_after_10_reviews)
    ok = pct_below_2 < 0.5  # less than 50% of cards stuck at extreme low difficulty
    return ok, mean_d, pct_below_2


def main():
    lines = []
    lines.append("=" * 70)
    lines.append("v5.4 FSRS Full - Validation Report")
    lines.append("Simulations: {} runs x {} days per persona".format(RUNS, SIM_DAYS))
    lines.append("Grade dist tolerance: +/- {:.0%}".format(TOLERANCE))
    lines.append("=" * 70)

    all_grade_ok = True
    all_ease_ok = True

    for persona_key in PERSONA_KEYS:
        lines.append("\n--- Persona: {} ---".format(persona_key))

        grade_ok, grade_details = check_first_exposure_grade_dist(persona_key)
        for d in grade_details:
            lines.append(d)
        if grade_ok:
            lines.append("  First-exposure grade distribution: PASS")
        else:
            lines.append("  First-exposure grade distribution: FAIL")
            all_grade_ok = False

        ease_ok, mean_d, pct_below = check_difficulty_degradation(persona_key)
        lines.append("  Difficulty degradation: mean_d={:.2f} pct_below_2={:.1f}% {}".format(
            mean_d, pct_below * 100, "PASS" if ease_ok else "FAIL"
        ))
        if not ease_ok:
            all_ease_ok = False

    lines.append("\n--- Full Simulation ({} runs per persona, {}d) ---".format(RUNS, SIM_DAYS))
    learned_words = {}
    for persona_key in PERSONA_KEYS:
        total_learned = 0
        total_late = 0.0
        max_late = 0
        for i in range(RUNS):
            seed = SEED_BASE * 1000 + i + hash(persona_key) % 10000
            cfg = m.SimConfig(
                plan="gold",
                persona=persona_key,
                days=SIM_DAYS,
                seed=seed,
                enable_rejection=False,
                enable_catchup=True,
                enable_session_rate_limit=True,
                jitter=0.15,
            )
            _, s = m.simulate(cfg)
            total_learned += s["learned_words"]
            total_late += s["avg_lateness_days"]
            max_late = max(max_late, s["max_lateness_days"])
        avg_learned = total_learned / RUNS
        avg_late = total_late / RUNS
        learned_words[persona_key] = avg_learned
        lines.append("  {}: avg_learned={:.1f} avg_late={:.1f} max_late={}".format(
            persona_key, avg_learned, avg_late, max_late
        ))

    lines.append("\n--- Learned Words Ratio (lazy / average / eager) ---")
    lazy_ratio = learned_words.get("lazy", 0) / max(learned_words.get("average", 1), 1)
    avg_ratio = learned_words.get("average", 0) / max(learned_words.get("eager", 1), 1)
    lines.append("  lazy/average ratio: {:.3f}".format(lazy_ratio))
    lines.append("  average/eager ratio: {:.3f}".format(avg_ratio))

    lines.append("\n--- Summary ---")
    all_ok = all_grade_ok and all_ease_ok
    if all_ok:
        lines.append("  ALL CHECKS PASSED")
    else:
        lines.append("  SOME CHECKS FAILED")
        if not all_grade_ok:
            lines.append("  - Grade distributions outside tolerance")
        if not all_ease_ok:
            lines.append("  - Difficulty degradation detected")

    report = "\n".join(lines)
    print(report)

    with open(SUMMARY_FILE, 'w', encoding='utf-8') as f:
        f.write(report)
    print("\nReport written to:", SUMMARY_FILE)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())