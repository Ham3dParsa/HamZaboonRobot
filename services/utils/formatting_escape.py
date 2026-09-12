"""Escape/digits/HTML leaf of the formatting seam (REF2-T1).

Verbatim home of the pure escape leaves split out of
``services/utils/formatting.py``: :func:`escape_mdv2`,
:func:`escape_mdv2_code`, :func:`to_persian_digits` (+ ``_PERSIAN_DIGITS``),
and :func:`html_escape`. ``formatting.py`` keeps a re-export shim so every
existing ``from services.utils.formatting import ...`` caller works unchanged.

Leaf-import law: stdlib only (``html``, ``re``). This module must never import
``services.utils.validation`` — that would invert the
``formatting -> validation -> helpers -> db`` chain.
"""

import html
import re


def escape_mdv2(text: str) -> str:
    """Escape کامل‌تر برای MarkdownV2"""
    if not text:
        return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([' + re.escape(special) + r'])', r'\\\1', text)


_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_persian_digits(value) -> str:
    """Convert Latin digits to Persian digits for learner-facing text."""
    return str(value).translate(_PERSIAN_DIGITS)


def escape_mdv2_code(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"([`\\])", r"\\\1", text)


def html_escape(text: object | None) -> str:
    """Escape a dynamic value for interpolation into a ParseMode.HTML message.

    Centralized choke point for HTML-mode admin/non-learner renderings. Escapes
    the reserved HTML characters (``& < > " '``) so a value containing them
    (e.g. a base_url query string) cannot break Telegram's entity parsing.
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=True)
