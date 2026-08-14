"""AI Model Benchmark Tool — CLI entry point.

Compares AI models on vocabulary card generation across non-batched and batched modes,
with cost analysis, retry handling, and repeatable configuration.

Usage:
    python -m tools.benchmark --presets preset1 preset2
    python -m tools.benchmark  (interactive fallback)
    python -m tools.benchmark --help
"""

import argparse
import logging
import sys
import time

from services import db
from tools.benchmark.runner import (
    run_preset_benchmark,
    delete_benchmark_data,
    DEFAULT_WORDS,
    DEFAULT_LANG,
    DEFAULT_GOAL,
    DEFAULT_LEVEL,
)
from tools.benchmark.report import generate_benchmark_report, generate_report_path

log = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _interactive_select_presets() -> list[dict]:
    """Show all enabled DB presets and let the user select by number/name."""
    presets = db.get_enabled_presets_ordered()
    if not presets:
        presets = db.get_presets()
    if not presets:
        print("هیچ پریستی در دیتابیس یافت نشد.", file=sys.stderr)
        sys.exit(1)

    print("\nپریست‌های موجود:")
    print("-" * 70)
    for i, p in enumerate(presets, 1):
        name = p.get("name", "?")
        model = p.get("default_model", p.get("model", "?"))
        enabled = "فعال" if p.get("enabled", 0) else "غیرفعال"
        print(f"  {i:2d}. {name:<35s} ({model}) [{enabled}]")
    print("-" * 70)
    print("  a. همه پریست‌های فعال")
    print("  q. انصراف")
    print()

    while True:
        choice = input("شماره پریست‌ها (مثلاً 1,3,5) یا a یا q: ").strip().lower()
        if choice == "q":
            print("انصراف.")
            sys.exit(0)
        if choice == "a":
            return [p for p in presets if p.get("enabled", 0)]

        try:
            indices = [int(x.strip()) for x in choice.split(",") if x.strip()]
            selected = []
            for idx in indices:
                if 1 <= idx <= len(presets):
                    selected.append(presets[idx - 1])
                else:
                    print(f"شماره {idx} خارج از محدوده است.")
                    break
            else:
                if selected:
                    return selected
        except (ValueError, IndexError):
            pass

        print("ورودی نامعتبر. دوباره تلاش کن.")


def _confirm_overwrite(preset_name: str, model: str) -> bool:
    """Ask user if existing benchmark data for this preset should be overwritten."""
    filters = {
        "request_kind": "benchmark",
        "model": model,
        "user_id": 0,
        "plan": "benchmark",
    }
    summary = db.summarize_llm_requests(filters)
    count = summary.get("request_count", 0) or 0
    if count == 0:
        return True

    print(f"\n⚠️  {count} رکورد بنچمارک قبلی برای {preset_name} ({model}) یافت شد.")
    while True:
        choice = input("  پاک کردن و دوباره اجرا کنم؟ (y/n): ").strip().lower()
        if choice in ("y", "yes"):
            deleted = delete_benchmark_data(model=model)
            print(f"  {deleted} رکورد پاک شد.")
            return True
        if choice in ("n", "no"):
            print(f"  ❌ پریست {preset_name} رد شد.")
            return False
        print("  لطفاً y یا n وارد کن.")


