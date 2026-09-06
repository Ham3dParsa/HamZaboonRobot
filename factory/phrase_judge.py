"""EN phrase-pool CEFR judge (TICKET F4) + phrase-type pass (R16).

Grades each phrase in ``phrases.csv`` as ONE WHOLE UNIT via the Zen
``/responses`` transport (same pattern as ``run_v16b_topup.py``: batch 32,
sleep 3.0s, per-model 2 attempts, 401/403 loud abort, fail-closed to prefill).
Zen key rotation (``OPENCODE_ZEN_API_KEY`` + ``_2``): on 429 rotate keys;
when every key 429s, flush progress and STOP for a server switch (no long
backoff — owner rule). Telemetry per attempt (key_idx only, never values).
Progress lives at ``--progress`` and is rewritten every batch; resume skips
phrases already in ``done_phrases``. Per-phrase audit lines append to
``--out`` (``judge_log.jsonl``).

``--dry-run`` prints the plan and writes NOTHING.

``--type-pass`` re-judges every already-judged phrase for PHRASE TYPE
(one LLM batch call per 8 phrases, same transport/chain/retry/progress/
resume conventions as the CEFR runner). Phrase source: the judge log at
``--out`` (``judge_log.jsonl``) when it exists, else ``--phrases``
(``phrases.csv``). Per-phrase audit lines append to ``--type-out``
(``phrase_type_log.jsonl``); resume state lives at ``--type-progress``
(``phrase_type_progress.json``), separate from the CEFR progress file.

Usage:
    python factory/phrase_judge.py [--phrases ...] [--out ...]
        [--progress ...] [--dry-run] [--limit N]
    python factory/phrase_judge.py --type-pass [--out judge_log.jsonl]
        [--type-out phrase_type_log.jsonl]
        [--type-progress phrase_type_progress.json] [--dry-run] [--limit N]
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
from telemetry import extract_usage as _tele_usage  # noqa: E402
from telemetry import record_call as _tele_record  # noqa: E402
from telemetry import write_summary as _tele_write  # noqa: E402

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

ZEN_BASE = "https://opencode.ai/zen/v1"
MODELS = ["muse-spark-1.3-contributor-free",
          "muse-spark-1.2-contributor-free",
          "ling-3.0-flash-fin-free",
          "mimo-v2.5-free",
          "nemotron-3.5-lightning-free"]
BATCH = 32

TIMEOUT = 180
MAX_ATTEMPTS = 2
SLEEP = 3.0
# R24 revised (owner): NO long backoff on quota errors — rotate keys, and
# STOP + report when every key is 429. Wasting hours in backoff is banned.
RATE_LIMIT_WAITS = ()


class RateLimited(Exception):
    """All keys 429 — caller flushes progress and exits for a server switch."""


class KeyRing:
    """Round-robin Zen keys. rotate() on 429; exhausted after a full circle."""

    def __init__(self, keys):
        self.keys = [k for k in keys if k]
        if not self.keys:
            raise ValueError(
                "KeyRing needs at least one non-empty key "
                "(set OPENCODE_ZEN_API_KEY in factory/.env)")
        self.idx = 0
        self.used = 0

    @property
    def current(self):
        return self.keys[self.idx]

    def rotate(self):
        """Move to next key. Returns False when every key just 429'd."""
        if not self.keys:
            return False
        self.used += 1
        self.idx = (self.idx + 1) % len(self.keys)
        if self.used >= len(self.keys):
            self.used = 0
            return False
        return True


def call_with_backoff(transport, api_key, model, prompt, sys_text=None,
                      ring=None):
    """Call transport with smart key rotation on 429. Returns raw text.

    On 429: rotate to the next key (brief 5s pause) and retry the same
    call. When EVERY key 429s in a row, raises RateLimited — the runner
    flushes progress and STOPS so the owner can switch servers.
    AuthError propagates untouched.
    """
    import urllib.error
    key = api_key if ring is None else ring.current
    while True:
        try:
            if sys_text is None:
                return transport(key, model, prompt)
            return transport(key, model, prompt, sys_text=sys_text)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and ring is not None:
                time.sleep(5)
                if ring.rotate():
                    key = ring.current
                    continue
                raise RateLimited(
                    "all Zen keys 429 — switch VPN server, then re-run")
            raise

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

