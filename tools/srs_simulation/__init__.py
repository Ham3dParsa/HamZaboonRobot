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
    PLAN_DEFAULTS,
    SimConfig,
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
                    help="User plan: free, silver, or gold (controls daily quotas)")
    p.add_argument("--days", type=int, default=None,
                    help="How many days to simulate (default: 30)")
    p.add_argument("--daily-cards", type=_int_or_none, default=None,
                    help="How many new vocabulary cards the system generates per day (plan default)")
    p.add_argument("--word-query-cap", type=_int_or_none, default=None,
                    help="How many 'Ask a Word' queries the user can do per day (plan default)")
    p.add_argument("--word-query-save-prob", type=float, default=None,
                    help="Chance (0.0-1.0) that a word query gets saved for later review (default: 0.5)")
    p.add_argument("--session-cap", type=_int_or_none, default=None,
                    help="How many review sessions per day (plan default)")
    p.add_argument("--session-size", type=int, default=None,
                    help="How many cards per review session (default: 5)")
    p.add_argument("--backlog-ceiling", type=int, default=None,
                    help="Maximum cards waiting for first review (default: 50)")
    p.add_argument("--fail-review-prob", type=float, default=None,
                    help="Chance (0.0-1.0) that user clicks 'Again' instead of 'Remembered' (default: 0.15)")
    p.add_argument("--overflow-session-threshold", type=_int_or_none, default=None,
                    help="If backlog exceeds this number, an extra overflow session runs (default: disabled)")
    p.add_argument("--seed", type=_int_or_none, default=None,
                    help="Random seed for repeatable results (default: random)")
    p.add_argument("--report-every", type=int, default=None,
                    help="Print progress every N days (default: 5, 0=final summary only)")
    p.add_argument("--csv", type=str, default=None,
                    help="Save results as CSV file")
    return p.parse_args(argv)


def _interactive_run() -> None:
    print("\n" + "=" * 60)
    print("  SRS Review Engine Simulation — Interactive Mode")
    print("=" * 60)
    print()
    print("This tool simulates how the SRS (Spaced Repetition System) behaves")
    print("over many days. It helps you understand whether the current plan limits")
    print("are balanced before locking them in the product.")
    print()
    print("Press Enter to accept the default shown in [brackets].")
    print()

    # ── Plan ──
    print("--- PLAN TIER ---")
    print("Free:    3 new cards/day,  3 queries/day,  1 session/day (5 cards)")
    print("Silver:  8 new cards/day, 10 queries/day,  4 sessions/day (20 cards)")
    print("Gold:   12 new cards/day, 14 queries/day, 10 sessions/day (50 cards)")
    plan = _prompt("Plan", default="free", choices=PLAN_CHOICES)
    print()

    # ── Duration ──
    print("--- HOW LONG ---")
    print("How many days should the simulation run?")
    print("  - 30 days = 1 month of usage")
    print("  - 60-90 days shows long-term trends")
    days = int(_prompt("Simulation days", default="30"))
    print()

    # ── New cards per day ──
    print("--- NEW CARDS PER DAY ---")
    print("How many new vocabulary cards does the system generate each day?")
    print("This is your daily AI generation budget for fresh content.")
    print("  - Higher = more learning material but more backlog pressure")
    print(f"  - Plan default: {PLAN_DEFAULTS[plan]['daily_cards']}")
    daily_cards = _prompt_int("New cards per day", default=None)
    print()

    # ── Word queries ──
    print("--- WORD QUERIES PER DAY ---")
    print("How many 'Ask a Word' queries can the user do each day?")
    print("Each query has a chance to add the word to the review queue.")
    print(f"  - Plan default: {PLAN_DEFAULTS[plan]['word_query_cap']}")
    word_query_cap = _prompt_int("Word queries per day", default=None)
    print()

    # ── Save probability ──
    print("--- QUERY SAVE RATE ---")
    print("When a user looks up a word, how often do they save it for review?")
    print("  - 0.5 = 50% of queries become review cards")
    print("  - Higher values fill the backlog faster")
    word_query_save_prob = float(_prompt("Save probability (0.0 to 1.0)", default="0.5"))
    print()

    # ── Session cap ──
    print("--- REVIEW SESSIONS PER DAY ---")
    print("How many review sessions can the user start per day?")
    print("Each session shows a batch of cards for spaced repetition.")
    print("  - More sessions = more reviews, faster backlog clearing")
    print(f"  - Plan default: {PLAN_DEFAULTS[plan]['session_cap']}")
    session_cap = _prompt_int("Sessions per day", default=None)
    print()

    # ── Session size ──
    print("--- CARDS PER SESSION ---")
    print("How many cards does one session contain?")
    print("  - 5 = standard, matches the current product design")
    print("  - Higher = more reviews per session but may feel heavy")
    session_size = int(_prompt("Cards per session", default="5"))
    print()

    # ── Backlog ceiling ──
    print("--- BACKLOG LIMIT ---")
    print("Maximum number of cards waiting for their FIRST review.")
    print("When this fills up, new cards are rejected with a warning.")
    print("  - 50 = current product setting")
    print("  - Higher = less rejection but more pressure on review sessions")
    backlog_ceiling = int(_prompt("Backlog ceiling", default="50"))
    print()

    # ── Fail probability ──
    print("--- FAIL RATE ---")
    print("How often does the user click 'Again' (forgot) vs 'Remembered'?")
    print("  - 0.15 = 15% fail rate (typical)")
    print("  - 0.3-0.5 = struggling user, more resets to early intervals")
    fail_review_prob = float(_prompt("Fail probability (0.0 to 1.0)", default="0.15"))
    print()

    # ── Overflow ──
    print("--- OVERFLOW RELIEF ---")
    print("If the backlog grows beyond a threshold, an EXTRA session runs")
    print("using only backlog cards. This is a safety valve.")
    print("  - Leave empty = disabled (no extra sessions)")
    print("  - Set a number (e.g. 40) = trigger when backlog > 40")
    overflow_raw = _prompt("Overflow threshold (number, or empty for disabled)", default="")
    overflow = None if overflow_raw.strip() == "" else int(overflow_raw)
    print()

    # ── Seed ──
    print("--- RANDOM SEED ---")
    print("A seed makes the simulation repeatable (same seed = same results).")
    print("  - Leave empty = random each time")
    print("  - Pick a number (e.g. 42) to compare different plans fairly")
    seed_raw = _prompt("Random seed (number, or empty for random)", default="")
    seed = None if seed_raw.strip() == "" else int(seed_raw)
    print()

    # ── Report frequency ──
    print("--- REPORT FREQUENCY ---")
    print("How often should we print the progress table?")
    print("  - 1 = every day (detailed)")
    print("  - 5 = every 5 days (balanced)")
    print("  - 0 = only show the final summary")
    report_every = int(_prompt("Report every N days", default="5"))
    print()

    # ── CSV ──
    print("--- CSV EXPORT ---")
    print("Save the results to a CSV file for Excel/Google Sheets analysis.")
    csv_path = _prompt("CSV file path (or empty to skip)", default="")
    csv_path = csv_path.strip().strip('"').strip("'")
    csv_path = None if csv_path == "" else csv_path

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
        print(f"CSV saved to: {args.csv}")
