"""Telegram retry helpers leaf of the utils seam (REF2-T3, last).

Verbatim home of the retry loops split out of
``services/utils/helpers.py``: the backoff constants, :func:`_retry_backoff_base`,
:func:`_retry_sleep`, :func:`_execute_telegram_action_with_retry`,
:func:`_reset_telegram_cb`, :func:`_send_with_retry`,
:func:`_edit_with_retry`, :func:`_edit_message_with_retry`,
:func:`_edit_markup_with_retry` and :func:`_delete_with_retry`.
``helpers.py`` keeps a re-export shim so every existing
``from services.utils.helpers import ...`` caller works unchanged.

No sibling-leaf imports (bottom leaf alongside pure). ``_telegram_slots`` /
``_send_media_with_retry`` / ``bot`` imports stay function-local —
``send_pretty`` imports this seam at top level, so a top-level import back
would cycle. ``_reset_telegram_cb()`` call sites resolve dynamically through
the ``helpers`` facade at call time — tests patch
``services.utils.helpers._reset_telegram_cb`` and must observe them
(send_pretty precedent: ``_helpers._reset_telegram_cb()`` dynamic lookup).
"""

import asyncio
import logging
import math
import os
import random

from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from services import db

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_BASE_DEFAULT = 1.0
_RETRY_BACKOFF_BASE_MAX = 60.0
_RETRY_BACKOFF_SLEEP_MAX = 30.0

# Retry seam (Issue #579) — Telegram Jittered Exponential Backoff, single seam.
# Contract lock 2026-09-05: 3 attempts, base 0.5s, cap 30s, RetryAfter honored
# (raise-over-cap drop). Sibling edit/delete loops keep their pre-existing
# 30s-clamp; only this central seam drops over-cap (scoped divergence).
_TELEGRAM_RETRY_MAX_ATTEMPTS = 3
_TELEGRAM_RETRY_BASE_DELAY = 0.5
_TELEGRAM_RETRY_MAX_DELAY = 30.0


def _retry_backoff_base() -> float:
    """Scale factor for the Telegram retry backoff (2**attempt) wall-clock wait.

    Production default is 1.0 (unchanged). Tests may shrink the wait via
    HAMZABAN_RETRY_BACKOFF_BASE (0.1 in the suite; 0.05 reserved for explicit
    performance benchmarks) while still exercising the real retry sequence:
    attempt count, ordering, retry conditions, final failure and success-after-
    retry are all untouched — only the elapsed waiting time scales.

    Invalid, NaN, infinite or non-positive values are warned and fall back to
    1.0; values above 60 are clamped.
    """
    raw = os.environ.get("HAMZABAN_RETRY_BACKOFF_BASE")
    if raw is None:
        return _RETRY_BACKOFF_BASE_DEFAULT
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid HAMZABAN_RETRY_BACKOFF_BASE=%r, using default 1.0", raw)
        return _RETRY_BACKOFF_BASE_DEFAULT
    if not math.isfinite(value) or value <= 0:
        logger.warning("Invalid HAMZABAN_RETRY_BACKOFF_BASE=%r, using default 1.0", raw)
        return _RETRY_BACKOFF_BASE_DEFAULT
    if value > _RETRY_BACKOFF_BASE_MAX:
        logger.warning(
            "HAMZABAN_RETRY_BACKOFF_BASE=%r exceeds max %.1f, clamping",
            raw,
            _RETRY_BACKOFF_BASE_MAX,
        )
        value = _RETRY_BACKOFF_BASE_MAX
    return value


def _retry_sleep(attempt: int) -> float:
    """Computed backoff sleep for *attempt*, capped to 30s."""
    return min(_retry_backoff_base() * (2**attempt), _RETRY_BACKOFF_SLEEP_MAX)


# NOTE (phase-03 retry seam move, R2): the Telegram send retry/slot seam
# (_telegram_slots, _send_media_with_retry, _capture_media_bytes,
# _SEND_METHOD_ALLOWLIST, _SEND_MEDIA_EXPECTED, _rich_api_request) is owned by
# services/send_pretty.py and re-exported at the bottom of the helpers facade.
# The edit/delete retry loops below still use the slot via a lazy import
# (send_pretty imports them from the facade at top level, so a top-level
# import back would cycle).


