"""Nudge catalog + silence policy (issue #467, dims 1/5/6).

Pure domain module: no Telegram imports, no DB writes, no schema changes,
no AI calls. All data arrives as arguments from the caller.

Bounded-read contract (documented for the caller, enforced by the caller):
a nudge tick performs at most 3 bounded reads — session budget via
``scheduling.daily_session_budget`` (or ``_get_used``), open session via
``db.load_study_session``, due cards via ``db.due_words_for_user`` — plus
the ``get_user`` row when the caller does not already hold plan/lang, and
(only for the M04 anti-starvation check) ``review_events`` first-exposure
dates to derive the last-fresh-card date. Results should be cached per tick.

Daily/window caps use ``settings`` keys (no new tables):
``nudges_sent_{user_id}_{YYYY-MM-DD}`` (day count) and
``nudges_sent_{user_id}_{YYYY-MM-DD}_{window}`` (window count). This module
only computes the key names and the pure ``can_send`` predicate; the caller
owns the atomic read/increment (same-transaction check+write, never held
across an await).

Theme slots (``{target_heat_theme}``, ``{theme_shield_event}``) are resolved
by the CALLER: ``config/themes.py`` does not exist yet, so callers pass
plain strings. Documented seam: when a themes module lands, callers switch
to it without touching this module.

Render contract: all ``render_*`` output is RAW text (no MarkdownV2
escaping) and must ride ``Plain`` spans — the send-site renderer escapes
exactly once. Naive datetimes: APP_TZ for quiet/windows helpers, UTC for
``hours_between`` (documented per function).
"""

from __future__ import annotations

import datetime

from config import APP_TZ

# Quiet hours: APP_TZ wall time in [23:00, 08:00).
QUIET_START_HOUR = 23
QUIET_END_HOUR = 8

# Send windows on APP_TZ wall time (owner lock 2026-09-07).
WINDOW_MORNING = "morning"  # 08:00-12:00
WINDOW_NOON = "noon"  # 12:00-17:00
WINDOW_EVENING = "evening"  # 17:00-23:00
WINDOW_NIGHT = "night"  # 23:00-08:00 (quiet, never send)

# At most one nudge per window, at most two per APP_TZ calendar day.
MAX_SENDS_PER_WINDOW = 1
MAX_SENDS_PER_DAY = 2

# M04 anti-starvation: no fresh cards for this many consecutive days.
M04_STARVATION_DAYS = 3

# Priority order, at most ONE nudge per window (owner lock):
# 1:M03 streak-at-risk, 2:M06 unfinished, 3:M08 one-step-to-40%,
# 4:M05/M09 dues, 5:M04 teaser. A starved M04 (see should_promote_m04)
# jumps to priority 2, ahead of M06 (tie-break: teaser-after-starvation
# outranks resuming, because a 3-day-starved learner has nothing to resume
# toward; documented owner-gap fill).
_PRIORITY = ("M03", "M04", "M06", "M08", "M05", "M09")
_PRIORITY_NORMAL = ("M03", "M06", "M08", "M05", "M09", "M04")

# Template registry M01-M09, EXACT owner Persian copy (dim-1 lock).
# M10 intentionally absent here: it aliases
# services.session.summary.pick_motivation (deterministic 2-tip block) —
# see m10_for_report. No duplicate copy per lock.
NUDGE_TEMPLATES: dict[str, str] = {
    "M01": "اون {count} {content_type} سخت این نشست، حدود {hours} ساعت دیگه برمی‌گردن؛ یه نشستت رو برای اون موقع نگه دار تا بهشون به موقع رسیدگی کنیم.",
    "M02": "{shield_emoji} «دیروز فرصت نشد سر بزنی؛ {theme_shield_event}. حواست باشه، برای حفظ پیوستگی باید امروز حتماً یه نشست بری!»",
    "M03": "امروز هنوز به هم‌زبان سر نزدی؛ حیف پیوستگی {streak} روزه‌ت نیست؟ با یه نشست ۳ دقیقه‌ای {next_streak} روزش کن! 🔥",
    "M04": "چند تا {content_type} تازه برات آماده کردم؛ میای چند دقیقه درس بخونیم؟",
    "M05": "نوبت مرور چندتا {content_type} رسیده؛ بیا با یه نشست کوتاه سبک و مرتبشون کنیم.",
    "M06": "یه نشست نصفه‌کاره داری که چندتا کارتش مونده؛ وقت داری سریع با هم ببندیمش؟",
    "M07": "هنوز {remaining} نشست از سهمیه امروزت مونده؛ سرت خلوت شد یکیش رو بریم؟",
    "M08": "فقط یه نشست تا {target_heat_theme} مونده؛ همینو بری وضعیت امروزت می‌درخشه!",
    "M09": "چند تا {content_type} برای امشب آماده مرور شدن؛ وقت داری یه دور سریع بزنیم؟",
    # M10: alias of services.session.summary.pick_motivation (no copy here)
    # — see M10_ALIAS + m10_for_report. No "M10" key: the registry stays pure
    # Persian send text, never the "pick_motivation" seam literal.
}

