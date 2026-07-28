"""SRS v4 Hybrid Session Simulation — CLI entry point.

Pure Python simulation of the session-based hybrid SRS engine.
No AI, no database.

Usage:
    python -m tools.srs_simulation_v3                     (interactive)
    python -m tools.srs_simulation_v3 --plan gold --days 360 --seed 42
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
PERSONA_CHOICES = ["lazy", "average", "eager", "fluctuating"]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SRS v4 Hybrid Session Simulation — test session-based engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.srs_simulation_v3
  python -m tools.srs_simulation_v3 --plan free --days 30 --seed 42
  python -m tools.srs_simulation_v3 --plan gold --days 360 --seed 7 --csv gold_v4.csv
  python -m tools.srs_simulation_v3 --persona eager --days 720 --no-auto-archive --csv eager_720.csv
        """,
    )
    p.add_argument("--plan", choices=PLAN_CHOICES, default=None,
                    help="Plan tier: free, silver, or gold (controls default caps)")
    p.add_argument("--persona", choices=PERSONA_CHOICES, default="eager",
                    help="User behavior profile: lazy, average, eager, fluctuating")
    p.add_argument("--days", type=int, default=None,
                    help="How many days to simulate (default: 90)")
    p.add_argument("--session-size", type=int, default=None,
                    help="Cards per session (plan default)")
    p.add_argument("--sessions", type=int, default=None,
                    help="Review sessions per day (plan default)")
    p.add_argument("--ai-daily-cap", type=int, default=None,
                    help="Maximum AI cards that can be generated per day (plan default)")
    p.add_argument("--query-daily-cap", type=int, default=None,
                    help="How many word queries the user makes per day (plan default)")
    p.add_argument("--seed", type=int, default=None,
                    help="Random seed for repeatable runs")
    p.add_argument("--queue-cap-days", type=int, default=None,
                    help="Queue capacity in days of plan capacity (plan default: free=2, silver=3, gold=4)")
    p.add_argument("--no-waiting-room", action="store_true",
                    help="Disable waiting room (unlimited admission)")
    p.add_argument("--no-auto-archive", action="store_true",
                    help="Disable auto-archiving of weak/overdue cards")
    p.add_argument("--no-adaptive-quota", action="store_true",
                    help="Disable AI throttle based on queue pressure")
    p.add_argument("--csv", type=str, default=None,
                    help="Save results to CSV file")
    return p.parse_args(argv)


