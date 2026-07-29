#!/usr/bin/env python3
"""
Generate Enhanced HTML Report: v5.2 (fixed) vs v5.4 (FSRS-6 Full 4-grade)
Per-row coloring, percentile metrics, all sections.
"""

import json
import os
import sys
from datetime import datetime
from collections import Counter

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(THIS_DIR, "compare_v52_v54_data.json")
OUTPUT_PATH = os.path.join(THIS_DIR, "report_v52_v54.html")

with open(DATA_PATH, "r", encoding="utf-8") as f:
    all_runs = json.load(f)

VERSIONS = ["v5.2 FSRS-6 (fixed)", "v5.4 FSRS-6 Full (4-grade)"]
PLANS = ["free", "silver", "gold"]
PERSONAS = ["eager", "average"]
MONTHS = [1, 3, 6, 12, 24]
DAYS_MAP = {1: 30, 3: 90, 6: 180, 12: 360, 24: 720}

VERSION_COLORS = {
    "v5.2 FSRS-6 (fixed)": "#6c757d",
    "v5.4 FSRS-6 Full (4-grade)": "#e63946",
}

PERSONA_PILLS = {
    "eager": 'class="pill pill-eager"',
    "average": 'class="pill pill-average"',
}
PLAN_PILLS = {
    "free": 'class="pill pill-free"',
    "silver": 'class="pill pill-silver"',
    "gold": 'class="pill pill-gold"',
}

def pill(text, pill_class):
    return f'<span {pill_class}>{text}</span>'

def get_runs(version=None, plan=None, persona=None, months=None):
    result = all_runs
    if version:
        result = [r for r in result if r["version"] == version]
    if plan:
        result = [r for r in result if r["plan"] == plan]
    if persona:
        result = [r for r in result if r["persona"] == persona]
    if months:
        result = [r for r in result if r["months"] == months]
    return result

# ---- Build HTML Sections ----

