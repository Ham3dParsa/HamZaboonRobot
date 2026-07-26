"""SRS v2.8 Session Simulation Tool — CLI entry point.

Pure Python simulation of the SRS review engine. No AI, no database.

Usage:
    python -m tools.srs_simulation                     (interactive mode)
    python -m tools.srs_simulation --plan free --days 30 --seed 42
    python -m tools.srs_simulation --help
"""

import argparse
import sys

from tools.srs_simulation.simulator import (
    SimConfig,
    Summary,
    simulate,
    format_table,
    write_csv,
)

PLAN_CHOICES = ["free", "silver", "gold"]


def _int_or_none(val: str):
    if val is None or val.strip().lower() in ("", "none", "off"):
        return None
    return int(val)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SRS v2.8 simulation — test session-based review scenarios",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.srs_simulation
  python -m tools.srs_simulation --plan free --days 30 --seed 42
  python -m tools.srs_simulation --plan gold --days 90 --seed 7 --overflow-session-threshold 40
  python -m tools.srs_simulation --plan silver --daily-cards 5 --session-cap 3 --csv results.csv
        """,
    )
    p.add_argument("--plan", choices=PLAN_CHOICES, default=None,
                    help="Plan tier (default: interactive)")
    p.add_argument("--days", type=int, default=None,
                    help="Number of days to simulate (default: 30)")
    p.add_argument("--daily-cards", type=_int_or_none, default=None,
                    help="New cards per day (default: plan default)")
    p.add_argument("--word-query-cap", type=_int_or_none, default=None,
                    help="Word queries per day (default: plan default)")
    p.add_argument("--word-query-save-prob", type=float, default=None,
                    help="Probability query becomes saved word (default: 0.5)")
    p.add_argument("--session-cap", type=_int_or_none, default=None,
                    help="Sessions per day (default: plan default)")
    p.add_argument("--session-size", type=int, default=None,
                    help="Cards per session (default: 5)")
    p.add_argument("--backlog-ceiling", type=int, default=None,
                    help="Max pre-graduation backlog (default: 50)")
    p.add_argument("--fail-review-prob", type=float, default=None,
                    help="Probability user fails a card (default: 0.15)")
    p.add_argument("--overflow-session-threshold", type=_int_or_none, default=None,
                    help="If backlog exceeds this, trigger overflow session")
    p.add_argument("--seed", type=_int_or_none, default=None,
                    help="Random seed (for reproducible runs)")
    p.add_argument("--report-every", type=int, default=None,
                    help="Print report every N days (default: 5, 0=final only)")
    p.add_argument("--csv", type=str, default=None,
                    help="Export results to CSV file")
    return p.parse_args(argv)


def _interactive_run() -> None:
    print("\n" + "=" * 60)
    print("  SRS v2.8 Simulation Tool — Interactive Mode")
    print("=" * 60)
    print("  Press Enter to accept defaults shown in [brackets].")
    print()

    plan = _prompt("Plan (free/silver/gold)", default="free", choices=PLAN_CHOICES)
    days = int(_prompt("Days", default="30"))
    daily_cards = _prompt_int("New cards per day", default=None)
    word_query_cap = _prompt_int("Word queries per day", default=None)
    word_query_save_prob = float(_prompt("Save probability (0-1)", default="0.5"))
    session_cap = _prompt_int("Sessions per day", default=None)
    session_size = int(_prompt("Cards per session", default="5"))
    backlog_ceiling = int(_prompt("Backlog ceiling", default="50"))
    fail_review_prob = float(_prompt("Fail review probability (0-1)", default="0.15"))
    overflow_raw = _prompt("Overflow threshold (or None)", default="None")
    overflow = None if overflow_raw.strip().lower() in ("none", "") else int(overflow_raw)
    seed_raw = _prompt("Random seed (or None)", default="None")
    seed = None if seed_raw.strip().lower() in ("none", "") else int(seed_raw)
    report_every = int(_prompt("Report every N days", default="5"))
    csv_path = _prompt("CSV output path (or None)", default="None")
    csv_path = None if csv_path.strip().lower() in ("none", "") else csv_path

    cfg = SimConfig(
        plan=plan, days=days,
        daily_cards=daily_cards, word_query_cap=word_query_cap,
        word_query_save_prob=word_query_save_prob,
        session_cap=session_cap, session_size=session_size,
        backlog_ceiling=backlog_ceiling,
        fail_review_prob=fail_review_prob,
        overflow_session_threshold=overflow,
        seed=seed, report_every=report_every,
    )
    rows, summary, _ = simulate(cfg)
    print()
    print(format_table(rows, summary, cfg))
    if csv_path:
        write_csv(rows, summary, csv_path)
        print(f"CSV written to: {csv_path}")


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
    raw = _prompt(text, default="(plan default)" if default is None else str(default))
    if raw.strip().lower() in ("", "(plan default)", "none"):
        return None
    return int(raw)


def _build_config(args: argparse.Namespace) -> SimConfig:
    plan_defaults = {"free": 0, "silver": 1, "gold": 2}
    return SimConfig(
        plan=args.plan or "free",
        days=args.days or 30,
        daily_cards=args.daily_cards,
        word_query_cap=args.word_query_cap,
        word_query_save_prob=args.word_query_save_prob or 0.5,
        session_cap=args.session_cap,
        session_size=args.session_size or 5,
        backlog_ceiling=args.backlog_ceiling or 50,
        fail_review_prob=args.fail_review_prob or 0.15,
        overflow_session_threshold=args.overflow_session_threshold,
        seed=args.seed,
        report_every=args.report_every or 5,
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
        print(f"CSV written to: {args.csv}")
