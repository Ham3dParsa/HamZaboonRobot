"""Operator repair-request composer (P06).

Builds the copy-ready Persian text the operator pastes back into the AI
chat after a strict whole-batch import reject (R3). Pure function over
plain data — deliberately decoupled from ``batch_import`` internals
(P04 sibling owns validation; this module only formats).

Input shapes (tolerant, never crash):

- ``batch``: dict with ``id`` (or ``batch_id``), ``prompt_version``,
  ``prompt_hash``, plus ``sense_ids`` and/or ``items`` ([{sense_id}]).
  Objects with the same attribute names (e.g. P01 ``BatchRecord``)
  are accepted too.
- ``error``: dict with ``message`` (or ``error``/``detail``) + failing
  ids under ``sense_ids``/``failing_ids``/``ids``; or a plain string;
  or an exception (``str(exc)`` is used).
"""

from __future__ import annotations


def _field(obj, *names, default=""):
    for name in names:
        if isinstance(obj, dict):
            val = obj.get(name)
        else:
            val = getattr(obj, name, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return default


def _failing_ids(error):
    if isinstance(error, dict):
        for key in ("sense_ids", "failing_ids", "ids", "failing_sense_ids"):
            raw = error.get(key)
            if isinstance(raw, (list, tuple)):
                ids = [str(v).strip() for v in raw if str(v).strip()]
                if ids:
                    return ids
            elif isinstance(raw, str) and raw.strip():
                return [raw.strip()]
    return []


def _error_lines(error):
    if isinstance(error, dict):
        for key in ("message", "error", "detail", "text"):
            val = error.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    elif isinstance(error, BaseException):
        text = str(error).strip()
        return text if text else repr(error)
    elif isinstance(error, str) and error.strip():
        return error.strip()
    return str(error).strip() if error is not None else ""


def compose_repair_request(batch, error) -> str:
    """Copy-ready Persian repair text for a rejected batch."""
    batch_id = _field(batch, "id", "batch_id", default="?")
    version = _field(batch, "prompt_version", "version", default="?")
    phash = _field(batch, "prompt_hash", "hash", default="?")
    failing = _failing_ids(error)
    err_text = _error_lines(error)

    lines = []
    lines.append("درخواست اصلاح پاسخ داوری (batch %s)" % batch_id)
    lines.append("")
    lines.append("شناسه بچ: %s" % batch_id)
    lines.append("نسخه پرامپت: %s" % version)
    lines.append("هش پرامپت: %s" % phash)
    lines.append("")
    if failing:
        lines.append("شناسه‌های خطادار (%d): %s"
                     % (len(failing), ", ".join(failing)))
        lines.append("")
    lines.append("متن دقیق خطا:")
    lines.append(err_text if err_text else "(بدون پیام خطا)")
    lines.append("")
    lines.append("لطفاً کل پاسخ‌نامه (full answer sheet) را اصلاح‌شده و کامل، "
                 "فقط و فقط (ONLY) در قالب JSON "
                 "دوباره صادر کنید؛ اصلاح جزئی یا تکه‌تکه نفرستید.")
    lines.append("فیلدهای model و prompt_hash (%s) را حفظ کنید." % phash)
    lines.append("")
    return "\n".join(lines)
