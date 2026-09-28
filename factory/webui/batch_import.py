"""Operator-supervised arbitration batch import + approve (P04).

Staged lifecycle for one exported batch (frozen contracts in
``.opencode/plans/factory/plan-supervised-arbitration.md``):

- ``validate_answer_sheet(batch, text)`` — strict whole-batch check of
  the AI answer sheet (``{model, prompt_hash,
  verdicts:[{sense_id, verdict:link|none, target_synset|null}]}``).
  Any violation (unknown sense_id / bad enum / link-without-target /
  none-with-target / prompt_hash mismatch / model missing / coverage
  gap / duplicate / no JSON block) raises ``BatchImportError`` with a
  precise Persian message — the batch is rejected as a whole, never
  partially. The exception carries ``failing_ids`` (plain attribute)
  so the P06 repair composer can quote them with zero coupling.
- ``stage_import(batch_id, answer_sheet)`` — validates first (batch +
  labels untouched on failure), then stores the sheet under
  ``answers/`` and flips meta status to ``in_review``. Nothing is
  finalized yet (no ``labels.jsonl`` writes).
- ``approve(batch_id, ids, reviewer)`` — finalizes the operator-chosen
  subset: each id appended to ``labels.jsonl`` via
  ``labels.save_label`` (``annotator=f"gemini:<batch_id>"``,
  ``stratum="supervised"``), rejected ids left unlabeled so they
  return to the queue (meta ``sense_ids`` narrows to the approved set,
  so ``batches.judged_ids`` releases them after cancel), status
  ``imported`` with ``approved``/``returned`` counts and
  ``reviewed_by``. All labels are pre-validated before the first
  append (zero partial writes).
- Cancel stays in ``batches.cancel_batch`` (single owner, reused here
  only via tests) — this module defines no second cancel path.

New module only — routes are mounted by the coordinator (server.py
untouched here).
"""

from __future__ import annotations

import datetime
import json
import os
import uuid

from factory.webui import batches
from factory.webui import labels as _labels

VERDICTS = ("link", "none")

#: Label stratum for supervised-arbitration verdicts (labels schema
#: needs a non-empty stratum; these are operator-reviewed AI verdicts,
#: not gold).
STRATUM = "supervised"


class BatchImportError(ValueError):
    """Strict whole-batch import/approve failure (Persian message only)."""

    def __init__(self, message, failing_ids=None):
        super().__init__(message)
        self.failing_ids = list(failing_ids or [])


def _reject(message, failing_ids=None):
    raise BatchImportError("کل بسته رد شد: %s" % message,
                           failing_ids=failing_ids)


def _batch_field(batch, *names, default=""):
    for name in names:
        if isinstance(batch, dict):
            val = batch.get(name)
        else:
            val = getattr(batch, name, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if val is not None and name in ("items", "sense_ids"):
            return val
    return default


def _batch_items(batch):
    if isinstance(batch, dict):
        items = batch.get("items")
    else:
        items = getattr(batch, "items", None)
    return items if isinstance(items, list) else []


def _extract_json_block(text):
    """Strict JSON block extraction: whole text, else first {...} span."""
    if not isinstance(text, str):
        _reject("پاسخ‌نامه باید متن باشد.")
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    if start < 0:
        _reject("بلوک JSON در پاسخ‌نامه پیدا نشد.")
    depth = 0
    in_str = False
    esc = False
    for pos in range(start, len(text)):
        ch = text[pos]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:pos + 1])
                except ValueError:
                    _reject("بلوک JSON پاسخ‌نامه خراب است.")
    _reject("بلوک JSON در پاسخ‌نامه پیدا نشد.")


