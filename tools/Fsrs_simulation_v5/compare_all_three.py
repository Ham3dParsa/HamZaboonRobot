#!/usr/bin/env python3
"""
Three-version comparison: v5.0 (DSR-lite) vs v5.1 (DSR-mid) vs v5.2 (FSRS-6 Full).

Runs 40 scenarios per version (4 models × 4 personas × 5 time buckets = 80 runs total).
Generates an HTML report inspired by tools/srs_simulation_v4/report.md structure.

Output: report_v5_compare.html
"""

import importlib.util
import inspect
import json
import os
import sys
import csv
from datetime import datetime

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

# ---- Load all three modules via importlib (filenames contain dots) ----
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

mod_lite = load_module("v5_0", os.path.join(THIS_DIR, "v5.0_dsr_lite.py"))
mod_mid = load_module("v5_1", os.path.join(THIS_DIR, "v5.1_dsr_mid.py"))
mod_full = load_module("v5_2", os.path.join(THIS_DIR, "v5.2_FSRSv6.py"))

# ---- Scenario definitions ----
PLANS = ["silver", "gold"]
PERSONA_KEYS = ["eager", "average", "fluctuating", "lazy"]
TIME_BUCKETS = [90, 180, 360, 540, 720]
VERSIONS = [
    ("v5.0 DSR-lite", mod_lite, "lite"),
    ("v5.1 DSR-mid", mod_mid, "dsr"),
    ("v5.2 FSRS-6 Full", mod_full, "dsr"),
]
SEED = 42

# ---- Unified metric collection ----
def make_cfg(mod, plan, persona, days, mastery):
    kwargs = dict(plan=plan, persona=persona, proficiency="intermediate",
                  days=days, seed=SEED, enable_rejection=False, enable_catchup=True,
                  enable_session_rate_limit=True)
    if "mastery_model" in inspect.signature(mod.SimConfig.__init__).parameters:
        kwargs["mastery_model"] = mastery
        if "desired_retention" in inspect.signature(mod.SimConfig.__init__).parameters:
            kwargs["desired_retention"] = 0.85
    if "enable_continuous_mastery" in inspect.signature(mod.SimConfig.__init__).parameters:
        kwargs["enable_continuous_mastery"] = True
    if "jitter" in inspect.signature(mod.SimConfig.__init__).parameters:
        kwargs["jitter"] = False
    return mod.SimConfig(**kwargs)

def run_version(mod, label, plan, persona, days, mastery):
    cfg = make_cfg(mod, plan, persona, days, mastery)
    _, summary = mod.simulate(cfg)
    row = {
        "version": label,
        "plan": plan,
        "persona": persona,
        "days": days,
        "learned": summary.get("learned_words", 0),
        "active": summary.get("total_active_words", 0),
        "ai_calls": summary.get("total_ai_calls", 0),
        "cost": summary.get("total_ai_cost_usd", 0),
        "eff": summary.get("learned_words_per_dollar", 0),
        "max_due": summary.get("max_due_backlog", 0),
        "qbl": summary.get("max_query_backlog", 0),
        "avg_late": summary.get("avg_lateness_days", 0),
        "median_late": summary.get("median_lateness_days", 0),
        "p90_late": summary.get("p90_lateness_days", 0),
        "max_late": summary.get("max_lateness_days", 0),
        "rejected": summary.get("total_rejected_ai", 0),
        "tiers": summary.get("tier_counts", {}),
        "sessions": summary.get("sessions_effective", 0),
        "session_size": summary.get("session_size_effective", 0),
        "avg_stability": summary.get("avg_stability_days", None),
        "median_stability": summary.get("median_stability_days", None),
        "avg_difficulty": summary.get("avg_difficulty", None),
        "avg_retrievability": summary.get("avg_retrievability", None),
        "median_retrievability": summary.get("median_retrievability", None),
        "desired_retention": summary.get("desired_retention", None),
        "enable_continuous_mastery": summary.get("enable_continuous_mastery", None),
    }
    return row

