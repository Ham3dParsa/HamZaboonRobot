"""PR meta labels: breaking-change, size/*, needs-tests.

Reads the PR via `gh` API (no checkout needed) and enforces the exact label
state for the three computed dimensions (add missing, remove stale).
Idempotent: re-running on an already-correct PR changes nothing.

Size bands (added+deleted lines): XS 0-9, S 10-99, M 100-499, L 500-999,
XL 1000+.
"""

import json
import re
import subprocess
import sys

REPO = "Ham3dParsa/HamZaboonRobot"
SIZE_BANDS = (
    ("size/XS", 0, 9),
    ("size/S", 10, 99),
    ("size/M", 100, 499),
    ("size/L", 500, 999),
    ("size/XL", 1000, float("inf")),
)
SIZE_LABELS = {name for name, _, _ in SIZE_BANDS}
PROD_PREFIXES = ("services/", "handlers/", "factory/", "tools/", "config/", "scripts/", "bot.py")
TEST_PREFIX = "tests/"
BREAKING_TITLE = re.compile(r"^[\w-]+(\([^)]*\))?!:")
BREAKING_BODY = re.compile(r"breaking change", re.IGNORECASE)


def gh(*args):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout.strip().lstrip("\ufeff"))


def main(pr_number: str) -> int:
    pr = gh("pr", "view", pr_number, "--repo", REPO,
            "--json", "title,body,labels,files")
    existing = {label["name"] for label in pr.get("labels", [])}
    files = pr.get("files", [])

    want = set()

    # breaking-change: `!` in conventional title or footer in body.
    title = pr.get("title", "")
    body = pr.get("body", "") or ""
    if BREAKING_TITLE.search(title) or BREAKING_BODY.search(body):
        want.add("breaking-change")

    # size/*: exactly one band from total churn.
    total = sum(f.get("additions", 0) + f.get("deletions", 0) for f in files)
    for name, low, high in SIZE_BANDS:
        if low <= total <= high:
            want.add(name)
            break

    # needs-tests: production touched, no tests touched.
    paths = [f.get("path", "") or f.get("filename", "") for f in files]
    touched_prod = any(p == "bot.py" or p.startswith(PROD_PREFIXES) for p in paths)
    touched_tests = any(p.startswith(TEST_PREFIX) for p in paths)
    if touched_prod and not touched_tests:
        want.add("needs-tests")

    managed = {"breaking-change", "needs-tests"} | SIZE_LABELS
    to_add = sorted(want - existing)
    to_remove = sorted((existing & managed) - want)

    for label in to_add:
        subprocess.run(["gh", "pr", "edit", pr_number, "--repo", REPO,
                        "--add-label", label], check=True)
    for label in to_remove:
        subprocess.run(["gh", "pr", "edit", pr_number, "--repo", REPO,
                        "--remove-label", label], check=True)

    print(f"PR #{pr_number}: total={total} added={to_add} removed={to_remove}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