M10_ALIAS = "services.session.summary.pick_motivation"


def _to_app_tz(now_dt: datetime.datetime) -> datetime.datetime:
    """Coerce to APP_TZ wall time (naive input assumed APP_TZ)."""
    if now_dt.tzinfo is None:
        return now_dt.replace(tzinfo=APP_TZ)
    return now_dt.astimezone(APP_TZ)


def is_quiet_hours(now_dt: datetime.datetime) -> bool:
    """True iff APP_TZ wall time of ``now_dt`` is in [23:00, 08:00)."""
    local = _to_app_tz(now_dt)
    return local.hour >= QUIET_START_HOUR or local.hour < QUIET_END_HOUR


def window_for(now_dt: datetime.datetime) -> str:
    """APP_TZ send window for ``now_dt``: morning/noon/evening/night."""
    local = _to_app_tz(now_dt)
    if local.hour < QUIET_END_HOUR or local.hour >= QUIET_START_HOUR:
        return WINDOW_NIGHT
    if local.hour < 12:
        return WINDOW_MORNING
    if local.hour < 17:
        return WINDOW_NOON
    return WINDOW_EVENING


def evaluate_silence(
    user_id: int,
    session_budget: dict | int,
    active_session_exists: bool,
    due_count: int,
    has_new_cards: bool = False,
) -> bool:
    """Hard-silence predicate: True means send NOTHING this tick.

    True iff a session is open, OR the daily budget is exhausted
    (remaining == 0), OR there is nothing to study
    (due == 0 and no Tier-2 new cards). ``session_budget`` is the
    ``scheduling.daily_session_budget`` dict (``remaining`` key) or a bare
    remaining int. ``user_id`` is carried for the counter-key seam only
    (no reads/writes here).
    """
    _ = user_id
    if active_session_exists:
        return True
    if isinstance(session_budget, dict):
        remaining = session_budget.get("remaining", 0)
    else:
        remaining = session_budget
    try:
        remaining = int(remaining)
    except (TypeError, ValueError):
        remaining = 0
    if remaining <= 0:
        return True
    try:
        due = int(due_count)
    except (TypeError, ValueError):
        due = 0
    return due <= 0 and not has_new_cards


def should_defer_m02(now_dt: datetime.datetime) -> bool:
    """M02 has NO quiet exemption: in quiet hours it defers to the first
    tick >= 08:00 next day (caller holds it until then)."""
    return is_quiet_hours(now_dt)


def should_promote_m04(
    days_without_fresh: int, tier2_ready: bool, window: str
) -> bool:
    """M04 anti-starvation: no fresh cards for >=3 consecutive days AND
    Tier-2 words ready promotes M04 to priority 2, noon window only.

    ``days_without_fresh`` derives from ``review_events`` first_exposure
    dates (bounded caller read, APP_TZ calendar days).
    """
    try:
        days = int(days_without_fresh)
    except (TypeError, ValueError):
        return False
    return days >= M04_STARVATION_DAYS and bool(tier2_ready) and window == WINDOW_NOON


def select_nudge(
    *,
    m03: bool = False,
    m06: bool = False,
    m08: bool = False,
    m05: bool = False,
    m09: bool = False,
    m04: bool = False,
    m04_promoted: bool = False,
) -> str | None:
    """Pick at most ONE nudge id by priority; None when nothing eligible.

    Flags mirror message ids (caller maps its own conditions). Promoted M04
    jumps to priority 2 (ahead of M06); a normal M04 stays last.
    ``m04_promoted=True`` implies M04 eligibility even when ``m04=False``.
    """
    eligible = {
        "M03": m03,
        "M06": m06,
        "M08": m08,
        "M05": m05,
        "M09": m09,
        "M04": m04 or m04_promoted,
    }
    order = _PRIORITY if m04_promoted else _PRIORITY_NORMAL
    for mid in order:
        if eligible[mid]:
            return mid
    return None


def nudge_counter_key(user_id: int, date_str: str) -> str:
    """Settings key for the per-day send counter (no new tables)."""
    return f"nudges_sent_{int(user_id)}_{date_str}"


def nudge_window_key(user_id: int, date_str: str, window: str) -> str:
    """Settings key for the per-window send counter (no new tables)."""
    return f"nudges_sent_{int(user_id)}_{date_str}_{window}"


def can_send(sent_in_window: int, sent_today: int) -> bool:
    """Pure cap predicate: <1 per window and <2 per APP_TZ calendar day.

    Defense note: the caller reads both counters and increments them in ONE
    synchronous settings transaction (check+write atomic, never held across
    an await); concurrent ticks serialize on the caller's per-user lock.
    """
    try:
        w = int(sent_in_window)
    except (TypeError, ValueError):
        w = MAX_SENDS_PER_WINDOW
    try:
        d = int(sent_today)
    except (TypeError, ValueError):
        d = MAX_SENDS_PER_DAY
    return w < MAX_SENDS_PER_WINDOW and d < MAX_SENDS_PER_DAY


