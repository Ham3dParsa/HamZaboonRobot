"""SRS v4.6+ Session Simulation — CLI entry point.

V3 Golden core + all bugfixes + continuous mastery + override.
Pure Python, offline math model. No AI, no database.
"""

import argparse
import sys

# Support both -m package run and direct script import
try:
    from srs_simulation_v3.simulator_v3 import (
        PLAN_DEFAULTS, SimConfig, simulate, format_table, write_csv,
    )
except ModuleNotFoundError:
    from .simulator_v3 import (
        PLAN_DEFAULTS, SimConfig, simulate, format_table, write_csv,
    )

PLAN_CHOICES = ["free", "silver", "gold"]
PERSONA_CHOICES = ["lazy", "average", "eager", "fluctuating"]
PROFICIENCY_CHOICES = ["beginner", "intermediate", "advanced"]

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SRS v4.6+ Bugfix — all features optional, session override supported",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.srs_simulation_v3
  python -m tools.srs_simulation_v3 --plan free --days 30 --seed 42
  python -m tools.srs_simulation_v3 --no-rejection --no-catchup --no-mastery
  python -m tools.srs_simulation_v3 --sessions-override 1.2 --session-size-override 0.85
        """,
    )
    p.add_argument("--plan", choices=PLAN_CHOICES, default=None,
                    help="Plan tier: free, silver, or gold")
    p.add_argument("--persona", choices=PERSONA_CHOICES, default="eager",
                    help="User behavior profile")
    p.add_argument("--proficiency", choices=PROFICIENCY_CHOICES, default="advanced",
                    help="User language proficiency level")
    p.add_argument("--days", type=int, default=None,
                    help="Days to simulate (default: 360)")
    p.add_argument("--seed", type=int, default=None,
                    help="Random seed (default: 42)")
    p.add_argument("--no-rejection", action="store_true",
                    help="Disable proficiency-based AI card rejection")
    p.add_argument("--no-catchup", action="store_true",
                    help="Disable catch-up bonus sessions")
    p.add_argument("--no-mastery", action="store_true",
                    help="Disable continuous mastery model (use legacy binary)")
    p.add_argument("--sessions-override", type=float, default=None,
                    help="Session count % override (0.7–1.3)")
    p.add_argument("--session-size-override", type=float, default=None,
                    help="Session size % override (0.7–1.3)")
    p.add_argument("--csv", type=str, default=None,
                    help="Save results to CSV")
    return p.parse_args(argv or sys.argv[1:])

def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or sys.argv[1:])

    plan = args.plan or "gold"
    days = args.days or 360
    seed = args.seed if args.seed is not None else 42

    cfg = SimConfig(
        plan=plan, persona=args.persona, proficiency=args.proficiency,
        days=days, seed=seed,
        enable_rejection=not args.no_rejection,
        enable_catchup=not args.no_catchup,
        enable_continuous_mastery=not args.no_mastery,
        sessions_override=args.sessions_override,
        session_size_override=args.session_size_override,
    )
    daily_log, summary = simulate(cfg)
    print(format_table(daily_log, summary, cfg))
    if args.csv:
        write_csv(daily_log, args.csv)
        print(f"\nCSV saved to: {args.csv}")

if __name__ == "__main__":
    main()