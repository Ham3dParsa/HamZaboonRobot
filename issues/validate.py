#!/usr/bin/env python3
"""Validate the canonical issue registry and optionally export its views.

The canonical source is ``issues.json``. The HTML app reads it, while the
Markdown report and embedded HTML fallback are optional exports.

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
HTML_PATH = BASE / "issues.html"
MARKDOWN_PATH = BASE.parent / "hamzaban-issues.md"
VALID_STATUSES = {"open", "partial", "resolved", "accepted-risk", "obsolete"}
VALID_PRIORITIES = {"high", "medium", "low", "none"}
VALID_PHASES = {"phase-1", "phase-2", "phase-3", "phase-4", "phase-6"}
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
    return normalized


def validate_issues(issues: list[dict]) -> None:
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
        if issue.get("phase") and issue.get("phase") not in VALID_PHASES:
            raise ValueError(f"issue {issue_id} has an invalid phase")
        if not isinstance(issue.get("roadmap_refs"), list):
            raise ValueError(f"issue {issue_id} roadmap_refs must be a list")


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


def render_html_data(issues: list[dict]) -> str:
    return (
        DATA_START
        + "\n        const ISSUES_DATA = "
        + json.dumps(issues, ensure_ascii=False, indent=4)
        + ";\n"
        + DATA_END
    )


def update_html(issues: list[dict]) -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(DATA_START) + r".*?" + re.escape(DATA_END),
        flags=re.DOTALL,
    )
    updated, replacements = pattern.subn(
        lambda _match: render_html_data(issues),
        html,
        count=1,
    )
    if replacements != 1:
        raise ValueError("generated issue data markers were not found in issues.html")
    HTML_PATH.write_text(updated, encoding="utf-8")


def write_json(issues: list[dict]) -> None:
    DATA_PATH.write_text(
        json.dumps(issues, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def synchronize(issues: list[dict]) -> None:
    validate_issues(issues)
    write_json(issues)
    MARKDOWN_PATH.write_text(render_markdown(issues), encoding="utf-8")
    update_html(issues)


def check() -> int:
    issues = load_data()
    validate_issues(issues)
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
