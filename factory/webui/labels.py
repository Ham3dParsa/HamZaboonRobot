"""Human-annotation store (Step 5): operator judgments over screened senses.

Thin append-only JSONL store. One record per saved label — exactly
these fields, no more:

- ``sense_id`` — source sense identifier (non-empty).
- ``lemma`` — source lemma (non-empty).
- ``target_synset`` — target synset id, or null for none.
- ``verdict`` — human verdict: ``link`` or ``none`` (enum-validated).
- ``stratum`` — sampling stratum (non-empty free text, e.g. ``gold``).
- ``annotator`` — annotator id (non-empty).
- ``created_at`` — creation timestamp (UTC ISO8601, stamped here).

Labels are not secrets, so nothing is encrypted here; the store
follows the console's honesty rules instead: records carry the exact
command reference that replays them, and custom (non-gold) strata are
surfaced to the caller for watermarking. Unknown/extra fields are
rejected fail-closed (no silent narrowing).

No screening or ranking internals are imported here — the store only
persists operator judgments keyed by identifier + gloss (resolved by
the caller from the exported screened file).
"""

from __future__ import annotations

import datetime
import json
import os

VERDICTS = ("link", "none")


class LabelError(ValueError):
    """Validation or store failure (fail-closed, message only)."""


def _clean(value):
    try:
        return str(value or "").strip()
    except Exception:
        return ""


def validate_label(fields):
    """Validate + normalize one label dict (raises LabelError).

    Returns the exact 7-field record WITHOUT ``created_at`` (stamped
    at save time so every stored line has a server-side timestamp).
    """
    if not isinstance(fields, dict):
        raise LabelError("label must be an object")
    sense_id = _clean(fields.get("sense_id"))
    lemma = _clean(fields.get("lemma"))
    verdict = _clean(fields.get("verdict")).lower()
    stratum = _clean(fields.get("stratum"))
    annotator = _clean(fields.get("annotator"))
    if not sense_id:
        raise LabelError("sense_id is required")
    if not lemma:
        raise LabelError("lemma is required")
    if verdict not in VERDICTS:
        raise LabelError("verdict must be one of %s" % "/".join(VERDICTS))
    if not stratum:
        raise LabelError("stratum is required")
    if not annotator:
        raise LabelError("annotator is required")
    raw_target = (fields.get("target_synset")
                  if "target_synset" in fields
                  else fields.get("target"))
    if raw_target is None or (isinstance(raw_target, str)
                              and not raw_target.strip()):
        target = None
    elif isinstance(raw_target, str) and raw_target.strip():
        target = raw_target.strip()
    else:
        raise LabelError("target_synset must be a string id or null")
    if verdict == "link" and target is None:
        raise LabelError("verdict link needs a target_synset (none has null)")
    if verdict == "none" and target is not None:
        raise LabelError("verdict none needs target_synset null")
    return {"sense_id": sense_id, "lemma": lemma,
            "target_synset": target, "verdict": verdict,
            "stratum": stratum, "annotator": annotator}


def save_label(fields, store_path):
    """Validate, stamp, and append one JSONL line. Returns the record.

    ``created_at`` is always server-stamped UTC (a caller-supplied
    value is ignored — the store is the clock). Parent directories are
    created; the file is append-only (never rewritten).
    """
    rec = validate_label(fields)
    rec["created_at"] = datetime.datetime.now(
        datetime.timezone.utc).isoformat()
    try:
        blob = json.dumps(rec, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise LabelError("label not JSON-serializable: %s" % exc)
    try:
        parent = os.path.dirname(str(store_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(str(store_path), "a", encoding="utf-8") as handle:
            handle.write(blob + "\n")
    except OSError as exc:
        raise LabelError("store append failed (%s): %s"
                         % (store_path, exc))
    return rec


def load_labels(store_path):
    """Read the store; missing file -> []. Bad lines skipped (never crash)."""
    try:
        with open(str(store_path), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("sense_id"):
            out.append(rec)
    return out


def replay_reference(rec):
    """Replayable reference for one stored label (receipt display only)."""
    return "label sense_id=%s verdict=%s target=%s stratum=%s annotator=%s" % (
        rec.get("sense_id"), rec.get("verdict"),
        rec.get("target_synset"), rec.get("stratum"),
        rec.get("annotator"))
