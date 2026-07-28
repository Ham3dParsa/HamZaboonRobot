"""SRS Session Engine v3 Simulation — CLI entry point (Hybrid Session Engine).

Pure Python simulation of the session-based hybrid SRS engine.
No AI, no database.

Usage:
    python -m tools.srs_simulation_v3                     (interactive)
    python -m tools.srs_simulation_v3 --plan free --days 30 --seed 42
    python -m tools.srs_simulation_v3 --help
"""

import argparse
import sys

from tools.srs_simulation_v3.simulator_v3 import (
    PLAN_DEFAULTS,
    SimConfig,
    simulate,
    format_table,
    write_csv,
)

PLAN_CHOICES = ["free", "silver", "gold"]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SRS v3 Hybrid Session Simulation — test session-based engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.srs_simulation_v3
  python -m tools.srs_simulation_v3 --plan free --days 30 --seed 42
  python -m tools.srs_simulation_v3 --plan gold --days 90 --seed 7 --csv gold_v3.csv
  python -m tools.srs_simulation_v3 --no-three-buttons --no-score --no-random-intervals
        """,
    )
    p.add_argument("--plan", choices=PLAN_CHOICES, default=None,
                    help="Plan tier: free, silver, or gold (controls default caps)")
    p.add_argument("--days", type=int, default=None,
                    help="How many days to simulate (default: 30)")
    p.add_argument("--ai-daily-cap", type=int, default=None,
                    help="Maximum AI cards that can be generated per day (plan default)")
    p.add_argument("--query-daily-cap", type=int, default=None,
                    help="How many word queries the user makes per day (plan default)")
    p.add_argument("--save-gate-rate", type=float, default=None,
                    help="Chance (0.0-1.0) a query saves to review (default: 0.5)")
    p.add_argument("--forget-rate", type=float, default=None,
                    help="Chance user clicks Again vs Remembered (default: 0.15)")
    p.add_argument("--sessions", type=int, default=None,
                    help="Review sessions per day (plan default)")
    p.add_argument("--session-size", type=int, default=None,
                    help="Cards per session (plan default: free=4, silver=6, gold=7)")
    p.add_argument("--seed", type=int, default=None,
                    help="Random seed for repeatable runs")
    p.add_argument("--report-every", type=int, default=None,
                    help="Print table every N days (default: 5, 0=final only)")
    p.add_argument("--csv", type=str, default=None,
                    help="Save results to CSV file")
    
    # Feature toggles
    p.add_argument("--no-three-buttons", action="store_true",
                    help="Disable 3-button review; use classic 2-button (Remembered/Again)")
    p.add_argument("--no-score", action="store_true",
                    help="Disable familiarity score tracking and interval adjustment")
    p.add_argument("--no-random-intervals", action="store_true",
                    help="Use fixed [1,3,7,16,30] intervals for all cards")
    return p.parse_args(argv)


def _interactive_run() -> None:
    print("\n" + "=" * 60)
    print("  SRS v3 Hybrid Session Simulation — Interactive Mode")
    print("=" * 60)
    print()
    print("This simulates the session-based hybrid SRS engine.")
    print("Queried/saved words immediately graduate and become due tomorrow.")
    print("AI cards fill remaining session slots.")
    print()
    print("Features: 3-button review (LATER/NEUTRAL/SOONER), familiarity score,")
    print("          randomized interval sets to spread due dates.")
    print("  (Disable with --no-three-buttons, --no-score, --no-random-intervals)")
    print()
    print("Press Enter to accept defaults shown in [brackets].")
    print()

    print("--- PLAN TIER ---")
    print("Free:   1 session x 4 cards  |  AI cap 3   |  Queries 3")
    print("Silver: 3 sessions x 6 cards |  AI cap 15  |  Queries 7")
    print("Gold:   4 sessions x 7 cards |  AI cap 20  |  Queries 10")
    plan = _prompt("Plan", default="free", choices=PLAN_CHOICES)
    print()

    print("--- DURATION ---")
    print("How many days to simulate?")
    print("  30 = one month, 60-90 shows long-term trends")
    days = int(_prompt("Days", default="30"))
    print()

    print("--- AI BUDGET (cap per day) ---")
    print("Maximum AI-generated cards allowed per day.")
    print("The system only uses AI if slots remain after due cards.")
    print("  Each query also counts as an AI API call (true financial tracking).")
    print(f"  Plan default: {PLAN_DEFAULTS[plan]['ai_daily_cap']}")
    ai_cap = _prompt_int("AI daily cap", default=None)
    print()

    print("--- WORD QUERIES ---")
    print("How many 'Ask a Word' queries per day? (Randomized)")
    print("  User makes 0..CAP queries daily (each roll is independent).")
    print("  Realistic: some days many, some days none.")
    print(f"  Plan default: {PLAN_DEFAULTS[plan]['query_daily_cap']}")
    q_cap = _prompt_int("Query daily cap", default=None)
    print()

    print("--- QUERY SAVE RATE ---")
    print("Chance each query gets saved to the review backlog.")
    print("  0.5 = 50% of queries become review cards")
    print("  Higher = more backlog, less AI cost.")
    q_save = float(_prompt("Save probability (0.0 to 1.0)", default="0.5"))
    print()

    print("--- FORGET RATE ---")
    print("How often does the user click 'Again' (forgot)?")
    print("  0.15 = 15% (typical learner)")
    print("  0.3+ = struggling, more resets to early intervals")
    forget_rate = float(_prompt("Forget rate (0.0 to 1.0)", default="0.15"))
    print()

    print("--- REVIEW SESSIONS ---")
    print("How many review sessions per day?")
    print("  Each session has multiple card slots.")
    print(f"  Plan default: {PLAN_DEFAULTS[plan]['sessions']}")
    sessions = _prompt_int("Sessions per day", default=None)
    print()

    print("--- CARDS PER SESSION ---")
    print("How many cards fit in one session?")
    print(f"  Free=4, Silver=6, Gold=7 (paid users can customize)")
    print(f"  Plan default: {PLAN_DEFAULTS[plan]['session_size']}")
    sess_size = _prompt_int("Cards per session", default=None)
    print()

    print("--- RANDOM SEED ---")
    print("Same seed = same results every time.")
    print("  Empty = random each run")
    print("  Pick a number (e.g. 42) for fair comparisons")
    seed_raw = _prompt("Seed (number, or empty for random)", default="")
    seed = None if seed_raw.strip() == "" else int(seed_raw)
    print()

    print("--- REPORT FREQUENCY ---")
    print("How often to print the progress table?")
    print("  1 = every day, 5 = every 5 days, 0 = final only")
    report = int(_prompt("Report every N days", default="5"))
    print()

    print("--- CSV EXPORT ---")
    csv_path = _prompt("CSV file path (or empty to skip)", default="")
    csv_path = csv_path.strip().strip('"').strip("'")
    csv_path = None if csv_path == "" else csv_path

    cfg = SimConfig(
        plan=plan, days=days,
        ai_daily_cap=ai_cap,
        query_daily_cap=q_cap, save_gate_rate=q_save,
        forget_rate=forget_rate,
        sessions=sessions, session_size=sess_size,
        seed=seed, report_every=report,
        three_button_mode=True,
        score_enabled=True,
        random_intervals=True,
    )

    print()
    print("Running simulation...")
    print()
    rows, summary, _ = simulate(cfg)
    print(format_table(rows, summary, cfg))
    if csv_path:
        write_csv(rows, summary, csv_path)
        print(f"CSV saved to: {csv_path}")


def _prompt(text: str, default: str = "", choices: list[str] | None = None) -> str:
    while True:
        raw = input(f"  {text} [{default}]: ").strip()
        if not raw:
            return default
        if choices and raw not in choices:
            print(f"    Must be one of: {', '.join(choices)}")
            continue
        return raw


def _prompt_int(text: str, default: int | None) -> int | None:
    default_str = "(plan default)" if default is None else str(default)
    raw = _prompt(text, default=default_str)
    if raw.strip().lower() in ("", "(plan default)", "none"):
        return None
    return int(raw)


def _build_config(args: argparse.Namespace) -> SimConfig:
    return SimConfig(
        plan=args.plan or "free",
        days=args.days or 30,
        ai_daily_cap=args.ai_daily_cap,
        query_daily_cap=args.query_daily_cap,
        save_gate_rate=args.save_gate_rate if args.save_gate_rate is not None else 0.5,
        forget_rate=args.forget_rate if args.forget_rate is not None else 0.15,
        sessions=args.sessions,
        session_size=args.session_size,
        seed=args.seed,
        report_every=args.report_every or 5,
        three_button_mode=not args.no_three_buttons,
        score_enabled=not args.no_score,
        random_intervals=not args.no_random_intervals,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or sys.argv[1:])

    if not args.plan:
        _interactive_run()
        return

    cfg = _build_config(args)
    rows, summary, _ = simulate(cfg)
    print(format_table(rows, summary, cfg))
    if args.csv:
        write_csv(rows, summary, args.csv)
        print(f"CSV saved to: {args.csv}")