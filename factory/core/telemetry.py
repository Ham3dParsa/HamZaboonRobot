"""Factory LLM-call telemetry (stdlib only, hermetic).

Every record carries ``key_idx`` (the keyring index, an int) — never the
key VALUE. Token counts come from the Zen ``/responses`` ``usage`` block
when the transport surfaces it (see ``extract_usage``); missing usage is
tolerated as ``None`` (summaries treat it as 0).

Record shape (``record_call``):
{ts, stage, batch_id, key_idx, model, prompt_tokens|None,
 completion_tokens|None, latency_s, outcome, http_status|None}
"""

from __future__ import annotations

import html
import json
import os
import pathlib
from datetime import datetime, timezone

OUTCOMES = ("ok", "invalid", "fallback", "error", "auth")


def new_store() -> list:
    """Fresh in-memory call list (tests + runners own one each)."""
    return []


def now_ts() -> str:
    """UTC ISO timestamp for one record."""
    return datetime.now(timezone.utc).isoformat()


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
                latency_s=0.0, outcome="ok", http_status=None):
    """Append one call record. ``key_idx`` MUST be an int (never a key).

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
        "stage": str(stage or ""),
        "batch_id": batch_id,
        "key_idx": key_idx,
        "model": str(model or ""),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_s": round(latency, 3),
        "outcome": outcome if outcome in OUTCOMES else "error",
        "http_status": http_status,
    }
    store.append(entry)
    return entry


def _bucket():
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def summarize(calls):
    """Aggregate {by_stage, by_model, by_key_idx} (None tokens count 0)."""
    summary = {"by_stage": {}, "by_model": {}, "by_key_idx": {}}
    for call in calls or []:
        for dim, raw in (("by_stage", call.get("stage")),
                         ("by_model", call.get("model")),
                         ("by_key_idx", call.get("key_idx"))):
            key = str(raw)
            bucket = summary[dim].setdefault(key, _bucket())
            bucket["calls"] += 1
            for token_key in ("prompt_tokens", "completion_tokens"):
                try:
                    number = call.get(token_key)
                    bucket[token_key] += int(number) if number is not None \
                        else 0
                except (TypeError, ValueError):
                    pass
    summary["records"] = len(list(calls or []))
    return summary


def write_summary(path, calls):
    """Write telemetry_summary.json (summary + record count)."""
    summary = summarize(calls)
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