async def _execute_telegram_action_with_retry(action_fn, *args, is_idempotent: bool = False, reset_telegram_cb: bool = True, **kwargs):
    """
    درزگاه سراسری اجرای متد تلگرام با Jittered Exponential Backoff و رعایت
    سربرگ RetryAfter. — Issue #579, R2 split policy. ریتری با is_idempotent
    گیت می‌شود (پیش‌فرض False: امن برای مسیر غیرایدم‌پوتنت).

    فقط مسیرهای ایدم‌پوتنت (edit/delete) مجاز به ریتری TimedOut/NetworkError
    هستند. ارسال‌ها غیرایدم‌پوتنت‌اند و هرگز نباید از این تابع عبور کنند —
    درگاه ارسال مالکانه services/send_pretty._send_media_with_retry است.
    is_idempotent=False (پیش‌فرض): خطای TimedOut/NetworkError بلافاصله
    بازپرتاب می‌شود (بدون ریتری/خواب) — نگهبان مسیرهای غیرایدم‌پوتنت آینده.
    is_idempotent=True: ریتری بک‌آف موجود حفظ می‌شود.
    reset_telegram_cb=True (پیش‌فرض): پس از موفقیت، پرچم آفلاین/شمارنده
    سلامت ریست می‌شود. مسیرهای health/offline-notice با False صدا می‌زنند
    تا وضعیت circuit-breaker را بازنویسی نکنند.
    Slot-missing fail-closed (R3 #583): اگر ایمپورت _telegram_slots شکست
    بخورد، RuntimeError("telegram slot unavailable") پرتاب می‌شود — هرگز
    بدون اسلات و بدون محدودیت اجرا نمی‌شود (سطح‌بندی miswire).
    """
    # Lazy slot — owned by services/send_pretty.py (phase-03 R2), avoid cycle.
    try:
        from services.send_pretty import _telegram_slots
    except ImportError:
        _telegram_slots = None  # type: ignore

    if _telegram_slots is None:
        raise RuntimeError("telegram slot unavailable")

    attempt = 0
    while True:
        attempt += 1
        try:
            async with _telegram_slots:
                result = await action_fn(*args, **kwargs)
                if reset_telegram_cb:
                    # Facade-dynamic (send_pretty precedent): tests patch
                    # services.utils.helpers._reset_telegram_cb and must
                    # observe it.
                    from services.utils import helpers as _helpers_facade

                    _helpers_facade._reset_telegram_cb()
                return result
        except Forbidden:
            raise

        except BadRequest as e:
            logger.debug("Telegram BadRequest non-retryable: %s", e)
            raise

        except RetryAfter as e:
            delay = float(e.retry_after)
            # Owner-approved drop semantics (Kilo round-1/2, owner 2026-09-05):
            # a RetryAfter above the cap honors Telegram's flood directive
            # by dropping instead of blocking the handler past the cap.
            # Flood-safe (never hammer a rate-limited endpoint) and
            # handler-bound (a single delivery never stalls a worker
            # beyond the budget). DIVERGENCE (owner-approved): the four
            # legacy paths (send owner + 3 sibling edit/delete loops) keep
            # their pre-existing min(delay,30s)-clamp-then-retry because
            # delivery matters more than flood-purity there; only this
            # central seam drops over-cap. Unified only if load evidence
            # demands it (see #585).
            if delay > _TELEGRAM_RETRY_MAX_DELAY:
                logger.error(
                    "Telegram RetryAfter %.2fs exceeds cap %.2fs on attempt %d/%d — dropping (no sleep, no retry)",
                    delay,
                    _TELEGRAM_RETRY_MAX_DELAY,
                    attempt,
                    _TELEGRAM_RETRY_MAX_ATTEMPTS,
                )
                raise
            logger.warning(
                "Telegram RetryAfter caught on attempt %d/%d. Wait %.2fs...",
                attempt,
                _TELEGRAM_RETRY_MAX_ATTEMPTS,
                delay,
            )
            if attempt >= _TELEGRAM_RETRY_MAX_ATTEMPTS:
                raise
            await asyncio.sleep(delay)

        except (TimedOut, NetworkError) as e:
            if not is_idempotent:
                raise
            logger.warning(
                "Telegram network error (%s) on attempt %d/%d.",
                e.__class__.__name__,
                attempt,
                _TELEGRAM_RETRY_MAX_ATTEMPTS,
            )
            if attempt >= _TELEGRAM_RETRY_MAX_ATTEMPTS:
                raise
            exp_delay = _TELEGRAM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
            jittered_delay = random.uniform(0.1, min(exp_delay, _TELEGRAM_RETRY_MAX_DELAY))
            await asyncio.sleep(jittered_delay)

        except Exception as e:
            logger.error("Unexpected error in telegram retry seam: %s", e, exc_info=True)
            raise


def _reset_telegram_cb():
    import bot
    bot._telegram_offline = False
    bot._consecutive_health_failures = 0


