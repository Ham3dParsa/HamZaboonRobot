"""Central callback-query notification policy and reliability handling."""

import contextvars
import logging
from enum import Enum

from telegram import CallbackQuery
from telegram.error import BadRequest, NetworkError, TimedOut

logger = logging.getLogger(__name__)

# Set True whenever notify_callback acknowledges a callback query. The central
# routing layer (services/routing.py) reads this to honor the single-answer
# contract (B1/R8) without mutating the live Telegram query object. A context
# var keeps the flag isolated per async task, so concurrent dispatches never
# collide and reused query objects are never patched.
_callback_answered = contextvars.ContextVar("callback_answered", default=False)


def reset_callback_answered() -> contextvars.Token:
    """Reset the answered flag for a single dispatch; returns the reset token."""
    return _callback_answered.set(False)


def is_callback_answered() -> bool:
    """Return True if notify_callback has acknowledged the current callback."""
    return _callback_answered.get()


def restore_callback_answered(token: contextvars.Token) -> None:
    """Restore the answered flag to the value captured by reset_callback_answered."""
    _callback_answered.reset(token)


class CallbackNoticeIntent(str, Enum):
    SUCCESS = "success"
    INFO = "info"
    IMPORTANT_ERROR = "important_error"
    SUCCESS_TOAST = "success_toast"
    THROTTLE = "throttle"


_SHOW_ALERT_BY_INTENT = {
    CallbackNoticeIntent.SUCCESS: False,
    CallbackNoticeIntent.INFO: False,
    CallbackNoticeIntent.IMPORTANT_ERROR: True,
    CallbackNoticeIntent.SUCCESS_TOAST: True,
    CallbackNoticeIntent.THROTTLE: True,
}


async def notify_callback(
    query: CallbackQuery | None,
    text: str | None = None,
    *,
    intent: CallbackNoticeIntent = CallbackNoticeIntent.SUCCESS,
) -> None:
    """Acknowledge a callback using semantic presentation intent.

    Stale callback queries and transient Telegram network failures are expected
    after a user waits too long or connectivity drops; other Telegram failures
    remain observable to callers.
    """
    if query is None:
        return
    _callback_answered.set(True)
    try:
        if text:
            await query.answer(text, show_alert=_SHOW_ALERT_BY_INTENT[intent])
        else:
            await query.answer()
    except BadRequest as exc:
        message = str(exc).casefold()
        if "query is too old" in message or "query id is invalid" in message:
            logger.debug("skipped stale callback answer: %s", exc)
        else:
            raise
    except (TimedOut, NetworkError):
        logger.warning("callback answer failed due to network error")
