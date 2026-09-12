"""Awaiting-prompt helpers leaf of the utils seam (REF2-T3, second).

Verbatim home of the awaiting-prompt tracking split out of
``services/utils/helpers.py``: :data:`_ADMIN_PENDING_KEYS`,
:data:`_AWAITING_PENDING_KEY`, :func:`clear_admin_pending_state`,
:func:`_resolve_awaiting_tuple`, :func:`_store_awaiting_msg`,
:func:`_clear_awaiting_prompt` and :func:`_rotate_awaiting_msg`.
``helpers.py`` keeps a re-export shim so every existing
``from services.utils.helpers import ...`` caller works unchanged.

No sibling-leaf imports at top level (DAG bottom-up: pure/retry/awaiting
are independent). The single cross-leaf call (``_edit_markup_with_retry``)
and the ``logger`` emission inside :func:`_clear_awaiting_prompt` resolve
dynamically through the ``helpers`` facade at call time — tests patch
``services.utils.helpers._edit_markup_with_retry`` /
``services.utils.helpers.logger`` and must observe them (send_pretty
precedent: ``_helpers._reset_telegram_cb()`` dynamic lookup).
"""

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

_ADMIN_PENDING_KEYS: tuple[str, ...] = (
    "pending_dm",
    "pending_plan",
    "pending_block",
    "pending_broadcast",
    "full_edit",
    "plan_full_edit",
    "preset_edits",
)

_AWAITING_PENDING_KEY = "_awaiting_pending"


def clear_admin_pending_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all admin pending state keys (single source for cancel/back cleanup)."""
    for _k in _ADMIN_PENDING_KEYS:
        context.user_data.pop(_k, None)
    context.user_data.pop(_AWAITING_PENDING_KEY, None)
    context.user_data.pop("awaiting", None)
    # _awaiting_msg is cleared by _clear_awaiting_prompt, not here


def _resolve_awaiting_tuple(msg, update) -> tuple[int, int] | None:
    """Resolve the (chat_id, message_id) tuple for an awaiting prompt.

    Single source of truth shared by ``_store_awaiting_msg`` and
    ``_rotate_awaiting_msg`` (AGENTS.md §3 — no duplicate resolution logic).
    Primary source is the Message returned by ``say``/``_edit_or_send``
    (``msg``); ``update`` is only used as fallback for the edit-path where
    the helper returns ``True``/``None`` (the prompt is the edited message).
    Returns None when no prompt message can be resolved.
    """
    try:
        mid = None
        cid = None
        if msg is not None and not isinstance(msg, bool):
            mid = getattr(msg, "message_id", None)
            chat = getattr(msg, "chat", None)
            if chat is not None:
                cid = getattr(chat, "id", None)
            # Some send helpers return int message_id directly
            if mid is None and isinstance(msg, int):
                mid = msg
        # Only fallback to effective_message (prompt-related), not callback_query.message
        if mid is None:
            try:
                em = getattr(update, "effective_message", None)
                if em is not None:
                    em_mid = getattr(em, "message_id", None)
                    if em_mid is not None:
                        mid = em_mid
                        if cid is None:
                            chat = getattr(em, "chat", None)
                            if chat is not None:
                                cid = getattr(chat, "id", None)
            except Exception:
                pass
        if cid is None and getattr(update, "effective_chat", None) is not None:
            try:
                cid = update.effective_chat.id  # type: ignore[union-attr]
            except Exception:
                pass
        if mid is None or cid is None:
            return None
        return (int(cid), int(mid))
    except Exception:
        return None


def _store_awaiting_msg(context: ContextTypes.DEFAULT_TYPE, update: Update, msg) -> None:
    """Store the prompt message id so its keyboard can be cleared on consume/cancel.

    Single source of truth — imported by handlers/admin.py and handlers/admin_users.py.

    Primary source is the Message returned by ``say``/``_edit_or_send`` (``msg``);
    ``update`` is only used as fallback for the edit-path where the helper returns
    ``True``/``None`` (the prompt is the edited message). In PTB
    ``effective_message`` and ``callback_query.message`` alias the same object, so
    we only read ``effective_message`` as fallback — never ``callback_query.message``
    directly — and we always prefer ``msg.message_id`` when ``msg`` carries one.
    """
    # Callback updates: effective_message aliases callback_query.message in PTB,
    # so say()/_edit_or_send returning None/True (edit not-modified) would write
    # the button message_id into _awaiting_msg and later _clear_awaiting_prompt
    # would strip the admin menu instead of the prompt. On callback updates with
    # no real Message (None/bool) we skip the store — awaiting text stays in
    # user_data["awaiting"] and will be cleared via clear_admin_pending_state.
    if (msg is None or isinstance(msg, bool)) and getattr(update, "callback_query", None) is not None:
        return
    tup = _resolve_awaiting_tuple(msg, update)
    if tup is None:
        return
    context.user_data["_awaiting_msg"] = {"chat_id": tup[0], "message_id": tup[1]}


async def _clear_awaiting_prompt(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear the stored awaiting prompt's keyboard, swallowing BadRequest.

    Single source of truth — imported by handlers/admin.py and handlers/admin_users.py.
    Restart-safe and idempotent: after a restart ``_awaiting_msg`` is absent
    (in-memory ``user_data``) so this is a no-op; a missing entry or an
    already-stripped/deleted message simply does nothing. Performs no DB I/O,
    so it never holds a DB transaction across an await.
    """
    data = context.user_data.pop("_awaiting_msg", None)
    if not data:
        return
    try:
        # Facade-dynamic (send_pretty precedent): tests patch
        # services.utils.helpers._edit_markup_with_retry and must observe it.
        from services.utils import helpers as _helpers_facade

        await _helpers_facade._edit_markup_with_retry(context.bot, data["chat_id"], data["message_id"], None)
    except BadRequest:
        pass
    except Exception:
        # Facade-dynamic: tests patch services.utils.helpers.logger here.
        from services.utils import helpers as _helpers_facade

        _helpers_facade.logger.exception("Failed to clear awaiting prompt")


