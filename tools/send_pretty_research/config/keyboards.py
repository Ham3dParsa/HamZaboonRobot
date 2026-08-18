"""Minimal config.keyboards stub for the send_pretty research sandbox.

Only the symbols `helpers.py` references are defined; the production
`keyboards.py` has a large catalog-driven menu system unused here.
"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

BTN_CANCEL = "❌ لغو"
BTN_BACK = "↩️ بازگشت"


def main_menu(owner: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([])


def awaiting_inline_keyboard() -> InlineKeyboardMarkup | None:
    return None
