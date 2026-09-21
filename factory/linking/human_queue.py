"""Human escalation queue sink (HQ tickets, deep module, stdlib only).

Single owner of the ``reports/linker/human_escalation_queue.jsonl`` record
shape. No I/O except the sink append (:func:`enqueue_escalation`) and the
reader (:func:`load_queue_deduped`); no network, no model calls, no imports
outside the stdlib.

Record schema (one JSON object per line)::

    {
      "queue_id": "esc-{lemma}-{pos}-{sense_id}",
      "created_at": "<ISO8601-UTC>",
      "escalation_reason": "<veto name(s)>",
      "source_entry": {...} | None,
      "candidates": [...] | None,
      "signals_trace": {...} | [...] | None,
      "arbiter_trace": {...} | [...] | None,
      "human_resolution": "PENDING",
    }

Identity fields (``lemma`` / ``pos`` / ``sense_id`` /
``escalation_reason``) are REQUIRED and non-empty; everything else is
nullable — the online enrich path carries no jaccard/votes, so
``candidates`` / ``signals_trace`` / ``arbiter_trace`` routinely arrive
empty or absent. I/O failures raise :class:`HumanQueueError`; the caller
(pipeline enrich seam, HQ7) catches it, warns, and continues — the run
never fails on the queue.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

HUMAN_RESOLUTION_PENDING = "PENDING"

_QUEUE_ID_PREFIX = "esc-"

# Path separators + whitespace never survive into a queue_id (the id is
# safe to embed in file names / logs without directory traversal).
_SANITIZE_RX = re.compile(r"[/\\\s]+")


class HumanQueueError(Exception):
    """Module-specific error: validation or sink I/O failure."""


def _clean(value):
    """Strip a value to text ("" for missing/hostile shapes)."""
    try:
        return str(value or "").strip()
    except Exception:
        return ""


def _sanitize_component(value):
    """One queue_id component: no path separators / whitespace."""
    cleaned = _SANITIZE_RX.sub("-", _clean(value))
    return cleaned.strip("-")


def _utc_now_iso():
    """Current UTC time as ISO8601 (``+00:00`` offset, stdlib only)."""
    return datetime.now(timezone.utc).isoformat()


def build_queue_id(lemma, pos, sense_id):
    """``esc-{lemma}-{pos}-{sense_id}`` (sanitized, deterministic).

    Raises :class:`HumanQueueError` when any component is missing/empty
    (after sanitizing — a component of only separators is empty).
    """
    parts = [_sanitize_component(lemma), _sanitize_component(pos),
             _sanitize_component(sense_id)]
    if not all(parts):
        raise HumanQueueError(
            "identity fields required: lemma/pos/sense_id (got %r)"
            % ((lemma, pos, sense_id),))
    return _QUEUE_ID_PREFIX + "-".join(parts)


def _nullable_list(value):
    """Pass-through for nullable trace fields (None stays None)."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def _source_entry(record, lemma, pos, sense_id):
    """Nullable source entry: caller's dict wins, else identity minimum."""
    try:
        entry = (record or {}).get("source_entry")
    except AttributeError:
        entry = None
    if isinstance(entry, dict):
        out = dict(entry)
        out.setdefault("lemma", lemma)
        out.setdefault("pos", pos)
        out.setdefault("sense_id", sense_id)
        return out
    if entry is not None and not isinstance(entry, dict):
        return None
    minimal = {"lemma": lemma, "pos": pos, "sense_id": sense_id}
    try:
        gloss = (record or {}).get("gloss")
        if gloss is None:
            gloss = (record or {}).get("winner_gloss", "")
    except AttributeError:
        gloss = ""
    if _clean(gloss):
        minimal["gloss"] = _clean(gloss)
    return minimal


def enqueue_escalation(record, sink_path):
    """Validate, stamp, and append one JSONL line. Returns ``queue_id``.

    ``record`` carries the identity fields (``lemma`` / ``pos`` /
    ``sense_id`` / ``escalation_reason``) plus any nullable extras
    (``source_entry`` / ``candidates`` / ``signals_trace`` /
    ``arbiter_trace`` / ``created_at``). ``sink_path`` is injected by
    the caller (tests pass a ``tmp_path`` file; the pipeline resolves
    its default against the run output root). Parent directories are
    created; the file is opened in append mode (multi-row runs append
    one line per veto row). Any validation or I/O failure raises
    :class:`HumanQueueError`.
    """
    if not isinstance(record, dict):
        raise HumanQueueError("record must be a dict (got %r)"
                              % type(record).__name__)
    lemma, pos, sense_id = (_clean(record.get("lemma")),
                            _clean(record.get("pos")),
                            _clean(record.get("sense_id")))
    reason = _clean(record.get("escalation_reason"))
    if not lemma or not pos or not sense_id or not reason:
        raise HumanQueueError(
            "identity fields required: lemma/pos/sense_id + "
            "escalation_reason (all non-empty)")
    queue_id = build_queue_id(lemma, pos, sense_id)
    try:
        created_at = record.get("created_at")
    except AttributeError:
        created_at = None
    created_at = _clean(created_at) or _utc_now_iso()

    def _trace(*names):
        for name in names:
            try:
                value = record.get(name)
            except AttributeError:
                continue
            if value is not None:
                return value
        return None

    line = {
        "queue_id": queue_id,
        "created_at": created_at,
        "escalation_reason": reason,
        "source_entry": _source_entry(record, lemma, pos, sense_id),
        "candidates": _nullable_list(_trace("candidates")),
        "signals_trace": _trace("signals_trace", "signals"),
        "arbiter_trace": _trace("arbiter_trace", "arbiter"),
        "human_resolution": HUMAN_RESOLUTION_PENDING,
    }
    try:
        blob = json.dumps(line, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HumanQueueError("record not JSON-serializable: %s" % exc)
    try:
        import os as _os
        parent = _os.path.dirname(str(sink_path))
        if parent:
            _os.makedirs(parent, exist_ok=True)
        with open(str(sink_path), "a", encoding="utf-8") as handle:
            handle.write(blob + "\n")
    except OSError as exc:
        raise HumanQueueError("sink append failed (%s): %s"
                              % (sink_path, exc))
    return queue_id


def load_queue_deduped(sink_path):
    """Read the sink; same ``queue_id`` keeps the latest ``created_at``.

    Missing file -> ``[]``. Blank/corrupt lines are skipped (the queue
    never breaks its reader). Records without a ``queue_id`` are
    skipped. Ties (equal/missing ``created_at``) keep the later line.
    Returns a ``created_at``-ordered list (deterministic).
    """
    try:
        with open(str(sink_path), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []
    latest = {}
    order = {}
    for pos, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        queue_id = _clean(rec.get("queue_id"))
        if not queue_id:
            continue
        stamp = _clean(rec.get("created_at"))
        prev = latest.get(queue_id)
        prev_stamp = _clean((prev or {}).get("created_at"))
        if prev is None or (stamp,) >= (prev_stamp,):
            latest[queue_id] = rec
            order[queue_id] = pos
    return [latest[key] for key in
            sorted(latest, key=lambda k: (_clean(latest[k].get("created_at")),
                                          order[k], k))]
