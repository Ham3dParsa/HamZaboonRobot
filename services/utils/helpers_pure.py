"""Pure helpers leaf of the utils seam (REF2-T3, first).

Verbatim home of the side-effect-free helpers split out of
``services/utils/helpers.py``: :func:`apply_log_level`,
:func:`_user_activity_line`, :data:`_CANCEL_INPUTS`,
:func:`_normalize_custom_word_input` and :func:`_is_cancel_input`.
``helpers.py`` keeps a re-export shim so every existing
``from services.utils.helpers import ...`` caller works unchanged.

No sibling-leaf imports (pure bottom leaf); stdlib + ``config.keyboards`` +
``services.db`` only.
"""

import logging
import re
import unicodedata

from config.keyboards import BTN_BACK, BTN_CANCEL
from services import db

logger = logging.getLogger(__name__)


def apply_log_level(level_name: str) -> None:
    """Set root logger level and quieter external loggers accordingly."""
    level = getattr(logging, level_name.upper(), None)
    if level is None:
        return
    logging.getLogger().setLevel(level)
    for name in ("apscheduler", "httpcore", "httpx", "telegram"):
        logging.getLogger(name).setLevel(max(level, logging.WARNING))
    logger.info("log level set to %s", level_name.upper())


def _user_activity_line(
    *,
    user_id: int,
    full_name: str | None = None,
    username: str | None = None,
    action: str,
    outcome: str,
    plan: str | None = None,
    lang: str | None = None,
    goal: str | None = None,
    level: str | None = None,
) -> str | None:
    """Build a USER_ACTIVITY log line if the feature is enabled; return None otherwise."""
    if db.get_setting("user_activity_log", "off") != "on":
        return None
    uname = f"@{username}" if username else "—"
    return (
        f"{action:<18s} │ {str(user_id):<12s} │ {uname:<16s} │ "
        f"{(plan or '—'):<8s} │ {(lang or '—'):<6s} │ "
        f"{(goal or '—'):<12s} │ {(level or '—'):<8s} │ "
        f"{outcome:<22s} │ {full_name or '—'}"
    )


_CANCEL_INPUTS = {
    "cancel",
    "back",
    "لغو",
    "بازگشت",
    "انصراف",
    BTN_CANCEL.casefold(),
    BTN_BACK.casefold(),
}


def _normalize_custom_word_input(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r'[\s\u200b]+', ' ', text.strip())
    text = re.sub(r' +', ' ', text)
    return text.strip()


def _is_cancel_input(text: str) -> bool:
    return _normalize_custom_word_input(text).casefold() in _CANCEL_INPUTS
