"""Offset index builder for Kaikki per-language JSONL dumps (TICKET T1b).

One streaming pass over ``kaikki-<lang>-words.jsonl`` (one JSON object per
line, each with a "word" key). For every line records the exact byte
offset + length (binary mode + tell()) plus word + pos, and writes index
lines ``{"word","pos","offset","length"}`` to ``kaikki-<lang>-index.jsonl``.

Also builds a compact lemma lookup ``{lemma_key: [offsets...]}`` where
``lemma_key`` is the registry normalizer (``registry.normalize_lemma`` —
single source of truth; this file defines NO normalizer of its own, so
T2/registry consumers must import it from ``factory/registry.py`` too).

Lookup write strategy (measured choice):
- The lookup dict is accumulated in memory with a running size estimate
  (``len(key bytes) + 8 bytes per offset``). If the estimate stays under
  1 GiB — the expected case (en: ~1.5M lines, on the order of tens of MB) —
  the lookup is written ONCE at the end as a single JSON object, via a
  temp file + atomic ``os.replace``.
- If the estimate exceeds 1 GiB, the builder spills to a second JSONL file
  (``...-lookup.jsonl``, one ``{"lemma_key","offsets"}`` line per flush;
  the same key may appear on several lines) instead of ever holding the
  full map in memory. JSONL readers MUST merge offset lists per key.

Checkpoint / resume:
- Progress lives at ``factory/index_<lang>_progress.json`` as
  ``{lang, dump_size, dump_mtime, offset, lines_done}``.
- Resume seeks the dump to ``offset`` and appends to the index; the lookup
  is rebuilt from the already-written index prefix (one read, no re-scan
  of the dump).
- A changed dump (size or mtime differs) aborts fail-closed
  (SystemExit) — never a silent append of stale offsets.
- ``--dry-run`` prints the plan and writes NOTHING (no index, no lookup,
  no progress).

Usage:
    python factory/build_kaikki_index.py --lang en [--dump PATH] [--out PATH]
        [--batch N] [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from registry import normalize_lemma  # noqa: E402  (single-source lemma normalizer)

DEFAULT_DUMP_TEMPLATE = "W:/hamzaban_data_factory/raw/kaikki-{lang}-words.jsonl"
DEFAULT_OUT_TEMPLATE = "W:/hamzaban_data_factory/raw/kaikki-{lang}-index.jsonl"
LOOKUP_SUFFIX_JSON = "-lookup.json"
LOOKUP_SUFFIX_JSONL = "-lookup.jsonl"
MEMORY_BUDGET_BYTES = 1_000_000_000  # 1 GiB: single-JSON vs spill-JSONL cutoff


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def progress_path(lang: str) -> str:
    return os.path.join(script_dir(), f"index_{lang}_progress.json")


def default_dump(lang: str) -> str:
    return DEFAULT_DUMP_TEMPLATE.format(lang=lang)


def default_out(lang: str) -> str:
    return DEFAULT_OUT_TEMPLATE.format(lang=lang)


def lookup_path_for(out: str, lang: str, as_jsonl: bool = False) -> str:
    base = out[:-len(".jsonl")] if out.endswith(".jsonl") else out
    if base.endswith("-index"):
        base = base[: -len("-index")]
    if not base.endswith(lang) and f"kaikki-{lang}" not in base:
        base = os.path.join(os.path.dirname(out) or ".", f"kaikki-{lang}")
    suffix = LOOKUP_SUFFIX_JSONL if as_jsonl else LOOKUP_SUFFIX_JSON
    return base + suffix


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Kaikki dump offset index.")
    parser.add_argument("--lang", required=True, help="language key, e.g. en (no default)")
    parser.add_argument("--dump", default=None, help="source .jsonl dump path")
    parser.add_argument("--out", default=None, help="destination index .jsonl path")
    parser.add_argument("--batch", type=int, default=50000,
                        help="lines per progress checkpoint (default 50000)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None,
                        help="debug cap on raw lines read from the dump")
    args = parser.parse_args(argv)
    if args.dump is None:
        args.dump = default_dump(args.lang)
    if args.out is None:
        args.out = default_out(args.lang)
    if args.batch is not None and args.batch <= 0:
        parser.error("--batch must be a positive integer")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")
    return args


def write_progress(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload))
    os.replace(tmp, path)


def fetch(dump, offset: int, length: int) -> dict:
    """Read the exact byte range [offset, offset+length) and parse it.

    Imported by T2 later for random access. Fail-closed: asserts the
    decoded object is a dict carrying a "word" key.
    """
    with open(dump, "rb") as handle:
        handle.seek(offset)
        raw = handle.read(length)
    obj = json.loads(raw.decode("utf-8"))
    assert isinstance(obj, dict) and "word" in obj, (
        f"fetch({offset!r}, {length!r}): decoded object has no 'word' key")
    return obj


def build_index(dump: str, out: str, lang: str, batch: int,
                limit: int | None = None,
                progress: str | None = None) -> dict:
    """Stream the dump once, writing the index + lookup. Returns a summary.

    Raises SystemExit on a stale dump (size/mtime changed since checkpoint).
    """
    progress = progress or progress_path(lang)
    try:
        stat = os.stat(dump)
    except OSError as exc:
        raise SystemExit(f"error: cannot stat dump {dump}: {exc}")
    dump_size, dump_mtime = stat.st_size, stat.st_mtime

    start_offset, lines_done = 0, 0
    if os.path.exists(progress):
        with open(progress, encoding="utf-8") as handle:
            saved = json.load(handle)
        if saved.get("lang") != lang:
            raise SystemExit("error: progress file is for "
                             f"lang={saved.get('lang')!r}, not {lang!r}; refusing resume.")
        if saved.get("dump_size") != dump_size or saved.get("dump_mtime") != dump_mtime:
            raise SystemExit(
                "error: dump changed since checkpoint "
                f"(size {saved.get('dump_size')}->{dump_size}, "
                f"mtime {saved.get('dump_mtime')}->{dump_mtime}); "
                "delete the progress/index files to rebuild from scratch.")
        start_offset = int(saved.get("offset", 0))
        lines_done = int(saved.get("lines_done", 0))
        if start_offset > 0 and not os.path.exists(out):
            raise SystemExit("error: progress says resume at offset "
                             f"{start_offset} but index {out} is missing; "
                             "delete the progress file to rebuild from scratch.")

    lookup: dict[str, list[int]] = {}
    mem_estimate = 0
    spilled = False
    spill_path = lookup_path_for(out, lang, as_jsonl=True)
    spill_handle = None
    mode = "ab" if start_offset > 0 else "wb"

    if start_offset > 0:
        # Rebuild the lookup from the already-written index prefix so the
        # resumed pass only scans the dump tail, not the whole dump.
        with open(out, "rb") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                entry = json.loads(line)
                try:
                    key = normalize_lemma(entry["word"])
                except (ValueError, KeyError, TypeError):
                    continue
                off = int(entry["offset"])
                if key in lookup:
                    lookup[key].append(off)
                    mem_estimate += 8
                else:
                    lookup[key] = [off]
                    mem_estimate += len(key.encode("utf-8")) + 8

    parent = os.path.dirname(os.path.abspath(out))
    os.makedirs(parent, exist_ok=True)
    t0 = time.time()
    lines_read = 0
    skipped = 0
    out_handle = open(out, mode)
    try:
        with open(dump, "rb") as handle:
            handle.seek(start_offset)
            while True:
                if limit is not None and lines_read >= limit:
                    break
                # tell() after a whole-line readline minus its byte length
                # is the exact start offset of that line.
                raw = handle.readline()
                if not raw:
                    break
                lines_read += 1
                offset = handle.tell() - len(raw)
                if not raw.strip():
                    continue
                try:
                    obj = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    skipped += 1
                    continue
                word = obj.get("word") if isinstance(obj, dict) else None
                try:
                    key = normalize_lemma(word)
                except (ValueError, TypeError):
                    skipped += 1
                    continue
                pos = obj.get("pos")
                entry = {"word": word, "pos": pos,
                         "offset": offset, "length": len(raw)}
                out_handle.write((json.dumps(entry, ensure_ascii=False) + "\n"
                                  ).encode("utf-8"))
                lines_done += 1
                if key in lookup:
                    lookup[key].append(offset)
                    mem_estimate += 8
                else:
                    lookup[key] = [offset]
                    mem_estimate += len(key.encode("utf-8")) + 8
                if mem_estimate > MEMORY_BUDGET_BYTES and spill_handle is None:
                    # Over budget: spill grouped-so-far lines to JSONL and
                    # keep only the tail in memory. Readers merge per key.
                    spill_handle = open(spill_path, "wb")
                    spilled = True
                if spill_handle is not None and len(lookup) > 100000:
                    for k, offs in lookup.items():
                        spill_handle.write((json.dumps(
                            {"lemma_key": k, "offsets": offs},
                            ensure_ascii=False) + "\n").encode("utf-8"))
                    lookup.clear()
                    mem_estimate = 0
                if lines_done % batch == 0:
                    out_handle.flush()
                    write_progress(progress, {
                        "lang": lang, "dump_size": dump_size,
                        "dump_mtime": dump_mtime,
                        "offset": handle.tell(), "lines_done": lines_done})
            final_offset = handle.tell()
        out_handle.flush()
    finally:
        out_handle.close()

    # Lookup write (single JSON when under budget, else grouped-JSONL tail
    # appended to the spill file). Atomic rename in both cases.
    lookup_path = lookup_path_for(out, lang, as_jsonl=spilled)
    if spilled:
        assert spill_handle is not None
        for k, offs in lookup.items():
            spill_handle.write((json.dumps({"lemma_key": k, "offsets": offs},
                                           ensure_ascii=False) + "\n").encode("utf-8"))
        spill_handle.close()
        os.replace(spill_path, lookup_path)
    else:
        tmp = lookup_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(lookup, ensure_ascii=False))
        os.replace(tmp, lookup_path)
    write_progress(progress, {"lang": lang, "dump_size": dump_size,
                              "dump_mtime": dump_mtime,
                              "offset": final_offset, "lines_done": lines_done})
    try:
        os.unlink(progress)
    except OSError:
        pass
    elapsed = time.time() - t0
    print(f"indexed: lines_read={lines_read} entries={lines_done} "
          f"skipped={skipped} lemmas={len(lookup) if not spilled else 'spilled'} "
          f"lookup={'jsonl-spill' if spilled else 'single-json'} "
          f"elapsed={elapsed:.1f}s")
    print(f"out: {out}")
    print(f"lookup: {lookup_path}")
    return {"lines_read": lines_read, "entries": lines_done,
            "skipped": skipped, "elapsed": elapsed, "out": out,
            "lookup": lookup_path, "spilled": spilled}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    progress = progress_path(args.lang)
    lookup = lookup_path_for(args.out, args.lang)

    if args.dry_run:
        plan = ["dry-run plan (nothing written, no dump scan):",
                f"  lang:     {args.lang}",
                f"  dump:     {args.dump}",
                f"  out:      {args.out} (index JSONL, append on resume)",
                f"  lookup:   {lookup} (single JSON; JSONL spill iff >1GiB est.)",
                f"  batch:    {args.batch} lines per checkpoint",
                f"  limit:    {args.limit}",
                f"  progress: {progress}"]
        try:
            stat = os.stat(args.dump)
            plan.append(f"  dump_stat: size={stat.st_size} mtime={stat.st_mtime}")
            if os.path.exists(progress):
                with open(progress, encoding="utf-8") as handle:
                    saved = json.load(handle)
                plan.append(f"  resume:   yes -> offset={saved.get('offset')} "
                            f"lines_done={saved.get('lines_done')}")
            else:
                plan.append("  resume:   no (fresh build)")
        except OSError as exc:
            plan.append(f"  dump_stat: unavailable ({exc})")
        except ValueError as exc:
            plan.append(f"  resume:   progress unreadable ({exc})")
        print("\n".join(plan))
        return 0

    build_index(args.dump, args.out, args.lang, args.batch,
                limit=args.limit, progress=progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
