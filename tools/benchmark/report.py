"""Markdown report generator for benchmark results.

Produces a structured comparison report with cost breakdown, token usage,
latency analysis, and full card output.
"""

import json
import logging
import os
from datetime import datetime

from tools.benchmark.runner import (
    ModeResult, WordResult, WordAttempt, recalculate_cost,
    get_model_cost, USD_TO_IRR,
)

log = logging.getLogger(__name__)


_REPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs", "reports",
)


def _esc(text: str | None) -> str:
    """Escape text for Markdown display (replace special chars)."""
    if text is None:
        return ""
    return str(text).replace("|", "\\|").replace("*", "\\*").replace("_", "\\_")


def _yes_no(val: bool) -> str:
    return "✅" if val else "❌"


def _model_label(model: str, compact: bool) -> str:
    return f"{model} ({'compact' if compact else 'full'})"


def _word_link(word: str) -> str:
    return f"`{_esc(word)}`"


def _cost_line(cost: dict) -> str:
    return f"${cost['cost_usd']:.6f} ({cost['cost_irr']:,} IRR)"


def _summary_table_row(
    preset_name: str,
    model: str,
    mode: str,
    compact: bool,
    mr: ModeResult,
    cost: dict,
) -> str:
    label = f"{preset_name} / {mode}"
    status = f"{mr.success_count}/{mr.total_words}"
    calls = str(mr.total_api_calls)
    avg_lat = f"{mr.batch_latency_ms:.0f}" if mode == "batch" and mr.batch_latency_ms else (
        f"{sum(w.total_latency_ms / max(w.total_attempts, 1) for w in mr.word_results) / max(mr.total_words, 1):.0f}"
    )
    cost_str = _cost_line(cost)
    return (
        f"| {_esc(label)} | {status} | {calls} | {avg_lat} ms | {cost_str} |"
    )


def _attempts_detail(word_result: WordResult) -> str:
    """Generate a detailed string about retry attempts for a word."""
    if word_result.first_attempt_success:
        return "✅ یک‌بار"
    parts = []
    for att in word_result.attempts:
        if att.success:
            parts.append(f"تلاش {att.attempt_number}: ✅ ({att.latency_ms:.0f}ms)")
        else:
            cls = att.error_class or "?"
            parts.append(f"تلاش {att.attempt_number}: ❌ {cls} ({att.latency_ms:.0f}ms)")
    return " → ".join(parts)