def build_header():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>v5.2 vs v5.4 FSRS Comparison</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8f9fa; color: #212529; line-height: 1.6; }}
  .container {{ max-width: 1600px; margin: 0 auto; padding: 20px; }}
  h1 {{ font-size: 1.8em; margin-bottom: 0.2em; color: #1a1a2e; border-bottom: 3px solid #4361ee; padding-bottom: 6px; }}
  h2 {{ font-size: 1.4em; margin: 1.4em 0 0.5em; color: #16213e; border-bottom: 2px solid #e0e0e0; padding-bottom: 4px; }}
  h3 {{ font-size: 1.15em; margin: 1em 0 0.4em; color: #0f3460; }}
  p, li {{ margin: 0.3em 0; }}
  .meta {{ color: #6c757d; font-size: 0.9em; margin-bottom: 1em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 0.5em 0 1em; font-size: 0.8em; }}
  th, td {{ border: 1px solid #dee2e6; padding: 3px 6px; text-align: right; white-space: nowrap; }}
  th {{ background: #4361ee; color: white; position: sticky; top: 0; z-index: 1; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
  tr:nth-child(even) {{ background: #f1f3f5; }}
  .row-best {{ background: #d4edda !important; font-weight: bold; }}
  .row-worst {{ background: #f8d7da !important; font-weight: bold; }}
  .p99 {{ background: #f8d7da !important; }}
  .p95 {{ background: #fff3cd !important; }}
  .p90 {{ background: #d1ecf1 !important; }}
  .p50 {{ background: #e2f0ff !important; }}
  .badge {{ display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 0.75em; font-weight: bold; }}
  .badge-green {{ background: #d4edda; color: #155724; }}
  .badge-yellow {{ background: #fff3cd; color: #856404; }}
  .badge-red {{ background: #f8d7da; color: #721c24; }}
  .badge-blue {{ background: #d1ecf1; color: #0c5460; }}
  .card {{ background: white; border-radius: 8px; padding: 16px; margin: 12px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.08); }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; margin: 12px 0; }}
  .stat-box {{ text-align: center; padding: 12px; border-radius: 6px; }}
  .stat-box .value {{ font-size: 1.5em; font-weight: bold; }}
  .stat-box .label {{ font-size: 0.75em; color: #6c757d; margin-top: 2px; }}
  .version-v52 {{ border-left: 4px solid #6c757d; }}
  .version-v54 {{ border-left: 4px solid #e63946; }}
  .note {{ font-size: 0.8em; color: #6c757d; font-style: italic; }}
  code {{ background: #f1f3f5; padding: 1px 4px; border-radius: 3px; font-size: 0.85em; }}
  .toc {{ margin: 1em 0; padding: 12px; background: white; border-radius: 6px; }}
  .toc a {{ color: #4361ee; text-decoration: none; margin-right: 12px; }}
  .toc a:hover {{ text-decoration: underline; }}
  .footer {{ margin-top: 2em; padding-top: 1em; border-top: 1px solid #dee2e6; font-size: 0.8em; color: #6c757d; }}
  .scroll-table {{ overflow-x: auto; }}
  .pill {{ display: inline-block; padding: 1px 6px; border-radius: 10px; font-size: 0.7em; margin-right: 2px; font-weight: 500; }}
  .pill-free {{ background: #28a745; color: white; }}
  .pill-silver {{ background: #e2e3e5; color: #383d41; }}
  .pill-gold {{ background: #ffc107; color: #333; }}
  .pill-eager {{ background: #17a2b8; color: white; }}
  .pill-average {{ background: #6c757d; color: white; }}
  .version-badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 0.75em; font-weight: bold; margin-right: 4px; }}
  .v-badge-0 {{ background: #6c757d; color: white; }}
  .v-badge-1 {{ background: #e63946; color: white; }}
</style>
</head>
<body>
<div class="container">
<h1>📊 FSRS Comparison: v5.2 (fixed) vs v5.4 (Full 4-grade)</h1>
<p class="meta">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")} | Seed: 42 | 30 scenarios × 2 versions = 60 runs</p>

<div class="toc">
<strong>Contents:</strong>
<a href="#s1">1. Scenario Matrix</a> |
<a href="#s2">2. Summary Dashboard</a> |
<a href="#s3">3. Long-Run Stress (24m)</a> |
<a href="#s4">4. Learning Curves</a> |
<a href="#s5">5. Percentile Deep-Dive</a> |
<a href="#s6">6. Worst-Case Analysis</a> |
<a href="#s7">7. Version Notes</a>
</div>"""

def build_section1_scenario_matrix():
    html = ['<div class="card"><h2 id="s1">1. Scenario Matrix (30 scenarios × 2 versions)</h2>']
    html.append('<p>Plans (Free/Silver/Gold) × Personas (Eager/Average) × Periods (1/3/6/12/24m) = 30 scenarios. Per-row coloring: <span class="row-best">green = best</span>, <span class="row-worst">red = worst</span> for learned words.</p>')
    html.append('<div class="scroll-table"><table>')
    html.append('<tr><th>Plan</th><th>Persona</th><th>Months</th>'
                '<th>v5.2 Learned</th><th>v5.4 Learned</th>'
                '<th>Ratio v5.4/v5.2</th>'
                '<th>v5.2 Eff($)</th><th>v5.4 Eff($)</th>'
                '<th>v5.2 Max Late</th><th>v5.4 Max Late</th>'
                '<th>v5.2 Max Due</th><th>v5.4 Max Due</th></tr>')
    
    scenarios = {}
    for r in all_runs:
        key = (r["plan"], r["persona"], r["months"])
        if key not in scenarios:
            scenarios[key] = {}
        scenarios[key][r["version"]] = r["summary"]["learned_words"]
    
    for (plan, persona, months), learns in sorted(scenarios.items()):
        v52 = learns.get("v5.2 FSRS-6 (fixed)", 0)
        v54 = learns.get("v5.4 FSRS-6 Full (4-grade)", 0)
        ratio = f"{v54/v52:.2f}" if v52 else "—"
        
        s52 = get_runs(version="v5.2 FSRS-6 (fixed)", plan=plan, persona=persona, months=months)[0]["summary"]
        s54 = get_runs(version="v5.4 FSRS-6 Full (4-grade)", plan=plan, persona=persona, months=months)[0]["summary"]
        
        best = "v5.2" if v52 > v54 else "v5.4"
        worst = "v5.4" if best == "v5.2" else "v5.2"
        
        html.append(f'<tr>'
                    f'<td>{pill(plan, PLAN_PILLS[plan])}</td>'
                    f'<td>{pill(persona, PERSONA_PILLS[persona])}</td>'
                    f'<td>{months}m</td>'
                    f'<td class="{"row-best" if best=="v5.2" else "row-worst"}">{v52}</td>'
                    f'<td class="{"row-best" if best=="v5.4" else "row-worst"}">{v54}</td>'
                    f'<td>{ratio}</td>'
                    f'<td class="{"row-best" if s52["learned_words_per_dollar"] > s54["learned_words_per_dollar"] else "row-worst"}">{s52["learned_words_per_dollar"]:.0f}</td>'
                    f'<td class="{"row-best" if s54["learned_words_per_dollar"] > s52["learned_words_per_dollar"] else "row-worst"}">{s54["learned_words_per_dollar"]:.0f}</td>'
                    f'<td class="{"row-best" if s52["max_lateness_days"] < s54["max_lateness_days"] else "row-worst"}">{s52["max_lateness_days"]}</td>'
                    f'<td class="{"row-best" if s54["max_lateness_days"] < s52["max_lateness_days"] else "row-worst"}">{s54["max_lateness_days"]}</td>'
                    f'<td class="{"row-best" if s52["max_due_backlog"] < s54["max_due_backlog"] else "row-worst"}">{s52["max_due_backlog"]}</td>'
                    f'<td class="{"row-best" if s54["max_due_backlog"] < s52["max_due_backlog"] else "row-worst"}">{s54["max_due_backlog"]}</td>'
                    f'</tr>')
    
    html.append('</table></div></div>')
    return "\n".join(html)

def build_section2_summary_dashboard():
    html = ['<div class="card"><h2 id="s2">2. Summary Dashboard</h2><div class="grid">']
    
    for v in VERSIONS:
        runs = get_runs(version=v)
        n = len(runs)
        learned_avg = sum(r["summary"]["learned_words"] for r in runs) / n
        learned_min = min(r["summary"]["learned_words"] for r in runs)
        learned_max = max(r["summary"]["learned_words"] for r in runs)
        eff_avg = sum(r["summary"]["learned_words_per_dollar"] for r in runs if r["summary"]["learned_words_per_dollar"] > 0) / max(sum(1 for r in runs if r["summary"]["learned_words_per_dollar"] > 0), 1)
        cost_avg = sum(r["summary"]["total_ai_cost_usd"] for r in runs) / n
        max_due_avg = sum(r["summary"]["max_due_backlog"] for r in runs) / n
        avg_late_avg = sum(r["summary"]["avg_lateness_days"] for r in runs) / n
        ai_calls_avg = sum(r["summary"]["total_ai_calls"] for r in runs) / n
        
        v_class = "version-v52" if "v5.2" in v else "version-v54"
        badge = "v-badge-0" if "v5.2" in v else "v-badge-1"
        v_label = v.split("(")[0].strip()
        
        html.append(f'''<div class="stat-box {v_class}">
<div class="value">{learned_avg:.0f}</div>
<div class="label">Avg Learned Words</div>
<div style="margin-top:4px;font-size:0.75em">min={learned_min} max={learned_max}</div>
<div class="value" style="font-size:1.1em">{eff_avg:.0f}</div>
<div class="label">Avg Efficiency (learned/$)</div>
<div class="value" style="font-size:1.1em">${cost_avg:.4f}</div>
<div class="label">Avg AI Cost</div>
<div class="value" style="font-size:1.1em">{ai_calls_avg:.1f}</div>
<div class="label">Avg AI Calls</div>
<div class="value" style="font-size:1.1em">{avg_late_avg:.1f}</div>
<div class="label">Avg Lateness (days)</div>
<div class="value" style="font-size:1.1em">{max_due_avg:.0f}</div>
<div class="label">Avg Max Due Backlog</div>
<div style="margin-top:8px"><span class="version-badge {badge}">{v_label}</span></div>
</div>''')
    
    html.append('</div></div>')
    return "\n".join(html)

def build_section3_longrun():
    html = ['<div class="card"><h2 id="s3">3. Long-Run Stress (24 months / 720 days)</h2>']
    html.append('<div class="scroll-table"><table>')
    html.append('<tr><th>Plan</th><th>Persona</th><th>Version</th>'
                '<th>Learned</th><th>Learned/$</th><th>Max Due</th>'
                '<th>Max QBL</th><th>Avg Late</th><th>Max Late</th>'
                '<th class="p99">p99 Late</th><th class="p95">p95 Late</th><th class="p90">p90 Late</th>'
                '<th>AI$ Total</th></tr>')
    
    for plan in PLANS:
        for persona in PERSONAS:
            for v in VERSIONS:
                runs = get_runs(version=v, plan=plan, persona=persona, months=24)
                if not runs:
                    continue
                r = runs[0]
                s = r["summary"]
                pct = r["percentiles"]
                late = pct.get("lateness_samples", {})
                
                html.append(f'<tr>'
                            f'<td>{pill(plan, PLAN_PILLS[plan])}</td>'
                            f'<td>{pill(persona, PERSONA_PILLS[persona])}</td>'
                            f'<td><span class="version-badge {"v-badge-0" if "v5.2" in v else "v-badge-1"}">{v.split(" ")[1]}</span></td>'
                            f'<td>{s["learned_words"]}</td>'
                            f'<td>{s["learned_words_per_dollar"]:.0f}</td>'
                            f'<td>{s["max_due_backlog"]}</td>'
                            f'<td>{s["max_query_backlog"]}</td>'
                            f'<td>{s["avg_lateness_days"]:.1f}</td>'
                            f'<td>{s["max_lateness_days"]}</td>'
                            f'<td class="p99">{late.get("p99", 0):.1f}</td>'
                            f'<td class="p95">{late.get("p95", 0):.1f}</td>'
                            f'<td class="p90">{late.get("p90", 0):.1f}</td>'
                            f'<td>${s["total_ai_cost_usd"]:.4f}</td>'
                            f'</tr>')
    
    html.append('</table></div></div>')
    return "\n".join(html)

def build_section4_learning_curves():
    html = ['<div class="card"><h2 id="s4">4. Learning Curves Over Time (silver/average)</h2>']
    html.append('<div class="scroll-table"><table>')
    html.append('<tr><th>Months</th>'
                '<th>v5.2 Active</th><th>v5.4 Active</th>'
                '<th>v5.2 Learned</th><th>v5.4 Learned</th>'
                '<th>v5.2 Stability</th><th>v5.4 Stability</th>'
                '<th>v5.2 AI$</th><th>v5.4 AI$</th>'
                '<th>v5.2 Tier Dist</th><th>v5.4 Tier Dist</th></tr>')
    
    import importlib.util, inspect
    def load_module(name, filename):
        spec = importlib.util.spec_from_file_location(name, os.path.join(THIS_DIR, filename))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    
    mod_v52 = load_module("v5_2", "v5.2_FSRSv6.py")
    mod_v54 = load_module("v5_4", "v5.4_FSRS_full.py")
    
    def make_cfg(mod, plan, persona, days, mastery):
        params = inspect.signature(mod.SimConfig.__init__).parameters
        kwargs = dict(
            plan=plan, persona=persona, proficiency="intermediate",
            days=days, seed=42, enable_rejection=False, enable_catchup=True,
            enable_session_rate_limit=True,
        )
        if "mastery_model" in params:
            kwargs["mastery_model"] = mastery
        if "desired_retention" in params:
            kwargs["desired_retention"] = 0.9 if "v5.4" in mod.__file__ else 0.85
        if "enable_continuous_mastery" in params:
            kwargs["enable_continuous_mastery"] = True
        if "enable_short_term" in params:
            kwargs["enable_short_term"] = False
        if "jitter" in params:
            kwargs["jitter"] = False
        return mod.SimConfig(**kwargs)
    
    for months in MONTHS:
        days = DAYS_MAP[months]
        results = {}
        for vlabel, mod, mastery in [("v5.2 FSRS-6 (fixed)", mod_v52, "dsr"),
                                       ("v5.4 FSRS-6 Full (4-grade)", mod_v54, "dsr")]:
            cfg = make_cfg(mod, "silver", "average", days, mastery)
            _, summary = mod.simulate(cfg)
            results[vlabel] = summary

        s52 = results["v5.2 FSRS-6 (fixed)"]
        s54 = results["v5.4 FSRS-6 Full (4-grade)"]

        def cell(s, key, fmt=None):
            val = s.get(key, 0)
            if fmt:
                return fmt(val)
            return str(val)

        tc52 = s52.get("tier_counts") or {}
        tier52 = ", ".join(f"{k}={v}" for k, v in tc52.items()) if tc52 else "—"
        tc54 = s54.get("tier_counts") or {}
        tier54 = ", ".join(f"{k}={v}" for k, v in tc54.items()) if tc54 else "—"

        row = [f"{months}m",
               cell(s52, "total_active_words"), cell(s54, "total_active_words"),
               cell(s52, "learned_words"), cell(s54, "learned_words"),
               f"{cell(s52, 'avg_stability_days', lambda v: f'{v:.1f}')}",
               f"{cell(s54, 'avg_stability_days', lambda v: f'{v:.1f}')}",
               cell(s52, "total_ai_cost_usd", lambda v: f"${v:.4f}"),
               cell(s54, "total_ai_cost_usd", lambda v: f"${v:.4f}"),
               tier52, tier54]
        html.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    
    html.append('</table></div></div>')
    return "\n".join(html)

def build_section5_percentiles():
    html = ['<div class="card"><h2 id="s5">5. Percentile Deep-Dive (all 60 scenarios)</h2>']
    
    # Lateness
    html.append('<h3>5a. Lateness Percentiles (from review samples)</h3>')
    html.append('<div class="scroll-table"><table>')
    html.append('<tr><th>Plan</th><th>Persona</th><th>Months</th><th>Version</th>'
                '<th class="p50">p50</th><th class="p90">p90</th><th class="p95">p95</th><th class="p99">p99</th><th class="p99">max</th></tr>')
    
    for r in all_runs:
        late = r["percentiles"].get("lateness_samples", {})
        if not late:
            continue
        html.append(f'<tr>'
                    f'<td>{pill(r["plan"], PLAN_PILLS[r["plan"]])}</td>'
                    f'<td>{pill(r["persona"], PERSONA_PILLS[r["persona"]])}</td>'
                    f'<td>{r["months"]}m</td>'
                    f'<td><span class="version-badge {"v-badge-0" if "v5.2" in r["version"] else "v-badge-1"}">{r["version"].split()[1]}</span></td>'
                    f'<td class="p50">{late.get("p50", 0):.1f}</td>'
                    f'<td class="p90">{late.get("p90", 0):.1f}</td>'
                    f'<td class="p95">{late.get("p95", 0):.1f}</td>'
                    f'<td class="p99">{late.get("p99", 0):.1f}</td>'
                    f'<td class="p99">{late.get("max", 0)}</td>'
                    f'</tr>')
    html.append('</table></div>')
    
    # Due backlog
    html.append('<h3>5b. Due Backlog Percentiles (daily)</h3>')
    html.append('<div class="scroll-table"><table>')
    html.append('<tr><th>Plan</th><th>Persona</th><th>Months</th><th>Version</th>'
                '<th class="p50">p50</th><th class="p90">p90</th><th class="p95">p95</th><th class="p99">p99</th><th class="p99">max</th></tr>')
    
    for r in all_runs:
        due = r["percentiles"].get("due_backlog_daily", {})
        html.append(f'<tr>'
                    f'<td>{pill(r["plan"], PLAN_PILLS[r["plan"]])}</td>'
                    f'<td>{pill(r["persona"], PERSONA_PILLS[r["persona"]])}</td>'
                    f'<td>{r["months"]}m</td>'
                    f'<td><span class="version-badge {"v-badge-0" if "v5.2" in r["version"] else "v-badge-1"}">{r["version"].split()[1]}</span></td>'
                    f'<td class="p50">{due.get("p50", 0):.0f}</td>'
                    f'<td class="p90">{due.get("p90", 0):.0f}</td>'
                    f'<td class="p95">{due.get("p95", 0):.0f}</td>'
                    f'<td class="p99">{due.get("p99", 0):.0f}</td>'
                    f'<td class="p99">{due.get("max", 0)}</td>'
                    f'</tr>')
    html.append('</table></div>')
    
    html.append('</div>')
    return "\n".join(html)

def build_section6_worst_case():
    html = ['<div class="card"><h2 id="s6">6. Worst-Case Analysis (top 5)</h2>']
    
    metrics = [
        ("max_lateness_days", "Max Lateness", "max_lateness_days"),
        ("max_due_backlog", "Max Due Backlog", "max_due_backlog"),
        ("max_query_backlog", "Max Query Backlog", "max_query_backlog"),
        ("learned_words_per_dollar", "Lowest Learned/$", "learned_words_per_dollar", True),
    ]
    
    for idx, (key, label, sum_key, *reverse) in enumerate(metrics):
        rev = reverse[0] if reverse else False
        html.append(f'<h3>6.{idx+1} Top 5 by {label}</h3>')
        html.append('<div class="scroll-table"><table>')
        html.append('<tr><th>Rank</th><th>Plan</th><th>Persona</th><th>Months</th><th>Version</th><th>Value</th></tr>')
        
        scored = []
        for r in all_runs:
            val = r["summary"].get(sum_key, 0)
            if key == "learned_words_per_dollar" and val == 0:
                continue
            scored.append((val, r))
        
        scored.sort(key=lambda x: x[0], reverse=not rev)
        
        for i, (val, r) in enumerate(scored[:5]):
            if isinstance(val, float):
                val_str = f"{val:.2f}"
            else:
                val_str = str(val)
            html.append(f'<tr>'
                        f'<td>{i+1}</td>'
                        f'<td>{pill(r["plan"], PLAN_PILLS[r["plan"]])}</td>'
                        f'<td>{pill(r["persona"], PERSONA_PILLS[r["persona"]])}</td>'
                        f'<td>{r["months"]}m</td>'
                        f'<td><span class="version-badge {"v-badge-0" if "v5.2" in r["version"] else "v-badge-1"}">{r["version"].split()[1]}</span></td>'
                        f'<td>{val_str}</td>'
                        f'</tr>')
        html.append('</table></div>')
    
    html.append('</div>')
    return "\n".join(html)

def build_section7_version_notes():
    return '''<div class="card"><h2 id="s7">7. Version Notes</h2>
<h3>v5.2 FSRS-6 (fixed)</h3>
<ul>
<li>3-grade system: Again(1), Hard(2), Good(3)</li>
<li>15 parameters (w0-w2, w4-w15)</li>
<li>Mean reversion toward D0(Good) — adaptation for 3-button UI</li>
<li>First-exposure grading with 3 buttons</li>
<li>Desired retention: 85%</li>
</ul>

<h3>v5.4 FSRS-6 Full (4-grade)</h3>
<ul>
<li>4-grade system: Again(1), Hard(2), Good(3), Easy(4)</li>
<li>21 parameters (w0-w20)</li>
<li>Mean reversion toward D0(Easy) — true FSRS-6 §2.7</li>
<li>Easy bonus (w16) and short-term stability (w17-w19)</li>
<li>Desired retention: 90%</li>
<li>Performance threshold for Easy: 0.90</li>
</ul>
</div>'''

def build_footer():
    return f'''<div class="footer">
<p>Generated from tools/Fsrs_simulation_v5/ | Seed=42 | Plans: Free/Silver/Gold | Personas: Eager/Average | Periods: 1/3/6/12/24 months</p>
<p>Per-row coloring: green = best, red = worst within each scenario row</p>
</div></div></body></html>'''

# ---- Main ----
if __name__ == "__main__":
    html_parts = [
        build_header(),
        build_section1_scenario_matrix(),
        build_section2_summary_dashboard(),
        build_section3_longrun(),
        build_section4_learning_curves(),
        build_section5_percentiles(),
        build_section6_worst_case(),
        build_section7_version_notes(),
        build_footer(),
    ]
    
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))
    
    print(f"Enhanced report saved to {OUTPUT_PATH}")
    print(f"Size: {os.path.getsize(OUTPUT_PATH):,} bytes")