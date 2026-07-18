#!/usr/bin/env python3
"""
One-time migration script: move issues from issues/issues.json to GitHub Issues.

Usage:
  python scripts/migrate_issues.py --dry-run    # preview mapping only
  python scripts/migrate_issues.py --execute    # create GH issues and update project_status.json

Before running --execute, ensure gh is authenticated (gh auth status).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ISSUES_PATH = BASE / "issues" / "issues.json"
PROJECT_STATUS_PATH = BASE / "project_status.json"

# Color/label definitions for reproducibility
LABEL_DEFS: dict[str, str] = {
    "bug": "d73a4a",
    "feature": "a2eeef",
    "risk": "fbca04",
    "tech-debt": "7057ff",
    "research": "d4c5f9",
    "decision": "006b75",
    "priority-high": "b60205",
    "priority-medium": "fbca04",
    "priority-low": "0e8a16",
    "priority-none": "e4e669",
    "phase-1": "5319e7",
    "phase-2": "5319e7",
    "phase-3": "5319e7",
    "phase-4": "5319e7",
    "phase-5": "5319e7",
    "phase-6": "5319e7",
    "phase-7": "5319e7",
    "phase-8": "5319e7",
    "partial": "fef2c0",
    "accepted-risk": "fef2c0",
    "obsolete": "d3d3d3",
}

STATUS_LABEL_MAP = {
    "partial": "partial",
    "accepted-risk": "accepted-risk",
    "obsolete": "obsolete",
}


def gh_run(*args: str) -> str:
    """Run a gh command and return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ["gh"] + list(args),
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def issue_body(issue: dict) -> str:
    parts = [f"## Problem\n{issue['problem']}"]
    if issue.get("solution"):
        parts.append(f"## Solution\n{issue['solution']}")
    if issue.get("evidence"):
        parts.append(f"## Evidence\n{issue['evidence']}")
    deps = issue.get("depends_on", [])
    if deps:
        parts.append(f"## Dependencies\n{' '.join(f'#{d}' for d in deps)}")
    refs = issue.get("roadmap_refs", [])
    if refs:
        parts.append(f"## Roadmap refs\n{', '.join(refs)}")
    if issue.get("last_reviewed"):
        parts.append(f"## Last reviewed\n{issue['last_reviewed']}")
    note = issue.get("note", "")
    if note:
        parts.append(f"## Note\n{note}")
    return "\n\n".join(parts)


def build_labels(issue: dict) -> list[str]:
    labels = []
    # Category
    cat = issue.get("category", "")
    if cat in {"feature", "bug", "risk", "tech-debt", "research", "decision"}:
        labels.append(cat)
    # Priority
    pri = issue.get("priority", "")
    if pri in {"high", "medium", "low", "none"}:
        labels.append(f"priority-{pri}")
    # Phase
    phase = issue.get("phase", "")
    if phase and phase.startswith("phase-"):
        labels.append(phase)
    # Non-standard status
    status = issue.get("status", "")
    status_label = STATUS_LABEL_MAP.get(status)
    if status_label:
        labels.append(status_label)
    return labels


def ensure_labels() -> None:
    """Create all defined labels if they don't exist (idempotent)."""
    existing = set(gh_run("label", "list", "--json", "name", "--limit", "200").splitlines())
    # Actually gh label list --json name outputs a JSON array, let me parse it
    raw = gh_run("label", "list", "--json", "name", "--limit", "200")
    existing_names = {entry["name"] for entry in json.loads(raw)}
    for label_name, color in LABEL_DEFS.items():
        if label_name not in existing_names:
            print(f"  Creating label: {label_name}")
            gh_run("label", "create", label_name, "--color", color)
        else:
            print(f"  Label exists: {label_name}")


def create_issue(issue: dict, mapping: dict[int, int]) -> int:
    """Create a GitHub Issue from an issues.json record. Returns GH issue number."""
    labels = build_labels(issue)
    title = issue["title"]
    body_text = issue_body(issue)
    cmd = ["issue", "create", "--title", title, "--body", body_text]
    for label in labels:
        cmd += ["--label", label]
    url = gh_run(*cmd)
    # Extract issue number from URL: https://github.com/owner/repo/issues/N
    gh_number = int(url.rstrip("/").split("/")[-1])
    print(f"  Created issue #{gh_number}: {title[:60]}")
    return gh_number