# --type-pass: phrase-type re-judge (applied-pool triage, recorded only).
PHRASE_TYPES = ["idiom", "phrasal-verb", "collocation", "proverb", "slang",
                "applied", "proper-noun", "term", "abbreviation", "other"]
# Applied pool rule (NOT executed now, just recorded): applied_keep=true
# iff the type is an everyday-useful unit. proper-noun/term/other drop.
# R29 v8: the "abbreviation" label keeps only for EN (lang="en", the
# default); every other language uses the unchanged pre-v8 set.
APPLIED_KEEP_TYPES = frozenset(
    ["idiom", "phrasal-verb", "collocation", "proverb", "slang", "applied"])
APPLIED_KEEP_TYPES_EN_EXTRA = frozenset(["abbreviation"])

TYPE_SYS = ("You are a lexicographer typing English multiword phrases for "
            "Persian learners. Judge each phrase as one whole unit. "
            "Return ONLY raw JSON, no markdown fences, no commentary.")

TYPE_USER_TMPL = (
    "Type EACH phrase below as one whole unit for Persian learners. "
    "phrase_type is one of: idiom (non-compositional established unit); "
    "phrasal-verb (verb+particle); collocation (compositional habitual "
    "pairing); proverb (full-sentence wisdom); slang (informal in-group "
    "usage); applied (everyday useful unit); proper-noun (a name); "
    "term (domain-specialized); abbreviation (shortened form); other. "
    "proper_noun is true when the phrase is a name. "
    "applied_keep is true when the phrase is an everyday useful unit "
    "(idiom, phrasal-verb, collocation, proverb, slang, applied, "
    "abbreviation). "
    "Output: {\"results\": [{\"phrase\": \"...\", "
    "\"phrase_type\": \"...\", \"proper_noun\": true/false, "
    "\"applied_keep\": true/false}]}. "
    "Cover EVERY input phrase exactly once, in input order. "
    "Input follows:\n{BATCH_JSON}")


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def default_phrases() -> str:
    return os.path.join(script_dir(), "packs", "en", "phrases.csv")


def default_out() -> str:
    return os.path.join(script_dir(), "phrase_judge_log.jsonl")


def default_progress() -> str:
    return os.path.join(script_dir(), "phrase_judge_progress.json")


def default_type_out() -> str:
    return ("W:/hamzaban_data_factory/fixtures/phrase_type_log.jsonl")


def default_type_progress() -> str:
    return ("W:/hamzaban_data_factory/fixtures/"
            "phrase_type_progress.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EN phrase CEFR judge.")
    parser.add_argument("--phrases", default=default_phrases())
    parser.add_argument("--out", default=default_out(),
                        help="audit log .jsonl path")
    parser.add_argument("--progress", default=default_progress())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None,
                        help="debug cap on phrases graded")
    parser.add_argument("--type-pass", action="store_true",
                        help="re-judge already-judged phrases for phrase type")
    parser.add_argument("--type-out", default=default_type_out(),
                        help="type-pass audit log .jsonl path")
    parser.add_argument("--type-progress", default=default_type_progress(),
                        help="type-pass resume progress path")
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


def applied_keep_for(phrase_type: str, lang: str = "en") -> bool:
    """Applied pool rule (recorded only, not executed): keep everyday-useful
    units (idiom/phrasal-verb/collocation/proverb/slang/applied).

    R29 v8: the "abbreviation" label keeps only for EN (default lang);
    other languages use the unchanged pre-v8 set (abbreviation drops).
    """
    if phrase_type in APPLIED_KEEP_TYPES:
        return True
    return (lang or "").strip().lower() == "en" \
        and phrase_type in APPLIED_KEEP_TYPES_EN_EXTRA