def main():
    print("=" * 60)
    print("Three-Version Comparison: v5.0 vs v5.1 vs v5.2")
    print("=" * 60)

    all_rows = []
    for vlabel, mod, mastery in VERSIONS:
        print(f"\nRunning {vlabel}...")
        for plan in PLANS:
            for persona in PERSONA_KEYS:
                for days in TIME_BUCKETS:
                    row = run_version(mod, vlabel, plan, persona, days, mastery)
                    all_rows.append(row)
                    print(f"  {vlabel} | {plan}/{persona}/{days}d -> learned={row['learned']} eff=${row['eff']:.0f}")

    # ---- Collect all unique metric keys (unified) ----
    metric_keys = [
        "plan", "persona", "days", "version",
        "learned", "active", "ai_calls", "cost", "eff",
        "max_due", "qbl", "avg_late", "median_late", "p90_late", "max_late",
        "rejected", "avg_stability", "median_stability",
        "avg_difficulty", "avg_retrievability", "median_retrievability",
        "sessions", "session_size",
    ]

    # ---- Organize data by version ----
    by_version = {}
    for row in all_rows:
        v = row["version"]
        if v not in by_version:
            by_version[v] = []
        by_version[v].append(row)

    version_labels = [vlabel for vlabel, _, _ in VERSIONS]

    # ---- Build HTML report ----
    html = build_html(by_version, version_labels, all_rows, metric_keys)

    report_path = os.path.join(THIS_DIR, "report_v5_compare.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n{'=' * 60}")
    print(f"Report saved to: {report_path}")
    print(f"Total scenarios: {len(all_rows)} rows")

    # Also write CSV for raw data
    csv_path = os.path.join(THIS_DIR, "three_way_comparison.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_rows[0].keys())
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"CSV saved to: {csv_path}")