def _slot(value: object) -> str:
    """One template slot: Persian digits, NO MarkdownV2 escaping.

    ``render_*`` output is raw and must ride ``Plain`` spans so the
    send-site renderer escapes it exactly once (pre-escaping here would
    double-escape on the MDV2 backend).
    """
    from services.utils.formatting import to_persian_digits

    return to_persian_digits(str(value))


def hours_between(
    now_dt: datetime.datetime, next_review_at: datetime.datetime
) -> int:
    """Rounded hours from ``now_dt`` to a grade ``next_review_at`` (>=1).

    Both are exact timestamps (words.py GradeResult.next_review_at, UTC).
    Naive inputs are assumed UTC.
    """
    utc = datetime.timezone.utc
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=utc)
    if next_review_at.tzinfo is None:
        next_review_at = next_review_at.replace(tzinfo=utc)
    seconds = (next_review_at - now_dt).total_seconds()
    return max(1, round(seconds / 3600))


def m01_due_today(records, today_str: str) -> list:
    """Records graded 1/2 whose next review falls on ``today_str``.

    ``today_str`` is the APP_TZ calendar day (YYYY-MM-DD); records carry
    ``grade`` + ``next_review_date`` (cf. WordReviewRecord). ``tomorrow``
    rows stay fully silent per lock.
    """
    out = []
    for r in records or ():
        grade = getattr(r, "grade", None)
        if grade not in (1, 2):
            continue
        if getattr(r, "next_review_date", None) == today_str:
            out.append(r)
    return out


def render_m01(count: object, content_type: str, hours: object) -> str:
    """Render M01 raw (ride a ``Plain`` span; escaped once at send)."""
    return NUDGE_TEMPLATES["M01"].format(
        count=_slot(count), content_type=_slot(content_type), hours=_slot(hours)
    )


def render_m02(shield_emoji: str, theme_shield_event: str) -> str:
    """Render M02; theme slot is a caller-provided plain string (seam)."""
    return NUDGE_TEMPLATES["M02"].format(
        shield_emoji=_slot(shield_emoji),
        theme_shield_event=_slot(theme_shield_event),
    )


def render_m03(streak: object, next_streak: object) -> str:
    """Render M03 streak-at-risk with sanitized slots."""
    return NUDGE_TEMPLATES["M03"].format(
        streak=_slot(streak), next_streak=_slot(next_streak)
    )


def render_m04(content_type: str) -> str:
    """Render M04 teaser with sanitized slot."""
    return NUDGE_TEMPLATES["M04"].format(content_type=_slot(content_type))


def render_m05(content_type: str) -> str:
    """Render M05 morning dues with sanitized slot."""
    return NUDGE_TEMPLATES["M05"].format(content_type=_slot(content_type))


def render_m06() -> str:
    """Render M06 unfinished-session nudge (slot-less static text, raw)."""
    return NUDGE_TEMPLATES["M06"]


def render_m07(remaining: object) -> str:
    """Render M07 quota-remaining with sanitized slot."""
    return NUDGE_TEMPLATES["M07"].format(remaining=_slot(remaining))


def render_m08(target_heat_theme: str) -> str:
    """Render M08; theme slot is a caller-provided plain string (seam)."""
    return NUDGE_TEMPLATES["M08"].format(
        target_heat_theme=_slot(target_heat_theme)
    )


def render_m09(content_type: str) -> str:
    """Render M09 evening dues with sanitized slot."""
    return NUDGE_TEMPLATES["M09"].format(content_type=_slot(content_type))


def m10_for_report(report, rng=None) -> str | None:
    """M10 for recall < 50%: alias of pick_motivation (no duplicate copy)."""
    from services.session.summary import pick_motivation

    return pick_motivation(report, rng=rng)


__all__ = [
    "M04_STARVATION_DAYS",
    "M10_ALIAS",
    "MAX_SENDS_PER_DAY",
    "MAX_SENDS_PER_WINDOW",
    "NUDGE_TEMPLATES",
    "QUIET_END_HOUR",
    "QUIET_START_HOUR",
    "WINDOW_EVENING",
    "WINDOW_MORNING",
    "WINDOW_NIGHT",
    "WINDOW_NOON",
    "can_send",
    "evaluate_silence",
    "hours_between",
    "is_quiet_hours",
    "m01_due_today",
    "m10_for_report",
    "nudge_counter_key",
    "nudge_window_key",
    "render_m01",
    "render_m02",
    "render_m03",
    "render_m04",
    "render_m05",
    "render_m06",
    "render_m07",
    "render_m08",
    "render_m09",
    "select_nudge",
    "should_defer_m02",
    "should_promote_m04",
    "window_for",
]
