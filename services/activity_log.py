"""Single owner of the USER_ACTIVITY diagnostic log (R4).

Consolidates the three duplicated caller blocks that previously lived in
``handlers/user.py`` (``_log_user_activity`` and the inline ``cmd_start``
block) and ``handlers/srs_handler.py`` (``_log_ua``) into one entry point.
``log_user_activity`` fetches the stored user row, builds the line via
``services.utils.helpers._user_activity_line``, and emits it only when the
feature is enabled. Rows always record plan/lang/goal/level uniformly.
"""

from __future__ import annotations

import logging

from telegram import Update

from services import db
from config import USER_ACTIVITY
from services.utils.helpers_pure import _user_activity_line

logger = logging.getLogger(__name__)


def log_user_activity(update: Update, *, action: str, outcome: str) -> None:
    """Log a USER_ACTIVITY line if the feature is enabled.

    No-op when ``update.effective_user`` is absent or the feature is off.
    """
    user = update.effective_user
    if not user:
        return
    row = db.get_user(user.id)
    line = _user_activity_line(
        user_id=user.id,
        full_name=user.full_name,
        username=user.username,
        action=action,
        outcome=outcome,
        plan=row["plan"] if row else None,
        lang=row["target_lang"] if row else None,
        goal=row["goal"] if row else None,
        level=row["level"] if row else None,
    )
    if line:
        logger.log(USER_ACTIVITY, "%s", line)