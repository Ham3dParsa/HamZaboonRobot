"""Generate or verify CHANGELOG.md from Conventional Commits via git-cliff.

Usage:
    python scripts/generate_changelog.py          # write CHANGELOG.md
    python scripts/generate_changelog.py --check  # fail if CHANGELOG.md is stale

Requires the `git-cliff` binary on PATH (https://git-cliff.org).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"

COMMIT_PATTERN = re.compile(
    r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?:\s*(?P<description>.+)$"
)

TYPE_GROUPS = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "docs": "Documentation",
    "refactor": "Refactoring",
    "perf": "Performance",
    "test": "Testing",
    "build": "Build",
    "ci": "Continuous Integration",
    "chore": "Chores",
    "revert": "Reverts",
}


class Commit(NamedTuple):
    hash: str
    date: str
    author: str
    message: str
    scope: str
    breaking: bool
    group: str
    footer: str


def parse_conventional_commit(message: str) -> tuple[str, str, bool, str]:
    match = COMMIT_PATTERN.match(message.strip())
    if not match:
        return "", "", False, message.strip()
    scope = match.group("scope") or ""
    breaking = match.group("breaking") is not None
    description = match.group("description").strip()
    commit_type = match.group("type")
    group = TYPE_GROUPS.get(commit_type, "Other")
    return scope, description, breaking, group


def extract_footer(body: str) -> str:
    parts = body.strip().split("\n")
    footer_parts = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("Co-authored") or part.startswith("Co-Authored"):
            continue
        if part.startswith("Merge pull request") or part.startswith("Merge branch"):
            continue
        if part.startswith("PR:"):
            pr = part.split(":", 1)[1].strip()
            footer_parts.append(f"#{pr}")
        elif re.match(r"#\d+", part):
            footer_parts.append(part)
    return ", ".join(footer_parts)


def fetch_commits() -> list[Commit] | None:
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H%n%aI%n%an%n%s%n%b%n---COMMIT_END---", "--no-merges"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"error: git log failed: {exc}", file=sys.stderr)
        return None

    raw = result.stdout
    commits: list[Commit] = []

    for block in raw.split("---COMMIT_END---"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n", 4)
        if len(lines) < 4:
            continue
        commit_hash = lines[0].strip()
        commit_date = lines[1].strip()
        author = lines[2].strip()
        subject = lines[3].strip() if len(lines) > 3 else ""
        body = lines[4].strip() if len(lines) > 4 else ""

        scope, description, breaking, group = parse_conventional_commit(subject)
        footer = extract_footer(body)

        commits.append(
            Commit(
                hash=commit_hash[:7],
                date=commit_date,
                author=author,
                message=description if description else subject,
                scope=scope,
                breaking=breaking,
                group=group,
                footer=footer,
            )
        )

    return commits


def build_changelog(commits: list[Commit]) -> str:
    lines: list[str] = [
        "# Changelog",
        "",
        "All notable changes to HamZaboon. Generated automatically from",
        "[Conventional Commits](https://www.conventionalcommits.org/) by",
        "[git-cliff](https://git-cliff.org). Do not edit by hand.",
        "",
    ]

    by_date: dict[str, list[Commit]] = defaultdict(list)
    for commit in commits:
        day = commit.date[:10] if commit.date else "unknown"
        by_date[day].append(commit)

    sorted_dates = sorted(by_date.keys(), reverse=True)

    for day in sorted_dates:
        lines.append(f"### {day}")
        day_commits = by_date[day]

        by_group: dict[str, list[Commit]] = defaultdict(list)
        for commit in day_commits:
            by_group[commit.group].append(commit)

        sorted_groups = sorted(by_group.keys())

        for group in sorted_groups:
            lines.append(f"#### {group}")
            for commit in by_group[group]:
                scope_part = f" (`{commit.scope}`)" if commit.scope else ""
                breaking_mark = " 🔥" if commit.breaking else ""
                footer_part = f" ({commit.footer})" if commit.footer else ""
                lines.append(
                    f"- {commit.message}{scope_part}{breaking_mark}"
                )
                lines.append(
                    f"  — @{commit.author} [{commit.hash}](https://github.com/Ham3dParsa/HamZaboonRobot/commit/{commit.hash}){footer_part}"
                )
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("This changelog is generated automatically. Manual edits will be overwritten.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    commits = fetch_commits()
    if commits is None:
        return 1

    changelog = build_changelog(commits)

    if "--check" in sys.argv:
        if is_up_to_date(changelog):
            print("CHANGELOG.md is up to date")
            return 0
        print("CHANGELOG.md is stale; run `python scripts/generate_changelog.py`")
        return 1

    CHANGELOG.write_text(changelog, encoding="utf-8")
    print(f"Wrote {CHANGELOG.relative_to(ROOT)}")
    return 0


def is_up_to_date(changelog: str) -> bool:
    current = CHANGELOG.read_bytes() if CHANGELOG.exists() else b""
    fresh = changelog.encode("utf-8")
    if current == fresh:
        return True
    normalized = current.replace(b"\r\n", b"\n")
    return normalized == fresh


if __name__ == "__main__":
    sys.exit(main())
