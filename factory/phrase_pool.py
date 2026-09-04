"""EN phrase-pool pilot collector (TICKET F4).

Single deterministic pass over ``kaikki-en-index.jsonl``: routes index rows
through the single-source ``shape_verdict()`` from ``factory/sample_lemmas.py``
(affix/digit/apostrophe/period DROP markers win over phrase-routing — never
redefined here), then keeps phrase verdicts whose tokens are 2-5 whitespace
tokens, all-alpha per token, each token len >= 2.

Frequency = index lines per normalized lemma key (lower, collapse spaces).
Dedup keep-first (first surface form wins; later lines only bump ``freq``).
Prefill = hardest (max-rank, A1<...<C2) component CEFR from the pack's
``evp_sense.json`` looked up per token (entry head match), else UNLEVELLED.
Output ``phrases.csv`` sorted by (freq desc, phrase asc), ``rank`` 1-based,
cut to ``--top-n``. ``pack.json`` gains a ``phrases`` section
``{file, top_n, shape, source}``.

``--dry-run`` prints counts and writes NOTHING (no CSV, no pack.json edit).

Usage:
    python factory/phrase_pool.py [--index ...] [--out-dir ...]
        [--top-n 500] [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sample_lemmas import shape_verdict  # noqa: E402  (single-source; never redefine)

LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
LEVEL_RANK = {level: rank for rank, level in enumerate(LEVEL_ORDER)}
UNLEVELLED = "UNLEVELLED"

DEFAULT_INDEX = "W:/hamzaban_data_factory/raw/kaikki-en-index.jsonl"
DEFAULT_OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs", "en")
DEFAULT_TOP_N = 500
PHRASES_FILE = "phrases.csv"
PHRASE_SHAPE = "2-5"
PHRASE_SOURCE = "kaikki-index"


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EN phrase-pool pilot collector.")
    parser.add_argument("--index", default=DEFAULT_INDEX,
                        help="kaikki en offset-index .jsonl path")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                        help="language pack dir (phrases.csv + pack.json live here)")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N,
                        help="pilot cap on phrases kept")
    parser.add_argument("--dry-run", action="store_true",
                        help="print counts, write nothing")
    parser.add_argument("--limit", type=int, default=None,
                        help="debug cap on index lines read")
    args = parser.parse_args(argv)
    if args.top_n is not None and args.top_n <= 0:
        parser.error("--top-n must be a positive integer")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")
    return args


def normalize_key(text: str) -> str:
    """Dedup key: lower + collapse internal whitespace."""
    return " ".join(text.strip().lower().split())


def phrase_tokens(text: str) -> list[str] | None:
    """Token gate layered on top of ``shape_verdict()`` phrase routing.

    Returns the collapsed token list when the phrase is a 2-5 token,
    all-alpha, each-token-len>=2 candidate; else None. Pure string logic.
    """
    tokens = text.strip().split()
    if not 2 <= len(tokens) <= 5:
        return None
    for token in tokens:
        if len(token) < 2 or not token.isalpha():
            return None
    return tokens


def load_token_levels(pack_dir: str) -> dict[str, str]:
    """Max-rank (hardest) CEFR per lowercased token from evp_sense.json.

    An entry contributes its ``cefr`` to the token that is its key head
    (text before the first ``|``). Only valid A1..C2 levels count.
    """
    evp_path = os.path.join(pack_dir, "evp_sense.json")
    try:
        with open(evp_path, encoding="utf-8") as handle:
            evp = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"error: cannot read pack file {evp_path}: {exc}")
    entries = evp.get("entries", {}) if isinstance(evp, dict) else None
    if not isinstance(entries, dict):
        raise SystemExit(
            f"error: corrupt pack file {evp_path}: "
            "'entries' must be an object mapping sense keys to records")
    levels: dict[str, str] = {}
    for entry_key, entry in entries.items():
        level = entry.get("cefr") if isinstance(entry, dict) else None
        if level not in LEVEL_RANK:
            continue
        head, sep, _ = entry_key.partition("|")
        if not sep:
            continue
        token = head.strip().lower()
        if not token:
            continue
        if token not in levels or LEVEL_RANK[level] > LEVEL_RANK[levels[token]]:
            levels[token] = level
    return levels


def prefill_for(tokens: list[str], token_levels: dict[str, str]) -> str:
    """Hardest component CEFR across tokens; UNLEVELLED when nothing hits."""
    best: str | None = None
    for token in tokens:
        level = token_levels.get(token.lower())
        if level is None:
            continue
        if best is None or LEVEL_RANK[level] > LEVEL_RANK[best]:
            best = level
    return best if best is not None else UNLEVELLED


def collect(index: str, token_levels: dict[str, str],
            limit: int | None = None) -> tuple[dict, dict[str, dict]]:
    """Single pass over the index. Returns (counters, phrases-by-key)."""
    counters = {"lines": 0, "bad_index_lines": 0, "phrase_lines": 0,
                "skipped_shape": 0, "skipped_token_gate": 0, "unique": 0}
    phrases: dict[str, dict] = {}
    with open(index, encoding="utf-8") as handle:
        for lineno, line in enumerate(handle):
            if limit is not None and lineno >= limit:
                break
            if not line.strip():
                continue
            counters["lines"] += 1
            try:
                entry = json.loads(line)
                word = entry["word"]
            except (ValueError, KeyError, TypeError):
                counters["bad_index_lines"] += 1
                continue
            if not isinstance(word, str):
                counters["bad_index_lines"] += 1
                continue
            if shape_verdict(word) != "phrase":
                counters["skipped_shape"] += 1
                continue
            tokens = phrase_tokens(word)
            if tokens is None:
                counters["skipped_token_gate"] += 1
                continue
            counters["phrase_lines"] += 1
            key = normalize_key(word)
            if key in phrases:
                phrases[key]["freq"] += 1
                continue
            phrases[key] = {
                "phrase": key,
                "freq": 1,
                "prefill": prefill_for(tokens, token_levels),
            }
    counters["unique"] = len(phrases)
    return counters, phrases


def rank(phrases: dict[str, dict], top_n: int) -> list[dict]:
    ordered = sorted(phrases.values(),
                     key=lambda row: (-row["freq"], row["phrase"]))
    rows = ordered[:top_n]
    for rank_no, row in enumerate(rows, start=1):
        row["rank"] = rank_no
    return rows


def write_csv(out_csv: str, rows: list[dict]) -> None:
    parent = os.path.dirname(os.path.abspath(out_csv))
    os.makedirs(parent, exist_ok=True)
    tmp = out_csv + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["phrase", "freq", "rank", "prefill"])
        for row in rows:
            writer.writerow([row["phrase"], row["freq"], row["rank"],
                             row["prefill"]])
    os.replace(tmp, out_csv)


def update_pack_manifest(pack_dir: str, top_n: int) -> None:
    manifest_path = os.path.join(pack_dir, "pack.json")
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"error: cannot read pack manifest {manifest_path}: {exc}")
    if not isinstance(manifest, dict):
        raise SystemExit(f"error: corrupt pack manifest {manifest_path}: "
                         "top-level JSON must be an object")
    manifest["phrases"] = {"file": PHRASES_FILE, "top_n": top_n,
                           "shape": PHRASE_SHAPE, "source": PHRASE_SOURCE}
    tmp = manifest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, manifest_path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    token_levels = load_token_levels(args.out_dir)
    counters, phrases = collect(args.index, token_levels, args.limit)
    rows = rank(phrases, args.top_n)
    out_csv = os.path.join(args.out_dir, PHRASES_FILE)
    if args.dry_run:
        print("dry-run plan (nothing written, no CSV/pack.json edit):")
        print(f"  index:   {args.index}")
        print(f"  out-dir: {args.out_dir} (not written)")
        print(f"  out:     {out_csv} (not written)")
        print(f"  top-n:   {args.top_n}")
        print(f"  limit:   {args.limit}")
        print(f"  counters: {counters}")
        print(f"  kept:    {len(rows)}")
        return 0
    write_csv(out_csv, rows)
    update_pack_manifest(args.out_dir, args.top_n)
    print(f"phrase-pool: unique={counters['unique']} kept={len(rows)} "
          f"out={out_csv}")
    print(f"counters: {counters}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
