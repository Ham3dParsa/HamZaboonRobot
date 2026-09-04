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

import pytest

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


def test_fetch_rejects_wordless_object():
    # fetch() must raise ValueError (fail-closed, catchable) — never a bare
    # assert — when the byte range decodes to a non-dict or a dict with no
    # "word" key.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dump = tmp / "kaikki-en-words.jsonl"
        lines = ['{"pos": "noun"}\n', '[1, 2]\n', '{"word": "ok", "pos": "noun"}\n']
        offsets = []
        with open(dump, "wb") as handle:
            for line in lines:
                raw = line.encode("utf-8")
                offsets.append((handle.tell(), len(raw)))
                handle.write(raw)
        for offset, length in offsets[:2]:
            try:
                B.fetch(str(dump), offset, length)
            except ValueError as exc:
                assert "word" in str(exc), exc
            else:
                raise AssertionError("fetch must reject a wordless object")
        assert B.fetch(str(dump), *offsets[2])["word"] == "ok"
    print("ok: fetch() raises ValueError on wordless objects")


def test_spill_handle_closed_on_exception(tmp_path, monkeypatch):
    # With the spill budget forced to zero, a mid-pass failure must still
    # close the spill handle (no leaked fd), via the finally path.
    tmp = Path(tmp_path)
    dump = tmp / "kaikki-en-words.jsonl"
    make_dump(dump, n=20)
    out = tmp / "kaikki-en-index.jsonl"
    progress = tmp / "index_en_progress.json"
    spill = B.lookup_path_for(str(out), "en", as_jsonl=True)
    monkeypatch.setattr(B, "MEMORY_BUDGET_BYTES", 0)
    opened = []
    real_open = open

    def tracking_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        try:
            is_spill = os.fspath(path) == spill
        except (TypeError, ValueError):
            is_spill = False
        mode = args[0] if args else kwargs.get("mode", "r")
        if is_spill and "b" in str(mode) and ("w" in str(mode) or "a" in str(mode)):
            opened.append(handle)
        return handle

    monkeypatch.setattr("builtins.open", tracking_open)
    calls = {"n": 0}
    real_dumps = json.dumps

    def flaky_dumps(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 5:
            raise RuntimeError("injected mid-pass failure")
        return real_dumps(*args, **kwargs)

    monkeypatch.setattr(json, "dumps", flaky_dumps)
    try:
        B.build_index(str(dump), str(out), "en", 50, progress=str(progress))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the injected mid-pass failure")
    assert opened, "spill file must have been opened under zero budget"
    assert all(handle.closed for handle in opened), "spill handle leaked"
    print("ok: spill handle closed even when the pass raises")


def _merge_lookup_jsonl(path: Path) -> dict:
    merged: dict[str, list[int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        merged.setdefault(row["lemma_key"], []).extend(row["offsets"])
    return {key: sorted(val) for key, val in merged.items()}


def test_spilled_resume_appends_without_truncation(tmp_path, monkeypatch):
    # Resume of a spilled run must APPEND to the spill file (never "wb"
    # truncate it) and must rebuild only the unflushed tail. A full rebuild
    # or a truncate would show up here as lost prefix bytes or duplicated
    # offsets in the merged lookup.
    tmp = Path(tmp_path)
    dump = tmp / "kaikki-en-words.jsonl"
    make_dump(dump, n=N)
    progress = tmp / "index_en_progress.json"

    full = tmp / "full.jsonl"
    B.build_index(str(dump), str(full), "en", 50, progress=str(tmp / "p0.json"))
    full_bytes = full.read_bytes()
    full_lookup = json.loads((tmp / "kaikki-en-lookup.json").read_text(encoding="utf-8"))
    full_lookup = {key: sorted(val) for key, val in full_lookup.items()}

    half = N // 2
    resumed = tmp / "resumed.jsonl"
    resumed.write_bytes(b"".join(full_bytes.splitlines(keepends=True)[:half]))
    half_lines = resumed.read_text(encoding="utf-8").splitlines()
    last = json.loads(half_lines[-1])
    mid_offset = last["offset"] + last["length"]
    # Hand-craft the spilled prefix: groups covering exactly the first half.
    from registry import normalize_lemma
    groups: dict[str, list[int]] = {}
    for line in half_lines:
        entry = json.loads(line)
        key = normalize_lemma(entry["word"])
        groups.setdefault(key, []).append(entry["offset"])
    spill = B.lookup_path_for(str(resumed), "en", as_jsonl=True)
    with open(spill, "wb") as handle:
        for key in sorted(groups):
            handle.write((json.dumps({"lemma_key": key,
                                      "offsets": sorted(groups[key])},
                                     ensure_ascii=False) + "\n").encode("utf-8"))
    spill_before = Path(spill).read_bytes()
    stat = os.stat(dump)
    progress.write_text(json.dumps({
        "lang": "en", "dump_size": stat.st_size,
        "dump_mtime": stat.st_mtime, "offset": mid_offset,
        "lines_done": half, "spilled": True,
        "spill_lines_done": half, "spill_size": len(spill_before)}),
        encoding="utf-8")
    monkeypatch.setattr(B, "MEMORY_BUDGET_BYTES", 0)
    B.build_index(str(dump), str(resumed), "en", 50, progress=str(progress))
    assert resumed.read_bytes() == full_bytes, "resumed index must be identical"
    lookup_path = Path(B.lookup_path_for(str(resumed), "en", as_jsonl=True))
    assert lookup_path.read_bytes().startswith(spill_before), \
        "resume must append to the spill file, never truncate it"
    assert _merge_lookup_jsonl(lookup_path) == full_lookup, \
        "merged spilled lookup must equal the single-JSON reference"
    print("ok: spilled resume appends and rebuilds tail-only")


def test_fresh_build_truncates_orphan_spill(tmp_path, monkeypatch):
    # Fresh build (no progress) with a leftover spill file must TRUNCATE it,
    # never append: otherwise stale offsets corrupt the merged lookup.
    tmp = Path(tmp_path)
    dump = tmp / "kaikki-en-words.jsonl"
    make_dump(dump, n=N)
    out = tmp / "kaikki-en-index.jsonl"
    spill = Path(B.lookup_path_for(str(out), "en", as_jsonl=True))
    spill.write_bytes(b'{"lemma_key": "zzq_orphan_stale", "offsets": [1, 2, 3]}\n')
    monkeypatch.setattr(B, "MEMORY_BUDGET_BYTES", 0)
    B.build_index(str(dump), str(out), "en", 50,
                  progress=str(tmp / "fresh.json"))
    merged = _merge_lookup_jsonl(spill)
    assert "zzq_orphan_stale" not in merged, \
        "fresh build must truncate orphan spill, not append to it"
    print("ok: fresh build truncates orphan spill")


if __name__ == "__main__":
    test_offsets_round_trip_via_fetch()
    test_resume_gives_identical_index()
    test_dry_run_writes_nothing()
    test_stale_dump_aborts()
    test_lang_is_required()
    test_fetch_rejects_wordless_object()
    from _pytest.monkeypatch import MonkeyPatch
    for _fn in (test_spill_handle_closed_on_exception,
                test_spilled_resume_appends_without_truncation,
                test_fresh_build_truncates_orphan_spill):
        _mp = MonkeyPatch()
        try:
            _fn(Path(tempfile.mkdtemp()), _mp)
        finally:
            _mp.undo()
    print("ALL INDEX TESTS PASSED")