def main() -> None:
    """Main CLI entry point for the benchmark tool."""
    parser = argparse.ArgumentParser(
        description="AI Model Benchmark — مقایسه مدل‌های AI برای تولید کارت واژه",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.benchmark --presets google_36_flash_eliapi
  python -m tools.benchmark --presets google_36_flash_eliapi google_flash_lite_latest_eliapi
  python -m tools.benchmark --words run,book,cozy --mode both
  python -m tools.benchmark --mode single --no-compact
        """,
    )
    parser.add_argument(
        "--presets", nargs="+", default=None,
        help="نام پریست‌ها برای بنچمارک (اگر داده نشه، لیست تعاملی نمایش داده می‌شه)",
    )
    parser.add_argument(
        "--words", type=lambda s: [w.strip() for w in s.split(",")],
        default=None,
        help="فهرست واژه‌ها با کاما جدا شده (پیش‌فرض: ۱۲ واژه built-in)",
    )
    parser.add_argument(
        "--mode", choices=["both", "single", "batch"], default="both",
        help="حالت اجرا: both (پیش‌فرض)، single (non-batched)، batch (batched)",
    )
    parser.add_argument(
        "--compact", action="store_true", default=True,
        help="استفاده از فرمت compact JSON (پیش‌فرض)",
    )
    parser.add_argument(
        "--no-compact", action="store_false", dest="compact",
        help="استفاده از فرمت full JSON",
    )
    parser.add_argument(
        "--lang", default=DEFAULT_LANG,
        help="کد زبان (پیش‌فرض: en)",
    )
    parser.add_argument(
        "--goal", default=DEFAULT_GOAL,
        help="کد هدف (پیش‌فرض: general)",
    )
    parser.add_argument(
        "--level", default=DEFAULT_LEVEL,
        help="کد سطح (پیش‌فرض: intermediate)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="خروجی debug",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="مسیر فایل خروجی گزارش (پیش‌فرض: docs/reports/...)",
    )

    args = parser.parse_args()
    _setup_logging(args.verbose)

    words = args.words or DEFAULT_WORDS

    # ── Resolve presets ──
    if args.presets:
        presets = []
        for name in args.presets:
            p = db.get_preset(name)
            if not p:
                print(f"⚠️  پریست '{name}' یافت نشد. رد شد.", file=sys.stderr)
                continue
            presets.append(p)
        if not presets:
            print("هیچ پریست معتبری انتخاب نشد.", file=sys.stderr)
            sys.exit(1)
    else:
        presets = _interactive_select_presets()

    # ── Confirm selection ──
    print(f"\n✅ {len(presets)} پریست انتخاب شد:")
    for p in presets:
        name = p.get("name", "?")
        model = p.get("default_model", p.get("model", "?"))
        print(f"   • {name} → {model}")
    print(f"   حالت: {args.mode}")
    print(f"   فرمت: {'compact' if args.compact else 'full'}")
    print(f"   واژه‌ها ({len(words)}): {', '.join(words[:5])}{'...' if len(words) > 5 else ''}")
    print()

    # ── Run benchmark ──
    all_results: list[dict] = []
    overall_start = time.time()

    for preset in presets:
        name = preset.get("name", "?")
        model = preset.get("default_model", preset.get("model", "?"))

        # Overwrite check
        if not _confirm_overwrite(name, model):
            continue

        print(f"\n{'='*60}")
        print(f"  اجرای بنچمارک برای: {name} ({model})")
        print(f"{'='*60}")

        try:
            result = run_preset_benchmark(
                preset=preset,
                words=words,
                mode=args.mode,
                compact=args.compact,
                lang=args.lang,
                goal=args.goal,
                level=args.level,
            )
            all_results.append(result)

            mr = result["modes"]
            for mode_name, mr_data in mr.items():
                print(f"  {mode_name}: {mr_data.success_count}/{mr_data.total_words} موفق"
                      f" ({mr_data.fail_count} خطا), "
                      f"{mr_data.total_api_calls} تماس")

        except Exception as exc:
            log.exception("Benchmark failed for preset %s: %s", name, exc)
            print(f"  ❌ خطا در بنچمارک {name}: {exc}", file=sys.stderr)

    if not all_results:
        print("\nهیچ بنچمارکی اجرا نشد.")
        sys.exit(1)

    elapsed = time.time() - overall_start

    # ── Generate report ──
    print(f"\n{'='*60}")
    print(f"  تولید گزارش...")
    print(f"{'='*60}")

    if args.output:
        output_paths = [args.output]
    else:
        output_paths = [
            generate_report_path(
                f"combined_{r['preset_name']}",
                args.mode,
            )
            for r in all_results
        ]

    for i, r in enumerate(all_results):
        path = output_paths[i] if i < len(output_paths) else output_paths[-1]
        report = generate_benchmark_report(
            results=[r],
            words=words,
            output_path=path,
        )

    # Also print to stdout
    print("\n" + "=" * 60)
    print("  گزارش خلاصه")
    print("=" * 60)
    summary_report = generate_benchmark_report(
        results=all_results,
        words=words,
        output_path=None,
    )
    # Print a more compact summary to stdout
    print(f"\nزمان کل: {elapsed:.1f} ثانیه")
    print(f"تعداد پریست‌ها: {len(all_results)}")
    print(f"تعداد واژه‌ها: {len(words)}")
    print(f"حالت: {args.mode}")
    print(f"گزارش ذخیره شد در: {', '.join(str(p) for p in output_paths)}")
    print()


if __name__ == "__main__":
    main()
