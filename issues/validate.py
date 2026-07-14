#!/usr/bin/env python3
"""Validate the canonical issue registry and project-status views.

``issues.json`` is canonical for engineering records and ``project_status.json``
is canonical for phases and decisions.

Usage:
  python issues/validate.py check
  python issues/validate.py sync
  python issues/validate.py export [out.json]
  python issues/validate.py import exported.json
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path


BASE = Path(__file__).parent
DATA_PATH = BASE / "issues.json"
PROJECT_STATUS_PATH = BASE.parent / "project_status.json"
HTML_PATH = BASE / "project_status.html"
MARKDOWN_PATH = BASE.parent / "hamzaban-issues.md"
VALID_STATUSES = {"open", "partial", "resolved", "accepted-risk", "obsolete"}
VALID_PRIORITIES = {"high", "medium", "low", "none"}
VALID_CATEGORIES = {"feature", "bug", "risk", "tech-debt", "research", "decision"}
VALID_PHASE_STATUSES = {"planned", "in-progress", "blocked", "complete", "deferred"}
VALID_DECISION_STATUSES = {"locked", "proposed", "superseded", "rejected"}
VALID_PHASES = {f"phase-{number}" for number in range(1, 9)}
PROJECT_DATA_START = "        // BEGIN GENERATED PROJECT STATUS DATA"
PROJECT_DATA_END = "        // END GENERATED PROJECT STATUS DATA"
DATA_START = "        // BEGIN GENERATED ISSUE DATA"
DATA_END = "        // END GENERATED ISSUE DATA"
LEGACY_STATUS_BY_ID = {
    1: "resolved",
    2: "partial",
    3: "partial",
    4: "resolved",
    5: "resolved",
    6: "resolved",
    7: "open",
    8: "partial",
    9: "open",
    10: "resolved",
    11: "partial",
    12: "open",
    13: "partial",
    14: "resolved",
    15: "resolved",
}


def load_data(path: Path = DATA_PATH) -> list[dict]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, list):
        raise ValueError("issue data must be a JSON array")
    return [normalize_issue(item) for item in parsed]


def load_project_status(path: Path = PROJECT_STATUS_PATH) -> dict:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("project status must be a JSON object")
    return parsed


def normalize_issue(issue: object) -> dict:
    if not isinstance(issue, dict):
        raise ValueError("each issue must be a JSON object")
    normalized = dict(issue)
    resolved = normalized.get("resolved") is True
    normalized["status"] = normalized.get(
        "status",
        LEGACY_STATUS_BY_ID.get(
            normalized.get("id"),
            "resolved" if resolved else "open",
        ),
    )
    normalized["resolved"] = normalized["status"] == "resolved"
    normalized.setdefault("note", "")
    normalized.setdefault("roadmap_refs", [])
    normalized.setdefault("evidence", "")
    normalized.setdefault("last_reviewed", "")
    normalized.setdefault("phase", "")
    normalized.setdefault("category", "tech-debt")
    normalized.setdefault("decision_refs", [])
    normalized.setdefault("depends_on", [])
    return normalized


def validate_project_status(project_status: dict, issues: list[dict]) -> None:
    if project_status.get("schema_version") != 1:
        raise ValueError("project status has an unsupported schema_version")
    model = project_status.get("status_model")
    if not isinstance(model, dict):
        raise ValueError("project status is missing status_model")
    if set(model.get("issue_categories", [])) != VALID_CATEGORIES:
        raise ValueError("project status issue categories do not match validator")
    phases = project_status.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ValueError("project status must contain phases")
    phase_ids = {phase.get("id") for phase in phases}
    if None in phase_ids or len(phase_ids) != len(phases):
        raise ValueError("project status phases must have unique ids")
    for phase in phases:
        if phase.get("status") not in VALID_PHASE_STATUSES:
            raise ValueError(f"invalid phase status: {phase.get('status')!r}")
        if not isinstance(phase.get("issue_ids"), list):
            raise ValueError(f"{phase.get('id')} issue_ids must be a list")
        for dependency in phase.get("depends_on", []):
            if dependency not in phase_ids:
                raise ValueError(f"{phase.get('id')} has an unknown dependency {dependency}")
    decisions = project_status.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("project status decisions must be a list")
    decision_ids = {decision.get("id") for decision in decisions}
    if None in decision_ids or len(decision_ids) != len(decisions):
        raise ValueError("project status decisions must have unique ids")
    issue_ids = {issue["id"] for issue in issues}
    referenced_issue_ids: list[int] = []
    for phase in phases:
        referenced_issue_ids.extend(phase["issue_ids"])
        if not set(phase["issue_ids"]).issubset(issue_ids):
            raise ValueError(f"{phase['id']} references an unknown issue")
    for decision in decisions:
        if decision.get("status") not in VALID_DECISION_STATUSES:
            raise ValueError(f"invalid decision status: {decision.get('status')!r}")
        if decision.get("phase") not in phase_ids:
            raise ValueError(f"{decision.get('id')} references an unknown phase")
        for issue_id in decision.get("issue_ids", []):
            if issue_id not in issue_ids:
                raise ValueError(f"{decision['id']} references an unknown issue")
    if len(referenced_issue_ids) != len(set(referenced_issue_ids)):
        raise ValueError("an issue is assigned to more than one project phase")
    for issue in issues:
        if issue.get("category") not in VALID_CATEGORIES:
            raise ValueError(f"issue {issue['id']} has an invalid category")
        if issue.get("phase") not in phase_ids:
            raise ValueError(f"issue {issue['id']} has an invalid phase")
        if issue["id"] not in referenced_issue_ids:
            raise ValueError(f"issue {issue['id']} is not assigned to a project phase")
        for decision_id in issue.get("decision_refs", []):
            if decision_id not in decision_ids:
                raise ValueError(f"issue {issue['id']} references an unknown decision")


def validate_issues(issues: list[dict], project_status: dict | None = None) -> None:
    ids: set[int] = set()
    for issue in issues:
        issue_id = issue.get("id")
        if not isinstance(issue_id, int) or issue_id <= 0:
            raise ValueError(f"invalid issue id: {issue_id!r}")
        if issue_id in ids:
            raise ValueError(f"duplicate issue id: {issue_id}")
        ids.add(issue_id)
        for field in ("title", "module", "problem", "solution"):
            if not isinstance(issue.get(field), str) or not issue[field].strip():
                raise ValueError(f"issue {issue_id} has an empty {field}")
        if issue.get("priority") not in VALID_PRIORITIES:
            raise ValueError(f"issue {issue_id} has an invalid priority")
        if issue.get("status") not in VALID_STATUSES:
            raise ValueError(f"issue {issue_id} has an invalid status")
        if issue.get("category") not in VALID_CATEGORIES:
            raise ValueError(f"issue {issue_id} has an invalid category")
        if not isinstance(issue.get("roadmap_refs"), list):
            raise ValueError(f"issue {issue_id} roadmap_refs must be a list")
        for field in ("decision_refs", "depends_on"):
            if not isinstance(issue.get(field), list):
                raise ValueError(f"issue {issue_id} {field} must be a list")
    if project_status is not None:
        validate_project_status(project_status, issues)


def render_markdown(issues: list[dict]) -> str:
    lines = [
        "# HamZaban — Issues Export",
        "",
        "> Generated from `issues/issues.json`; edit the JSON or use the issue app.",
        f"> Last synchronized: {date.today().isoformat()}",
        "",
    ]
    status_labels = {
        "open": "Open",
        "partial": "Partial",
        "resolved": "Resolved",
        "accepted-risk": "Accepted risk",
        "obsolete": "Obsolete",
    }
    for index, issue in enumerate(sorted(issues, key=lambda item: item["id"])):
        lines.extend(
            [
                f"# {issue['title']}",
                "",
                f"- ID: {issue['id']}",
                f"- Module: {issue['module']}",
                f"- Function: {issue.get('func') or '—'}",
                f"- Priority: {issue['priority']}",
                f"- Status: {status_labels[issue['status']]}",
                f"- Category: {issue['category']}",
                f"- Phase: {issue.get('phase') or '—'}",
                f"- Roadmap refs: {', '.join(issue['roadmap_refs']) or '—'}",
                f"- Evidence: {issue['evidence'] or '—'}",
                "",
                "## Problem",
                issue["problem"],
                "",
                "## Solution",
                issue["solution"],
            ]
        )
        if issue.get("note"):
            lines.extend(["", "## Note", issue["note"]])
        if index < len(issues) - 1:
            lines.extend(["", "---", ""])
    return "\n".join(lines) + "\n"


def render_html_data(issues: list[dict], project_status: dict) -> str:
    return (
        PROJECT_DATA_START
        + "\n        const PROJECT_STATUS_DATA = "
        + json.dumps(project_status, ensure_ascii=False, indent=4)
        + ";\n"
        + PROJECT_DATA_END
        + "\n"
        + DATA_START
        + "\n        const ISSUES_DATA = "
        + json.dumps(issues, ensure_ascii=False, indent=4)
        + ";\n"
        + DATA_END
    )


def update_html(issues: list[dict], project_status: dict) -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(PROJECT_DATA_START) + r".*?" + re.escape(DATA_END),
        flags=re.DOTALL,
    )
    updated, replacements = pattern.subn(
        lambda _match: render_html_data(issues, project_status),
        html,
        count=1,
    )
    if replacements != 1:
        raise ValueError("generated project-status data markers were not found")
    HTML_PATH.write_text(updated, encoding="utf-8")


def write_json(issues: list[dict]) -> None:
    DATA_PATH.write_text(
        json.dumps(issues, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def synchronize(issues: list[dict]) -> None:
    project_status = load_project_status()
    validate_issues(issues, project_status)
    write_json(issues)
    MARKDOWN_PATH.write_text(render_markdown(issues), encoding="utf-8")
    update_html(issues, project_status)


def check() -> int:
    issues = load_data()
    validate_issues(issues, load_project_status())
    print(f"Valid: {len(issues)} issues")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"check", "sync", "export", "import"}:
        print(__doc__.strip())
        return 1
    if argv[1] == "export":
        destination = Path(argv[2]) if len(argv) == 3 else None
        content = DATA_PATH.read_text(encoding="utf-8")
        if destination is None:
            print(content, end="")
        else:
            destination.write_text(content, encoding="utf-8")
            print(f"Exported issue data to {destination}")
        return 0
    if argv[1] == "import":
        if len(argv) != 3:
            print("Usage: python issues/validate.py import exported.json")
            return 1
        source = Path(argv[2])
        imported = load_data(source)
        validate_issues(imported)
        write_json(imported)
        print(f"Imported {len(imported)} issues into issues.json")
        return 0
    if argv[1] == "sync":
        synchronize(load_data())
        print(f"Synchronized {len(load_data())} issues")
        return 0
    return check()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
