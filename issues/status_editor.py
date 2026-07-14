#!/usr/bin/env python3
"""Safely preview and apply project-status changes.

Examples:
  python issues/status_editor.py show
  python issues/status_editor.py preview changes.json
  python issues/status_editor.py apply changes.json --confirm

The change file is a reviewable patch. It edits canonical JSON sources and
regenerates only the explicitly generated views.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from issues import validate
ALLOWED_ISSUE_FIELDS = {
    "title",
    "module",
    "func",
    "problem",
    "solution",
    "priority",
    "status",
    "category",
    "phase",
    "note",
    "roadmap_refs",
    "evidence",
    "last_reviewed",
    "decision_refs",
    "depends_on",
}
ALLOWED_PHASE_FIELDS = {
    "name",
    "status",
    "objective",
    "depends_on",
    "done",
    "in_progress",
    "todo",
    "acceptance_criteria",
    "issue_ids",
    "roadmap_anchor",
}
ALLOWED_DECISION_FIELDS = {
    "status",
    "title",
    "phase",
    "roadmap_ref",
    "summary",
    "issue_ids",
}


def load_changes(path: Path) -> dict:
    changes = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(changes, dict):
        raise ValueError("change file must be a JSON object")
    for key in ("issues", "phases", "decisions"):
        value = changes.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
    return changes


def update_record(
    records: list[dict],
    identifier: object,
    updates: object,
    key: str,
    allowed_fields: set[str],
) -> None:
    if not isinstance(updates, dict):
        raise ValueError(f"{key} update must be an object")
    unknown = set(updates) - allowed_fields
    if unknown:
        raise ValueError(f"{key} update has unsupported fields: {sorted(unknown)}")
    matches = [record for record in records if record.get(key) == identifier]
    if len(matches) != 1:
        raise ValueError(f"{key} {identifier!r} was not found exactly once")
    matches[0].update(updates)


def apply_changes(
    issues: list[dict],
    project_status: dict,
    changes: dict,
) -> tuple[list[dict], dict]:
    updated_issues = [dict(issue) for issue in issues]
    updated_status = json.loads(json.dumps(project_status))
    for change in changes["issues"]:
        if not isinstance(change, dict) or "id" not in change:
            raise ValueError("each issue change needs an id")
        issue_id = change["id"]
        updates = dict(change)
        del updates["id"]
        update_record(updated_issues, issue_id, updates, "id", ALLOWED_ISSUE_FIELDS)
    for issue in updated_issues:
        issue["resolved"] = issue["status"] == "resolved"
    for change in changes["phases"]:
        if not isinstance(change, dict) or "id" not in change:
            raise ValueError("each phase change needs an id")
        phase_id = change["id"]
        updates = dict(change)
        del updates["id"]
        update_record(
            updated_status["phases"],
            phase_id,
            updates,
            "id",
            ALLOWED_PHASE_FIELDS,
        )
    for change in changes["decisions"]:
        if not isinstance(change, dict) or "id" not in change:
            raise ValueError("each decision change needs an id")
        decision_id = change["id"]
        updates = dict(change)
        del updates["id"]
        update_record(
            updated_status["decisions"],
            decision_id,
            updates,
            "id",
            ALLOWED_DECISION_FIELDS,
        )
    validate.validate_issues(updated_issues, updated_status)
    return updated_issues, updated_status


def generated_documents(issues: list[dict], project_status: dict) -> dict[Path, str]:
    current_html = validate.HTML_PATH.read_text(encoding="utf-8")
    current_roadmap = validate.ROADMAP_PATH.read_text(encoding="utf-8")
    return {
        validate.DATA_PATH: json.dumps(issues, ensure_ascii=False, indent=2) + "\n",
        validate.PROJECT_STATUS_PATH: json.dumps(project_status, ensure_ascii=False, indent=2) + "\n",
        validate.MARKDOWN_PATH: validate.render_markdown(issues),
        validate.HTML_PATH: validate.replace_generated_block(
            current_html,
            validate.PROJECT_DATA_START,
            validate.DATA_END,
            validate.render_html_data(issues, project_status),
        ),
        validate.ROADMAP_PATH: validate.replace_generated_block(
            current_roadmap,
            validate.ROADMAP_DATA_START,
            validate.ROADMAP_DATA_END,
            validate.render_roadmap_status(issues, project_status),
        ),
    }


def preview_documents(documents: dict[Path, str]) -> str:
    chunks: list[str] = []
    for path, new_content in documents.items():
        old_content = path.read_text(encoding="utf-8")
        if old_content == new_content:
            continue
        chunks.extend(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=str(path),
                tofile=str(path),
            )
        )
    return "".join(chunks) or "No changes."


def atomic_write(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def apply_documents(documents: dict[Path, str]) -> None:
    for path, content in documents.items():
        atomic_write(path, content)


def show() -> None:
    issues = validate.load_data()
    project_status = validate.load_project_status()
    validate.validate_issues(issues, project_status)
    print(f"Issues: {len(issues)}")
    for phase in project_status["phases"]:
        print(f"{phase['id']}: {phase['status']} — {phase['name']} ({len(phase['issue_ids'])} issues)")
    print("Decision locks:")
    for decision in project_status["decisions"]:
        print(f"{decision['id']}: {decision['status']} — {decision['title']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("show")
    for name in ("preview", "apply"):
        command = subparsers.add_parser(name)
        command.add_argument("changes", type=Path)
        if name == "apply":
            command.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.command == "show":
        show()
        return 0
    changes = load_changes(args.changes)
    issues = validate.load_data()
    project_status = validate.load_project_status()
    updated_issues, updated_status = apply_changes(issues, project_status, changes)
    documents = generated_documents(updated_issues, updated_status)
    if args.command == "preview":
        print(preview_documents(documents), end="")
        return 0
    if not args.confirm:
        parser.error("apply requires --confirm")
    apply_documents(documents)
    print("Applied and synchronized status changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
