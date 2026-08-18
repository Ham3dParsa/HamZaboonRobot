"""Generate or verify CHANGELOG.md from Conventional Commits via git-cliff.

Usage:
    python scripts/generate_changelog.py          # write CHANGELOG.md
    python scripts/generate_changelog.py --check  # fail if CHANGELOG.md is stale

Requires the `git-cliff` binary on PATH (https://git-cliff.org).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"


def run_cliff(*args: str) -> bytes:
    return subprocess.run(
        ["git-cliff", "--config", ".github/cliff.toml", *args],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout


def main() -> int:
    if "--check" in sys.argv:
        fresh = run_cliff()
        current = CHANGELOG.read_bytes() if CHANGELOG.exists() else b""
        if fresh == current:
            print("CHANGELOG.md is up to date")
            return 0
        print("CHANGELOG.md is stale; run `python scripts/generate_changelog.py`")
        return 1

    run_cliff("-o", str(CHANGELOG))
    print(f"Wrote {CHANGELOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())