"""Screened export (Step 2): Kaikki -> screen_for_linking -> JSONL on disk.

Infrastructure only (no screening logic here): calls the current
in-memory :func:`factory.precard.prune.screen_for_linking` as-is, one
call per lemma, and writes its output under the standard data path as
line-delimited JSON:

- ``screened.jsonl`` — one line per KEPT sense:
  ``{"lemma": ..., "sense": {...kept dict verbatim...}}``.
  Every ``sense_id`` stays byte-identical to the screening output
  (pre-existing ids pass through; fallbacks are the chain's own
  ``<lemma>#<index>`` stamps — this script never invents ids).
- ``screened.drops.jsonl`` (sidecar) — one line per dropped sense:
  ``{"lemma": ..., "sense_id": ..., "reason": ...}`` verbatim.
- ``screened.manifest.json`` — words, counts, timestamps, replay command.

Input senses come from the Kaikki index+raw pair via the pipeline's own
readers (``load_kaikki_index`` / ``read_kaikki_entry``): file-order
``senses`` lists across every entry of the lemma, concatenated in
index order. Reads are seek-based (the raw file is GBs, never loaded).

Usage:
    python -m factory.linking.export_screened --words run,light,take
    python -m factory.linking.export_screened --words run --out-dir <dir>
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shlex
import sys
import uuid

DEFAULT_OUT_DIR = (
    "W:/hamzaban_data_factory/proof-linker/screened")

DEFAULT_WORDS = "run,light,take,get,make"


#: T01 — drop-reason taxonomy over the drops sidecar ``reason`` strings
#: (reuses the prune controller's existing reason classes, never
#: re-derives screening): twin/dedup/dup → twin_r3 (R3 twin dedup);
#: proper/propn/name → proper_r2 (R2 proper-noun hard drop); the rest
#: (obsolete/form-of/xref/niche/…) → other.
_TWIN_RE = re.compile(r"twin|dedup|dup", re.IGNORECASE)
_PROPER_RE = re.compile(r"proper|propn|[^a-z]name[^a-z]|^name$", re.IGNORECASE)


def classify_drop_reason(reason) -> str:
    """Sidecar ``reason`` string → ``twin_r3`` / ``proper_r2`` / ``other``."""
    text = str(reason or "")
    if _TWIN_RE.search(text):
        return "twin_r3"
    if _PROPER_RE.search(text):
        return "proper_r2"
    return "other"


def aggregate_drop_reasons(drops_path):
    """Count ``{twin_r3, proper_r2, other}`` from the drops sidecar.

    Pure aggregation over ``screened.drops.jsonl`` ``reason`` strings
    (never re-runs screening). Returns the counts dict, or None when
    the sidecar is missing/unreadable (honest absence — never zeros).
    """
    counts = {"twin_r3": 0, "proper_r2": 0, "other": 0}
    try:
        handle = open(drops_path, encoding="utf-8")
    except OSError:
        return None
    try:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            counts[classify_drop_reason(row.get("reason", ""))] += 1
    except OSError:
        return None
    finally:
        try:
            handle.close()
        except Exception:
            pass
    return counts


def registry_path(data_root=None):
    """T03 — ``<DATA_ROOT>/screened_registry.jsonl`` (W root, single source).

    ``data_root`` defaults to the factory ``data_root()`` resolver —
    no second resolver lives here.
    """
    if data_root is None:
        try:
            from factory.core.env_loader import data_root as _root

            data_root = _root()
        except Exception:
            data_root = ""
    return os.path.join(str(data_root or ""), "screened_registry.jsonl")


def append_registry(words, out_dir, created_at, run_id,
                    data_root=None):
    """T03 — append one ``{lemma, out_dir, created_at, run_id}`` line per lemma.

    Best-effort ledger (atomic ``open("a")`` per run): never raises,
    never fails a successful export.
    """
    try:
        path = registry_path(data_root)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            for lemma in words:
                handle.write(json.dumps(
                    {"lemma": lemma, "out_dir": out_dir,
                     "created_at": created_at, "run_id": run_id},
                    ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_registry_lemmas(data_root=None):
    """T03 — screened lemma set (lowercase) from the registry; missing → empty."""
    seen = set()
    try:
        with open(registry_path(data_root), encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    lemma = str(row.get("lemma") or "").strip().lower()
                    if lemma:
                        seen.add(lemma)
    except (OSError, ValueError):
        pass
    return seen


def _project_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def load_lemma_senses(lemma, index, raw_path):
    """File-order sense dicts for one lemma across its index entries."""
    from factory.precard import pipeline as _pipe

    senses = []
    for row in (index or {}).get((lemma or "").lower(), []):
        try:
            entry = _pipe.read_kaikki_entry(
                raw_path, int(row["offset"]), int(row["length"]))
        except (KeyError, TypeError, ValueError, OSError):
            continue
        for sense in (entry or {}).get("senses") or []:
            if isinstance(sense, dict):
                senses.append(sense)
    return senses


def export_words(words, out_dir, index=None, raw_path=None,
                 screen_fn=None):
    """Run the screening chain per lemma; write JSONL + sidecar + manifest.

    ``screen_fn`` defaults to the real ``screen_for_linking`` (tests
    inject a fake). Returns the manifest dict. Pure dispatch — no
    screening logic here.
    """
    from factory.precard import pipeline as _pipe
    from factory.precard.prune import screen_for_linking as _real

    if index is None:
        index = _pipe.load_kaikki_index(_pipe.DEFAULT_KAIKKI_INDEX)
    if raw_path is None:
        raw_path = _pipe.DEFAULT_KAIKKI_RAW
    if screen_fn is None:
        screen_fn = _real

    os.makedirs(out_dir, exist_ok=True)
    kept_path = os.path.join(out_dir, "screened.jsonl")
    drops_path = os.path.join(out_dir, "screened.drops.jsonl")
    manifest_path = os.path.join(out_dir, "screened.manifest.json")

    created = datetime.datetime.now(datetime.timezone.utc).isoformat()
    kept_total = 0
    dropped_total = 0
    per_lemma = []
    with open(kept_path, "w", encoding="utf-8") as kept_h, open(
            drops_path, "w", encoding="utf-8") as drops_h:
        for lemma in words:
            senses = load_lemma_senses(lemma, index, raw_path)
            link_inputs, screening_drops, _stats = screen_fn(
                senses, lemma=lemma)
            for row in link_inputs or []:
                kept_h.write(json.dumps(
                    {"lemma": lemma, "sense": row},
                    ensure_ascii=False) + "\n")
            for drop in screening_drops or []:
                drops_h.write(json.dumps(
                    {"lemma": lemma,
                     "sense_id": drop.get("sense_id", ""),
                     "reason": drop.get("reason", "")},
                    ensure_ascii=False) + "\n")
            kept_total += len(link_inputs or [])
            dropped_total += len(screening_drops or [])
            per_lemma.append({"lemma": lemma,
                              "input_senses": len(senses),
                              "kept": len(link_inputs or []),
                              "dropped": len(screening_drops or [])})
    manifest = {
        "created_at": created,
        "words": list(words),
        "kept_total": kept_total,
        "dropped_total": dropped_total,
        "per_lemma": per_lemma,
        "files": {"kept": kept_path, "drops": drops_path},
        "replay": replay_command(words, out_dir),
    }
    # T01 — aggregate drop_reasons from the just-written sidecar (never
    # re-derive); missing/unreadable sidecar → key absent (honest empty,
    # never zeros). Invariant: twin+proper+other == dropped_total.
    drop_reasons = aggregate_drop_reasons(drops_path)
    if drop_reasons is not None:
        manifest["drop_reasons"] = drop_reasons
    tmp = manifest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, manifest_path)
    # T03 — ledger append (best-effort, never fails the export).
    append_registry(list(words), out_dir, created,
                    uuid.uuid4().hex)
    return manifest


def replay_command(words, out_dir):
    """Exact re-run command string (display only)."""
    return shlex.join(["python", "-m", "factory.linking.export_screened",
                       "--words", ",".join(words),
                       "--out-dir", out_dir])


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Export screened senses (screen_for_linking as-is).")
    ap.add_argument("--words", default=DEFAULT_WORDS,
                    help="comma-separated lemmas")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                    help="output directory (standard data path by default)")
    args = ap.parse_args(argv)
    words = [w.strip() for w in (args.words or "").split(",") if w.strip()]
    if not words:
        print("no words given (--words a,b,c)", file=sys.stderr)
        return 2
    root = _project_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    manifest = export_words(words, args.out_dir)
    print("kept=%d dropped=%d out=%s" % (
        manifest["kept_total"], manifest["dropped_total"], args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
