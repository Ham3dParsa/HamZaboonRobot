"""Compile all production .py files to check for syntax errors."""
import py_compile
import subprocess
import sys


def main():
    files = subprocess.check_output(
        ["git", "ls-files", "*.py"], text=True
    ).splitlines()
    failures = 0
    for f in files:
        if "/tests/" in f or f.startswith("tests/") or "/." in f:
            continue
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as e:
            print(f"ERROR: {f}: {e}", file=sys.stderr)
            failures += 1
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
