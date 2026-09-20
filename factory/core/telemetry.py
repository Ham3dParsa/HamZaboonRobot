"""Factory LLM-call telemetry (stdlib only, hermetic).

Single owner of the precard line's telemetry record shape (R10):
``factory.precard.provider_transport`` only re-exports these recorders, and every
leg module (judge/topics/pipeline) imports them from here.

Every record carries ``key_idx`` (the keyring index, an int) — never the
key VALUE — plus ``run_id`` (``start-ts + pid``, joining provider_map,
run.log, and every record of one run). Token counts come from the
``usage`` block when the transport surfaces it (see ``extract_usage``);
missing usage is tolerated as ``None`` and NEVER a silent zero: paid
legs with no surfaced usage carry ``cost="unknown"`` (e.g. Google
direct), legs that made no call carry ``cost="none"`` (deterministic /
cache resolutions).

Record shape (``record_call``):
{ts, run_id, stage, batch_id, key_idx, model (requested), model_actual,
 provider, prompt_tokens|None, completion_tokens|None, latency_s,
 outcome, http_status|None, cost|None, kind ("terminal"|"attempt")}
"""

from __future__ import annotations

import html
import json
import os
import pathlib
from datetime import datetime, timezone

OUTCOMES = ("ok", "invalid", "fallback", "error", "auth")

KINDS = ("terminal", "attempt")


def new_store() -> list:
    """Fresh in-memory call list (tests + runners own one each)."""
    return []


