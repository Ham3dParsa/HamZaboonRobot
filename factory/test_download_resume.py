"""Focused test for factory/download_kaikki.py (TICKET T1).

Covers (plain asserts; run `python factory/test_download_resume.py`
or `python -m pytest factory/test_download_resume.py`):
  (a) byte-range resume: a half-written .part is continued via the Range
      header and the result equals the full body;
  (b) server-ignores-range: a 200 reply to a ranged request restarts cleanly;
  (c) atomic rename: main() verifies .part then moves it to final;
  (d) existing final file is re-verified, never re-downloaded;
  (d) dry-run writes NOTHING (no target, no .part, no progress file);
  (e) verify(): accepts good lines, rejects a missing "word" key and bad JSON.

Never touches the network: a fake opener serves a LOCAL tiny byte buffer.
Never touches W: or the real factory progress file: everything in temp dirs.
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import download_kaikki as D  # noqa: E402

LINES = [json.dumps({"word": f"w{i}", "pos": "noun"}) + "\n" for i in range(50)]
BODY = "".join(LINES).encode("utf-8")
HALF = len(BODY) // 2


class FakeHeaders(dict):
    pass


class FakeResponse:
    """Minimal urllib-response double honouring the Range header."""

    def __init__(self, body: bytes, status: int):
        self._buf = io.BytesIO(body)
        self.status = status
        self.headers = FakeHeaders({"Content-Length": str(len(body))})

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_opener(ignore_range: bool = False, seen: dict | None = None):
    def opener(request, timeout=None):
        ranged = request.get_header("Range") if hasattr(request, "get_header") else None
        # urllib Request stores headers capitalised; fall back to dict scan.
        if ranged is None:
            try:
                ranged = request.headers.get("Range", request.headers.get("range"))
            except AttributeError:
                ranged = None
        if seen is not None:
            seen["range"] = ranged
        if ranged and not ignore_range:
            start = int(ranged.split("=")[1].split("-")[0])
            return FakeResponse(BODY[start:], 206)
        return FakeResponse(BODY, 200)

    return opener


def test_resume_continues_partial_part():
    with tempfile.TemporaryDirectory() as tmp:
        part = Path(tmp) / "k.jsonl.part"
        part.write_bytes(BODY[:HALF])
        progress = Path(tmp) / "download_en_progress.json"
        seen: dict = {}
        done, total = D.download_stream("http://local/x", part, True, progress,
                                        opener=make_opener(seen=seen))
        assert seen.get("range") == f"bytes={HALF}-", seen
        assert part.read_bytes() == BODY
        assert done == len(BODY) and total == len(BODY)
        payload = json.loads(progress.read_text(encoding="utf-8"))
        assert payload["done"] == len(BODY) and payload["total"] == len(BODY)
    print("ok: resume continues partial .part via Range")


def test_server_ignoring_range_restarts_cleanly():
    with tempfile.TemporaryDirectory() as tmp:
        part = Path(tmp) / "k.jsonl.part"
        part.write_bytes(BODY[:HALF])
        progress = Path(tmp) / "download_en_progress.json"
        done, _ = D.download_stream("http://local/x", part, True, progress,
                                    opener=make_opener(ignore_range=True))
        assert part.read_bytes() == BODY, "must restart, not append, on 200"
        assert done == len(BODY)
    print("ok: 200-to-ranged-request restarts instead of corrupting")


def test_fetch_complete_resumes_short_read():
    # Server declares the full length but truncates round 1; round 2 must
    # continue via Range until the whole body is present.
    state = {"calls": 0}
    ranged = make_opener()

    def opener(request, timeout=None):
        state["calls"] += 1
        if state["calls"] == 1:
            resp = FakeResponse(BODY[:100], 200)
            resp.headers["Content-Length"] = str(len(BODY))  # declared, not delivered
            return resp
        return ranged(request, timeout=timeout)

    with tempfile.TemporaryDirectory() as tmp:
        part = Path(tmp) / "k.jsonl.part"
        progress = Path(tmp) / "download_en_progress.json"
        orig_sleep = D.time.sleep
        D.time.sleep = lambda s: None
        try:
            done, total = D.fetch_complete("http://local/x", part, True, progress,
                                           opener=opener, max_rounds=5)
        finally:
            D.time.sleep = orig_sleep
        assert done == len(BODY) and total == len(BODY), (done, total)
        assert part.read_bytes() == BODY
        assert state["calls"] == 2
    print("ok: fetch_complete() resumes a truncated round via Range")


def test_main_atomic_rename_and_verify():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "kaikki-en-words.jsonl"
        progress = Path(tmp) / "download_en_progress.json"
        orig_fetch, orig_verify, orig_progress = D.fetch_complete, D.verify, D.progress_path
        calls = {}

        def fake_fetch(url, part, resume, progress_file, opener=None):
            calls["part"] = Path(part)
            Path(part).write_bytes(BODY)
            progress_file.write_text(json.dumps({"done": 1, "total": 1}), encoding="utf-8")
            return len(BODY), len(BODY)

        def fake_verify(path, **kwargs):
            calls["verified"] = Path(path)
            return len(LINES)

        D.fetch_complete, D.verify = fake_fetch, fake_verify
        D.progress_path = lambda lang: progress
        try:
            assert D.main(["--lang", "en", "--out", str(out)]) == 0
        finally:
            D.fetch_complete, D.verify, D.progress_path = orig_fetch, orig_verify, orig_progress
        assert out.read_bytes() == BODY
        assert not calls["part"].exists(), ".part must be gone after atomic rename"
        assert not progress.exists(), "progress file must be cleaned up"
        assert calls["verified"] == calls["part"], "verify runs on .part before rename"
    print("ok: main() verifies .part then atomically renames")


def test_main_existing_out_verifies_without_redownload():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "kaikki-en-words.jsonl"
        out.write_bytes(BODY)
        orig_fetch, orig_verify = D.fetch_complete, D.verify
        calls = {}

        def no_fetch(*a, **k):
            raise AssertionError("must not re-download an existing file")

        def fake_verify(path, **kwargs):
            calls["verified"] = Path(path)
            return len(LINES)

        D.fetch_complete, D.verify = no_fetch, fake_verify
        try:
            assert D.main(["--lang", "en", "--out", str(out)]) == 0
        finally:
            D.fetch_complete, D.verify = orig_fetch, orig_verify
        assert calls["verified"] == out
    print("ok: main() re-verifies an existing file instead of re-downloading")


def test_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "kaikki-en-words.jsonl"
        progress = Path(tmp) / "download_en_progress.json"
        orig = D.progress_path
        D.progress_path = lambda lang: progress
        try:
            assert D.main(["--lang", "en", "--out", str(out), "--dry-run"]) == 0
        finally:
            D.progress_path = orig
        leftovers = list(Path(tmp).iterdir())
        assert leftovers == [], f"dry-run wrote files: {leftovers}"
    print("ok: --dry-run writes nothing")


def test_verify_accepts_and_rejects():
    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "good.jsonl"
        good.write_bytes(BODY)
        assert D.verify(good, min_size=10, need=50) == 50

        bad_key = Path(tmp) / "badkey.jsonl"
        bad_key.write_text('{"word": "a"}\n{"pos": "noun"}\n', encoding="utf-8")
        try:
            D.verify(bad_key, min_size=10, need=2)
        except SystemExit as exc:
            assert "word" in str(exc), exc
        else:
            raise AssertionError("verify must reject a line without 'word'")

        bad_json = Path(tmp) / "badjson.jsonl"
        bad_json.write_text('{"word": "a"}\n{nope}\n', encoding="utf-8")
        try:
            D.verify(bad_json, min_size=10, need=2)
        except SystemExit as exc:
            assert "JSON" in str(exc), exc
        else:
            raise AssertionError("verify must reject invalid JSON")

        try:
            D.verify(good, min_size=10**18, need=50)
        except SystemExit as exc:
            assert "bytes" in str(exc), exc
        else:
            raise AssertionError("verify must reject an undersized file")
    print("ok: verify() accepts good lines, rejects bad key / bad JSON / small size")


def test_lang_is_required():
    try:
        D.parse_args([])
    except SystemExit:
        print("ok: --lang is required")
    else:
        raise AssertionError("--lang must be required")


if __name__ == "__main__":
    test_resume_continues_partial_part()
    test_server_ignoring_range_restarts_cleanly()
    test_fetch_complete_resumes_short_read()
    test_main_atomic_rename_and_verify()
    test_main_existing_out_verifies_without_redownload()
    test_dry_run_writes_nothing()
    test_verify_accepts_and_rejects()
    test_lang_is_required()
    print("ALL DOWNLOAD TESTS PASSED")
