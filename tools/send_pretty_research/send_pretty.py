"""Research sandbox wrapper — delegates to the real services/send_pretty.py

This file exists so the sandbox's test_bot_send_pretty.py can import
send_pretty and get the real Rich-enabled implementation from services/.

The sandbox script runs from this directory, so ``services`` / ``config`` are
not on sys.path by default. We add the worktree root (two levels up) so the
real module and its dependencies resolve.
"""

import os
import sys

_WORKTREE_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _WORKTREE_ROOT not in sys.path:
    sys.path.insert(0, _WORKTREE_ROOT)

# Re-export everything from the real implementation
from services.send_pretty import (  # noqa: F403,F401,E402
    Backend,
    RawFormat,
    Message,
    Span,
    Plain,
    Bold,
    Italic,
    Code,
    Spoiler,
    Link,
    Quote,
    Newline,
    CustomEmoji,
    Details,
    Heading,
    Table,
    List,
    ListItem,
    TaskListItem,
    Math,
    Raw,
    Underline,
    Strikethrough,
    Marked,
    TgSpoiler,
    plain,
    bold,
    italic,
    code,
    spoiler,
    underline,
    strike,
    mark,
    tg_spoiler,
    link,
    quote,
    nl,
    line,
    emoji,
    heading,
    table,
    rich_list,
    details,
    math,
    raw_rich,
    send,
    say,
    edit,
    edit_markup,
    telegram_rich,
)
