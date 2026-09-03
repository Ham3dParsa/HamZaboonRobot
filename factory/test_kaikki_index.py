"""Focused test for factory/build_kaikki_index.py (TICKET T1b).

Covers (plain asserts; run `python factory/test_kaikki_index.py`
or `python -m pytest factory/test_kaikki_index.py`):
  (a) offsets round-trip: every index entry fetch()es back the source line;
  (b) resume from mid-file gives a byte-identical index + equal lookup;
  (c) dry-run writes NOTHING (no index, no lookup, no progress);
  (d) stale dump (size/mtime change after checkpoint) aborts fail-closed;
  (e) --lang is required.

Never touches W: or the real factory progress file: everything in temp
dirs (progress path is monkeypatched per test). Hermetic: synthetic
200-line JSONL dump only.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import build_kaikki_index as B  # noqa: E402

N = 200
WORDS = ["Apple", "apple", "BANANA", "Cherry", "date", "Elderberry"]
POS = ["noun", "verb", "adj"]


def make_dump(path: Path, n: int = N) -> list[dict]:
    objs = [{"word": WORDS[i % len(WORDS)], "pos": POS[i % len(POS)],
             "extra": "x" * (i % 37)} for i in range(n)]
    with open(path, "wb") as handle:
        for obj in objs:
            handle.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    return objs


def run_build(tmp: Path, *argv: str) -> dict:
    progress = str(tmp / "index_en_progress.json")
    orig = B.progress_path
    B.progress_path = lambda lang: str(tmp / f"index_{lang}_progress.json")  # noqa: E731
    try:
        assert B.main(list(argv)) == 0
    finally:
        B.progress_path = orig
    return {"progress": Path(progress)}


def test_offsets_round_trip_via_fetch():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dump = tmp / "kaikki-en-words.jsonl"
        objs = make_dump(dump)
        out = tmp / "kaikki-en-index.jsonl"
        run_build(tmp, "--lang", "en", "--dump", str(dump), "--out", str(out))
        entries = [json.loads(line) for line in
                   out.read_text(encoding="utf-8").splitlines()]
        assert len(entries) == N, f"expected {N} entries, got {len(entries)}"
        for i, entry in enumerate(entries):
            assert set(entry) == {"word", "pos", "offset", "length"}, entry
            back = B.fetch(str(dump), entry["offset"], entry["length"])
            assert back["word"] == objs[i]["word"], (i, back)
            assert back["pos"] == objs[i]["pos"], (i, back)
        lookup = json.loads((tmp / "kaikki-en-lookup.json").read_text(encoding="utf-8"))
        assert set(lookup) == {"apple", "banana", "cherry", "date", "elderberry"}, lookup.keys()
        assert sorted(lookup["apple"]) == sorted(
            e["offset"] for e in entries if e["word"].lower() == "apple")
        assert not (tmp / "index_en_progress.json").exists(), \
            "progress must be cleaned up on success"
    print("ok: offsets round-trip via fetch(); lookup groups case-insensitively")


def test_resume_gives_identical_index():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dump = tmp / "kaikki-en-words.jsonl"
        make_dump(dump)
        full = tmp / "full.jsonl"
        run_build(tmp, "--lang", "en", "--dump", str(dump), "--out", str(full))
        full_text = full.read_bytes()
        full_lookup = (tmp / "kaikki-en-lookup.json").read_text(encoding="utf-8")

        resumed = tmp / "resumed.jsonl"
        progress = tmp / "index_en_progress.json"
        orig = B.progress_path
        B.progress_path = lambda lang: str(progress)  # noqa: E731
        try:
            # Half build with --limit, keeping the checkpoint file.
            B.build_index(str(dump), str(resumed), "en", 50, limit=N // 2,
                          progress=str(progress))
            # build_index deletes progress on success; restore a mid-file
            # checkpoint by hand: offset/line-count of the half-written index.
            half_lines = resumed.read_text(encoding="utf-8").splitlines()
            last = json.loads(half_lines[-1])
            mid_offset = last["offset"] + last["length"]
            stat = os.stat(dump)
            progress.write_text(json.dumps({
                "lang": "en", "dump_size": stat.st_size,
                "dump_mtime": stat.st_mtime, "offset": mid_offset,
                "lines_done": len(half_lines)}), encoding="utf-8")
            assert B.main(["--lang", "en", "--dump", str(dump),
                           "--out", str(resumed), "--batch", "50"]) == 0
        finally:
            B.progress_path = orig
        assert resumed.read_bytes() == full_text, "resumed index must be identical"
        assert (tmp / "kaikki-en-lookup.json").read_text(encoding="utf-8") \
            == full_lookup, "resumed lookup must be identical"
    print("ok: resume from mid-file gives byte-identical index + lookup")


def test_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dump = tmp / "kaikki-en-words.jsonl"
        make_dump(dump)
        out = tmp / "kaikki-en-index.jsonl"
        orig = B.progress_path
        B.progress_path = lambda lang: str(tmp / "index_en_progress.json")  # noqa: E731
        try:
            assert B.main(["--lang", "en", "--dump", str(dump),
                           "--out", str(out), "--dry-run"]) == 0
        finally:
            B.progress_path = orig
        leftovers = list(tmp.iterdir())
        assert leftovers == [dump], f"dry-run wrote files: {leftovers}"
    print("ok: --dry-run writes nothing")


def test_stale_dump_aborts():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dump = tmp / "kaikki-en-words.jsonl"
        make_dump(dump)
        out = tmp / "kaikki-en-index.jsonl"
        progress = tmp / "index_en_progress.json"
        B.build_index(str(dump), str(out), "en", 50, limit=10,
                      progress=str(progress))
        # build_index succeeded -> progress removed; recreate a checkpoint…
        stat = os.stat(dump)
        progress.write_text(json.dumps({
            "lang": "en", "dump_size": stat.st_size,
            "dump_mtime": stat.st_mtime, "offset": 100, "lines_done": 5}),
            encoding="utf-8")
        before = out.read_bytes()
        # …then mutate the dump (size change) and require fail-closed abort.
        with open(dump, "ab") as handle:
            handle.write(b'{"word": "zombie", "pos": "noun"}\n')
        try:
            B.build_index(str(dump), str(out), "en", 50, progress=str(progress))
        except SystemExit as exc:
            assert "changed" in str(exc), exc
        else:
            raise AssertionError("stale dump must abort fail-closed")
        assert out.read_bytes() == before, "aborted resume must not append"
    print("ok: stale dump aborts fail-closed, index untouched")


def test_lang_is_required():
    try:
        B.parse_args([])
    except SystemExit:
        print("ok: --lang is required")
    else:
        raise AssertionError("--lang must be required")


if __name__ == "__main__":
    test_offsets_round_trip_via_fetch()
    test_resume_gives_identical_index()
    test_dry_run_writes_nothing()
    test_stale_dump_aborts()
    test_lang_is_required()
    print("ALL INDEX TESTS PASSED")