def generate_benchmark_report(
    results: list[dict],
    words: list[str],
    output_path: str | None = None,
) -> str:
    """Generate a full Markdown benchmark report.

    Args:
        results: List of result dicts from runner.run_preset_benchmark().
        words: The word list used in the benchmark.
        output_path: If provided, save report to this path.

    Returns the report as a string.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    _w = lines.append

    _w("# گزارش بنچمارک مدل‌های AI")
    _w("")
    _w(f"**تولید شده:** {now_str}")
    _w(f"**واژه‌ها:** {', '.join(_esc(w) for w in words)}")
    _w(f"**تعداد:** {len(words)} واژه")
    _w("")

    # ── 1. Summary table ──
    _w("## ۱. خلاصه مقایسه")
    _w("")
    _w("| پریست / حالت | موفق/کل | تماس‌ها | میانه latency | مجموع هزینه (USD / IRR) |")
    _w("|---|---|---|---|---|")
    for r in results:
        preset_name = r["preset_name"]
        model = r["model"]
        for mode_name, mr in r["modes"].items():
            cost = recalculate_cost(
                prompt_tokens=sum(
                    w.total_attempts * 500 for w in mr.word_results
                ),
                completion_tokens=sum(
                    w.total_attempts * 250 for w in mr.word_results
                ),
                model=model,
            )
            _w(_summary_table_row(preset_name, model, mode_name, mr.compact, mr, cost))

    _w("")
    _w(f"نرخ دلار: ۱ USD = {USD_TO_IRR:,} IRR")
    _w("")

    # ── 2. Per-preset breakdown ──
    _w("## ۲. جزئیات هر پریست")
    _w("")

    for r_idx, r in enumerate(results, 1):
        preset_name = r["preset_name"]
        model = r["model"]
        _w(f"### {r_idx}. {_esc(preset_name)} ({_esc(model)})")
        _w("")

        for mode_name, mr in r["modes"].items():
            _w(f"**حالت:** {mode_name}")
            _w("")

            telemetry = r["telemetry"]
            pt = telemetry.get("prompt_tokens", 0) or 0
            ct = telemetry.get("completion_tokens", 0) or 0
            tt = telemetry.get("total_tokens", 0) or 0
            avg_lat = telemetry.get("avg_latency_ms") or 0
            cost = r["cost"]

            rates = get_model_cost(model)
            _w(f"| معیار | مقدار |")
            _w("|---|---|")
            _w(f"| موفق/کل واژه | {mr.success_count}/{mr.total_words} |")
            _w(f"| مجموع تماس‌های API | {mr.total_api_calls} |")
            _w(f"| مجموع توکن‌های ورودی | {pt:,} |")
            _w(f"| مجموع توکن‌های خروجی | {ct:,} |")
            _w(f"| مجموع کل توکن‌ها | {tt:,} |")
            _w(f"| میانگین latency | {avg_lat:.0f} ms |")
            if mode_name == "batch" and mr.batch_latency_ms:
                _w(f"| Latency کل batch | {mr.batch_latency_ms:.0f} ms |")
            _w(f"| نرخ ورودی (USD/M) | ${rates['in']} |")
            _w(f"| نرخ خروجی (USD/M) | ${rates['out']} |")
            _w(f"| مجموع هزینه (USD) | ${cost['cost_usd']:.6f} |")
            _w(f"| مجموع هزینه (IRR) | {cost['cost_irr']:,} ریال |")
            _w("")

            # ── Word-level results ──
            _w("#### نتایج هر واژه")
            _w("")
            _w("| واژه | وضعیت | تلاش‌ها | latency کل |")
            _w("|---|---|---|---|")
            for wr in mr.word_results:
                icon = _yes_no(wr.success)
                lat_sum = f"{wr.total_latency_ms:.0f} ms" if wr.total_latency_ms > 0 else "—"
                _w(f"| {_word_link(wr.word)} | {icon} | {_attempts_detail(wr)} | {lat_sum} |")
            _w("")

        # ── Cost comparison per mode ──
        if len(r["modes"]) > 1:
            _w("#### مقایسه هزینه بین حالت‌ها")
            _w("")
            _w("| حالت | تماس‌ها | توکن کل | هزینه (USD) | هزینه (IRR) |")
            _w("|---|---|---|---|---|")
            for mode_name, mr in r["modes"].items():
                calls = mr.total_api_calls
                tokens_est = sum(
                    w.total_attempts * 750 for w in mr.word_results
                )
                mode_telemetry = r.get("telemetry", {})
                mode_cost = recalculate_cost(
                    prompt_tokens=mode_telemetry.get("prompt_tokens", 0) or 0,
                    completion_tokens=mode_telemetry.get("completion_tokens", 0) or 0,
                    model=model,
                )
                _w(f"| {mode_name} | {calls} | {tokens_est:,} | ${mode_cost['cost_usd']:.6f} | {mode_cost['cost_irr']:,} ریال |")
            _w("")

    # ── 3. Error analysis ──
    _w("## ۳. تحلیل خطاها")
    _w("")
    errors_found = False
    for r in results:
        for mode_name, mr in r["modes"].items():
            failed = [wr for wr in mr.word_results if not wr.success]
            if not failed:
                continue
            errors_found = True
            _w(f"### {_esc(r['preset_name'])} / {mode_name}")
            _w("")
            _w("| واژه | خطا | آخرین تلاش (ms) |")
            _w("|---|---|---|")
            for wr in failed:
                last_att = wr.attempts[-1] if wr.attempts else None
                err_msg = _esc(last_att.error_message if last_att else "?")
                lat = f"{last_att.latency_ms:.0f}" if last_att else "—"
                _w(f"| {_word_link(wr.word)} | {err_msg[:120]} | {lat} |")
            _w("")

    if not errors_found:
        _w("هیچ خطایی رخ نداده است.")
        _w("")

    # ── 4. Qualitative comparison ──
    _w("## ۴. تحلیل کیفی")
    _w("")
    _w("| جنبه | توضیح |")
    _w("|---|---|")
    _w("| **کیفیت فارسی** | با بررسی خروجی‌های JSON می‌توان کیفیت معادل‌های فارسی را مقایسه کرد |")
    _w("| **grammar_tip** | آیا نکات گرامری دقیق و آموزشی هستند؟ |")
    _w("| **مثال‌ها** | آیا مثال‌ها طبیعی و در سطح مناسب هستند؟ |")
    _w("| **IPA** | آیا آوانگاری دقیق است؟ |")
    _w("")

    # ── 5. Full card output ──
    _w("## ۵. پیوست: خروجی خام کارت‌ها")
    _w("")

    for r in results:
        preset_name = r["preset_name"]
        model = r["model"]
        _w(f"### {_esc(preset_name)} ({_esc(model)})")
        _w("")

        for mode_name, mr in r["modes"].items():
            _w(f"**حالت: {mode_name}**")
            _w("")

            for wr in mr.word_results:
                _w(f"#### {_esc(wr.word)}")
                _w("")
                if wr.success and wr.final_card:
                    _w("```json")
                    _w(json.dumps(wr.final_card, indent=2, ensure_ascii=False))
                    _w("```")
                else:
                    last_att = wr.attempts[-1] if wr.attempts else None
                    err = _esc(last_att.error_message if last_att else "نامشخص")
                    _w(f"> **خطا:** {err}")
                _w("")

    report = "\n".join(lines)

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        log.info("Report saved to %s", output_path)

    return report


def generate_report_path(preset_name: str, mode: str) -> str:
    """Generate a file path for a benchmark report."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_name = preset_name.replace(" ", "_").replace("/", "_")
    os.makedirs(_REPORT_DIR, exist_ok=True)
    return os.path.join(_REPORT_DIR, f"benchmark_{safe_name}_{mode}_{date_str}.md")
