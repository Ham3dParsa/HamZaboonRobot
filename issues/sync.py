#!/usr/bin/env python3
"""Backward-compatible wrapper for the issue validation CLI."""

from validate import main


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