def validate_answer_sheet(batch, text):
    """Validate an AI answer sheet against a batch (pure, no disk writes).

    Returns the staged verdicts in batch item order:
    ``[{sense_id, verdict, target_synset}]``. Raises
    ``BatchImportError`` (whole-batch reject) on any violation.
    """
    payload = _extract_json_block(text)
    if not isinstance(payload, dict):
        _reject("پاسخ‌نامه باید یک آبجکت JSON باشد.")
    model = payload.get("model")
    if not (isinstance(model, str) and model.strip()):
        _reject("فیلد model خالی است (نام مدل هوش مصنوعی الزامی است).")
    want_hash = _batch_field(batch, "prompt_hash", "hash")
    got_hash = payload.get("prompt_hash")
    if not (isinstance(got_hash, str) and got_hash.strip()
            and got_hash.strip() == want_hash):
        _reject("prompt_hash پاسخ‌نامه با این بچ نمی‌خواند "
                "(نسخه پرامپت اشتباه است).")
    want_version = _batch_field(batch, "prompt_version", "version")
    got_version = payload.get("prompt_version")
    if (isinstance(got_version, str) and got_version.strip()
            and want_version and got_version.strip() != want_version):
        _reject("prompt_version پاسخ‌نامه (%s) با این بچ (%s) نمی‌خواند."
                % (got_version.strip(), want_version))
    verdicts = payload.get("verdicts")
    if not isinstance(verdicts, list):
        _reject("فیلد verdicts باید لیست باشد.")
    items = _batch_items(batch)
    by_id = {}
    order = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sid = item.get("sense_id")
        if isinstance(sid, str) and sid.strip() and sid.strip() not in by_id:
            by_id[sid.strip()] = item
            order.append(sid.strip())
    seen = set()
    staged = {}
    for entry in verdicts:
        if not isinstance(entry, dict):
            _reject("هر verdict باید یک آبجکت JSON باشد.")
        raw_sid = entry.get("sense_id")
        sid = raw_sid.strip() if isinstance(raw_sid, str) else ""
        if not sid:
            _reject("یک verdict بدون sense_id است.")
        if sid not in by_id:
            _reject("شناسه ناشناس «%s» در پاسخ‌نامه (جزو این بچ نیست)."
                    % sid, failing_ids=[sid])
        if sid in seen:
            _reject("شناسه تکراری «%s» در پاسخ‌نامه." % sid,
                    failing_ids=[sid])
        seen.add(sid)
        raw_verdict = entry.get("verdict")
        verdict = (raw_verdict.strip().lower()
                   if isinstance(raw_verdict, str) else "")
        if verdict not in VERDICTS:
            _reject("verdict نامعتبر «%s» برای %s (فقط link یا none)."
                    % (raw_verdict, sid), failing_ids=[sid])
        raw_target = entry.get("target_synset")
        if raw_target is None or (isinstance(raw_target, str)
                                  and not raw_target.strip()):
            target = None
        elif isinstance(raw_target, str) and raw_target.strip():
            target = raw_target.strip()
        else:
            _reject("target_synset برای %s باید شناسه یا null باشد."
                    % sid, failing_ids=[sid])
        if verdict == "link" and target is None:
            _reject("verdict=link برای %s بدون target_synset است."
                    % sid, failing_ids=[sid])
        if verdict == "none" and target is not None:
            _reject("verdict=none برای %s باید target_synset=null داشته باشد."
                    % sid, failing_ids=[sid])
        staged[sid] = {"sense_id": sid, "verdict": verdict,
                       "target_synset": target}
    missing = [sid for sid in order if sid not in staged]
    if missing:
        _reject("verdict برای %s جا افتاده (پوشش باید دقیق و کامل باشد)."
                % ", ".join(missing), failing_ids=missing)
    return [staged[sid] for sid in order]


def _check_id(batch_id):
    if (not isinstance(batch_id, str) or not batch_id.strip()
            or "/" in batch_id or "\\" in batch_id
            or batch_id.strip() in (".", "..")):
        raise ValueError("VALIDATION-unknown-batch: no batch %s"
                         % (batch_id,))
    return batch_id.strip()


