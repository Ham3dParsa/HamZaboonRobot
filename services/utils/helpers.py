"""Helpers facade (REF2-T3).

Thin re-export shim over the split leaves — ``helpers_pure.py`` (pure),
``helpers_awaiting.py`` (awaiting-prompt tracking), ``helpers_llm.py``
(LLM wait-state + awaiting exit + ``say`` adapter) and ``helpers_retry.py``
(Telegram retry loops). Every existing
``from services.utils.helpers import ...`` caller works unchanged; the
canonical definitions live in the leaves (old defs removed same PR).

Patch-contract compat: ``asyncio`` and ``logger`` are intentionally exposed
here — tests patch ``services.utils.helpers.asyncio.sleep`` and
``services.utils.helpers.logger``, and the leaves resolve those (plus
``_reset_telegram_cb`` / ``_edit_markup_with_retry`` / ``notify_callback``)
dynamically through this facade at call time (send_pretty precedent).
``CallbackNoticeIntent`` / ``notify_callback`` are re-exported (same objects)
for the same reason. New code MUST import from the leaves directly.
"""

import asyncio  # noqa: F401 — compat: tests patch helpers.asyncio.sleep (same stdlib singleton)
import logging

from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.helpers_awaiting import (
    _ADMIN_PENDING_KEYS,
    _AWAITING_PENDING_KEY,
    _clear_awaiting_prompt,
    _resolve_awaiting_tuple,
    _rotate_awaiting_msg,
    _store_awaiting_msg,
    clear_admin_pending_state,
)
from services.utils.helpers_llm import (
    _edit_or_send,
    _exit_awaiting_flow,
    _finish_llm_wait_state,
    _start_llm_wait_state,
    exit_admin_awaiting_cancel,
)
from services.utils.helpers_pure import (
    _CANCEL_INPUTS,
    _is_cancel_input,
    _normalize_custom_word_input,
    _user_activity_line,
    apply_log_level,
)
from services.utils.helpers_retry import (
    _RETRY_BACKOFF_BASE_DEFAULT,
    _RETRY_BACKOFF_BASE_MAX,
    _RETRY_BACKOFF_SLEEP_MAX,
    _TELEGRAM_RETRY_BASE_DELAY,
    _TELEGRAM_RETRY_MAX_ATTEMPTS,
    _TELEGRAM_RETRY_MAX_DELAY,
    _delete_with_retry,
    _edit_markup_with_retry,
    _edit_message_with_retry,
    _edit_with_retry,
    _execute_telegram_action_with_retry,
    _reset_telegram_cb,
    _retry_backoff_base,
    _retry_sleep,
    _send_with_retry,
)

logger = logging.getLogger(__name__)

__all__ = [
    "apply_log_level",
    "_user_activity_line",
    "_CANCEL_INPUTS",
    "_normalize_custom_word_input",
    "_is_cancel_input",
    "_start_llm_wait_state",
    "_finish_llm_wait_state",
    "_exit_awaiting_flow",
    "exit_admin_awaiting_cancel",
    "_edit_or_send",
    "_retry_backoff_base",
    "_retry_sleep",
    "_execute_telegram_action_with_retry",
    "_reset_telegram_cb",
    "_send_with_retry",
    "_edit_with_retry",
    "_edit_message_with_retry",
    "_edit_markup_with_retry",
    "_delete_with_retry",
    "_ADMIN_PENDING_KEYS",
    "_AWAITING_PENDING_KEY",
    "clear_admin_pending_state",
    "_resolve_awaiting_tuple",
    "_store_awaiting_msg",
    "_clear_awaiting_prompt",
    "_rotate_awaiting_msg",
    "CallbackNoticeIntent",
    "notify_callback",
]


# Wiring guard static alias — satisfies tests/test_wiring.py AST check for
# from services.utils.helpers import _send_media_with_retry (runtime via __getattr__).
# REF2-T3: extended to cover the retry-leaf move — the send seam stays owned by
# services/send_pretty.py; the edit/delete loops moved to helpers_retry.py and
# are statically re-exported above (no alias needed for them).
if False:  # pragma: no cover
    from services.send_pretty import _send_media_with_retry  # noqa: F401

# ---------------------------------------------------------------------------
# One-PR re-export shim (phase-03 retry seam move, R2).
#
# The Telegram send retry/slot seam is owned by services/send_pretty.py.
# These names are re-exported here so existing importers (services/tts_service,
# services/archive, bot.py health job, tests) keep working untouched; the next
# cleanup PR retargets them to the owner and deletes this shim (route-delete).
# New code MUST import from services.send_pretty directly.
# ---------------------------------------------------------------------------
_SEND_PRETTY_REEXPORTS = frozenset({
    "_telegram_slots",
    "_send_media_with_retry",
    "_capture_media_bytes",
    "_SEND_METHOD_ALLOWLIST",
    "_SEND_MEDIA_EXPECTED",
    "_rich_api_request",
})


def __getattr__(name: str):
    if name in _SEND_PRETTY_REEXPORTS:
        from services import send_pretty

        return getattr(send_pretty, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
