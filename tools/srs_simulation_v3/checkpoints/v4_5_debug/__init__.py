"""SRS v4.5 Hybrid Session Simulation — CLI entry point.

v3 Golden core + 4 organic v4 enhancements.
Pure Python, offline math model. No AI, no database.
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
PERSONA_CHOICES = ["lazy", "average", "eager", "fluctuating"]

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SRS v4.5 Hybrid Simulation — v3 Golden + v4 Organic Lessons",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.srs_simulation_v3
  python -m tools.srs_simulation_v3 --plan free --days 30 --seed 42
  python -m tools.srs_simulation_v3 --plan gold --days 720 --seed 42 --csv gold.csv
        """,
    )
    p.add_argument("--plan", choices=PLAN_CHOICES, default=None,
                    help="Plan tier: free, silver, or gold")
    p.add_argument("--persona", choices=PERSONA_CHOICES, default="eager",
                    help="User behavior profile")
    p.add_argument("--days", type=int, default=None,
                    help="Days to simulate (default: 360)")
    p.add_argument("--seed", type=int, default=None,
                    help="Random seed (default: 42)")
    p.add_argument("--csv", type=str, default=None,
                    help="Save results to CSV")
    return p.parse_args(argv or sys.argv[1:])

def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or sys.argv[1:])

    plan = args.plan or "gold"
    days = args.days or 360
    seed = args.seed if args.seed is not None else 42

    cfg = SimConfig(plan=plan, persona=args.persona, days=days, seed=seed)
    daily_log, summary = simulate(cfg)
    print(format_table(daily_log, summary, cfg))
    if args.csv:
        write_csv(daily_log, args.csv)
        print(f"\nCSV saved to: {args.csv}")

if __name__ == "__main__":
    main()