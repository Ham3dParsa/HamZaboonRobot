"""Jalali/date leaf of the formatting seam (REF2-T2).

Verbatim home of the date renderings split out of
``services/utils/formatting.py``: :func:`_to_jalali_str` (alias
:func:`to_jalali_str`), the ``_JALALI_MONTHS``/``_JALALI_WEEKDAYS`` constants,
:func:`_parse_iso_to_app_tz` (alias :func:`parse_iso_to_app_tz`), the day/time
labels, the reports group-key + day-key validators, and the relative-date
helpers (``_app_date``, ``_jalali_day_month``, ``_relative_next_review``).
``formatting.py`` keeps a re-export shim so every existing
``from services.utils.formatting import ...`` caller works unchanged.

Leaf-import law: ``datetime``/``re`` stdlib + ``config`` (``APP_TZ``,
``_app_today``) + the T1 leaf ``services/utils/formatting_escape.py``
(:func:`to_persian_digits`, never duplicated). This module must never import
``services.utils.formatting_cards`` — the cards leaf imports this one
(one-directional, no cycle).
"""

import datetime
import re

try:
    import jdatetime as _jdatetime
    jdatetime = _jdatetime
except Exception:  # pragma: no cover — fallback when jdatetime not installed
    jdatetime = None  # type: ignore[assignment]

from config import APP_TZ, _app_today
from services.utils.formatting_escape import to_persian_digits


def _to_jalali_str(iso_str: str) -> str:
    """Convert an ISO datetime/date string to Jalali ``YYYY/MM/DD HH:MM`` with Persian digits.

    Parses ``iso_str`` via ``datetime.fromisoformat`` (handles ``Z`` suffix),
    converts through ``jdatetime.datetime.fromgregorian`` when available, and
    falls back to Gregorian formatting when ``jdatetime`` is absent or parsing
    fails. All digits are Persian via :func:`to_persian_digits`.
    Returns ``""`` for empty input and Persian-digit fallback for unparseable input.
    """
    if not iso_str:
        return ""
    # Normalise trailing Z to +00:00 for fromisoformat
    raw = iso_str.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        # Try date-only
        try:
            d = datetime.date.fromisoformat(raw)
            dt = datetime.datetime.combine(d, datetime.time.min)
        except (TypeError, ValueError):
            return to_persian_digits(iso_str)
    # jdatetime path — requires Gregorian datetime; strip tzinfo for conversion
    if jdatetime is not None:
        try:
            greg = dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
            jd = jdatetime.datetime.fromgregorian(datetime=greg)
            formatted = f"{jd.year}/{jd.month:02d}/{jd.day:02d} {jd.hour:02d}:{jd.minute:02d}"
            return to_persian_digits(formatted)
        except Exception:
            pass
    # Fallback: Gregorian formatted the same way
    try:
        formatted = dt.strftime("%Y/%m/%d %H:%M")
        return to_persian_digits(formatted)
    except Exception:
        return to_persian_digits(iso_str)


# Public alias (Q2 spec says _to_jalali_str, but expose friendly name too).
to_jalali_str = _to_jalali_str


# ---------------------------------------------------------------------------
# Session Summary Report rendering (R2–R9)
# ---------------------------------------------------------------------------

# Jalali month names (jdatetime month number 1..12 → Persian).
_JALALI_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)

# Persian weekday names Monday=0 -> دوشنبه ... Sunday=6 -> یکشنبه ; derived from Gregorian weekday.
_JALALI_WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")


def _weekday_name(dt: datetime.date) -> str:
    """Persian weekday for a Gregorian date."""
    return _JALALI_WEEKDAYS[dt.weekday()]


def _parse_iso_to_app_tz(iso_str: str) -> datetime.datetime | None:
    """Parse ISO string and convert to APP_TZ. Returns None on failure."""
    if not iso_str or not isinstance(iso_str, str):
        return None
    raw = iso_str.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    try:
        return dt.astimezone(APP_TZ)
    except Exception:
        return dt


