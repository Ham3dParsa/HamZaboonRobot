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


def run_cliff(*args: str) -> bytes | None:
    """Run git-cliff; return stdout, or None with a clean error message if the
    binary is missing or the run fails (so the caller exits plainly instead of
    dumping a traceback)."""
    try:
        result = subprocess.run(
            ["git-cliff", "--config", ".github/cliff.toml", *args],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError:
        print("error: 'git-cliff' not found on PATH.", file=sys.stderr)
        print("Install it (https://git-cliff.org) and retry.", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        print("error: git-cliff failed:", file=sys.stderr)
        if detail:
            print(detail, file=sys.stderr)
        return None
    return result.stdout


def main() -> int:
    if "--check" in sys.argv:
        fresh = run_cliff()
        if fresh is None:
            return 1
        current = CHANGELOG.read_bytes() if CHANGELOG.exists() else b""
        if fresh == current:
            print("CHANGELOG.md is up to date")
            return 0
        print("CHANGELOG.md is stale; run `python scripts/generate_changelog.py`")
        return 1

    if run_cliff("-o", str(CHANGELOG)) is None:
        return 1
    print(f"Wrote {CHANGELOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())