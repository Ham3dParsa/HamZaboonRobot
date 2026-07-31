"""v3 Pull-Based Study Session Handler.

Handles the golden '📚 شروع مطالعه امروز' button callback.
Phase 2 implementation — scaffold with TODO stubs.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_BYPASS_LIMITS, is_owner
from services import db
from services.session import build_session_list
from services.utils.helpers import _answer_callback_safely

logger = logging.getLogger(__name__)


async def handle_study_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the '📚 شروع مطالعه امروز' golden button callback."""
    user_id = update.effective_user.id
    row = db.get_user(user_id)

    if not row or not row["onboarded"]:
        await _answer_callback_safely(
            update.callback_query,
            "ابتدا /start را بزنید.",
            show_alert=True,
        )
        return

    # TODO: Check session quota (sessions_used_today)
    # TODO: Generate session via generate_v3_session()
    # TODO: Send the first card and initialize in-place editing flow

    logger.info("handle_study_start called (stub) user_id=%s", user_id)
    await _answer_callback_safely(
        update.callback_query,
        "📚 جلسه مطالعه در حال آماده‌سازی… (هنوز پیاده‌سازی نشده)",
        show_alert=True,
    )