def jalali_day_label(iso_str: str) -> str:
    """Convert UTC ISO datetime to Tehran Jalali day label.

    Returns "{weekday} {day} {month} {year}" with Persian digits, e.g.
    "جمعه ۹ خرداد ۱۴۰۴". Falls back to Gregorian "YYYY/MM/DD weekday" style
    when jdatetime unavailable. Returns "—" for empty/invalid input.
    """
    if not iso_str or not isinstance(iso_str, str):
        return "—"
    dt_app = _parse_iso_to_app_tz(iso_str)
    if dt_app is None:
        return "—"
    greg_date = dt_app.date()
    weekday = _weekday_name(greg_date)
    if jdatetime is not None:
        try:
            jd = jdatetime.date.fromgregorian(date=greg_date)
            return to_persian_digits(f"{weekday} {jd.day} {_JALALI_MONTHS[jd.month - 1]} {jd.year}")
        except Exception:
            pass
    # Fallback: Gregorian numeric with Persian digits + weekday (no Jalali month when jdatetime absent)
    return to_persian_digits(f"{weekday} {greg_date.day}/{greg_date.month}/{greg_date.year}")


def jalali_time_label(iso_str: str) -> str:
    """Convert UTC ISO datetime to Tehran HH:MM with Persian digits.

    Returns "—" for empty/invalid input.
    """
    if not iso_str or not isinstance(iso_str, str):
        return "—"
    dt_app = _parse_iso_to_app_tz(iso_str)
    if dt_app is None:
        return "—"
    return to_persian_digits(f"{dt_app.hour:02d}:{dt_app.minute:02d}")


def reports_jalali_group_key(iso_str: str) -> str:
    """Gregorian YYYY-MM-DD in APP_TZ for /reports grouping (R6, single source)."""
    dt_app = _parse_iso_to_app_tz(iso_str)
    if dt_app is None:
        s = (iso_str or "").strip()
        return s[:10] if len(s) >= 10 else ""
    return dt_app.date().isoformat()


# Public alias — config/handlers must import this, not the private _parse helper.
parse_iso_to_app_tz = _parse_iso_to_app_tz

# Single source for reports day-key validation + sort (Kilo §3)
_ISO_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_iso_day_key(s: str) -> bool:
    """True if s is YYYY-MM-DD (reports day key)."""
    return bool(_ISO_DAY_RE.match(s or ""))


def reports_day_sort_key(k: str) -> tuple[int, str]:
    """Sort key for reports day keys: ISO days first (DESC), fallback last."""
    return (1, k) if _ISO_DAY_RE.match(k or "") else (0, k)


def _app_date() -> datetime.date:
    """Today's date in the application timezone (``APP_TIMEZONE``).

    Stored ``next_review_at``/prior dates are derived from app-time timestamps
    (``words.py`` ``astimezone(APP_TZ)``), so the relative-date baseline must be
    the app day too — otherwise labels flip at local midnight. Falls back to the
    config ``_app_today()`` source of truth.
    """
    return datetime.date.fromisoformat(_app_today())


def _jalali_day_month(iso_date: str) -> str:
    """Convert an ISO ``YYYY-MM-DD`` to ``{day} {jalali month name}`` with
    Persian digits (e.g. ``۲۹ مرداد``). Falls back to Gregorian day/month when
    jdatetime is unavailable."""
    d = datetime.date.fromisoformat(iso_date)
    if jdatetime is not None:
        try:
            j = jdatetime.date.fromgregorian(date=d)
            return to_persian_digits(f"{j.day} {_JALALI_MONTHS[j.month - 1]}")
        except Exception:
            pass
    # Fallback: Gregorian month name via Jalali array (approximate) or numeric
    return to_persian_digits(f"{d.day} {_JALALI_MONTHS[d.month - 1]}")


def _relative_next_review(iso_date: str, today: datetime.date) -> str:
    """Relative-first date for the ``بعدی`` field (R3).

    today→امروز, +1→فردا, +2→پس‌فردا, +3..6→«{n} روز دیگه», ≥7 (or past)→Jalali
    absolute date. Returns "" for an unparseable date.
    """
    try:
        d = datetime.date.fromisoformat(iso_date)
    except (TypeError, ValueError, AttributeError):
        return ""
    delta = (d - today).days
    if delta < 0:
        return _jalali_day_month(iso_date)
    if delta == 0:
        return "امروز"
    if delta == 1:
        return "فردا"
    if delta == 2:
        return "پس‌فردا"
    if delta <= 6:
        return f"{to_persian_digits(delta)} روز دیگه"
    return _jalali_day_month(iso_date)
