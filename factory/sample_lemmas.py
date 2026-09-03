"""Seeded checkpointed lemma sampler for Kaikki per-language dumps (TICKET T2).

Streams ``kaikki-<lang>-index.jsonl`` ONCE (never loads the dump), classifies
each indexed word to a CEFR level from the language pack, and fills per-level
reservoirs up to ``--mix`` quotas. The pilot ``pack/lemmas.csv`` rows are
pinned first (keeping their pilot CEFR); reservoirs top up the remainder.

CEFR fallback rule (locked, documented here — never invent a level):
  1. pack hit -> keep: ``cefrj_pos.json`` ``fallback`` entry for
     ``<norm-lemma>|<norm-pos>`` wins; else the easiest (lowest) level among
     ``evp_sense.json`` ``entries`` whose key starts with
     ``<norm-lemma>|<norm-pos>|``.
  2. miss -> ``wordfreq`` zipf bucket via ``pack.json`` ``cefr.zipf_cutoffs``
     (locked default ``[5.2, 4.6, 4.0, 3.5, 3.0]`` -> A1..C1, else C2).
  3. still-miss (zipf <= 0, i.e. wordfreq has no frequency for the lemma)
     -> SKIP with a counter. No default level is ever assigned.

Determinism: one ``random.Random(seed)``; reservoir draws are consumed in
index file order; pilot pinning is sorted by (level, lemma_key); the output
CSV is sorted by (level_order, lemma_key).

Checkpoints: progress lives at ``factory/sample_<lang>_progress.json`` as
``{lang, seed, mix, dump_size, dump_mtime, lines_done, seen, reservoirs,
rng_state}`` and is rewritten every ``--batch`` index lines. A changed dump
(size/mtime), seed, mix, or lang aborts fail-closed (SystemExit) — never a
silent resume of stale reservoirs. On success the CSV is written atomically
(temp + os.replace) and the progress file is unlinked.

``--dry-run`` prints the plan + in-memory per-level counts and writes
NOTHING (no CSV, no checkpoint, no progress).

Lemma normalization and random-access ``fetch`` are REUSED from
``factory/registry.py`` (``normalize_lemma``) and
``factory/build_kaikki_index.py`` (``fetch``) — this file defines neither.
``fetch`` is used only for a bounded post-pass spot-check (first 5
reservoir-picked entries) that warns on offset/word mismatch.

Usage:
    python factory/sample_lemmas.py --lang en [--mix 364,485,667,727,454,303]
        [--seed 7] [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from registry import lemma_key_for, normalize_lemma, normalize_pos  # noqa: E402
from build_kaikki_index import fetch  # noqa: E402  (reuse; never redefine)

LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
LEVEL_RANK = {level: rank for rank, level in enumerate(LEVEL_ORDER)}
DEFAULT_MIX = "364,485,667,727,454,303"  # locked R2: scaled pilot x6 = 3000
DEFAULT_SEED = 7
DEFAULT_BATCH = 50000
ZIPF_CUTOFFS_FALLBACK = [5.2, 4.6, 4.0, 3.5, 3.0]
SPOT_CHECK_N = 5

DEFAULT_DUMP_TEMPLATE = "W:/hamzaban_data_factory/raw/kaikki-{lang}-words.jsonl"
DEFAULT_INDEX_TEMPLATE = "W:/hamzaban_data_factory/raw/kaikki-{lang}-index.jsonl"
DEFAULT_LOOKUP_TEMPLATE = "W:/hamzaban_data_factory/raw/kaikki-{lang}-lookup.json"


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def progress_path(lang: str) -> str:
    return os.path.join(script_dir(), f"sample_{lang}_progress.json")


def default_pack(lang: str) -> str:
    return os.path.join(script_dir(), "packs", lang)


def default_out(lang: str) -> str:
    return os.path.join(default_pack(lang), "lemmas_10k.csv")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seeded lemma sampler.")
    parser.add_argument("--lang", required=True, help="language key, e.g. en (no default)")
    parser.add_argument("--dump", default=None, help="source .jsonl dump path")
    parser.add_argument("--index", default=None, help="offset index .jsonl path")
    parser.add_argument("--lookup", default=None, help="lemma lookup .json path")
    parser.add_argument("--pack", default=None, help="language pack dir")
    parser.add_argument("--mix", default=DEFAULT_MIX,
                        help="A1..C2 quotas, comma-separated (default locked R2 mix)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", default=None, help="destination CSV path")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH,
                        help="index lines per progress checkpoint")
    parser.add_argument("--progress", default=None, help="progress file override")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None,
                        help="debug cap on index lines read")
    args = parser.parse_args(argv)
    if args.dump is None:
        args.dump = DEFAULT_DUMP_TEMPLATE.format(lang=args.lang)
    if args.index is None:
        args.index = DEFAULT_INDEX_TEMPLATE.format(lang=args.lang)
    if args.lookup is None:
        args.lookup = DEFAULT_LOOKUP_TEMPLATE.format(lang=args.lang)
    if args.pack is None:
        args.pack = default_pack(args.lang)
    if args.out is None:
        args.out = default_out(args.lang)
    if args.progress is None:
        args.progress = progress_path(args.lang)
    try:
        mix = [int(part) for part in args.mix.split(",")]
    except ValueError:
        parser.error("--mix must be six comma-separated integers")
    if len(mix) != 6 or any(quota < 0 for quota in mix):
        parser.error("--mix must be six non-negative integers (A1..C2)")
    args.mix_list = mix
    if args.batch is not None and args.batch <= 0:
        parser.error("--batch must be a positive integer")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")
    pilot_csv = os.path.join(args.pack, "lemmas.csv")
    if os.path.abspath(args.out) == os.path.abspath(pilot_csv):
        parser.error("--out must not overwrite the pilot pack lemmas.csv")
    return args


def write_progress(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
    os.replace(tmp, path)


def load_pack(pack: str) -> dict:
    """Read evp/CEFR-J/zipf-cutoff data. Pack owns CEFR authority."""
    with open(os.path.join(pack, "evp_sense.json"), encoding="utf-8") as handle:
        evp = json.load(handle)
    with open(os.path.join(pack, "cefrj_pos.json"), encoding="utf-8") as handle:
        cefrj = json.load(handle)
    cutoffs = ZIPF_CUTOFFS_FALLBACK
    try:
        with open(os.path.join(pack, "pack.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        cutoffs = list(manifest["cefr"]["zipf_cutoffs"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {
        "evp_entries": evp.get("entries", {}),
        "cefrj_fallback": cefrj.get("fallback", {}),
        "zipf_cutoffs": cutoffs,
    }


def zipf_to_cefr(z: float, cutoffs: list[float]) -> str:
    for cut, level in zip(cutoffs, ["A1", "A2", "B1", "B2", "C1"]):
        if z >= cut:
            return level
    return "C2"


def classify(word: str, pos: object, pack_data: dict, lang: str) -> str | None:
    """Pack hit -> zipf bucket -> None (skip, never invent)."""
    try:
        lemma_norm = normalize_lemma(word)
    except (ValueError, TypeError):
        return None
    try:
        pos_norm = normalize_pos(pos)
    except (ValueError, TypeError):
        pos_norm = ""
    key = f"{lemma_norm}|{pos_norm}"
    hit = pack_data["cefrj_fallback"].get(key)
    if hit in LEVEL_RANK:
        return hit
    prefix = f"{lemma_norm}|{pos_norm}|" if pos_norm else f"{lemma_norm}|"
    best: str | None = None
    for entry_key, entry in pack_data["evp_entries"].items():
        if not entry_key.startswith(prefix):
            continue
        level = entry.get("cefr") if isinstance(entry, dict) else None
        if level not in LEVEL_RANK:
            continue
        if best is None or LEVEL_RANK[level] < LEVEL_RANK[best]:
            best = level
    if best is not None:
        return best
    try:
        from wordfreq import zipf_frequency
    except ImportError:
        return None
    z = zipf_frequency(lemma_norm, lang)
    if z <= 0:
        return None
    return zipf_to_cefr(z, pack_data["zipf_cutoffs"])


def load_pilot(pack: str) -> tuple[list[tuple[str, str, str]], int]:
    """Pilot rows as (lemma_raw, pos_raw, cefr); returns rows + bad-row count."""
    rows: list[tuple[str, str, str]] = []
    bad = 0
    with open(os.path.join(pack, "lemmas.csv"), encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            try:
                lemma_key_for(record["lemma"], record["pos"])
            except (ValueError, TypeError, KeyError):
                bad += 1
                continue
            if record.get("cefr") not in LEVEL_RANK:
                bad += 1
                continue
            rows.append((record["lemma"], record["pos"], record["cefr"]))
    rows.sort(key=lambda row: (
        LEVEL_RANK[row[2]],
        lemma_key_for(row[0], row[1]),
    ))
    return rows, bad


def dump_stat(dump: str) -> tuple[int | None, float | None]:
    try:
        stat = os.stat(dump)
    except OSError:
        return None, None
    return stat.st_size, stat.st_mtime


def sample(
    lang: str,
    index: str,
    dump: str,
    pack_data: dict,
    quotas: list[int],
    seed: int,
    pilot: list[tuple[str, str, str]],
    limit: int | None,
    batch: int,
    progress: str,
    dry_run: bool,
) -> dict:
    dump_size, dump_mtime = dump_stat(dump)
    mix = ",".join(str(quota) for quota in quotas)
    header = {"lang": lang, "seed": seed, "mix": mix,
              "dump_size": dump_size, "dump_mtime": dump_mtime}

    rng = random.Random(seed)
    reservoirs: dict[str, list[tuple[str, str, str, int, int]]] = {
        level: [] for level in LEVEL_ORDER}
    seen: dict[str, int] = {level: 0 for level in LEVEL_ORDER}
    seen_keys: set[str] = set()
    pilot_keys: set[str] = set()
    for lemma_raw, pos_raw, cefr in pilot:
        key = lemma_key_for(lemma_raw, pos_raw)
        seen_keys.add(key)
        pilot_keys.add(key)

    lines_done = 0
    processed = 0
    counters = {"bad_index_lines": 0, "duplicates": 0,
                "skipped_no_freq": 0, "pilot_rows": len(pilot),
                "pilot_bad_rows": 0}
    if not dry_run and os.path.exists(progress):
        with open(progress, encoding="utf-8") as handle:
            saved = json.load(handle)
        for field in ("lang", "seed", "mix", "dump_size", "dump_mtime"):
            if saved.get(field) != header[field]:
                raise SystemExit(
                    f"error: stale progress {progress} "
                    f"({field} {saved.get(field)!r} != {header[field]!r}); "
                    "delete it to resample from scratch.")
        lines_done = int(saved.get("lines_done", 0))
        seen = {level: int(saved["seen"][level]) for level in LEVEL_ORDER}
        reservoirs = {level: [tuple(entry) for entry in saved["reservoirs"][level]]
                      for level in LEVEL_ORDER}
        for level_entries in reservoirs.values():
            for entry in level_entries:
                seen_keys.add(lemma_key_for(entry[0], entry[1]))
        rng.setstate((saved["rng"][0], tuple(saved["rng"][1]), saved["rng"][2]))

    caps = {level: max(0, quota - sum(1 for row in pilot if row[2] == level))
            for level, quota in zip(LEVEL_ORDER, quotas)}

    with open(index, encoding="utf-8") as handle:
        for lineno, line in enumerate(handle):
            if lineno < lines_done:
                continue
            if limit is not None and processed >= limit:
                break
            processed += 1
            lines_done = lineno + 1
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                word, pos = entry["word"], entry.get("pos")
                offset, length = int(entry["offset"]), int(entry["length"])
            except (ValueError, KeyError, TypeError):
                counters["bad_index_lines"] += 1
                continue
            try:
                key = lemma_key_for(word, pos) if pos else \
                    normalize_lemma(word) + "|"
            except (ValueError, TypeError):
                counters["bad_index_lines"] += 1
                continue
            if key in seen_keys:
                counters["duplicates"] += 1
                continue
            seen_keys.add(key)
            level = classify(word, pos, pack_data, lang)
            if level is None:
                counters["skipped_no_freq"] += 1
                continue
            seen[level] += 1
            cap = caps[level]
            if cap == 0:
                continue
            record = (word, pos if isinstance(pos, str) else "", level,
                      offset, length)
            if len(reservoirs[level]) < cap:
                reservoirs[level].append(record)
            else:
                pick = rng.randrange(seen[level])
                if pick < cap:
                    reservoirs[level][pick] = record
            if not dry_run and (processed % batch == 0):
                write_progress(progress, {
                    **header, "lines_done": lines_done, "seen": seen,
                    "reservoirs": {level: [list(e) for e in reservoirs[level]]
                                   for level in LEVEL_ORDER},
                    "rng": [rng.getstate()[0],
                            list(rng.getstate()[1]),
                            rng.getstate()[2]],
                })

    rows = list(pilot) + [(lemma, pos, level)
                          for level in LEVEL_ORDER
                          for lemma, pos, level, _, _ in reservoirs[level]]
    rows.sort(key=lambda row: (
        LEVEL_RANK[row[2]],
        lemma_key_for(row[0], row[1]) if row[1] else
        normalize_lemma(row[0]) + "|",
    ))
    picked = [(lemma, pos, level, offset, length)
              for level in LEVEL_ORDER
              for lemma, pos, level, offset, length in reservoirs[level]]
    return {"rows": rows, "seen": seen, "reservoirs": picked,
            "lines_done": lines_done, "counters": counters,
            "rng": rng, "header": header}


def write_csv(out: str, rows: list[tuple[str, str, str]]) -> None:
    parent = os.path.dirname(os.path.abspath(out))
    os.makedirs(parent, exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["lemma", "pos", "cefr"])
        writer.writerows(rows)
    os.replace(tmp, out)


def spot_check(dump: str, picked: list[tuple], count: int = SPOT_CHECK_N) -> int:
    """Bounded offset-integrity check via reused fetch(); warns, never aborts."""
    mismatches = 0
    try:
        handle = open(dump, "rb")
        handle.close()
    except OSError as exc:
        print(f"spot-check skipped (dump unreadable: {exc})")
        return 0
    for lemma, pos, _level, offset, length in picked[:count]:
        try:
            obj = fetch(dump, offset, length)
            if normalize_lemma(obj.get("word")) != normalize_lemma(lemma):
                mismatches += 1
                print(f"spot-check mismatch at offset {offset}: "
                      f"index={lemma!r} dump={obj.get('word')!r}")
        except (OSError, ValueError, AssertionError) as exc:
            mismatches += 1
            print(f"spot-check error at offset {offset}: {exc}")
    print(f"spot-check: {min(count, len(picked))} entries, "
          f"{mismatches} mismatches")
    return mismatches


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pack_data = load_pack(args.pack)
    pilot, pilot_bad = load_pilot(args.pack)

    if args.dry_run:
        print("dry-run plan (nothing written, no CSV/checkpoint/progress):")
        print(f"  lang:     {args.lang}")
        print(f"  dump:     {args.dump}")
        print(f"  index:    {args.index}")
        print(f"  lookup:   {args.lookup} (accepted, not loaded)")
        print(f"  pack:     {args.pack}")
        print(f"  out:      {args.out}")
        print(f"  seed:     {args.seed}")
        print(f"  mix:      {args.mix}")
        print(f"  limit:    {args.limit}")
        print(f"  progress: {args.progress} (not written)")
        result = sample(args.lang, args.index, args.dump, pack_data,
                        args.mix_list, args.seed, pilot, args.limit,
                        args.batch, args.progress, dry_run=True)
        for level in LEVEL_ORDER:
            quota = args.mix_list[LEVEL_ORDER.index(level)]
            pinned = sum(1 for row in pilot if row[2] == level)
            picked = sum(1 for row in result["reservoirs"] if row[2] == level)
            print(f"  {level}: quota={quota} pinned={pinned} "
                  f"candidates_seen={result['seen'][level]} picked={picked}")
        print(f"  counters: {result['counters']} pilot_bad={pilot_bad}")
        return 0

    result = sample(args.lang, args.index, args.dump, pack_data,
                    args.mix_list, args.seed, pilot, args.limit,
                    args.batch, args.progress, dry_run=False)
    result["counters"]["pilot_bad_rows"] = pilot_bad
    write_csv(args.out, result["rows"])
    spot_check(args.dump, result["reservoirs"])
    try:
        os.unlink(args.progress)
    except OSError:
        pass
    counts = {level: sum(1 for row in result["rows"] if row[2] == level)
              for level in LEVEL_ORDER}
    print(f"sampled: rows={len(result['rows'])} counts={counts} out={args.out}")
    print(f"counters: {result['counters']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
