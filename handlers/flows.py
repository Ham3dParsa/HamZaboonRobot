"""Central awaiting text-input flow registry (R2).

Deep module: a small interface (``register_flow``, ``resolve_flow``,
``text_router``, ``is_admin_awaiting``) hides the entire awaiting text-input
namespace. Every awaiting key the bot can set (across handlers/user.py,
handlers/admin.py and its domain submodules) is registered here by its owning
module at import time, so ``bot.py``'s text router never hard-codes a prefix
and can never silently drop a new key (the root-cause fix for the
``ai_fallback_rank`` routing gap, Finding #6).

A flow maps an awaiting *prefix* to a handler with the uniform signature
``async def(update, context, awaiting, text)``. ``text_router`` looks up the
longest matching prefix and delegates, hiding all ``awaiting.split(":")``
parsing from callers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

#: Uniform handler signature for every awaiting flow.
FlowHandler = Callable[
    [Update, ContextTypes.DEFAULT_TYPE, str, str],
    Awaitable[None],
]


@dataclass(frozen=True)
class AwaitingFlow:
    """One registered awaiting text-input flow.

    A ``prefix`` ending in ``:`` is matched with ``startswith`` (a namespace
    carrying extra state, e.g. ``ai_preset_edit:``); any other ``prefix`` is an
    exact-key match (e.g. ``admin_broadcast``), preserving the old ``==``/``in``
    semantics so a stray suffix can never widen a flow like ``admin_broadcast``.
    Longer prefixes win so specific states never collide with generic ones.
    """

    prefix: str
    handler: FlowHandler


_FLOWS: list[AwaitingFlow] = []


def register_flow(prefix: str, handler: FlowHandler) -> None:
    """Register an awaiting flow (prefix -> handler) at import time."""
    if not prefix:
        raise ValueError("awaiting flow prefix must be non-empty")
    _FLOWS.append(AwaitingFlow(prefix, handler))


def _matches(awaiting: str, flow: AwaitingFlow) -> bool:
    """True if *awaiting* matches *flow* under exact-key vs prefix semantics."""
    if flow.prefix.endswith(":"):
        return awaiting.startswith(flow.prefix)
    return awaiting == flow.prefix


def resolve_flow(awaiting: str) -> AwaitingFlow | None:
    """Return the best matching flow for *awaiting*, or None.

    Exact keys (no trailing ``:``) are matched with ``==``; ``:``-suffixed
    prefixes with ``startswith`` (longest prefix wins). This mirrors the old
    dispatch's exact ``==``/``in`` and ``startswith`` branches, so a stray
    suffix cannot widen an exact-state flow.
    """
    best: AwaitingFlow | None = None
    for flow in _FLOWS:
        if _matches(awaiting, flow):
            if best is None or len(flow.prefix) > len(best.prefix):
                best = flow
    return best


def is_admin_awaiting(awaiting: str) -> bool:
    """True if *awaiting* resolves to a registered flow (was a hard-coded list)."""
    return bool(awaiting) and resolve_flow(awaiting) is not None


async def text_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    awaiting: str,
    text: str,
) -> None:
    """Dispatch *awaiting* to its registered handler; no-op if unregistered.

    This is the only entry ``bot.py`` calls for admin text input. It resolves
    the flow and delegates, so callers never parse awaiting keys themselves.
    """
    flow = resolve_flow(awaiting)
    if flow is None:
        logger.warning("No awaiting flow registered for %r", awaiting)
        return
    await flow.handler(update, context, awaiting, text)