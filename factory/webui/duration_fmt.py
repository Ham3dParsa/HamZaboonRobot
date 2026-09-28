"""Human duration + moment formatting for the factory web consoles (T02).

Single owner of web-console duration rendering — no duration logic in
``config/`` or ``services/utils/``. Pure functions only (no I/O, no
clock reads): the server passes ``elapsed`` seconds / ISO timestamps
in and renders the returned strings.

Fa digits use a local 1-line transliteration table (domain-agnostic,
stdlib only — the factory console never imports the bot-layer
``services.utils`` formatting seam). Jalali conversion uses
``jdatetime`` directly with a Gregorian fallback, mirroring the
existing repo helper's approach (that helper is bot-layer-bound via a
``config`` import, so the factory cannot reuse it without dragging
bot config into the console process).
"""

from __future__ import annotations

import datetime

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_FA_DECIMAL = "٫"


def _fa(value) -> str:
    """Latin digits (and ``.``) in ``value`` → Persian digits."""
    text = str(value)
    text = text.replace(".", _FA_DECIMAL)
    return text.translate(_FA_DIGITS)


def format_duration(seconds) -> str:
    """Monotonic seconds → Persian human string (fa digits, never raw float).

    - ``None`` / non-numeric / negative → ``"—"`` (honest empty).
    - ≤90s: ``N ثانیه`` (1 decimal under 10s, integer otherwise).
    - <90min: ``M دقیقه و S ثانیه`` (seconds omitted when 0).
    - else: ``H ساعت و M دقیقه`` (minutes omitted when 0).
    Never more than 1 decimal place.
    """
    try:
        total = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if total != total or total == float("inf") or total == float("-inf"):
        return "—"
    if total < 0:
        return "—"
    if total <= 90:
        if total < 10:
            shown = str(round(total, 1))
            if shown.endswith(".0"):
                shown = shown[:-2]
        else:
            shown = str(int(round(total)))
        return "%s ثانیه" % _fa(shown)
    if total < 90 * 60:
        minutes = int(total // 60)
        secs = int(round(total - minutes * 60))
        if secs >= 60:
            minutes += 1
            secs = 0
        if secs == 0:
            return "%s دقیقه" % _fa(minutes)
        return "%s دقیقه و %s ثانیه" % (_fa(minutes), _fa(secs))
    hours = int(total // 3600)
    minutes = int(round((total - hours * 3600) / 60))
    if minutes >= 60:
        hours += 1
        minutes = 0
    if minutes == 0:
        return "%s ساعت" % _fa(hours)
    return "%s ساعت و %s دقیقه" % (_fa(hours), _fa(minutes))


def _parse_iso(iso):
    """ISO string → aware UTC datetime, or None."""
    raw = str(iso or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        try:
            day = datetime.date.fromisoformat(raw)
            parsed = datetime.datetime.combine(day, datetime.time.min)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _relative_label(delta_seconds: float) -> str:
    """Past delta seconds → Persian smart-relative label."""
    if delta_seconds < 0:
        delta_seconds = 0
    if delta_seconds < 60:
        if delta_seconds < 10:
            return "لحظاتی پیش"
        return "%s ثانیه پیش" % _fa(int(delta_seconds))
    if delta_seconds < 3600:
        return "%s دقیقه پیش" % _fa(int(delta_seconds // 60))
    if delta_seconds < 24 * 3600:
        return "%s ساعت پیش" % _fa(int(delta_seconds // 3600))
    return "%s روز پیش" % _fa(int(delta_seconds // (24 * 3600)))


def _jalali_detail(utc_dt) -> str:
    """UTC datetime → ``شمسی … + میلادی …`` detail string (fa digits)."""
    try:
        from zoneinfo import ZoneInfo

        tehran = utc_dt.astimezone(ZoneInfo("Asia/Tehran"))
    except Exception:
        tehran = utc_dt
    gregorian = tehran.strftime("%Y-%m-%d %H:%M")
    try:
        import jdatetime as _jdatetime

        naive = tehran.replace(tzinfo=None)
        jd = _jdatetime.datetime.fromgregorian(datetime=naive)
        jalali = "%d/%02d/%02d %02d:%02d" % (
            jd.year, jd.month, jd.day, jd.hour, jd.minute)
        jalali = _fa(jalali)
    except Exception:
        jalali = _fa(gregorian)
    return "شمسی %s (Asia/Tehran) • میلادی %s (UTC)" % (
        jalali, _fa(utc_dt.strftime("%Y-%m-%d %H:%M")))


def format_moment(iso, now=None) -> dict:
    """ISO timestamp → ``{relative, detail}`` for history/dialog stamps.

    ``relative`` is the smart-relative primary label
    (``۵ دقیقه پیش``); ``detail`` carries the dual calendar
    (شمسی Asia/Tehran + میلادی UTC). Unparseable input → honest
    ``"—"`` pair (never raises).
    """
    parsed = _parse_iso(iso)
    if parsed is None:
        return {"relative": "—", "detail": "—"}
    if now is None:
        ref = datetime.datetime.now(datetime.timezone.utc)
    else:
        ref = _parse_iso(now)
        if ref is None:
            ref = datetime.datetime.now(datetime.timezone.utc)
    delta = (ref - parsed).total_seconds()
    return {"relative": _relative_label(delta),
            "detail": _jalali_detail(parsed)}
