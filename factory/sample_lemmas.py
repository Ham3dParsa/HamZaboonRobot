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
``{lang, seed, mix, dump_size, dump_mtime, shape_v, lines_done, seen,
counters, reservoirs, rng}`` and is rewritten every ``--batch`` index lines.
A changed dump (size/mtime), seed, mix, lang, or shape rule version
(``shape_v``) aborts fail-closed (SystemExit) — never a silent resume of
stale reservoirs. On success the CSV is written atomically
(temp + os.replace) and the progress file is unlinked.

``--dry-run`` prints the plan + in-memory per-level counts and writes
NOTHING (no CSV, no checkpoint, no progress).

Lemma shape filter (locked R5, TICKET F2 — deterministic, zero LLM):
pilot ``pack/lemmas.csv`` rows are EXEMPT (curated continuity); every
index-stream row passes ``shape_verdict()`` BEFORE the reservoir. DROP
markers win over phrase-routing (so ``A. M. A.`` drops as a period
abbreviation instead of entering phrase candidates):
  - ``phrase``: contains internal whitespace (multiword ``all in all``) —
    EXCLUDED from the word pool but NOT dropped from the universe: counted
    as ``phrase_candidates`` for future F4, never written to the word CSV.
  - ``drop:affix``: starts/ends with hyphen (``-by``, ``-got-``, ``-our``).
  - ``drop:digit``: any digit (``2``, ``3-1-3``).
  - ``drop:apostrophe``: ``'`` or U+2019 (``'d``).
  - ``drop:period``: contains ``.`` (``A. M. A.``, ``e.g.``).
  - ``drop:single_char``: stripped length < 2.
  - keep-gate: alphabetic, len >= 2, containing a vowel (aeiouAEIOU).
    A-list lemmas (``April``, ``about``) stay via the vowel rule — no
    special-casing. Anything else (``co-op``, ``rhythm``) drops.
R5 amendment (TICKET F2b, owner-ordered — real words never dropped):
a ``drop:no_vowel`` alphabetic word is KEPT via the allowlist when EITHER
(a) the pack gives it a CEFR hit (same ``pack_data`` lookups as
``classify``: ``cefrj_fallback`` or the ``evp`` index — reused, never
redefined), OR (b) ``wordfreq`` zipf_frequency > ``FREQUENT_ZIPF_MIN``
(frequent everyday word like ``by``/``my``/``try``). All other drop
classes are unchanged. Allowlisted rows count as ``allowed_vowelless``.
Filtered rows count as ``skipped_shape`` and join ``seen_keys`` dedup
exactly like other skips (never reach ``classify`` or the reservoir).

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
VOWELS = frozenset("aeiouAEIOU")
# Frequent everyday word floor (F2b): a vowel-less alphabetic word with
# wordfreq zipf above this is kept (e.g. by/my/try/fly/sky). Rare junk
# (e.g. qxwzea, zipf 0) stays dropped.
FREQUENT_ZIPF_MIN = 3.0
# Lemma-shape rule version (TICKET F2b follow-up): bump whenever the
# shape/allowlist rules change. v1 = pre-F2b R5 (all drop:no_vowel rows
# dropped); v2 = F2b allowlist (pack-hit or frequent vowel-less kept).
# Stored in the checkpoint header; a mismatch aborts fail-closed so a
# resume never mixes counters/reservoirs across rule regimes.
SHAPE_VERSION = 2

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
    """Read evp/CEFR-J/zipf-cutoff data. Pack owns CEFR authority.

    The evp entries are pre-indexed ONCE here by ``lemma|pos`` prefix
    (``evp_index``) so classify() is pure dict lookups, never a scan.
    """
    evp_path = os.path.join(pack, "evp_sense.json")
    try:
        with open(evp_path, encoding="utf-8") as handle:
            evp = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"error: cannot read pack file {evp_path}: {exc}")
    cefrj_path = os.path.join(pack, "cefrj_pos.json")
    try:
        with open(cefrj_path, encoding="utf-8") as handle:
            cefrj = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"error: cannot read pack file {cefrj_path}: {exc}")
    if not isinstance(cefrj, dict) or not isinstance(cefrj.get("fallback"), dict):
        raise SystemExit(
            f"error: corrupt pack file {cefrj_path}: "
            "'fallback' must be an object mapping 'lemma|pos' to CEFR")
    manifest_path = os.path.join(pack, "pack.json")
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"error: cannot read pack manifest {manifest_path}: {exc}")
    cutoffs = ZIPF_CUTOFFS_FALLBACK
    try:
        cutoffs = list(manifest["cefr"]["zipf_cutoffs"])
    except (KeyError, TypeError, ValueError) as exc:
        print(f"WARNING: pack manifest {manifest_path} missing "
              f"cefr.zipf_cutoffs ({exc}); using default {cutoffs}",
              file=sys.stderr)
    entries = evp.get("entries", {}) if isinstance(evp, dict) else None
    if not isinstance(entries, dict):
        raise SystemExit(
            f"error: corrupt pack file {evp_path}: "
            "'entries' must be an object mapping sense keys to records")
    # Pre-index by pipe prefix so classify() is dict lookups, never a scan.
    # Semantics mirror the old startswith scan exactly:
    # - qualified query (lemma|pos): an entry matched iff its key started
    #   with "L|P|" (3+ segments); entries with fewer segments never matched.
    # - bare query (pos empty): an entry matched iff its key started with
    #   "L|" (the bare lemma alone never matched).
    evp_index: dict[str, list[str]] = {}
    evp_lemma_index: dict[str, list[str]] = {}
    for entry_key, entry in entries.items():
        level = entry.get("cefr") if isinstance(entry, dict) else None
        if level not in LEVEL_RANK:
            continue
        parts = entry_key.split("|")
        if len(parts) >= 3:
            evp_index.setdefault("|".join(parts[:2]), []).append(level)
        head, sep, _ = entry_key.partition("|")
        if sep:
            evp_lemma_index.setdefault(head, []).append(level)
    return {
        "evp_entries": entries,
        "evp_index": evp_index,
        "evp_lemma_index": evp_lemma_index,
        "cefrj_fallback": cefrj.get("fallback", {}),
        "zipf_cutoffs": cutoffs,
        "manifest_sample": manifest.get("lemmas_10k") if isinstance(manifest, dict) else None,
    }