def _load_batch(batch_id, data_root=None):
    """``(meta, items)`` from disk; unknown/corrupt -> VALIDATION error."""
    bid = _check_id(batch_id)
    base = batches.batch_dir(bid, data_root)
    try:
        with open(os.path.join(base, "batch.json"),
                  encoding="utf-8") as handle:
            meta = json.load(handle)
        with open(os.path.join(base, "batch.json-data"),
                  encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        raise ValueError("VALIDATION-unknown-batch: no batch %s" % (bid,))
    if (not isinstance(meta, dict) or meta.get("id") != bid
            or not isinstance(payload, dict)
            or not isinstance(payload.get("items"), list)):
        raise ValueError("VALIDATION-unknown-batch: no batch %s" % (bid,))
    return meta, payload


def _save_meta(base, meta, payload):
    with open(os.path.join(base, "batch.json"), "w",
              encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=1)
    payload["status"] = meta["status"]
    with open(os.path.join(base, "batch.json-data"), "w",
              encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def stage_import(batch_id, answer_sheet, data_root=None):
    """Validate + stage an answer sheet (status ``in_review``).

    Validates fully BEFORE any disk write (reject leaves batch +
    labels untouched). Returns ``{"staged": n}``.
    """
    bid = _check_id(batch_id)
    meta, payload = _load_batch(bid, data_root)
    if str(meta.get("status") or "") != "exported":
        _reject("بچ در وضعیت «%s» است؛ فقط بچ exported قابل ثبت پاسخ است."
                % (meta.get("status"),))
    batch_view = {"id": bid,
                  "prompt_hash": meta.get("prompt_hash", ""),
                  "prompt_version": meta.get("prompt_version", ""),
                  "items": payload["items"]}
    staged = validate_answer_sheet(batch_view, answer_sheet)
    try:
        parsed = _extract_json_block(answer_sheet)
        model = parsed.get("model", "").strip()
    except BatchImportError:  # pragma: no cover - validated above
        model = ""
    base = batches.batch_dir(bid, data_root)
    answers_dir = os.path.join(base, "answers")
    os.makedirs(answers_dir, exist_ok=True)
    name = "staged-%s-%s.json" % (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        uuid.uuid4().hex[:6])
    with open(os.path.join(answers_dir, name), "w",
              encoding="utf-8") as handle:
        json.dump({"model": model,
                   "prompt_hash": meta.get("prompt_hash", ""),
                   "received_at": _stamp(),
                   "verdicts": staged},
                  handle, ensure_ascii=False, indent=1)
    meta["status"] = "in_review"
    meta["answered"] = len(staged)
    meta["approved"] = 0
    meta["model"] = model
    meta["staged_at"] = _stamp()
    _save_meta(base, meta, payload)
    return {"staged": len(staged)}


def load_staged(batch_id, data_root=None):
    """Latest staged verdicts for a batch (``[]`` when nothing staged)."""
    bid = _check_id(batch_id)
    answers_dir = os.path.join(batches.batch_dir(bid, data_root), "answers")
    try:
        names = sorted(os.listdir(answers_dir))
    except OSError:
        return []
    for name in reversed(names):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(answers_dir, name),
                      encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and isinstance(
                record.get("verdicts"), list):
            return record["verdicts"]
    return []


def approve(batch_id, ids, reviewer, data_root=None, labels_path=None):
    """Finalize the operator-approved subset into ``labels.jsonl``.

    Returns ``{"finalized": n, "returned": m}``; rejected (staged but
    unapproved) ids stay unlabeled and return to the queue. All labels
    are pre-validated before the first append (zero partial writes).
    """
    bid = _check_id(batch_id)
    if not (isinstance(reviewer, str) and reviewer.strip()):
        _reject("نام داور (reviewer) خالی است.")
    meta, payload = _load_batch(bid, data_root)
    if str(meta.get("status") or "") != "in_review":
        _reject("بچ در وضعیت «%s» است؛ اول باید پاسخ‌نامه ثبت (stage) شود."
                % (meta.get("status"),))
    staged = load_staged(bid, data_root)
    staged_by_id = {v.get("sense_id"): v for v in staged
                    if isinstance(v, dict) and v.get("sense_id")}
    if not staged_by_id:
        _reject("پاسخ ثبت‌شده‌ای برای این بچ پیدا نشد.")
    want = []
    for sid in ids or []:
        text = sid.strip() if isinstance(sid, str) else ""
        if text and text not in want:
            want.append(text)
    unknown = [sid for sid in want if sid not in staged_by_id]
    if unknown:
        _reject("شناسه «%s» در پاسخ ثبت‌شده این بچ نیست."
                % ", ".join(unknown), failing_ids=unknown)
    lemma_by_id = {}
    for item in payload["items"]:
        if isinstance(item, dict) and item.get("sense_id"):
            lemma_by_id[item["sense_id"]] = item.get("lemma", "")
    fields = []
    for sid in want:
        verdict = staged_by_id[sid]
        try:
            fields.append(_labels.validate_label({
                "sense_id": sid,
                "lemma": lemma_by_id.get(sid, ""),
                "target_synset": verdict.get("target_synset"),
                "verdict": verdict.get("verdict"),
                "stratum": STRATUM,
                "annotator": "gemini:%s" % bid,
            }))
        except _labels.LabelError as exc:
            _reject("برچسب %s نامعتبر است (%s)." % (sid, exc),
                    failing_ids=[sid])
    store = labels_path or batches.default_labels_path(data_root)
    for field in fields:
        _labels.save_label(field, store)
    staged_ids = [v["sense_id"] for v in staged]
    returned = [sid for sid in staged_ids if sid not in set(want)]
    meta["status"] = "imported"
    meta["approved"] = len(want)
    meta["returned"] = len(returned)
    meta["reviewed_by"] = reviewer.strip()
    meta["approved_at"] = _stamp()
    meta["approved_ids"] = want
    meta["returned_ids"] = returned
    meta["sense_ids"] = want
    _save_meta(batches.batch_dir(bid, data_root), meta, payload)
    return {"finalized": len(want), "returned": len(returned)}
