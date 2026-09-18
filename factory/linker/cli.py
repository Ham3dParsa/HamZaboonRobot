"""Offline linker CLI — stdlib only, no model, no network, no embeddings.

Wired as ``python -m factory.linker.cli``. All commands work offline over a
TSV link table (default: the shipped ``factory/linker/table.tsv``).

- ``link``     — select shipped-table rows for a wordlist, write a subset
                TSV. (Fresh candidate scoring needs injected Kaikki/WordNet
                data via the :mod:`factory.linker.linker` core — the CLI
                never calls a model; it filters the frozen vendor table.)
- ``lookup``   — print the row(s) for one ``kaikki_sense_id``.
- ``stats``    — method distribution + flag counts for a table.
- ``validate`` — run :func:`validate_table_rows`, pretty report.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from factory.linker import build_link_index, lookup_link, validate_table_rows

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_TABLE = PACKAGE_DIR / "table.tsv"

TABLE_FIELDNAMES = [
    "kaikki_sense_id",
    "wordnet_sensekey",
    "method",
    "evidence",
    "provenance",
]


def read_table(path):
    """Read a TSV link table -> ``(header, rows)`` (stdlib csv)."""
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        header = reader.fieldnames or []
        return header, list(reader)


def read_wordlist(path):
    """One headword-or-kid per line; blanks and ``#`` comments skipped."""
    words = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                words.append(line)
    return words


def word_matches_kid(word, kid):
    """Match a wordlist entry against a ``kaikki_sense_id``.

    Exact kid match, or headword match on the ``en-<lemma>-en-`` prefix
    (case-insensitive).
    """
    if word == kid:
        return True
    probe = word.lower()
    head = kid.lower()
    return head.startswith("en-" + probe + "-en-")


def cmd_link(args):
    words = read_wordlist(args.words)
    header, rows = read_table(args.table)
    if not header:
        header = list(TABLE_FIELDNAMES)
    kept = [row for row in rows
            if any(word_matches_kid(w, row.get("kaikki_sense_id", ""))
                   for w in words)]
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)
    if args.progress:
        print("words=%d scanned=%d kept=%d out=%s"
              % (len(words), len(rows), len(kept), args.out),
              file=sys.stderr)
    if not kept:
        print("warning: 0 rows matched %s" % args.words, file=sys.stderr)
    return 0


def cmd_lookup(args):
    _, rows = read_table(args.table)
    hits = lookup_link(build_link_index(rows), args.kid)
    if not hits:
        print("no rows for %s in %s" % (args.kid, args.table),
              file=sys.stderr)
        return 1
    writer = csv.DictWriter(sys.stdout, fieldnames=TABLE_FIELDNAMES,
                            delimiter="\t", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(hits)
    return 0


def cmd_stats(args):
    _, rows = read_table(args.table)
    methods = {}
    for row in rows:
        methods[row.get("method", "?")] = methods.get(
            row.get("method", "?"), 0) + 1
    linked = sum(n for m, n in methods.items() if m.startswith("LINK"))
    print("rows=%d" % len(rows))
    print("methods:")
    for method in sorted(methods):
        print("  %s: %d" % (method, methods[method]))
    print("flags:")
    print("  LINK: %d" % linked)
    for flag in ("twin-pending", "quarantined-known-false", "MANUAL-NONE"):
        print("  %s: %d" % (flag, methods.get(flag, 0)))
    return 0


def cmd_validate(args):
    _, rows = read_table(args.table)
    violations = validate_table_rows(rows)
    if not violations:
        print("OK: %d rows, 0 violations (%s)" % (len(rows), args.table))
        return 0
    print("FAIL: %d rows, %d violations (%s)"
          % (len(rows), len(violations), args.table))
    for violation in violations:
        print("  - %s" % violation)
    return 1


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m factory.linker.cli",
        description="Offline Kaikki->WordNet link-table tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_link = sub.add_parser("link", help="subset the vendor table by wordlist")
    p_link.add_argument("--words", required=True,
                        help="wordlist file (one headword or kid per line)")
    p_link.add_argument("--out", required=True, help="output TSV path")
    p_link.add_argument("--table", default=str(DEFAULT_TABLE),
                        help="input link table (default: shipped table.tsv)")
    p_link.add_argument("--progress", action="store_true",
                        help="print words/scanned/kept counts to stderr")
    p_link.set_defaults(func=cmd_link)

    p_lookup = sub.add_parser("lookup", help="print rows for one kid")
    p_lookup.add_argument("kid", help="kaikki_sense_id to look up")
    p_lookup.add_argument("--table", default=str(DEFAULT_TABLE),
                          help="link table (default: shipped table.tsv)")
    p_lookup.set_defaults(func=cmd_lookup)

    p_stats = sub.add_parser("stats", help="method distribution + flag counts")
    p_stats.add_argument("table", nargs="?", default=str(DEFAULT_TABLE),
                         help="link table (default: shipped table.tsv)")
    p_stats.set_defaults(func=cmd_stats)

    p_validate = sub.add_parser("validate",
                                help="validate_table_rows pretty report")
    p_validate.add_argument("table", nargs="?", default=str(DEFAULT_TABLE),
                            help="link table (default: shipped table.tsv)")
    p_validate.set_defaults(func=cmd_validate)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
