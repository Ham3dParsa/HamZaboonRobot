"""Minimal formatting module for the send_pretty research sandbox.

Only the three escaping helpers `send_pretty` actually imports are kept here.
The full production `services/utils/formatting.py` has a deep dependency chain
(config / catalog / validation) that is irrelevant for outbound-formatting
research; a self-contained copy avoids dragging that whole tree into the sandbox.
"""

import html
import re

__all__ = ["escape_mdv2", "escape_mdv2_code", "html_escape"]


def escape_mdv2(text: str) -> str:
    """Escape کامل‌تر برای MarkdownV2"""
    if not text:
        return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([' + re.escape(special) + r'])', r'\\\1', text)


def escape_mdv2_code(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"([`\\])", r"\\\1", text)


def html_escape(text: object | None) -> str:
    """Escape a dynamic value for interpolation into a ParseMode.HTML message."""
    if text is None:
        return ""
    return html.escape(str(text), quote=True)
