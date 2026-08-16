"""Central callback routing registry (R1).

Replaces the distributed if/elif dispatch that previously lived in
``bot.py``'s ``callback_router`` and the admin sub-routers
(``handlers/admin*.py``) with a single prefix -> handler registry plus a
``dispatch()`` entry point.

Routing contract
----------------
- ``ROUTES`` holds ``(prefix, handler, owner_only)`` tuples in registration
  order. ``dispatch()`` performs longest-prefix matching: the registered prefix
  that the callback data equals, or that the data starts with (followed by a
  ``:``), and that has the greatest length wins.
- The matched handler receives ``(update, context, action)`` where *action* is
  the remainder of the callback data after the matched prefix (with a leading
  ``:`` stripped). The handler is responsible for acknowledging the callback
  exactly once (the B1/R8 single-answer contract).
- The owner gate is centralized here via the ``owner_only`` route flag, so the
  admin domain does not repeat ``is_owner`` checks in every branch.
- Unknown / unmatched prefixes are acknowledged exactly once here (single
  "unknown" fallback), instead of each router duplicating the fallback.

This seam is deliberately dependency-free: it imports only the notification
module and ``config``. The admin domain registers its routes from
``handlers/admin.py`` at import time, so no handler module is imported here.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

from telegram import Update
from telegram.ext import ContextTypes

from config import is_owner
from services.utils.callback_notifications import (
    CallbackNoticeIntent,
    is_callback_answered,
    notify_callback,
    reset_callback_answered,
    restore_callback_answered,
)

# A registered callback handler: async (update, context, action) -> None.
CallbackHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE, str], Awaitable[None]]

# Registry entry: (prefix, handler, owner_only).
_Route = tuple[str, CallbackHandler, bool]

ROUTES: list[_Route] = []


def register(prefix: str, handler: CallbackHandler, *, owner_only: bool = False) -> None:
    """Register *handler* for the callback-data *prefix*.

    *owner_only* marks the route as restricted to the bot owner; ``dispatch``
    enforces the gate. Registration order does not matter because matching is
    by longest prefix.
    """
    ROUTES.append((prefix, handler, owner_only))


def _longest_match(data: str) -> _Route | None:
    """Return the registered route whose prefix best matches *data*.

    A prefix matches only when *data* starts with ``prefix + ":"`` (e.g.
    ``admin:back`` matches the ``admin`` route). Bare tokens with no trailing
    colon (a malformed ``admin`` / ``llm`` with no sub-action) intentionally do
    NOT match, so they fall through to the unknown-prefix fallback and produce the
    standard error toast rather than dispatching with an empty action. This keeps
    the pre-refactor behavior for malformed input.
    """
    best: _Route | None = None
    for route in ROUTES:
        prefix = route[0]
        if data.startswith(prefix + ":"):
            if best is None or len(prefix) > len(best[0]):
                best = route
    return best


async def dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Route *data* to the best-matching registered handler.

    Guarantees the B1/R8 single-answer contract: exactly one
    ``answer_callback_query`` is produced per callback — by the matched handler
    (which owns its own ack), or here for the owner-gate rejection and for the
    unknown-prefix fallback.
    """
    route = _longest_match(data)
    if not ROUTES:
        logger.warning("callback dispatch invoked with an empty ROUTES registry")
    if route is None:
        await notify_callback(
            update.callback_query,
            "عملیات ناموفق بود.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return

    prefix, handler, owner_only = route
    if owner_only and not is_owner(update.effective_user.id):
        await notify_callback(
            update.callback_query,
            "فقط مالک ربات دسترسی داره.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return

    action = data[len(prefix):].lstrip(":")
    await _invoke_and_ensure_answered(update, context, action, handler)


async def _invoke_and_ensure_answered(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
    handler: CallbackHandler,
) -> None:
    """Call a matched handler and guarantee exactly one callback answer (R8/B1).

    A router and its leaf handler may both attempt to acknowledge the callback
    (the B1 double-notify bug). Every callback acknowledgement flows through the
    shared ``notify_callback`` seam, which records whether it answered the
    callback in a per-dispatch ``contextvars`` flag. We read that flag here: if
    the handler already answered, we do nothing; otherwise we provide the sole
    answer for leaf branches that only edit a message.

    Tracking lives in the seam (not via a per-call ``query.answer`` monkeypatch)
    so the live Telegram query object is never mutated and concurrent dispatches
    stay isolated per async task (addresses the Kilo review SUGGESTION on
    routing.py:132). The flag is reset before the handler and restored afterwards
    so a raised exception cannot leak state into the next dispatch.
    """
    token = reset_callback_answered()
    try:
        await handler(update, context, action)
    finally:
        # Read the answered flag before restoring the token so the post-handler
        # fallback below sees whether the handler already acknowledged.
        answered = is_callback_answered()
    if not answered:
        await notify_callback(update.callback_query)
    restore_callback_answered(token)
