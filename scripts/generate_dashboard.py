#!/usr/bin/env python3
"""Generate issues/project_status.html from project_status.json.

Usage:
  python scripts/generate_dashboard.py

The dashboard renders phase status, acceptance criteria, decision locks,
and links to GitHub Issues by number. It does NOT embed issue detail data
(issues live natively on GitHub Issues).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PROJECT_STATUS_PATH = BASE / "project_status.json"
HTML_PATH = BASE / "issues" / "project_status.html"

PHASE_BADGE: dict[str, str] = {
    "complete": "🟢",
    "in-progress": "🟡",
    "planned": "🔵",
    "blocked": "🔴",
    "deferred": "⚪",
}

DECISION_BADGE: dict[str, str] = {
    "locked": "🔒",
    "proposed": "💡",
    "superseded": "♻️",
    "rejected": "❌",
}

STATUS_LABEL: dict[str, str] = {
    "open": "Open",
    "partial": "Partial",
    "resolved": "Resolved",
    "accepted-risk": "Accepted",
    "obsolete": "Obsolete",
}

STATUS_COLOR: dict[str, str] = {
    "open": "#dc3545",
    "partial": "#fd7e14",
    "resolved": "#28a745",
    "accepted-risk": "#6f42c1",
    "obsolete": "#6c757d",
}


def render() -> str:
    ps = json.loads(PROJECT_STATUS_PATH.read_text(encoding="utf-8"))
    phases = ps.get("phases", [])
    decisions = ps.get("decisions", [])
    today = date.today().isoformat()

    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "<title>HamZaboon — Project Status</title>",
        "<style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 960px; margin: 0 auto; padding: 1em; }",
        "h1, h2, h3 { margin: 0.5em 0; }",
        ".phase { border: 1px solid #ddd; border-radius: 8px; padding: 1em; margin: 1em 0; }",
        ".phase h3 { margin-top: 0; display: flex; align-items: center; gap: 0.5em; }",
        ".phase .badge { font-size: 1.2em; }",
        ".section { margin: 0.5em 0; }",
        ".section-title { font-weight: 600; color: #555; font-size: 0.9em; text-transform: uppercase; letter-spacing: 0.05em; }",
        "ul { margin: 0.25em 0; padding-left: 1.5em; }",
        "li { margin: 0.15em 0; }",
        ".decision { border-left: 3px solid #0366d6; padding: 0.5em 1em; margin: 0.5em 0; background: #f6f8fa; border-radius: 0 4px 4px 0; }",
        ".decision .meta { font-size: 0.85em; color: #666; }",
        ".footer { margin-top: 2em; font-size: 0.85em; color: #888; text-align: center; }",
        "a { color: #0366d6; text-decoration: none; }",
        "a:hover { text-decoration: underline; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>HamZaboon — Project Status</h1>",
        f"<p>Generated from <code>project_status.json</code> on {today}. "
        "Issue detail lives on <a href='https://github.com/Ham3dParsa/HamZaboonRobot/issues'>GitHub Issues</a>.</p>",
        *render_phases(phases),
        render_decisions(decisions),
        '<div class="footer">',
        f"<p>Last generated: {today}</p>",
        '<p>Edit <code>project_status.json</code> and re-run <code>python scripts/generate_dashboard.py</code> to refresh.</p>',
        "</div>",
        "</body>",
        "</html>",
    ]
    return "\n".join(lines)


def render_phases(phases: list[dict]) -> list[str]:
    lines: list[str] = ["<h2>Phases</h2>"]
    for phase in phases:
        status = phase.get("status", "")
        badge = PHASE_BADGE.get(status, "⚪")
        name = phase.get("name", phase.get("id", "?"))
        objective = phase.get("objective", "")
        phase_id = phase.get("id", "")
        lines.append(f'<div class="phase" id="{phase_id}">')
        lines.append(f"<h3><span class='badge'>{badge}</span> {phase_id}: {name} <small>({status})</small></h3>")
        lines.append(f"<p><em>{objective}</em></p>")

        if deps := phase.get("depends_on", []):
            lines.append(f"<p><strong>Dependencies:</strong> {', '.join(deps)}</p>")

        for section_name, field in [("Done", "done"), ("In progress", "in_progress"), ("To-do", "todo")]:
            items = phase.get(field, [])
            if items:
                lines.append(f"<div class='section'><span class='section-title'>{section_name}</span><ul>")
                for item in items:
                    lines.append(f"<li>{item}</li>")
                lines.append("</ul></div>")

        if criteria := phase.get("acceptance_criteria", []):
            lines.append("<div class='section'><span class='section-title'>Acceptance criteria</span><ul>")
            for item in criteria:
                lines.append(f"<li>{item}</li>")
            lines.append("</ul></div>")

        if issue_ids := phase.get("issue_ids", []):
            links = []
            for issue_id in issue_ids:
                links.append(f"<a href='https://github.com/Ham3dParsa/HamZaboonRobot/issues/{issue_id}'>#{issue_id}</a>")
            lines.append(f"<p><strong>Issues:</strong> {', '.join(links)}</p>")

        lines.append("</div>")

    return lines


def render_decisions(decisions: list[dict]) -> str:
    lines: list[str] = ["<h2>Decision Locks</h2>"]
    if not decisions:
        return ""
    for decision in decisions:
        did = decision.get("id", "")
        title = decision.get("title", "")
        summary = decision.get("summary", "")
        status = decision.get("status", "")
        phase = decision.get("phase", "")
        badge = DECISION_BADGE.get(status, "❓")
        lines.append(f'<div class="decision">')
        lines.append(f"<strong>{badge} {title}</strong> ({status})")
        lines.append(f"<div class='meta'>ID: {did} | Phase: {phase}")
        if issue_ids := decision.get("issue_ids", []):
            links = []
            for issue_id in issue_ids:
                links.append(f"<a href='https://github.com/Ham3dParsa/HamZaboonRobot/issues/{issue_id}'>#{issue_id}</a>")
            lines.append(f" | Issues: {', '.join(links)}")
        lines.append("</div>")
        lines.append(f"<p>{summary}</p>")
        lines.append("</div>")
    return "\n".join(lines)


def main() -> int:
    content = render()
    HTML_PATH.write_text(content, encoding="utf-8")
    print(f"Generated {HTML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