def shape_verdict(word: object) -> str:
    """Single-source lemma shape gate (locked R5, TICKET F2).

    Returns ``"keep"``, ``"phrase"``, or ``"drop:<reason>"`` where reason
    is one of affix/digit/apostrophe/period/single_char/non_alpha/no_vowel/
    non_string.
    Pure string logic — deterministic, zero LLM. Shape DROP markers for
    affix/digit/apostrophe/period/single_char win over phrase-routing;
    ``non_alpha``/``no_vowel`` are checked after the phrase branch, so a
    spaced row with symbols counts as phrase (both excluded from the word
    CSV either way). Pilot rows never reach this function.
    """
    if not isinstance(word, str):
        return "drop:non_string"
    text = word.strip()
    if text.startswith("-") or text.endswith("-"):
        return "drop:affix"
    if any(ch.isdigit() for ch in text):
        return "drop:digit"
    if "'" in text or "\u2019" in text:
        return "drop:apostrophe"
    if "." in text:
        return "drop:period"
    if len(text) < 2:
        return "drop:single_char"
    if any(ch.isspace() for ch in text):
        return "phrase"
    if not text.isalpha():
        return "drop:non_alpha"
    if not any(ch in VOWELS for ch in text):
        return "drop:no_vowel"
    return "keep"


def pack_has_cefr_hit(word: object, pos: object, pack_data: dict) -> bool:
    """Pack-hit branch of classify() reused for the F2b allowlist.

    Returns True iff ``classify`` would hit via ``cefrj_fallback`` or the
    ``evp`` index (zipf bucket excluded). Same ``pack_data`` structures,
    same normalization — never redefined.
    """
    try:
        lemma_norm = normalize_lemma(word)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return False
    try:
        pos_norm = normalize_pos(pos)
    except (ValueError, TypeError):
        pos_norm = ""
    key = f"{lemma_norm}|{pos_norm}"
    if pack_data.get("cefrj_fallback", {}).get(key) in LEVEL_RANK:
        return True
    if pos_norm:
        levels = pack_data.get("evp_index", {}).get(key, [])
    else:
        levels = pack_data.get("evp_lemma_index", {}).get(lemma_norm, [])
    return any(level in LEVEL_RANK for level in levels)


