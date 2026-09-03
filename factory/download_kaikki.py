"""Resumable downloader for the Kaikki English-words JSONL dump (TICKET T1).

Source (verified 2026-09-04 via HEAD): the per-language dictionary page
https://kaikki.org/dictionary/English/ lists exactly one post-processed
download, ``kaikki.org-dictionary-English.jsonl`` (3_212_282_689 bytes).
The legacy ``...-English-words.jsonl`` name from the ticket brief 404s.

Usage:
    python factory/download_kaikki.py --lang en [--out PATH] [--no-resume] [--dry-run]

Behaviour:
- streams the dump to ``<out>.part`` then atomically renames to ``<out>``
- ``--resume`` (default ON) continues a partial ``.part`` via HTTP Range
- progress (bytes done/total) goes to ``factory/download_<lang>_progress.json``
- ``--dry-run`` prints the plan and writes NOTHING (no network, no files)
- after download, verifies size > 2GB + first 1000 lines are JSON with a
  "word" key, then prints the total line count
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # 1 MiB
MIN_SIZE_BYTES = 2_000_000_000  # brief: final size must exceed 2 GB
VERIFY_LINES = 1000
MAX_ROUNDS = 10  # bounded resume rounds against truncated responses
RETRY_BACKOFF = 5  # seconds, multiplied by round number

# Canonical per-language source URLs (verified via HEAD; do NOT guess new ones).
SOURCE_URLS = {
    "en": "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl",
}

DEFAULT_OUT_TEMPLATE = "W:/hamzaban_data_factory/raw/kaikki-{lang}-words.jsonl"


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def progress_path(lang: str) -> Path:
    return script_dir() / f"download_{lang}_progress.json"


def resolve_url(lang: str) -> str:
    try:
        return SOURCE_URLS[lang]
    except KeyError:
        raise SystemExit(
            f"error: no verified source URL for lang={lang!r}. "
            f"Known: {sorted(SOURCE_URLS)}. Add one only after HEAD-verifying it."
        )


def default_out(lang: str) -> str:
    return DEFAULT_OUT_TEMPLATE.format(lang=lang)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resumable Kaikki dump downloader.")
    parser.add_argument("--lang", required=True, help="language key, e.g. en (no default)")
    parser.add_argument("--out", default=None, help="destination .jsonl path")
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.out is None:
        args.out = default_out(args.lang)
    return args


def read_progress(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_progress(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def download_stream(url: str, part: Path, resume: bool, progress_file: Path,
                    opener=None) -> tuple[int, int | None]:
    """Stream *url* into *part*, resuming via HTTP Range when asked.

    Returns (bytes_done, bytes_total or None). *opener* is an injectable
    ``urllib.request.urlopen``-compatible callable (tests pass a fake so no
    network is touched).
    """
    opener = opener or urllib.request.urlopen
    start = part.stat().st_size if (resume and part.exists()) else 0
    if not resume and part.exists():
        part.unlink()
        start = 0

    request = urllib.request.Request(url)
    if start:
        request.add_header("Range", f"bytes={start}-")

    try:
        response = opener(request, timeout=60)
    except urllib.error.HTTPError as exc:
        # Server ignored/denied the range: restart from scratch on 200-style
        # fallback is handled by the caller status check below; 416 means the
        # part is already complete (or longer) — verify will decide.
        if exc.code == 416:
            return start, start
        raise

    with response as resp:
        status = getattr(resp, "status", 200)
        if start and status == 200:
            # Server ignored Range: restart cleanly instead of corrupting.
            start = 0
            mode = "wb"
        else:
            mode = "ab" if start else "wb"

        total = resp.headers.get("Content-Length")
        length = int(total) if total is not None else None
        if length is not None and (status == 206 or (start and mode == "ab")):
            total_bytes: int | None = start + length
        elif length is not None and mode == "wb":
            total_bytes = length
        else:
            total_bytes = None

        done = start
        write_progress(progress_file, {"url": url, "out": str(part), "done": done,
                                       "total": total_bytes})
        with open(part, mode) as handle:
            while True:
                chunk = resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                write_progress(progress_file, {"url": url, "out": str(part), "done": done,
                                               "total": total_bytes})
    return done, total_bytes


def fetch_complete(url: str, part: Path, resume: bool, progress_file: Path,
                   opener=None, max_rounds: int = MAX_ROUNDS) -> tuple[int, int | None]:
    """Drive download_stream until done >= declared total (or rounds run out).

    Servers/middleboxes may truncate a response (empty read long before the
    declared Content-Length). A single pass would then leave a corrupt short
    file, so re-enter with resume=True until the gap closes. Network errors
    are retried too; everything is bounded by *max_rounds*.
    """
    done, total = 0, None
    for round_no in range(1, max_rounds + 1):
        try:
            done, total = download_stream(url, part, resume if round_no == 1 else True,
                                          progress_file, opener=opener)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            print(f"round {round_no}/{max_rounds}: network error ({exc}); retrying...")
            time.sleep(RETRY_BACKOFF * round_no)
            continue
        if total is None or done >= total:
            return done, total
        print(f"round {round_no}/{max_rounds}: short read ({done}/{total} bytes); resuming...")
        time.sleep(RETRY_BACKOFF)
    return done, total


def verify(path: Path, min_size: int = MIN_SIZE_BYTES, need: int = VERIFY_LINES) -> int:
    """Verify size + first *need* JSON lines each carrying a "word" key.

    Returns the total line count. Raises SystemExit on failure.
    """
    size = path.stat().st_size
    if size <= min_size:
        raise SystemExit(f"error: {path} is {size} bytes, need > {min_size}.")
    checked = 0
    with open(path, "rb") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError as exc:
                raise SystemExit(f"error: line {checked + 1} is not valid JSON: {exc}")
            if "word" not in obj:
                raise SystemExit(f"error: line {checked + 1} has no 'word' key.")
            checked += 1
            if checked >= need:
                break
    if checked < need:
        raise SystemExit(f"error: only {checked} non-empty lines, need {need}.")
    total = 0
    with open(path, "rb") as handle:
        for _ in handle:
            total += 1
    print(f"verified: size={size} bytes, first {need} lines carry 'word', total_lines={total}")
    return total


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    url = resolve_url(args.lang)
    out = Path(args.out)
    progress = progress_path(args.lang)

    if args.dry_run:
        print("dry-run plan (nothing written, no network):")
        print(f"  lang:     {args.lang}")
        print(f"  url:      {url}")
        print(f"  out:      {out}")
        print(f"  temp:     {out}.part (stream here, then atomic rename)")
        print(f"  resume:   {'on (HTTP Range)' if args.resume else 'off (restart)'}")
        print(f"  progress: {progress} (bytes done/total)")
        print(f"  verify:   size > {MIN_SIZE_BYTES} bytes + first {VERIFY_LINES} "
              "lines valid JSON with 'word' key, then print total line count")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    if out.exists() and not part.exists():
        print(f"found existing {out}; verifying without re-downloading...")
        verify(out)
        return 0
    done, total = fetch_complete(url, part, args.resume, progress)
    print(f"downloaded: done={done} bytes"
          + (f" total={total} bytes" if total is not None else " total=unknown"))
    if total is not None and done < total:
        raise SystemExit(f"error: incomplete after {MAX_ROUNDS} rounds "
                         f"({done}/{total} bytes); re-run to resume from .part.")
    verify(part)
    os.replace(part, out)
    try:
        progress.unlink()
    except OSError:
        pass
    print(f"done: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
