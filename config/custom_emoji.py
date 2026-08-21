"""Custom emoji registry — single source of truth (AGENTS.md §3).

Maps a logical key to ``(custom_emoji_id, fallback_emoji)``. Callers in
``services/send_pretty`` use the ``emoji("book")`` factory; the id is resolved
here so IDs live in exactly one place.

Sending custom emoji requires the bot owner to hold a Telegram Premium
subscription (Bot API 9.4, 2026-02-09) for the bot to emit custom emoji in
private / group / supergroup chats. Populate ``REAL_ID`` entries with your
sticker set's ``custom_emoji_id`` values (inspect via ``getCustomEmojiStickers``
or web.telegram.org). Until then the registry is empty and ``emoji(key)`` falls
back to treating the key as a raw id with ``DEFAULT_FALLBACK``.
"""

from __future__ import annotations

# Logical key -> (custom_emoji_id, fallback_emoji). Add real IDs here.
CUSTOM_EMOJI: dict[str, tuple[str, str]] = {
    # Real custom_emoji_id observed in a forwarded message (Telegram global id).
    # Replace with an id from a sticker set your bot can emit; emitting custom
    # emoji also requires the bot owner to hold Telegram Premium.
    "book": ("5350716797622442220", "📖"),
}

DEFAULT_FALLBACK = "❓"


def resolve_emoji(key_or_id: str, *, fallback: str | None = None) -> tuple[str, str]:
    """Return ``(custom_emoji_id, fallback_emoji)`` for a registry key or raw id.

    A recognized key returns its configured ``(id, fallback)`` (the explicit
    ``fallback`` argument, if given, overrides the stored one). An unknown key
    is treated as a raw ``custom_emoji_id`` and paired with ``DEFAULT_FALLBACK``
    unless ``fallback`` is supplied.
    """
    if key_or_id in CUSTOM_EMOJI:
        cid, stored_fb = CUSTOM_EMOJI[key_or_id]
        return cid, fallback or stored_fb
    return key_or_id, fallback or DEFAULT_FALLBACK