def now_ts() -> str:
    """UTC ISO timestamp for one record."""
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    """One run's join key: UTC start timestamp + pid (``run_id``).

    Stamped into provider_map.json, the run.log header, and every
    telemetry record, so backoff/progress/telemetry rows join by run.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "%s-pid%d" % (stamp, os.getpid())


def resolve_cost(*, prompt_tokens=None, completion_tokens=None,
                 made_call=True):
    """Cost flag for one terminal record (never a silent zero).

    ``"none"`` when no network call happened (deterministic / cache /
    skipped resolutions); ``"unknown"`` when a call happened but no
    usage surfaced (Google direct always — it exposes no counters; any
    other paid leg that hides usage); ``None`` when token counts speak
    for themselves.
    """
    if not made_call:
        return "none"
    if prompt_tokens is None and completion_tokens is None:
        return "unknown"
    return None


def extract_usage(data) -> tuple:
    """Probe a Zen responses payload for token usage.

    Accepts the full response JSON (``{"usage": {...}}``) or a bare
    usage dict. Probes ``input_tokens``/``output_tokens`` first, then
    ``prompt_tokens``/``completion_tokens``. Anything missing or
    non-numeric -> ``None`` (tolerated, never raises).
    """
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict) and isinstance(data, dict):
        usage = data
    if not isinstance(usage, dict):
        return None, None

    def _num(*names):
        for name in names:
            try:
                value = usage.get(name)
            except AttributeError:
                continue
            if isinstance(value, bool):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            return int(number)
        return None

    return (_num("input_tokens", "prompt_tokens"),
            _num("output_tokens", "completion_tokens"))


def record_call(store, *, stage, batch_id, key_idx, model,
                prompt_tokens=None, completion_tokens=None,
                latency_s=0.0, outcome="ok", http_status=None,
                run_id="", provider="", model_actual=None,
                cost=None, kind="terminal"):
    """Append one call record. ``key_idx`` MUST be an int (never a key).

    ``model`` is the REQUESTED name; ``model_actual`` is the model
    really hit (remap legs substitute e.g. the precard model for a
    requested Zen name — the old single-field label lied here).
    ``latency_s``/``key_idx`` must be the measured values
    (perf_counter / ring.idx), never a hardcoded 0. ``cost`` comes
    from ``resolve_cost`` (unknown, never a silent zero). ``kind`` is
    "terminal" (one per batch) or "attempt" (per try, flag-gated).

    Raises ``TypeError`` when ``key_idx`` is not an int — a literal key
    string must never reach the persisted file.
    """
    if not isinstance(key_idx, int) or isinstance(key_idx, bool):
        raise TypeError("key_idx must be an int (key values never persist)")
    try:
        batch_id = int(batch_id)
    except (TypeError, ValueError):
        batch_id = 0
    try:
        latency = float(latency_s or 0.0)
    except (TypeError, ValueError):
        latency = 0.0
    entry = {
        "ts": now_ts(),
        "run_id": str(run_id or ""),
        "stage": str(stage or ""),
        "batch_id": batch_id,
        "key_idx": key_idx,
        "model": str(model or ""),
        "model_actual": str(model_actual if model_actual else model or ""),
        "provider": str(provider or ""),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_s": round(latency, 3),
        "outcome": outcome if outcome in OUTCOMES else "error",
        "http_status": http_status,
        "cost": cost,
        "kind": kind if kind in KINDS else "terminal",
    }
    store.append(entry)
    return entry


def emit_attempt_rows(store, attempts, *, stage, batch_id, run_id="",
                      provider="", model_actual=None):
    """Append one kind="attempt" record per try (flag-gated, default off).

    ``attempts`` are ``{model, attempt, latency_s, key_idx, outcome}``
    dicts collected by the rotation wrapper / review loops. Attempt
    rows are diagnostic: cost stays None and summaries never count
    them as cost-unknown. The raw try-outcome (settled / rotated /
    retry / cooldown / auth / error) rides on ``try_outcome``;
    ``outcome`` maps onto the terminal taxonomy (settled -> ok,
    auth -> auth, else error) so summaries stay homogeneous.
    """
    for att in attempts or []:
        if not isinstance(att, dict):
            continue
        model = str(att.get("model") or "")
        raw = str(att.get("outcome") or "error")
        outcome = "ok" if raw == "settled" \
            else ("auth" if raw == "auth" else "error")
        try:
            attempt_no = int(att.get("attempt", 0) or 0)
        except (TypeError, ValueError):
            attempt_no = 0
        # A bool key_idx is never a real ring index (bool is an int
        # subclass, so isinstance alone lets it through to record_call,
        # whose TypeError would abort the run from this diagnostic
        # path): coerce to 0, same as a missing value. record_call's
        # loud TypeError stays for genuinely non-int input.
        raw_idx = att.get("key_idx", 0)
        entry = record_call(
            store, stage=stage, batch_id=batch_id,
            key_idx=raw_idx if isinstance(raw_idx, int)
            and not isinstance(raw_idx, bool) else 0,
            model=model, latency_s=att.get("latency_s", 0.0),
            outcome=outcome,
            http_status=att.get("http_status"),
            run_id=run_id, provider=provider,
            model_actual=model_actual or model, kind="attempt")
        entry["attempt"] = attempt_no
        entry["try_outcome"] = raw
    return store


def last_attempt_latency(attempt_rows):
    """Measured latency of the last logged try (0.0 when none).

    Error-path terminal rows stamp this instead of a hardcoded 0.0,
    keeping the real-latency claim; 0.0 survives only where no call
    happened (empty attempt log or unparseable value)."""
    try:
        return float((attempt_rows or [])[-1].get("latency_s", 0.0)
                     or 0.0)
    except (TypeError, ValueError, AttributeError, IndexError):
        return 0.0


def _bucket():
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "unknown": 0}


def summarize(calls):
    """Aggregate {by_stage, by_model, by_key_idx} (None tokens count 0).

    Only ``kind == "terminal"`` rows feed the calls/tokens
    aggregation: per-try ``kind == "attempt"`` rows are diagnostic
    (flag-gated, default off) and would otherwise inflate call counts
    vs default runs. Attempt rows are counted separately under
    top-level ``attempts``; ``records`` counts terminal rows.
    ``unknown`` per bucket (and top-level ``cost_unknown``) counts
    terminal records flagged ``cost="unknown"`` — a None-usage zero is
    always flagged, never silent.
    """
    summary = {"by_stage": {}, "by_model": {}, "by_key_idx": {},
               "cost_unknown": 0, "attempts": 0, "records": 0}
    for call in calls or []:
        if call.get("kind", "terminal") != "terminal":
            summary["attempts"] += 1
            continue
        summary["records"] += 1
        unknown = (call.get("cost") == "unknown")
        for dim, raw in (("by_stage", call.get("stage")),
                         ("by_model", call.get("model")),
                         ("by_key_idx", call.get("key_idx"))):
            key = str(raw)
            bucket = summary[dim].setdefault(key, _bucket())
            bucket["calls"] += 1
            if unknown:
                bucket["unknown"] += 1
            for token_key in ("prompt_tokens", "completion_tokens"):
                try:
                    number = call.get(token_key)
                    bucket[token_key] += int(number) if number is not None \
                        else 0
                except (TypeError, ValueError):
                    pass
        if unknown:
            summary["cost_unknown"] += 1
    return summary


def write_summary(path, calls, run_id=""):
    """Write telemetry_summary.json (summary + record count + run_id)."""
    summary = summarize(calls)
    summary["run_id"] = str(run_id or "")
    dest = pathlib.Path(str(path))
    if str(dest.parent) not in ("", "."):
        dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False))
    return summary


def render_telemetry_table(summary):
    """Gallery header table: per-stage/model/key rows (calls + tokens)."""
    if not summary or not summary.get("records"):
        return ""
    rows = []
    for dim, title in (("by_stage", "مرحله"), ("by_model", "مدل"),
                       ("by_key_idx", "کلید")):
        for key in sorted((summary.get(dim) or {})):
            bucket = summary[dim][key]
            rows.append(
                '<tr><td dir="rtl" lang="fa">%s</td>'
                '<td class="en" dir="ltr" lang="en">%s</td>'
                '<td class="nums">%d</td>'
                '<td class="nums">%d</td>'
                '<td class="nums">%d</td></tr>'
                % (html.escape(title, quote=True),
                   html.escape(str(key), quote=True),
                   int(bucket.get("calls", 0)),
                   int(bucket.get("prompt_tokens", 0)),
                   int(bucket.get("completion_tokens", 0))))
    if not rows:
        return ""
    return (
        "<h2>تله‌متری فراخوانی‌ها</h2>\n"
        '<div class="tbl-scroll">\n'
        '<table border="1" cellpadding="4">\n'
        "<tr><th>بُعد</th><th>نام</th><th>فراخوانی</th>"
        "<th>توکن ورودی</th><th>توکن خروجی</th></tr>\n"
        + "\n".join(rows) + "\n</table>\n</div>")


def key_file_contains_value(path, value):
    """True iff the literal key VALUE appears anywhere in the file."""
    if not value:
        return False
    try:
        with open(path, encoding="utf-8") as handle:
            blob = handle.read()
    except OSError:
        return False
    return str(value) in blob


def env_key_present():
    """Indirection so tests can scan without touching real env files."""
    return os.environ.get("OPENCODE_ZEN_API_KEY", "")
