"""Central callback-query notification policy and reliability handling."""

import logging
from enum import Enum

from telegram import CallbackQuery
from telegram.error import BadRequest, NetworkError, TimedOut

logger = logging.getLogger(__name__)


class CallbackNoticeIntent(str, Enum):
    SUCCESS = "success"
    INFO = "info"
    IMPORTANT_ERROR = "important_error"


_SHOW_ALERT_BY_INTENT = {
    CallbackNoticeIntent.SUCCESS: False,
    CallbackNoticeIntent.INFO: False,
    CallbackNoticeIntent.IMPORTANT_ERROR: True,
}


async def notify_callback(
    query: CallbackQuery,
    text: str | None = None,
    *,
    intent: CallbackNoticeIntent = CallbackNoticeIntent.SUCCESS,
) -> None:
    """Acknowledge a callback using semantic presentation intent.

    Stale callback queries and transient Telegram network failures are expected
    after a user waits too long or connectivity drops; other Telegram failures
    remain observable to callers.
    """
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