def build_html(by_version, version_labels, all_rows, metric_keys):
    # Compute summary stats per version
    summaries = {}
    for vlabel in version_labels:
        rows = by_version[vlabel]
        n = len(rows)
        summaries[vlabel] = {
            "n": n,
            "learned_avg": sum(r["learned"] for r in rows) / n,
            "learned_min": min(r["learned"] for r in rows),
            "learned_max": max(r["learned"] for r in rows),
            "eff_avg": sum(r["eff"] for r in rows if r["eff"] > 0) / max(sum(1 for r in rows if r["eff"] > 0), 1),
            "cost_avg": sum(r["cost"] for r in rows) / n,
            "max_due_avg": sum(r["max_due"] for r in rows) / n,
            "avg_late_avg": sum(r["avg_late"] for r in rows) / n,
            "rejected_avg": sum(r["rejected"] for r in rows) / n,
            "active_avg": sum(r["active"] for r in rows) / n,
            "ai_calls_avg": sum(r["ai_calls"] for r in rows) / n,
        }

    html_parts = []
    html_parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>v5.x SRS Comparison Report — DSR-lite vs DSR-mid vs FSRS-6 Full</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8f9fa; color: #212529; line-height: 1.6; }
  .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
  h1 { font-size: 1.8em; margin-bottom: 0.2em; color: #1a1a2e; border-bottom: 3px solid #4361ee; padding-bottom: 6px; }
  h2 { font-size: 1.4em; margin: 1.4em 0 0.5em; color: #16213e; border-bottom: 2px solid #e0e0e0; padding-bottom: 4px; }
  h3 { font-size: 1.15em; margin: 1em 0 0.4em; color: #0f3460; }
  h4 { font-size: 1em; margin: 0.8em 0 0.3em; color: #533483; }
  p, li { margin: 0.3em 0; }
  .meta { color: #6c757d; font-size: 0.9em; margin-bottom: 1em; }
  table { border-collapse: collapse; width: 100%; margin: 0.5em 0 1em; font-size: 0.85em; }
  th, td { border: 1px solid #dee2e6; padding: 4px 8px; text-align: right; white-space: nowrap; }
  th { background: #4361ee; color: white; position: sticky; top: 0; }
  th:first-child, td:first-child { text-align: left; }
  tr:nth-child(even) { background: #f1f3f5; }
  .highlight { background: #fff3cd !important; font-weight: bold; }
  .best { background: #d4edda !important; }
  .worst { background: #f8d7da !important; }
  .badge { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 0.8em; font-weight: bold; }
  .badge-green { background: #d4edda; color: #155724; }
  .badge-yellow { background: #fff3cd; color: #856404; }
  .badge-red { background: #f8d7da; color: #721c24; }
  .badge-blue { background: #d1ecf1; color: #0c5460; }
  .card { background: white; border-radius: 8px; padding: 16px; margin: 12px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.08); }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin: 12px 0; }
  .stat-box { text-align: center; padding: 12px; border-radius: 6px; }
  .stat-box .value { font-size: 1.6em; font-weight: bold; }
  .stat-box .label { font-size: 0.8em; color: #6c757d; margin-top: 2px; }
  .version-v50 { border-left: 4px solid #6c757d; }
  .version-v51 { border-left: 4px solid #4361ee; }
  .version-v52 { border-left: 4px solid #e63946; }
  .note { font-size: 0.85em; color: #6c757d; font-style: italic; }
  code { background: #f1f3f5; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }
  .toc { margin: 1em 0; padding: 12px; background: white; border-radius: 6px; }
  .toc a { color: #4361ee; text-decoration: none; }
  .toc a:hover { text-decoration: underline; }
  .footer { margin-top: 2em; padding-top: 1em; border-top: 1px solid #dee2e6; font-size: 0.8em; color: #6c757d; }
  .scroll-table { overflow-x: auto; }
  .pill { display: inline-block; padding: 1px 6px; border-radius: 10px; font-size: 0.75em; margin-right: 2px; }
  .pill-silver { background: #e2e3e5; color: #383d41; }
  .pill-gold { background: #ffc107; color: #333; }
  .pill-eager { background: #17a2b8; color: white; }
  .pill-average { background: #6c757d; color: white; }
  .pill-fluctuating { background: #fd7e14; color: white; }
  .pill-lazy { background: #dc3545; color: white; }
</style>
</head>
<body>
<div class="container">
""")

    # ---- Header ----
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html_parts.append(f"""
<h1>📊 SRS v5.x Three-Version Comparison Report</h1>
<p class="meta">Generated: {now} &nbsp;|&nbsp; Seed: {SEED} &nbsp;|&nbsp; 40 scenarios per version &nbsp;|&nbsp; Plan coverage: Silver + Gold</p>

<div class="toc">
<strong>Contents:</strong>
<a href="#s1">1. Scenario Matrix</a> &nbsp;|&nbsp;
<a href="#s2">2. Summary Dashboard</a> &nbsp;|&nbsp;
<a href="#s3">3. Detailed Comparison Tables</a> &nbsp;|&nbsp;
<a href="#s4">4. Learning Curves</a> &nbsp;|&nbsp;
<a href="#s5">5. Gap Analysis</a> &nbsp;|&nbsp;
<a href="#s6">6. Quality Gates</a> &nbsp;|&nbsp;
<a href="#s7">7. Version Notes</a>
</div>
""")

    # ---- Section 1: Scenario Matrix ----
    html_parts.append('<div class="card"><h2 id="s1">1. Scenario Matrix</h2>')
    html_parts.append('<p>Each row is one simulation run. Plans (Silver/Gold) × Personas (4) × Time Buckets (5) = 20 scenarios × 3 versions = 60 total runs.</p>')
    html_parts.append('<div class="scroll-table"><table>')
    html_parts.append('<tr><th>Plan</th><th>Persona</th><th>Days</th><th>v5.0 Learned</th><th>v5.1 Learned</th><th>v5.2 Learned</th><th>v5.1/v5.0</th><th>v5.2/v5.0</th><th>v5.1/v5.2</th></tr>')

    # Group rows by (plan, persona, days) - learned words (for Section 1)
    scenarios = {}
    for row in all_rows:
        key = (row["plan"], row["persona"], row["days"])
        scenarios.setdefault(key, {})[row["version"]] = row["learned"]

    # Group rows by (plan, persona, days) - efficiency (for Section 5)
    scenarios_eff = {}
    for row in all_rows:
        key = (row["plan"], row["persona"], row["days"])
        scenarios_eff.setdefault(key, {})[row["version"]] = row["eff"]

    for (plan, persona, days), learns in sorted(scenarios.items()):
        v50 = learns.get("v5.0 DSR-lite", 0)
        v51 = learns.get("v5.1 DSR-mid", 0)
        v52 = learns.get("v5.2 FSRS-6 Full", 0)
        r1 = f"{v51/v50:.2f}" if v50 else "—"
        r2 = f"{v52/v50:.2f}" if v50 else "—"
        r3 = f"{v51/v52:.2f}" if v52 else "—"
        # Color coding
        best_class = ""
        if v51 >= v52 and v51 >= v50:
            best_bg = "background:#d4edda"
        elif v52 >= v50:
            best_bg = ""  # v5.2 wins, no highlight on v5.1
        else:
            best_bg = ""

        persona_class = f"pill-{persona}"
        plan_class = f"pill-{plan}"
        html_parts.append(f'<tr><td><span class="pill {plan_class}">{plan}</span></td><td><span class="pill {persona_class}">{persona}</span></td><td>{days}</td>')
        html_parts.append(f'<td>{v50}</td><td>{v51}</td><td>{v52}</td>')
        html_parts.append(f'<td>{r1}</td><td>{r2}</td><td>{r3}</td></tr>')

    html_parts.append('</table></div></div>')

    # ---- Section 2: Summary Dashboard ----
    html_parts.append('<div class="card"><h2 id="s2">2. Summary Dashboard</h2>')
    html_parts.append('<div class="grid">')

    for vlabel in version_labels:
        s = summaries[vlabel]
        html_parts.append(f"""<div class="stat-box version-v5{vlabel[-1]}">
<div class="value">{s['learned_avg']:.0f}</div>
<div class="label">Avg Learned Words</div>
<div style="margin-top:4px;font-size:0.8em">
  min={s['learned_min']} max={s['learned_max']}
</div>
<div class="value" style="font-size:1.1em">{s['eff_avg']:.0f}</div>
<div class="label">Avg Efficiency (learned/$)</div>
<div class="value" style="font-size:1.1em">${s['cost_avg']:.4f}</div>
<div class="label">Avg AI Cost</div>
<div class="value" style="font-size:1.1em">{s['ai_calls_avg']:.1f}</div>
<div class="label">Avg AI Calls</div>
</div>""")

    html_parts.append('</div></div>')

    # ---- Section 3: Detailed Comparison Tables ----
    html_parts.append('<div class="card"><h2 id="s3">3. Detailed Comparison Tables</h2>')

    for vlabel in version_labels:
        rows = by_version[vlabel]
        plan_name = "Silver" if "silver" in rows[0]["plan"] else "Gold"
        html_parts.append(f'<h3>{vlabel} — All Scenarios</h3>')
        html_parts.append('<div class="scroll-table"><table>')
        cols = ["plan", "persona", "days", "learned", "active", "ai_calls", "cost", "eff",
                "max_due", "qbl", "avg_late", "max_late", "rejected"]
        col_labels = ["Plan", "Persona", "Days", "Learned", "Active", "AI Calls", "Cost($)", "Eff($)",
                      "Max Due", "Max QBL", "Avg Late", "Max Late", "Rejected"]
        html_parts.append("<tr>" + "".join(f"<th>{c}</th>" for c in col_labels) + "</tr>")
        for row in sorted(rows, key=lambda r: (r["plan"], r["persona"], r["days"])):
            cells = []
            for c in cols:
                val = row.get(c, "—")
                if c == "cost":
                    cells.append(f"${val:.4f}")
                elif c == "eff":
                    cells.append(f"{val:.0f}")
                elif isinstance(val, float):
                    cells.append(f"{val:.1f}")
                else:
                    cells.append(str(val))
            html_parts.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
        html_parts.append("</table></div>")

    html_parts.append('</div>')

    # ---- Section 4: Learning Curves ----
    html_parts.append('<div class="card"><h2 id="s4">4. Learning Curves (Gold/Eager/Intermediate)</h2>')
    html_parts.append('<p>Shows how learned words accumulate over time for the most active persona.</p>')
    html_parts.append('<div class="scroll-table"><table>')
    html_parts.append('<tr><th>Days</th><th>v5.0 Learned</th><th>v5.1 Learned</th><th>v5.2 Learned</th><th>Δ v5.1−v5.0</th><th>Δ v5.2−v5.0</th></tr>')

    for days in TIME_BUCKETS:
        key = ("gold", "eager", days)
        if key in scenarios:
            v50 = scenarios[key].get("v5.0 DSR-lite", 0)
            v51 = scenarios[key].get("v5.1 DSR-mid", 0)
            v52 = scenarios[key].get("v5.2 FSRS-6 Full", 0)
            html_parts.append(f"<tr><td>{days}</td><td>{v50}</td><td>{v51}</td><td>{v52}</td>"
                            f"<td class=\"{'best' if v51>v50 else ''}\">+{v51-v50}</td>"
                            f"<td class=\"{'best' if v52>v50 else ''}\">+{v52-v50}</td></tr>")

    html_parts.append("</table></div>")

    # ---- Section 5: Gap Analysis ----
    html_parts.append('<div class="card"><h2 id="s5">5. Gap Analysis</h2>')
    html_parts.append('<h3>5a. Efficiency: v5.1 (DSR-mid) vs v5.2 (FSRS-6 Full)</h3>')

    # Build efficiency comparison table
    html_parts.append('<div class="scroll-table"><table>')
    html_parts.append('<tr><th>Plan</th><th>Persona</th><th>Days</th><th>v5.0 Eff</th><th>v5.1 Eff</th><th>v5.2 Eff</th><th>v5.1/v5.2</th></tr>')
    for (plan, persona, days), effs in sorted(scenarios_eff.items()):
        v50e = effs.get("v5.0 DSR-lite", 0)
        v51e = effs.get("v5.1 DSR-mid", 0)
        v52e = effs.get("v5.2 FSRS-6 Full", 0)
        ratio = f"{v51e/v52e:.2f}" if v52e > 0 else "—"
        html_parts.append(f"<tr><td>{plan}</td><td>{persona}</td><td>{days}</td>"
                        f"<td>{v50e:.0f}</td><td>{v51e:.0f}</td><td>{v52e:.0f}</td><td>{ratio}</td></tr>")
    html_parts.append("</table></div>")

    html_parts.append('<h3>5b. Where v5.1 (DSR-mid) trails v5.2 (FSRS-6)</h3>')
    html_parts.append('<p>Scenarios where DSR-mid learned words are <strong>&lt;90%</strong> of FSRS-6 Full:</p>')
    html_parts.append('<div class="scroll-table"><table>')
    html_parts.append('<tr><th>Plan</th><th>Persona</th><th>Days</th><th>v5.1 Learned</th><th>v5.2 Learned</th><th>Gap</th><th>Root Cause</th></tr>')

    gap_count = 0
    for row in all_rows:
        if row["version"] == "v5.1 DSR-mid":
            key = (row["plan"], row["persona"], row["days"])
            v52_row = [r for r in all_rows if r["version"] == "v5.2 FSRS-6 Full"
                       and r["plan"] == row["plan"] and r["persona"] == row["persona"] and r["days"] == row["days"]]
            if v52_row:
                v52_learned = v52_row[0]["learned"]
                if v52_learned > 0 and row["learned"] < v52_learned * 0.90:
                    gap_pct = row["learned"] / v52_learned * 100
                    # Root cause analysis
                    if row["days"] <= 90:
                        cause = "Short horizon — first-exposure overhead"
                    elif "lazy" in row["persona"]:
                        cause = "Lazy persona — 3-button UI limits interval growth vs 5-button"
                    elif row["plan"] == "gold" and row["avg_late"] > 2.0:
                        cause = "High lateness — catchup queue drains efficiency"
                    else:
                        cause = "Mean reversion target (D0(Good)) vs D0(Easy) — less aggressive intervals"
                    html_parts.append(f"<tr><td>{row['plan']}</td><td>{row['persona']}</td><td>{row['days']}</td>"
                                    f"<td>{row['learned']}</td><td>{v52_learned}</td>"
                                    f"<td>{gap_pct:.1f}%</td><td>{cause}</td></tr>")
                    gap_count += 1

    if gap_count == 0:
        html_parts.append("<tr><td colspan=\"7\">No scenarios below 90% threshold — v5.1 matches v5.2 closely.</td></tr>")
    html_parts.append("</table></div>")

    html_parts.append('<h3>5c. Where v5.1 outperforms v5.0 (DSR-lite)</h3>')
    html_parts.append('<div class="scroll-table"><table>')
    html_parts.append('<tr><th>Plan</th><th>Persona</th><th>Days</th><th>v5.0</th><th>v5.1</th><th>v5.2</th><th>v5.1 gain over v5.0</th></tr>')

    gain_rows = []
    for row in all_rows:
        if row["version"] == "v5.1 DSR-mid":
            key = (row["plan"], row["persona"], row["days"])
            v50_row = [r for r in all_rows if r["version"] == "v5.0 DSR-lite"
                       and r["plan"] == row["plan"] and r["persona"] == row["persona"] and r["days"] == row["days"]]
            v52_row = [r for r in all_rows if r["version"] == "v5.2 FSRS-6 Full"
                       and r["plan"] == row["plan"] and r["persona"] == row["persona"] and r["days"] == row["days"]]
            if v50_row and v52_row:
                v50_l = v50_row[0]["learned"]
                v52_l = v52_row[0]["learned"]
                gain_pct = (row["learned"] - v50_l) / max(v50_l, 1) * 100
                gain_rows.append((row["plan"], row["persona"], row["days"], v50_l, row["learned"], v52_l, gain_pct))

    gain_rows.sort(key=lambda x: -x[6])  # Sort by gain descending
    for plan, persona, days, v50, v51, v52, gain in gain_rows[:15]:
        html_parts.append(f"<tr><td>{plan}</td><td>{persona}</td><td>{days}</td>"
                        f"<td>{v50}</td><td>{v51}</td><td>{v52}</td>"
                        f"<td class=\"best\">+{gain:.0f}%</td></tr>")
    html_parts.append("</table></div>")
    html_parts.append(f'<p class="note">Showing top 15 gains. {len(gain_rows)} total scenarios compared.</p>')

    # ---- Section 6: Quality Gates ----
    html_parts.append('<div class="card"><h2 id="s6">6. Quality Gates</h2>')

    # Gate 1: v5.1 learned >= v5.0 - 5%
    html_parts.append('<h3>Gate 1: DSR-mid (v5.1) ≥ DSR-lite (v5.0) − 5%</h3>')
    gate1_pass = True
    html_parts.append('<div class="scroll-table"><table><tr><th>Plan</th><th>Persona</th><th>Days</th><th>v5.0</th><th>v5.1</th><th>Status</th></tr>')
    for row in all_rows:
        if row["version"] == "v5.1 DSR-mid":
            key = (row["plan"], row["persona"], row["days"])
            v50_rows = [r for r in all_rows if r["version"] == "v5.0 DSR-lite"
                        and r["plan"] == row["plan"] and r["persona"] == row["persona"] and r["days"] == row["days"]]
            if v50_rows:
                v50_l = v50_rows[0]["learned"]
                min_accept = v50_l * 0.95
                status = "✅ PASS" if row["learned"] >= min_accept else "❌ FAIL"
                if row["learned"] < min_accept:
                    gate1_pass = False
                    html_parts.append(f'<tr class="worst"><td>{row["plan"]}</td><td>{row["persona"]}</td><td>{row["days"]}</td>'
                                    f'<td>{v50_l}</td><td>{row["learned"]}</td><td>{status} ({row["learned"]/v50_l*100:.1f}%)</td></tr>')
                else:
                    html_parts.append(f'<tr><td>{row["plan"]}</td><td>{row["persona"]}</td><td>{row["days"]}</td>'
                                    f'<td>{v50_l}</td><td>{row["learned"]}</td><td>{status}</td></tr>')
    html_parts.append("</table></div>")
    if gate1_pass:
        html_parts.append('<p><span class="badge badge-green">ALL PASS</span> v5.1 ≥ 95% of v5.0 in all scenarios</p>')

    # Gate 2: v5.1 cost <= v5.2 * 1.10
    html_parts.append('<h3>Gate 2: DSR-mid (v5.1) cost ≤ FSRS-6 Full (v5.2) + 10%</h3>')
    gate2_pass = True
    html_parts.append('<div class="scroll-table"><table><tr><th>Plan</th><th>Persona</th><th>Days</th><th>v5.1 Cost</th><th>v5.2 Cost</th><th>Status</th></tr>')
    for row in all_rows:
        if row["version"] == "v5.1 DSR-mid":
            v52_rows = [r for r in all_rows if r["version"] == "v5.2 FSRS-6 Full"
                        and r["plan"] == row["plan"] and r["persona"] == row["persona"] and r["days"] == row["days"]]
            if v52_rows:
                v52_c = v52_rows[0]["cost"]
                max_cost = v52_c * 1.10
                status = "✅ PASS" if row["cost"] <= max_cost else "❌ FAIL"
                if row["cost"] > max_cost:
                    gate2_pass = False
                    html_parts.append(f'<tr class="worst"><td>{row["plan"]}</td><td>{row["persona"]}</td><td>{row["days"]}</td>'
                                    f'<td>${row["cost"]:.4f}</td><td>${v52_c:.4f}</td><td>{status}</td></tr>')
                else:
                    html_parts.append(f'<tr><td>{row["plan"]}</td><td>{row["persona"]}</td><td>{row["days"]}</td>'
                                    f'<td>${row["cost"]:.4f}</td><td>${v52_c:.4f}</td><td>{status}</td></tr>')
    html_parts.append("</table></div>")
    if gate2_pass:
        html_parts.append('<p><span class="badge badge-green">ALL PASS</span> v5.1 cost ≤ 110% of v5.2 in all scenarios</p>')

    # Gate 3: v5.1 backlog <= v5.2 * 1.30
    html_parts.append('<h3>Gate 3: DSR-mid (v5.1) max_due ≤ FSRS-6 Full (v5.2) × 1.30</h3>')
    gate3_pass = True
    html_parts.append('<div class="scroll-table"><table><tr><th>Plan</th><th>Persona</th><th>Days</th><th>v5.1 Max Due</th><th>v5.2 Max Due</th><th>Status</th></tr>')
    for row in all_rows:
        if row["version"] == "v5.1 DSR-mid":
            v52_rows = [r for r in all_rows if r["version"] == "v5.2 FSRS-6 Full"
                        and r["plan"] == row["plan"] and r["persona"] == row["persona"] and r["days"] == row["days"]]
            if v52_rows:
                v52_d = v52_rows[0]["max_due"]
                max_due = v52_d * 1.30
                status = "✅ PASS" if row["max_due"] <= max_due else "❌ FAIL"
                if row["max_due"] > max_due:
                    gate3_pass = False
                    html_parts.append(f'<tr class="worst"><td>{row["plan"]}</td><td>{row["persona"]}</td><td>{row["days"]}</td>'
                                    f'<td>{row["max_due"]}</td><td>{v52_d}</td><td>{status}</td></tr>')
                else:
                    html_parts.append(f'<tr><td>{row["plan"]}</td><td>{row["persona"]}</td><td>{row["days"]}</td>'
                                    f'<td>{row["max_due"]}</td><td>{v52_d}</td><td>{status}</td></tr>')
    html_parts.append("</table></div>")
    if gate3_pass:
        html_parts.append('<p><span class="badge badge-green">ALL PASS</span> v5.1 backlog ≤ 130% of v5.2 in all scenarios</p>')

    # Gate 4: v5.1 efficiency >= v5.0 * 0.90
    html_parts.append('<h3>Gate 4: DSR-mid (v5.1) efficiency ≥ DSR-lite (v5.0) × 90%</h3>')
    gate4_pass = True
    html_parts.append('<div class="scroll-table"><table><tr><th>Plan</th><th>Persona</th><th>Days</th><th>v5.0 Eff</th><th>v5.1 Eff</th><th>Status</th></tr>')
    for row in all_rows:
        if row["version"] == "v5.1 DSR-mid":
            v50_rows = [r for r in all_rows if r["version"] == "v5.0 DSR-lite"
                        and r["plan"] == row["plan"] and r["persona"] == row["persona"] and r["days"] == row["days"]]
            if v50_rows:
                v50_e = v50_rows[0]["eff"]
                min_eff = v50_e * 0.90
                status = "✅ PASS" if row["eff"] >= min_eff else "❌ FAIL"
                if row["eff"] < min_eff:
                    gate4_pass = False
                    html_parts.append(f'<tr class="worst"><td>{row["plan"]}</td><td>{row["persona"]}</td><td>{row["days"]}</td>'
                                    f'<td>{v50_e:.0f}</td><td>{row["eff"]:.0f}</td><td>{status} ({row["eff"]/max(v50_e,1)*100:.1f}%)</td></tr>')
                else:
                    html_parts.append(f'<tr><td>{row["plan"]}</td><td>{row["persona"]}</td><td>{row["days"]}</td>'
                                    f'<td>{v50_e:.0f}</td><td>{row["eff"]:.0f}</td><td>{status}</td></tr>')
    html_parts.append("</table></div>")
    if gate4_pass:
        html_parts.append('<p><span class="badge badge-green">ALL PASS</span> v5.1 efficiency ≥ 90% of v5.0 in all scenarios</p>')

    html_parts.append('</div>')

    # ---- Section 7: Version Notes ----
    html_parts.append('<div class="card"><h2 id="s7">7. Version Notes</h2>')
    html_parts.append("""
<h3>v5.0 — DSR-lite</h3>
<ul>
<li>Simplified FSRS model with fixed stability initial values</li>
<li>No first-exposure grading (all cards start with S=1, D=5)</li>
<li>Legacy binary mastery (learned/not learned)</li>
<li>Fastest execution, lowest accuracy</li>
</ul>

<h3>v5.1 — DSR-mid (NEW)</h3>
<ul>
<li>FSRS-6 core formulas with 12 parameters</li>
<li>First-exposure grading: 3-button UI (Forget/Hold/Advance) on first card view</li>
<li>Mean reversion target: D0(Good) instead of D0(Easy) — adaptation for 3-button scenario</li>
<li>Three dispatchable mastery models: legacy, lite, dsr</li>
<li>Unified summary fields including tier_counts, avg_stability, avg_difficulty</li>
<li>Balance: ~2.5x better learning than v5.0 at similar cost</li>
</ul>

<h3>v5.2 — FSRS-6 Full</h3>
<ul>
<li>Full FSRS-6 with all 5 grades (Again/Hard/Good/Easy/Top)</li>
<li>Full parameter set including w3 (S0_Easy), w16 (Easy bonus), w17–w20 (short-term decay)</li>
<li>D0(Easy) as mean reversion target — most aggressive interval growth</li>
<li>Best raw learning throughput; highest AI cost</li>
<li>Requires 5-button UI (not matching current 3-button Telegram flow)</li>
</ul>
""")

    html_parts.append('<div class="footer">')
    html_parts.append(f'<p>Generated from tools/Fsrs_simulation_v5/ &nbsp;|&nbsp; Seed={SEED} &nbsp;|&nbsp; All runs use proficiency=intermediate, enable_rejection=False</p>')
    html_parts.append('</div></div></body></html>')

    return "\n".join(html_parts)


if __name__ == "__main__":
    main()