def _interactive_run() -> None:
    print("\n" + "=" * 60)
    print("  SRS v4 Hybrid Session Simulation — Interactive Mode")
    print("=" * 60)
    print()
    print("This simulates the session-based hybrid SRS engine.")
    print("Features: debt-based pressure, waiting room, auto-archive, adaptive AI throttle.")
    print("Press Enter to accept defaults shown in [brackets].")
    print()

    print("--- PLAN TIER ---")
    print("Free:   1 session x 4 cards  | AI cap 3  | Query cap 3  | Queue 2d")
    print("Silver: 2 sessions x 6 cards | AI cap 12 | Query cap 7  | Queue 3d")
    print("Gold:   3 sessions x 8 cards | AI cap 20 | Query cap 10 | Queue 4d")
    plan = _prompt("Plan", default="free", choices=PLAN_CHOICES)
    print()

    print("--- USER PERSONA ---")
    print("lazy        - 40% attend, low queries, high forget")
    print("average     - 72% attend, balanced")
    print("eager       - 92% attend, high queries, low forget")
    print("fluctuating - 21-day motivation cycles")
    persona = _prompt("Persona", default="eager", choices=PERSONA_CHOICES)
    print()

    print("--- DURATION ---")
    print("How many days to simulate?")
    print("  90 = 3 months, 360 = 1 year, 720 = 2 years")
    days = int(_prompt("Days", default="360"))
    print()

    print("--- SESSION SETTINGS (optional overrides) ---")
    print(f"Plan defaults: {PLAN_DEFAULTS[plan]['sessions']} sessions x {PLAN_DEFAULTS[plan]['session_size']} cards")
    sessions = _prompt_int("Sessions per day", default=None)
    session_size = _prompt_int("Cards per session", default=None)
    print()

    print("--- AI & QUERY CAPS (optional overrides) ---")
    print(f"Plan defaults: AI cap {PLAN_DEFAULTS[plan]['ai_daily_cap']}, Query cap {PLAN_DEFAULTS[plan]['query_daily_cap']}")
    ai_cap = _prompt_int("AI daily cap", default=None)
    query_cap = _prompt_int("Query daily cap", default=None)
    print()

    print("--- QUEUE & ARCHIVE SETTINGS ---")
    print(f"Plan queue cap: {PLAN_DEFAULTS[plan]['queue_cap_days']} days of capacity")
    queue_cap = _prompt_int("Queue capacity (days)", default=None)
    print(f"Plan archive: score<{PLAN_DEFAULTS[plan]['archive_threshold_score']}, overdue>{PLAN_DEFAULTS[plan]['archive_threshold_overdue']}d")
    archive_score = _prompt_float("Archive score threshold", default=None)
    archive_overdue = _prompt_int("Archive overdue days", default=None)
    print()

    print("--- FEATURE TOGGLES ---")
    wr = _prompt_yn("Waiting room", default="y")
    aa = _prompt_yn("Auto-archive weak cards", default="y")
    aq = _prompt_yn("Adaptive AI throttle", default="y")
    print()

    print("--- RANDOM SEED ---")
    print("Same seed = same results. Empty = random each run.")
    seed_raw = _prompt("Seed (number, or empty for random)", default="")
    seed = None if seed_raw.strip() == "" else int(seed_raw)
    print()

    print("--- CSV EXPORT ---")
    csv_path = _prompt("CSV file path (or empty to skip)", default="")
    csv_path = csv_path.strip().strip('"').strip("'")
    csv_path = None if csv_path == "" else csv_path
    print()

    cfg = SimConfig(
        plan=plan,
        persona=persona,
        days=days,
        session_size=session_size,
        sessions=sessions,
        ai_daily_cap=ai_cap,
        query_daily_cap=query_cap,
        seed=seed,
        queue_cap_days=queue_cap,
        archive_threshold_score=archive_score,
        archive_threshold_overdue=archive_overdue,
        enable_waiting_room=wr,
        enable_auto_archive=aa,
        enable_adaptive_quota=aq,
    )

    print()
    print("Running simulation...")
    print()
    rows, summary = simulate(cfg)
    print(format_table(rows, summary, cfg))
    if csv_path:
        write_csv(rows, csv_path)
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


def _prompt_float(text: str, default: float | None) -> float | None:
    default_str = "(plan default)" if default is None else str(default)
    raw = _prompt(text, default=default_str)
    if raw.strip().lower() in ("", "(plan default)", "none"):
        return None
    return float(raw)


def _prompt_yn(text: str, default: str = "y") -> bool:
    raw = _prompt(f"{text} (y/n)", default=default)
    return raw.strip().lower() in ("y", "yes", "true", "1")


def _build_config(args: argparse.Namespace) -> SimConfig:
    return SimConfig(
        plan=args.plan or "free",
        persona=args.persona,
        days=args.days or 90,
        session_size=args.session_size,
        sessions=args.sessions,
        ai_daily_cap=args.ai_daily_cap,
        query_daily_cap=args.query_daily_cap,
        seed=args.seed,
        queue_cap_days=args.queue_cap_days,
        enable_waiting_room=not args.no_waiting_room,
        enable_auto_archive=not args.no_auto_archive,
        enable_adaptive_quota=not args.no_adaptive_quota,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or sys.argv[1:])

    if not args.plan:
        _interactive_run()
        return

    cfg = _build_config(args)
    rows, summary = simulate(cfg)
    print(format_table(rows, summary, cfg))
    if args.csv:
        write_csv(rows, args.csv)
        print(f"CSV saved to: {args.csv}")


if __name__ == "__main__":
    main()