def update_project_status(mapping: dict[int, int]) -> None:
    """Replace local issue IDs in project_status.json with GitHub issue numbers."""
    ps = json.loads(PROJECT_STATUS_PATH.read_text(encoding="utf-8"))
    updated_count = 0
    for phase in ps.get("phases", []):
        new_ids = []
        for local_id in phase.get("issue_ids", []):
            gh_num = mapping.get(local_id)
            if gh_num is None:
                print(f"  WARNING: local issue {local_id} not found in mapping, keeping as-is")
                new_ids.append(local_id)
            else:
                new_ids.append(gh_num)
                updated_count += 1
        phase["issue_ids"] = new_ids
    for decision in ps.get("decisions", []):
        new_ids = []
        for local_id in decision.get("issue_ids", []):
            gh_num = mapping.get(local_id)
            if gh_num is None:
                print(f"  WARNING: decision {decision['id']} references missing local issue {local_id}")
                new_ids.append(local_id)
            else:
                new_ids.append(gh_num)
                updated_count += 1
        if new_ids:
            decision["issue_ids"] = new_ids
    PROJECT_STATUS_PATH.write_text(
        json.dumps(ps, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n  Updated {updated_count} issue references in project_status.json")


MAPPING_FILE = BASE / "scripts" / "migration_mapping.json"


def load_existing_mapping() -> dict[int, int]:
    if MAPPING_FILE.exists():
        return {int(k): v for k, v in json.loads(MAPPING_FILE.read_text()).items()}
    return {}


def save_mapping(mapping: dict[int, int]) -> None:
    MAPPING_FILE.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    execute = "--execute" in sys.argv

    if not dry_run and not execute:
        print("Usage: python scripts/migrate_issues.py --dry-run | --execute")
        return 1

    issues = json.loads(ISSUES_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(issues)} issues from issues.json\n")

    existing = load_existing_mapping()
    if existing:
        print(f"Resuming with {len(existing)} already-migrated issues\n")

    if dry_run:
        print("=== DRY RUN — no issues will be created ===\n")
        print(f"{'Local ID':>8}  {'Title':<60}  {'Labels'}")
        print(f"{'-'*8}  {'-'*60}  {'-'*30}")
        for issue in sorted(issues, key=lambda i: i.get("id", 0)):
            lid = issue.get("id", "?")
            title = issue.get("title", "?")[:60]
            labels = ", ".join(build_labels(issue))
            print(f"{lid:>8}  {title:<60}  {labels}")
        print(f"\n{'='*80}")
        print(f"Total: {len(issues)} issues to migrate")
        print("Run 'python scripts/migrate_issues.py --execute' to create them")
        return 0

    # --execute mode
    print("=== Phase 1: Creating labels ===\n")
    ensure_labels()

    print(f"\n=== Phase 2: Creating {len(issues)} issues ===\n")
    mapping: dict[int, int] = {}
    mapping.update(existing)  # Load already-migrated issues
    skipped = 0
    for issue in sorted(issues, key=lambda i: i.get("id", 0)):
        lid = issue.get("id")
        if lid is None:
            print(f"  SKIP: issue with no id: {issue.get('title', '?')[:60]}")
            continue
        if lid in mapping:
            print(f"  SKIP (already migrated): {lid} → #{mapping[lid]}")
            skipped += 1
            continue
        try:
            gh_num = create_issue(issue, mapping)
            mapping[lid] = gh_num
            save_mapping(mapping)  # Persist after each issue
            # Close resolved issues
            if issue.get("status") == "resolved":
                gh_run("issue", "close", str(gh_num))
                print(f"  Closed issue #{gh_num} (resolved)")

        except subprocess.CalledProcessError as e:
            print(f"  FAILED to create issue {lid}: {e.stderr.strip()}")
            print(f"  Created {len(mapping) - len(existing)} new issues so far.")
            print(f"  Re-run to resume (mapping saved to scripts/migration_mapping.json)")
            return 1
        except Exception as e:
            print(f"  FAILED to create issue {lid}: {e}")
            print(f"  Created {len(mapping) - len(existing)} new issues so far.")
            print(f"  Re-run to resume (mapping saved to scripts/migration_mapping.json)")
            return 1

    print(f"\n=== Phase 3: Updating project_status.json ===\n")
    update_project_status(mapping)

    print(f"\n{'='*80}")
    print(f"Migration complete: {len(mapping)} issues created")
    print(f"\nMapping (local ID → GH issue #):")
    for local_id in sorted(mapping):
        print(f"  {local_id:>4} → #{mapping[local_id]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