async def _rotate_awaiting_msg(context: ContextTypes.DEFAULT_TYPE, update: Update, msg) -> None:
    """Start a new awaiting prompt: strip the previous prompt's keyboard, then store the new one.

    Single source of truth for prompt rotation (R2 stale-orphan fix): preset
    awaiting prompt starts should go through here instead of calling
    ``_store_awaiting_msg`` directly, so a second prompt can never orphan the
    first one's keyboard. Restart-safe and idempotent (inherits both from
    ``_clear_awaiting_prompt``/``_store_awaiting_msg``); performs no DB I/O,
    so no DB transaction is ever held across the await.

    Two guards (opencode WARNING, PR 568 — verified against ``say`` +
    ``_store_awaiting_msg`` semantics):

    - Same message: callback edits reuse one message, so the stored old tuple
      routinely aliases the just-rendered prompt. Stripping it would remove
      the keyboard ``say`` just set — skip the strip and just (re-)store
      (same pattern as the admin:close same-message skip in handlers/admin).
    - Unresolvable new prompt: ``say`` returns None/True on the callback
      edit-not-modified path. Clearing first would drop the still-valid old
      tracking while storing nothing — keep the old entry intact instead
      (same guard as ``_store_awaiting_msg``: never guess from the button
      message on callback updates).
    """
    if (msg is None or isinstance(msg, bool)) and getattr(update, "callback_query", None) is not None:
        return
    new_tup = _resolve_awaiting_tuple(msg, update)
    if new_tup is None:
        return
    old = context.user_data.get("_awaiting_msg")
    old_tup = None
    if isinstance(old, dict):
        try:
            if old.get("chat_id") is not None and old.get("message_id") is not None:
                old_tup = (int(old["chat_id"]), int(old["message_id"]))
        except Exception:
            old_tup = None
    if old_tup is None or old_tup != new_tup:
        await _clear_awaiting_prompt(context)
    context.user_data["_awaiting_msg"] = {"chat_id": new_tup[0], "message_id": new_tup[1]}
