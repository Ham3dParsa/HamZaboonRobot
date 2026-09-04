"""EN phrase-pool CEFR judge (TICKET F4).

Grades each phrase in ``phrases.csv`` as ONE WHOLE UNIT via the Zen
``/responses`` transport (same pattern as ``run_v16b_topup.py``: batch 8,
sleep 2.5s, per-model 2 attempts, 401/403 loud abort, fail-closed to prefill).
Progress lives at ``--progress`` and is rewritten every batch; resume skips
phrases already in ``done_phrases``. Per-phrase audit lines append to
``--out`` (``judge_log.jsonl``).

``--dry-run`` prints the plan and writes NOTHING.

Usage:
    python factory/phrase_judge.py [--phrases ...] [--out ...]
        [--progress ...] [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_json import AuthError, extract_json, raise_for_auth  # noqa: E402

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

ZEN_BASE = "https://opencode.ai/zen/v1"
MODELS = ["muse-spark-1.3-contributor-free",
          "muse-spark-1.2-contributor-free",
          "ling-3.0-flash-fin-free",
          "mimo-v2.5-free",
          "nemotron-3.5-lightning-free"]
BATCH = 8
SLEEP = 2.5
TIMEOUT = 180
MAX_ATTEMPTS = 2

SYS = ("You are a lexicographer assigning CEFR levels to English multiword "
       "phrases for Persian learners. Judge the WHOLE phrase as one unit: "
       "A1 = everyday transparent routine (\"take care\" as farewell, "
       "\"a lot of\"); A2 = common concrete collocation still guessable "
       "from parts; B1 = independent-use phrase with mild opacity or "
       "limited context; B2 = abstract, workplace/academic, or figurative "
       "extension; C1-C2 = rare, idiomatic, literary, or culturally loaded. "
       "Return ONLY raw JSON, no markdown fences, no commentary.")

USER_TMPL = (
    "Grade EACH phrase below as one whole unit for Persian learners. "
    "Rules: level is one of A1 A2 B1 B2 C1 C2; confidence is a number "
    "0..1; literal is true when the phrase means what its parts say, "
    "false when idiomatic/figurative/opaque. "
    "Edge rules: proper nouns default B1 with literal=false; transparent "
    "compounds are literal=true capped at A2; opaque idioms are "
    "literal=false floored at B1; phrasal verbs are graded on the dominant "
    "figurative sense; near-duplicates are graded independently. "
    "Output: {\"results\": [{\"phrase\": \"...\", \"level\": \"...\", "
    "\"confidence\": 0..1, \"literal\": true/false}]}. "
    "Cover EVERY input phrase exactly once, in input order. "
    "Input follows:\n{BATCH_JSON}")

RETRY_PREFIX = ("Your last reply was not valid JSON. "
                "Re-send ONLY the JSON object.\n")


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def default_phrases() -> str:
    return os.path.join(script_dir(), "packs", "en", "phrases.csv")


def default_out() -> str:
    return os.path.join(script_dir(), "phrase_judge_log.jsonl")


def default_progress() -> str:
    return os.path.join(script_dir(), "phrase_judge_progress.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EN phrase CEFR judge.")
    parser.add_argument("--phrases", default=default_phrases())
    parser.add_argument("--out", default=default_out(),
                        help="audit log .jsonl path")
    parser.add_argument("--progress", default=default_progress())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None,
                        help="debug cap on phrases graded")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")
    return args


def load_phrases(path: str) -> list[dict]:
    try:
        handle = open(path, encoding="utf-8", newline="")
    except OSError as exc:
        raise SystemExit(f"error: cannot read phrases {path}: {exc}")
    with handle:
        try:
            records = list(csv.DictReader(handle))
        except (csv.Error, ValueError) as exc:
            raise SystemExit(f"error: corrupt phrases CSV {path}: {exc}")
    rows = []
    for record in records:
        phrase = (record.get("phrase") or "").strip()
        if not phrase:
            raise SystemExit(f"error: corrupt phrases CSV {path}: "
                             "blank phrase row")
        try:
            freq = int(record.get("freq", "0"))
        except (ValueError, TypeError):
            raise SystemExit(f"error: corrupt phrases CSV {path}: "
                             f"bad freq for {phrase!r}")
        rows.append({"phrase": phrase, "freq": freq,
                     "prefill": (record.get("prefill") or "UNLEVELLED").strip()
                     or "UNLEVELLED"})
    return rows


def validate_results(data: object, want: list[str]) -> tuple[bool, list[dict] | None]:
    """Validate a judge reply against the requested batch phrases.

    Rejects: non-object envelope, missing/non-list ``results``, count
    mismatch, phrase mismatch (exact, in order), bad level, bad
    confidence, non-bool literal. Returns (ok, normed-or-None).
    """
    if not isinstance(data, dict):
        return False, None
    items = data.get("results")
    if not isinstance(items, list) or len(items) != len(want):
        return False, None
    normed = []
    for item, phrase in zip(items, want):
        if not isinstance(item, dict) or item.get("phrase") != phrase:
            return False, None
        if item.get("level") not in LEVELS:
            return False, None
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            return False, None
        if not 0.0 <= confidence <= 1.0:
            return False, None
        if not isinstance(item.get("literal"), bool):
            return False, None
        normed.append({"phrase": phrase, "level": item["level"],
                       "confidence": confidence,
                       "literal": item["literal"]})
    return True, normed


def call_responses(api_key: str, model: str, user_text: str,
                   timeout: int = TIMEOUT) -> str:
    body = json.dumps({
        "model": model,
        "input": [{"role": "system", "content": SYS},
                  {"role": "user", "content": user_text}],
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": 4000,
    }).encode()
    req = urllib.request.Request(
        ZEN_BASE + "/responses", data=body,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json",
                 "User-Agent": "HamZaban-factory/1.0",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    parts = []
    for item in data.get("output", []):
        for chunk in item.get("content", []):
            if chunk.get("type") == "output_text":
                parts.append(chunk.get("text", ""))
    return "".join(parts)


def grade_batch(batch: list[dict], api_key: str, batch_id: int,
                transport=call_responses) -> tuple[list[dict], str, dict]:
    """Grade one batch via the model chain. Returns (verdicts, model, calls).

    Raises AuthError on 401/403 (loud abort, no fallback). On total
    exhaustion raises LookupError — the caller fails closed to prefill.
    """
    batch_json = json.dumps(
        [{"phrase": row["phrase"], "freq": row["freq"],
          "prefill": row["prefill"]} for row in batch],
        ensure_ascii=False)
    user_text = USER_TMPL.replace("{BATCH_JSON}", batch_json)
    want = [row["phrase"] for row in batch]
    calls: dict[str, int] = {}
    import urllib.error
    for model in MODELS:
        prompts = [user_text, RETRY_PREFIX + user_text]
        for attempt_no, prompt in enumerate(prompts, start=1):
            try:
                raw = transport(api_key, model, prompt)
                data = extract_json(raw)
            except AuthError:
                raise
            except urllib.error.HTTPError as exc:
                raise_for_auth(exc)
            except Exception:
                continue
            ok, normed = validate_results(data, want)
            if not ok or normed is None:
                continue
            calls[model] = calls.get(model, 0) + 1
            for verdict in normed:
                verdict["attempts"] = attempt_no
            return normed, model, calls
    raise LookupError(f"all judge models exhausted for batch {batch_id}")


def write_progress(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
    os.replace(tmp, path)


def append_audit(out: str, lines: list[dict]) -> None:
    with open(out, "a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None,
         transport=call_responses) -> int:
    args = parse_args(argv)
    rows = load_phrases(args.phrases)
    if args.limit is not None:
        rows = rows[:args.limit]
    total_batches = (len(rows) + BATCH - 1) // BATCH if rows else 0
    done: dict[str, dict] = {}
    failed: list[str] = []
    calls: dict[str, int] = {}
    done_batches = 0
    if os.path.exists(args.progress) and not args.dry_run:
        try:
            with open(args.progress, encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"error: corrupt progress {args.progress}: {exc}")
        done = saved.get("done_phrases", {})
        failed = saved.get("failed_phrases", [])
        calls = saved.get("model_calls", {})
        done_batches = int(saved.get("done_batches", 0))
    if args.dry_run:
        print("dry-run plan (nothing written, no log/progress):")
        print(f"  phrases:  {args.phrases} ({len(rows)} rows)")
        print(f"  out:      {args.out} (not written)")
        print(f"  progress: {args.progress} (not written)")
        print(f"  batches:  {total_batches} x {BATCH}")
        print(f"  models:   {', '.join(MODELS)}")
        return 0

    from env_loader import load_factory_env
    env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
    api_key = env["OPENCODE_ZEN_API_KEY"]
    if not api_key:
        raise SystemExit("no OPENCODE_ZEN_API_KEY in factory/.env")

    try:
        from tqdm.auto import tqdm
        batch_ids = tqdm(range(total_batches), desc="phrase judge")
    except ImportError:
        batch_ids = range(total_batches)  # type: ignore[assignment]
    for batch_id in batch_ids:
        batch = rows[batch_id * BATCH:(batch_id + 1) * BATCH]
        pending = [row for row in batch if row["phrase"] not in done]
        audit_lines: list[dict] = []
        if pending:
            try:
                verdicts, model_used, batch_calls = grade_batch(
                    pending, api_key, batch_id, transport)
            except AuthError:
                raise
            except LookupError:
                verdicts, model_used = [], ""
                for row in pending:
                    done[row["phrase"]] = {"level": row["prefill"],
                                           "confidence": 0.0,
                                           "literal": False,
                                           "model": "prefill-fallback",
                                           "attempts": MAX_ATTEMPTS * len(MODELS)}
                    if row["phrase"] not in failed:
                        failed.append(row["phrase"])
                    audit_lines.append({
                        "phrase": row["phrase"], "freq": row["freq"],
                        "prefill": row["prefill"],
                        "verdict_level": row["prefill"], "confidence": 0.0,
                        "literal": False, "model_used": "prefill-fallback",
                        "attempts": MAX_ATTEMPTS * len(MODELS),
                        "batch_id": batch_id, "failed_flag": True})
            else:
                for key, count in batch_calls.items():
                    calls[key] = calls.get(key, 0) + count
                by_phrase = {v["phrase"]: v for v in verdicts}
                for row in pending:
                    verdict = by_phrase[row["phrase"]]
                    done[row["phrase"]] = {
                        "level": verdict["level"],
                        "confidence": verdict["confidence"],
                        "literal": verdict["literal"],
                        "model": model_used,
                        "attempts": verdict["attempts"]}
                    audit_lines.append({
                        "phrase": row["phrase"], "freq": row["freq"],
                        "prefill": row["prefill"],
                        "verdict_level": verdict["level"],
                        "confidence": verdict["confidence"],
                        "literal": verdict["literal"],
                        "model_used": model_used,
                        "attempts": verdict["attempts"],
                        "batch_id": batch_id, "failed_flag": False})
            if audit_lines:
                append_audit(args.out, audit_lines)
            time.sleep(SLEEP)
        done_batches = batch_id + 1
        write_progress(args.progress, {
            "done_batches": done_batches,
            "total_batches": total_batches,
            "done_phrases": done,
            "failed_phrases": failed,
            "model_calls": calls})
    print(f"phrase-judge: {len(done)} phrases, failed={len(failed)}, "
          f"calls={calls}")
    if failed:
        print(f"failed phrases (prefill fallback): {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
