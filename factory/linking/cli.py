"""Offline linker CLI — stdlib only, no model, no network, no embeddings.

Wired as ``python -m factory.linking.cli``. All commands work offline over a
TSV link table (default: the shipped ``factory/linking/table.tsv``).

- ``link``     — select shipped-table rows for a wordlist, write a subset
                TSV. (Fresh candidate scoring needs injected Kaikki/WordNet
                data via the :mod:`factory.linking.linker` core — the CLI
                never calls a model; it filters the frozen vendor table.)
- ``lookup``   — print the row(s) for one ``kaikki_sense_id``.
- ``stats``    — method distribution + flag counts for a table.
- ``validate`` — run :func:`validate_table_rows`, pretty report.
- ``arbitrate`` — run the LLM arbiter over screened senses (the ONLY
  network command here: needs ``--endpoint`` or a registered provider
  plus ``--key-var``; keys resolve from env/dotenv, never from args).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from factory.linking import build_link_index, lookup_link, validate_table_rows

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
    """One headword-or-kid per line; blanks and ``#`` comments skipped.

    Polymorphic: lines starting with ``{`` parse as JSON objects
    (screening JSONL outputs) extracting ``text`` else ``lemma``;
    every other line reads directly as the input word (plain text
    files). Unparseable ``{`` lines and objects without a text/lemma
    value are skipped (never crash, never invent).
    """
    words = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("{"):
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                val = rec.get("text") or rec.get("lemma") or ""
                val = val.strip() if isinstance(val, str) else ""
                if val:
                    words.append(val)
                continue
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


def _build_transport(args, key_value):
    """Adapter for the arbitrate run (names only in errors, never keys)."""
    from factory.linking import arbitration as _arb

    model = args.model
    timeout = args.timeout
    if args.endpoint:
        return _arb.LocalGemmaAdapter(
            endpoint=args.endpoint, timeout=timeout, model=model,
            key_value=key_value)
    try:
        from factory.precard import provider_registry as _reg
    except Exception:
        _reg = None
    row = {}
    if _reg is not None:
        try:
            names = _reg.provider_names()
        except Exception:
            names = []
        if args.provider not in list(names or []):
            raise ValueError("unknown provider: %r" % (args.provider,))
        try:
            row = _reg.resolve_provider(args.provider) or {}
        except Exception as exc:
            raise ValueError("cannot resolve provider %r (%s)"
                             % (args.provider, exc))
    protocol = str(row.get("protocol") or "")
    if protocol == "gemini_rest" or args.provider == "google":
        if not key_value:
            raise ValueError("provider %r needs --key-var (no key "
                             "resolves)" % (args.provider,))
        return _arb.GeminiRestAdapter(model=model, key_value=key_value,
                                      timeout=timeout)
    base = str(row.get("base_url") or "")
    if not base:
        raise ValueError("provider %r has no base_url (use --endpoint "
                         "for local models)" % (args.provider,))
    return _arb.LocalGemmaAdapter(endpoint=base, timeout=timeout,
                                  model=model, key_value=key_value)


def cmd_arbitrate(args):
    import shlex

    from factory.linking import arbiter_runner as _runner
    from factory.linking import sense_feed as _feed

    try:
        key_value = ""
        if args.key_var:
            from factory.precard.provider_lease_policy import (
                resolve_key as _resolve)
            key_value = _resolve(args.key_var) or ""
            if not key_value:
                print("error: no key resolves for %r (env/dotenv empty)"
                      % args.key_var, file=sys.stderr)
                return 1
        transport = _build_transport(args, key_value)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    senses = _feed.load_senses(args.in_file, args.table)
    if args.limit and args.limit > 0:
        senses = senses[:args.limit]
    if not senses:
        print("error: no senses to arbitrate in %s" % args.in_file,
              file=sys.stderr)
        return 1
    preset = {"provider": args.provider, "model": args.model,
              "label": args.preset_label or "cli"}
    records = _runner.run_arbiter(senses, preset, transport.execute_arbitration)
    try:
        with open(args.out, "w", encoding="utf-8") as handle:
            for rec in records:
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as exc:
        print("error: cannot write %s (%s)" % (args.out, exc),
              file=sys.stderr)
        return 1
    abstained = sum(1 for rec in records if rec.get("needs_review"))
    print("provider=%s model=%s senses=%d verdicts=%d abstained=%d out=%s"
          % (args.provider, args.model, len(senses), len(records),
             abstained, args.out), file=sys.stderr)
    print("replay: %s" % shlex.join(
        ["python", "-m", "factory.linking.cli", "arbitrate"]
        + sys.argv[2:]), file=sys.stderr)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m factory.linking.cli",
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

    p_arb = sub.add_parser("arbitrate",
                           help="run the LLM arbiter over screened senses")
    p_arb.add_argument("--in", dest="in_file", required=True,
                       help="screened senses JSONL (one sense per line)")
    p_arb.add_argument("--out", required=True,
                       help="output verdicts JSONL path")
    p_arb.add_argument("--table", default=str(DEFAULT_TABLE),
                       help="link table for candidates "
                       "(default: shipped table.tsv)")
    p_arb.add_argument("--provider", required=True,
                       help="provider name (registry row or local label)")
    p_arb.add_argument("--model", required=True,
                       help="exact model id (recorded; sent to the endpoint)")
    p_arb.add_argument("--preset-label", default="cli",
                       help="identity label recorded on verdicts")
    p_arb.add_argument("--endpoint", default="",
                       help="local base URL override (forces openai_compat)")
    p_arb.add_argument("--key-var", default="",
                       help="env/dotenv variable holding the key "
                       "(never pass values)")
    p_arb.add_argument("--limit", type=int, default=0,
                       help="max senses (0 = all)")
    p_arb.add_argument("--timeout", type=int, default=120,
                       help="per-request seconds")
    p_arb.set_defaults(func=cmd_arbitrate)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