def is_vowelless_allowlisted(word: object, pos: object,
                             pack_data: dict, lang: str) -> bool:
    """F2b allowlist: pack CEFR hit OR frequent (zipf > FREQUENT_ZIPF_MIN)."""
    if pack_has_cefr_hit(word, pos, pack_data):
        return True
    try:
        lemma_norm = normalize_lemma(word)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return False
    try:
        from wordfreq import zipf_frequency
    except ImportError:
        return False
    try:
        return bool(zipf_frequency(lemma_norm, lang) > FREQUENT_ZIPF_MIN)
    except (ValueError, TypeError):
        return False


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
    hit = pack_data.get("cefrj_fallback", {}).get(key)
    if hit in LEVEL_RANK:
        return hit
    if pos_norm:
        levels = pack_data.get("evp_index", {}).get(key, [])
    else:
        levels = pack_data.get("evp_lemma_index", {}).get(lemma_norm, [])
    best: str | None = None
    for level in levels:
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
    return zipf_to_cefr(z, pack_data.get("zipf_cutoffs", ZIPF_CUTOFFS_FALLBACK))


def _index_key(entry: dict) -> str | None:
    """lemma_key for an index line, or None when the line is unusable."""
    try:
        word, pos = entry["word"], entry.get("pos")
        return lemma_key_for(word, pos) if pos else normalize_lemma(word) + "|"
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def load_pilot(pack: str) -> tuple[list[tuple[str, str, str]], int, int]:
    """Pilot rows as (lemma_raw, pos_raw, cefr).

    Returns (rows, bad_count, dupe_count). Duplicate lemma_keys are
    deduped KEEP-FIRST (conservative: first row wins, later rows skipped
    with a warning) — never merged, never invented.
    """
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    bad = 0
    dupes = 0
    with open(os.path.join(pack, "lemmas.csv"), encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            try:
                key = lemma_key_for(record["lemma"], record["pos"])
            except (ValueError, TypeError, KeyError):
                bad += 1
                continue
            if record.get("cefr") not in LEVEL_RANK:
                bad += 1
                continue
            if key in seen:
                dupes += 1
                print(f"warning: duplicate pilot row for {key!r} "
                      f"(cefr={record.get('cefr')!r}); keeping first, skipping.")
                continue
            seen.add(key)
            rows.append((record["lemma"], record["pos"], record["cefr"]))
    rows.sort(key=lambda row: (
        LEVEL_RANK[row[2]],
        lemma_key_for(row[0], row[1]),
    ))
    return rows, bad, dupes


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
              "dump_size": dump_size, "dump_mtime": dump_mtime,
              "shape_v": SHAPE_VERSION}

    rng = random.Random(seed)
    reservoirs: dict[str, list[tuple[str, str, str, int, int]]] = {
        level: [] for level in LEVEL_ORDER}
    seen: dict[str, int] = {level: 0 for level in LEVEL_ORDER}
    seen_keys: set[str] = set()
    for lemma_raw, pos_raw, cefr in pilot:
        key = lemma_key_for(lemma_raw, pos_raw)
        seen_keys.add(key)

    lines_done = 0
    processed = 0
    counters = {"bad_index_lines": 0, "duplicates": 0,
                "skipped_no_freq": 0, "skipped_shape": 0,
                "allowed_vowelless": 0,
                "phrase_candidates": 0, "pilot_rows": len(pilot),
                "pilot_bad_rows": 0, "pilot_dupes": 0}
    if not dry_run and os.path.exists(progress):
        with open(progress, encoding="utf-8") as handle:
            saved = json.load(handle)
        for field in ("lang", "seed", "mix", "dump_size", "dump_mtime"):
            if saved.get(field) != header[field]:
                raise SystemExit(
                    f"error: stale progress {progress} "
                    f"({field} {saved.get(field)!r} != {header[field]!r}); "
                    "delete it to resample from scratch.")
        if saved.get("shape_v") != SHAPE_VERSION:
            raise SystemExit(
                f"error: stale progress {progress} "
                f"(shape_v {saved.get('shape_v')!r} != {SHAPE_VERSION!r}: "
                "shape/allowlist rules changed since checkpoint); "
                "delete it to resample from scratch.")
        lines_done = int(saved.get("lines_done", 0))
        seen = {level: int(saved["seen"][level]) for level in LEVEL_ORDER}
        if "counters" not in saved:
            raise SystemExit(
                f"error: pre-R5 checkpoint {progress} has no counters; "
                "delete it to resample from scratch.")
        saved_counters = saved.get("counters") or {}
        for key in counters:
            if key in ("pilot_rows", "pilot_bad_rows", "pilot_dupes"):
                continue  # recomputed from pilot, not accumulated
            counters[key] = int(saved_counters.get(key, 0))
        reservoirs = {level: [tuple(entry) for entry in saved["reservoirs"][level]]
                      for level in LEVEL_ORDER}
        for level_entries in reservoirs.values():
            for entry in level_entries:
                # Fail-closed: a corrupt checkpoint record (e.g. empty pos)
                # aborts loudly instead of raising a bare traceback.
                try:
                    seen_keys.add(lemma_key_for(entry[0], entry[1]))
                except (ValueError, TypeError, KeyError, IndexError) as exc:
                    raise SystemExit(
                        f"error: corrupt reservoir record {entry!r} in "
                        f"progress {progress} ({exc}); delete it to "
                        "resample from scratch.")
        rng.setstate((saved["rng"][0], tuple(saved["rng"][1]), saved["rng"][2]))
        # Rebuild dedup state: replay lines [0, lines_done) classification-only
        # (no RNG consumption, no counter changes) so skipped/duplicate/
        # reservoir-rejected keys are relearned. Cost: one partial scan.
        with open(index, encoding="utf-8") as replay_handle:
            for replay_lineno, replay_line in enumerate(replay_handle):
                if replay_lineno >= lines_done:
                    break
                if not replay_line.strip():
                    continue
                try:
                    replay_entry = json.loads(replay_line)
                except ValueError:
                    continue
                replay_key = _index_key(replay_entry)
                if replay_key is not None:
                    seen_keys.add(replay_key)

    pilot_counts = {level: sum(1 for row in pilot if row[2] == level)
                    for level in LEVEL_ORDER}
    over = {level: (pilot_counts[level], quota)
            for level, quota in zip(LEVEL_ORDER, quotas)
            if pilot_counts[level] > quota}
    if over:
        detail = ", ".join(f"{level} pilot={n} quota={q}"
                           for level, (n, q) in over.items())
        raise SystemExit(f"error: pilot exceeds mix quota ({detail}); "
                         "adjust --mix or pilot, never silently over-fill.")
    caps = {level: quota - pilot_counts[level]
            for level, quota in zip(LEVEL_ORDER, quotas)}

    with open(index, encoding="utf-8") as handle:
        truncated = False
        for lineno, line in enumerate(handle):
            if lineno < lines_done:
                continue
            if limit is not None and processed >= limit:
                truncated = True
                break
            processed += 1
            lines_done = lineno + 1
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                counters["bad_index_lines"] += 1
                continue
            key = _index_key(entry)
            if key is None:
                counters["bad_index_lines"] += 1
                continue
            try:
                word, pos = entry["word"], entry.get("pos")
                offset, length = int(entry["offset"]), int(entry["length"])
            except (ValueError, KeyError, TypeError):
                counters["bad_index_lines"] += 1
                continue
            if key in seen_keys:
                counters["duplicates"] += 1
                continue
            seen_keys.add(key)
            verdict = shape_verdict(word)
            if verdict == "phrase":
                counters["phrase_candidates"] += 1
                continue
            if verdict == "drop:no_vowel" and is_vowelless_allowlisted(
                    word, pos, pack_data, lang):
                counters["allowed_vowelless"] += 1
            elif verdict != "keep":
                counters["skipped_shape"] += 1
                continue
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
                    "counters": counters,
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
            "rng": rng, "header": header, "truncated": truncated}


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
    pilot, pilot_bad, pilot_dupes = load_pilot(args.pack)
    # Manifest seed/mix are evidence metadata; CLI stays authoritative.
    # Warn (don't abort) so a re-run with different params is still possible.
    pinned = pack_data.get("manifest_sample") or {}
    if isinstance(pinned, dict):
        # Manifest stores mix as a comma string; normalize defensively so a
        # future list-typed mix does not warn spuriously.
        manifest_mix = pinned.get("mix")
        if isinstance(manifest_mix, list):
            manifest_mix = ",".join(str(part) for part in manifest_mix)
        if "seed" in pinned and pinned["seed"] != args.seed:
            print(f"WARNING: manifest lemmas_10k.seed={pinned['seed']} "
                  f"differs from --seed={args.seed} (CLI wins)",
                  file=sys.stderr)
        if "mix" in pinned and manifest_mix != args.mix:
            print(f"WARNING: manifest lemmas_10k.mix={pinned['mix']} "
                  f"differs from --mix={args.mix} (CLI wins)",
                  file=sys.stderr)

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
        print(f"  counters: {result['counters']} pilot_bad={pilot_bad} "
              f"pilot_dupes={pilot_dupes}")
        return 0

    result = sample(args.lang, args.index, args.dump, pack_data,
                    args.mix_list, args.seed, pilot, args.limit,
                    args.batch, args.progress, dry_run=False)
    result["counters"]["pilot_bad_rows"] = pilot_bad
    result["counters"]["pilot_dupes"] = pilot_dupes
    write_csv(args.out, result["rows"])
    spot_check(args.dump, result["reservoirs"])
    if not result["truncated"]:
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