async def _send_with_retry(
    bot,
    chat_id: int,
    text: str,
    *,
    reset_telegram_cb: bool = True,
    **kwargs,
):
    """جایگزین درگاه خط ۳۴۲: ارسال پیام — Issue #579, R2 delegation.

    Thin wrapper روی درگاه مالکانه services/send_pretty._send_media_with_retry
    (تک‌درگاه ارسال: allowlist، byte-recapture، reset_telegram_cb gating).
    ارسال‌ها غیرایدم‌پوتنت‌اند: ریتری فقط RetryAfter (مالکانه) — هرگز
    TimedOut/NetworkError. Forbidden→blocked در درگاه مالک انجام می‌شود.
    """
    # Lazy: send_pretty از این ماژول ایمپورت سطح بالا دارد — ایمپورت سطح بالا چرخه می‌سازد.
    from services.send_pretty import _send_media_with_retry

    return await _send_media_with_retry(
        bot,
        chat_id,
        method="send_message",
        media_kw=None,
        media=text,
        reset_telegram_cb=reset_telegram_cb,
        **kwargs,
    )


async def _edit_with_retry(query, text, *, reset_telegram_cb: bool = True, **kwargs):
    # Lazy: the slot lives in services/send_pretty.py (phase-03 R2); a
    # top-level import back would cycle (send_pretty imports this module).
    from services.send_pretty import _telegram_slots

    if _telegram_slots is None:
        raise RuntimeError("telegram slot unavailable")

    for attempt in range(3):
        try:
            async with _telegram_slots:
                result = await query.edit_message_text(text, **kwargs)
                if reset_telegram_cb:
                    # Facade-dynamic (send_pretty precedent): tests patch
                    # services.utils.helpers._reset_telegram_cb and must
                    # observe it.
                    from services.utils import helpers as _helpers_facade

                    _helpers_facade._reset_telegram_cb()
                return result
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(_retry_sleep(attempt))


async def _edit_message_with_retry(
    bot, chat_id: int, message_id: int, text: str, *, reset_telegram_cb: bool = True, **kwargs
):
    """جایگزین درگاه خط ۳۷۴: فراخوانی با ریتری هوشمند برای ویرایش پیام — Issue #579."""

    async def _act():
        try:
            return await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, **kwargs
            )
        except Forbidden:
            if chat_id > 0:
                try:
                    db.set_user_blocked(chat_id)
                except Exception:
                    pass
            raise

    return await _execute_telegram_action_with_retry(_act, is_idempotent=True, reset_telegram_cb=reset_telegram_cb)


async def _edit_markup_with_retry(
    bot, chat_id: int, message_id: int, reply_markup, *, reset_telegram_cb: bool = True, **kwargs
):
    """Edit only the reply markup of an existing message (no text change),
    holding the shared concurrency slot.

    RT-B2: routes the handler ``context.bot.edit_message_reply_markup`` bypass
    sites back onto the retry/slot seam.
    """
    # Lazy: the slot lives in services/send_pretty.py (phase-03 R2); a
    # top-level import back would cycle (send_pretty imports this module).
    from services.send_pretty import _telegram_slots

    if _telegram_slots is None:
        raise RuntimeError("telegram slot unavailable")

    for attempt in range(3):
        try:
            async with _telegram_slots:
                result = await bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                    **kwargs,
                )
                if reset_telegram_cb:
                    # Facade-dynamic (send_pretty precedent): tests patch
                    # services.utils.helpers._reset_telegram_cb and must
                    # observe it.
                    from services.utils import helpers as _helpers_facade

                    _helpers_facade._reset_telegram_cb()
                return result
        except Forbidden:
            if chat_id > 0:
                try:
                    db.set_user_blocked(chat_id)
                except Exception:
                    pass
            raise
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(_retry_sleep(attempt))


async def _delete_with_retry(bot, chat_id: int, message_id: int, *, reset_telegram_cb: bool = True, **kwargs):
    # Lazy: the slot lives in services/send_pretty.py (phase-03 R2); a
    # top-level import back would cycle (send_pretty imports this module).
    from services.send_pretty import _telegram_slots

    if _telegram_slots is None:
        raise RuntimeError("telegram slot unavailable")

    for attempt in range(3):
        try:
            async with _telegram_slots:
                result = await bot.delete_message(chat_id=chat_id, message_id=message_id, **kwargs)
                if reset_telegram_cb:
                    # Facade-dynamic (send_pretty precedent): tests patch
                    # services.utils.helpers._reset_telegram_cb and must
                    # observe it.
                    from services.utils import helpers as _helpers_facade

                    _helpers_facade._reset_telegram_cb()
                return result
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(_retry_sleep(attempt))
