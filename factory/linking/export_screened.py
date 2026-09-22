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
import shlex
import sys

DEFAULT_OUT_DIR = (
    "W:/hamzaban_data_factory/proof-linker/screened")

DEFAULT_WORDS = "run,light,take,get,make"


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
    tmp = manifest_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, manifest_path)
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