def validate_type_results(data: object,
                          want: list[str]) -> tuple[bool, list[dict] | None]:
    """Validate a type-pass reply against the requested batch phrases.

    Rejects: non-object envelope, missing/non-list ``results``, count
    mismatch, phrase mismatch (exact, in order), bad phrase_type,
    non-bool proper_noun. ``applied_keep`` is always (re)computed from
    the deterministic applied pool rule, never trusted from the model.
    Returns (ok, normed-or-None).
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
        phrase_type = item.get("phrase_type")
        if phrase_type not in PHRASE_TYPES:
            return False, None
        if not isinstance(item.get("proper_noun"), bool):
            return False, None
        normed.append({"phrase": phrase, "phrase_type": phrase_type,
                        "proper_noun": item["proper_noun"],
                        "applied_keep": applied_keep_for(phrase_type)})
    return True, normed


def load_judged_phrases(path: str) -> list[str]:
    """Phrase list from a judge_log.jsonl (``phrase`` keys, order kept)."""
    try:
        handle = open(path, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"error: cannot read judge log {path}: {exc}")
    phrases = []
    with handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise SystemExit(f"error: corrupt judge log {path} "
                                 f"line {lineno}: {exc}")
            phrase = (row.get("phrase") or "").strip()
            if not phrase:
                raise SystemExit(f"error: corrupt judge log {path} "
                                 f"line {lineno}: blank phrase")
            phrases.append(phrase)
    return phrases


def _tele_tokens(usage):
    """Token pair from a surfaced usage dict (None-tolerated)."""
    if isinstance(usage, dict):
        return _tele_usage(usage)
    return None, None


def _tele_key_idx(ring):
    """Keyring index for telemetry (int only — never the key value)."""
    try:
        return int(ring.idx) if ring is not None else 0
    except (TypeError, ValueError, AttributeError):
        return 0


def call_responses(api_key: str, model: str, user_text: str,
                   timeout: int = TIMEOUT, sys_text: str | None = None) -> str:
    body = json.dumps({
        "model": model,
        "input": [{"role": "system", "content": sys_text or SYS},
                  {"role": "user", "content": user_text}],
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": 8000,
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
                transport=call_responses,
                ring=None, telemetry=None,
                tele_stage="phrase-judge") -> tuple[list[dict], str, dict]:
    """Grade one batch via the model chain. Returns (verdicts, model, calls).

    Raises AuthError on 401/403 (loud abort, no fallback). Raises
    RateLimited when every ring key 429s (flush + stop for server switch).
    On total exhaustion raises LookupError — the caller fails closed.
    R27: each transport attempt is telemetry-recorded (key_idx only,
    never the key value; tuple (text, usage) transports surface token
    counts, plain-text transports record None — tolerated).
    """
    batch_json = json.dumps(
        [{"phrase": row["phrase"], "freq": row["freq"],
          "prefill": row["prefill"]} for row in batch],
        ensure_ascii=False)
    user_text = USER_TMPL.replace("{BATCH_JSON}", batch_json)
    want = [row["phrase"] for row in batch]
    calls: dict[str, int] = {}
    import time as _time
    import urllib.error
    for model in MODELS:
        prompts = [user_text, RETRY_PREFIX + user_text]
        for attempt_no, prompt in enumerate(prompts, start=1):
            try:
                _start = _time.perf_counter()
                res = call_with_backoff(transport, api_key, model, prompt,
                                        ring=ring)
                _latency = _time.perf_counter() - _start
                if isinstance(res, tuple) and len(res) == 2:
                    raw, _usage = res
                else:
                    raw, _usage = res, None
                if telemetry is not None:
                    _pt, _ct = _tele_tokens(_usage)
                    _tele_record(
                        telemetry, stage=tele_stage, batch_id=batch_id,
                        key_idx=_tele_key_idx(ring), model=model,
                        prompt_tokens=_pt, completion_tokens=_ct,
                        latency_s=_latency, outcome="ok")
                data = extract_json(raw)
            except AuthError:
                if telemetry is not None:
                    _tele_record(
                        telemetry, stage=tele_stage, batch_id=batch_id,
                        key_idx=_tele_key_idx(ring), model=model,
                        latency_s=0.0, outcome="auth")
                raise
            except RateLimited:
                if telemetry is not None:
                    _tele_record(
                        telemetry, stage=tele_stage, batch_id=batch_id,
                        key_idx=_tele_key_idx(ring), model=model,
                        latency_s=0.0, outcome="error", http_status=429)
                raise
            except urllib.error.HTTPError as exc:
                if telemetry is not None:
                    _tele_record(
                        telemetry, stage=tele_stage, batch_id=batch_id,
                        key_idx=_tele_key_idx(ring), model=model,
                        latency_s=0.0, outcome="error",
                        http_status=getattr(exc, "code", None))
                raise_for_auth(exc)
            except Exception:
                if telemetry is not None:
                    _tele_record(
                        telemetry, stage=tele_stage, batch_id=batch_id,
                        key_idx=_tele_key_idx(ring), model=model,
                        latency_s=0.0, outcome="error")
                continue
            ok, normed = validate_results(data, want)
            if not ok or normed is None:
                continue
            calls[model] = calls.get(model, 0) + 1
            for verdict in normed:
                verdict["attempts"] = attempt_no
            return normed, model, calls
    raise LookupError(f"all judge models exhausted for batch {batch_id}")


def grade_type_batch(batch: list[str], api_key: str, batch_id: int,
                     transport=call_responses,
                     ring=None, telemetry=None,
                     tele_stage="phrase-type") -> tuple[list[dict], str, dict]:
    """Type one batch via the model chain. Returns (verdicts, model, calls).

    Same conventions as grade_batch (per-model 2 attempts, 401/403 loud
    abort, RateLimited when every ring key 429s). On total exhaustion
    raises LookupError — the caller fails closed to a type-fallback line.
    R27 telemetry: same per-attempt recording as grade_batch.
    """
    batch_json = json.dumps([{"phrase": phrase} for phrase in batch],
                            ensure_ascii=False)
    user_text = TYPE_USER_TMPL.replace("{BATCH_JSON}", batch_json)
    calls: dict[str, int] = {}
    import time as _time
    import urllib.error
    for model in MODELS:
        prompts = [user_text, RETRY_PREFIX + user_text]
        for attempt_no, prompt in enumerate(prompts, start=1):
            try:
                _start = _time.perf_counter()
                res = call_with_backoff(transport, api_key, model, prompt,
                                        sys_text=TYPE_SYS, ring=ring)
                _latency = _time.perf_counter() - _start
                if isinstance(res, tuple) and len(res) == 2:
                    raw, _usage = res
                else:
                    raw, _usage = res, None
                if telemetry is not None:
                    _pt, _ct = _tele_tokens(_usage)
                    _tele_record(
                        telemetry, stage=tele_stage, batch_id=batch_id,
                        key_idx=_tele_key_idx(ring), model=model,
                        prompt_tokens=_pt, completion_tokens=_ct,
                        latency_s=_latency, outcome="ok")
                data = extract_json(raw)
            except AuthError:
                if telemetry is not None:
                    _tele_record(
                        telemetry, stage=tele_stage, batch_id=batch_id,
                        key_idx=_tele_key_idx(ring), model=model,
                        latency_s=0.0, outcome="auth")
                raise
            except RateLimited:
                if telemetry is not None:
                    _tele_record(
                        telemetry, stage=tele_stage, batch_id=batch_id,
                        key_idx=_tele_key_idx(ring), model=model,
                        latency_s=0.0, outcome="error", http_status=429)
                raise
            except urllib.error.HTTPError as exc:
                if telemetry is not None:
                    _tele_record(
                        telemetry, stage=tele_stage, batch_id=batch_id,
                        key_idx=_tele_key_idx(ring), model=model,
                        latency_s=0.0, outcome="error",
                        http_status=getattr(exc, "code", None))
                raise_for_auth(exc)
            except Exception:
                if telemetry is not None:
                    _tele_record(
                        telemetry, stage=tele_stage, batch_id=batch_id,
                        key_idx=_tele_key_idx(ring), model=model,
                        latency_s=0.0, outcome="error")
                continue
            ok, normed = validate_type_results(data, batch)
            if not ok or normed is None:
                continue
            calls[model] = calls.get(model, 0) + 1
            for verdict in normed:
                verdict["attempts"] = attempt_no
            return normed, model, calls
    raise LookupError(f"all type models exhausted for batch {batch_id}")


def write_progress(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
    os.replace(tmp, path)


def append_audit(out: str, lines: list[dict]) -> None:
    with open(out, "a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def main_type(args: argparse.Namespace, transport=call_responses) -> int:
    """--type-pass runner: re-judge already-judged phrases for phrase type."""
    if os.path.exists(args.out):
        phrases = load_judged_phrases(args.out)
        source = "judge-log %s" % args.out
    else:
        phrases = [row["phrase"] for row in load_phrases(args.phrases)]
        source = "phrases CSV %s" % args.phrases
    if args.limit is not None:
        phrases = phrases[:args.limit]
    total_batches = (len(phrases) + BATCH - 1) // BATCH if phrases else 0
    done: dict[str, dict] = {}
    failed: list[str] = []
    calls: dict[str, int] = {}
    done_batches = 0
    if os.path.exists(args.type_progress) and not args.dry_run:
        try:
            with open(args.type_progress, encoding="utf-8") as handle:
                saved = json.load(handle)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"error: corrupt progress "
                             f"{args.type_progress}: {exc}")
        done = saved.get("done_phrases", {})
        failed = saved.get("failed_phrases", [])
        calls = saved.get("model_calls", {})
        done_batches = int(saved.get("done_batches", 0))
    if args.dry_run:
        print("dry-run type plan (nothing written, no log/progress):")
        print(f"  source:   {source} ({len(phrases)} phrases)")
        print(f"  out:      {args.type_out} (not written)")
        print(f"  progress: {args.type_progress} (not written)")
        print(f"  batches:  {total_batches} x {BATCH}")
        print(f"  models:   {', '.join(MODELS)}")
        return 0

    from env_loader import load_factory_env
    try:
        env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
    except KeyError as exc:
        raise SystemExit("missing env: %s" % exc)
    api_key = env["OPENCODE_ZEN_API_KEY"]
    if not api_key:
        raise SystemExit("no OPENCODE_ZEN_API_KEY in factory/.env")
    try:
        ring = KeyRing([api_key, env.get("OPENCODE_ZEN_API_KEY_2", "")])
    except ValueError as exc:
        raise SystemExit("no Zen keys: %s" % exc)
    print(f"keys in ring: {len(ring.keys)}")
    tele_store = []  # R27: per-attempt records (key_idx only, never values)

    try:
        from tqdm.auto import tqdm
        batch_ids = tqdm(range(total_batches), desc="phrase type")
    except ImportError:
        batch_ids = range(total_batches)  # type: ignore[assignment]
    for batch_id in batch_ids:
        batch = phrases[batch_id * BATCH:(batch_id + 1) * BATCH]
        pending = [phrase for phrase in batch if phrase not in done]
        audit_lines: list[dict] = []
        if pending:
            try:
                verdicts, model_used, batch_calls = grade_type_batch(
                    pending, api_key, batch_id, transport, ring=ring,
                    telemetry=tele_store)
            except AuthError:
                raise
            except RateLimited as exc:
                write_progress(args.type_progress, {
                    "done_batches": batch_id,
                    "total_batches": total_batches,
                    "done_phrases": done,
                    "failed_phrases": failed,
                    "model_calls": calls})
                raise SystemExit(
                    f"STOP at batch {batch_id}: {exc} — "
                    f"progress flushed, switch VPN server then re-run")
            except LookupError:
                verdicts, model_used = [], ""
                for phrase in pending:
                    done[phrase] = {"phrase_type": "other",
                                    "proper_noun": False,
                                    "applied_keep": applied_keep_for("other"),
                                    "model": "type-fallback",
                                    "attempts": MAX_ATTEMPTS * len(MODELS)}
                    if phrase not in failed:
                        failed.append(phrase)
                    audit_lines.append({
                        "phrase": phrase, "phrase_type": "other",
                        "proper_noun": False,
                        "applied_keep": applied_keep_for("other"),
                        "model": "type-fallback"})
            else:
                for key, count in batch_calls.items():
                    calls[key] = calls.get(key, 0) + count
                by_phrase = {v["phrase"]: v for v in verdicts}
                for phrase in pending:
                    verdict = by_phrase[phrase]
                    done[phrase] = {
                        "phrase_type": verdict["phrase_type"],
                        "proper_noun": verdict["proper_noun"],
                        "applied_keep": verdict["applied_keep"],
                        "model": model_used,
                        "attempts": verdict["attempts"]}
                    audit_lines.append({
                        "phrase": phrase,
                        "phrase_type": verdict["phrase_type"],
                        "proper_noun": verdict["proper_noun"],
                        "applied_keep": verdict["applied_keep"],
                        "model": model_used})
            if audit_lines:
                append_audit(args.type_out, audit_lines)
            time.sleep(SLEEP)
        done_batches = batch_id + 1
        write_progress(args.type_progress, {
            "done_batches": done_batches,
            "total_batches": total_batches,
            "done_phrases": done,
            "failed_phrases": failed,
            "model_calls": calls})
    print(f"phrase-type: {len(done)} phrases, failed={len(failed)}, "
          f"calls={calls}")
    if failed:
        print(f"failed phrases (type fallback): {failed}")
    _tele_write(os.path.join(os.path.dirname(os.path.abspath(args.type_out)),
                             "telemetry_summary.json"), tele_store)
    return 0


def main(argv: list[str] | None = None,
         transport=call_responses) -> int:
    args = parse_args(argv)
    if args.type_pass:
        return main_type(args, transport)
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
    try:
        env = load_factory_env(required=("OPENCODE_ZEN_API_KEY",))
    except KeyError as exc:
        raise SystemExit("missing env: %s" % exc)
    api_key = env["OPENCODE_ZEN_API_KEY"]
    if not api_key:
        raise SystemExit("no OPENCODE_ZEN_API_KEY in factory/.env")
    try:
        ring = KeyRing([api_key, env.get("OPENCODE_ZEN_API_KEY_2", "")])
    except ValueError as exc:
        raise SystemExit("no Zen keys: %s" % exc)
    print(f"keys in ring: {len(ring.keys)}")
    tele_store = []  # R27: per-attempt records (key_idx only, never values)

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
                    pending, api_key, batch_id, transport,
                    telemetry=tele_store, ring=ring)
            except AuthError:
                raise
            except RateLimited as exc:
                write_progress(args.progress, {
                    "done_batches": batch_id,
                    "total_batches": total_batches,
                    "done_phrases": done,
                    "failed_phrases": failed,
                    "model_calls": calls})
                raise SystemExit(
                    f"STOP at batch {batch_id}: {exc} — "
                    f"progress flushed, switch VPN server then re-run")
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
    _tele_write(os.path.join(os.path.dirname(os.path.abspath(args.out)),
                             "telemetry_summary.json"), tele_store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
