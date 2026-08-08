"""Focused tests for the admin_stats module (Finding #7).

Task 7.5 (migrate): ``handle_admin_stats`` owns the ``admin:stats`` handling that
was inline in the admin monolith; the stats keyboards are still re-exported from
``config.keyboards``. Behavior is unchanged.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config.keyboards import stats_back_keyboard, stats_menu_keyboard
from handlers import admin_stats


class TestAdminStatsModule(unittest.TestCase):
    def test_reexports_stats_keyboards_verbatim(self):
        self.assertIs(admin_stats.stats_menu_keyboard, stats_menu_keyboard)
        self.assertIs(admin_stats.stats_back_keyboard, stats_back_keyboard)

    def test_all_is_explicit(self):
        self.assertEqual(
            admin_stats.__all__,
            ["handle_admin_stats", "stats_back_keyboard", "stats_menu_keyboard"],
        )


class TestHandleAdminStats(unittest.TestCase):
    def _make_update(self):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 1
        update.effective_chat.id = 1
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def test_menu_renders_stats_keyboard(self):
        update = self._make_update()
        ctx = self._make_context()
        import asyncio
        asyncio.run(admin_stats.handle_admin_stats(update, ctx, "stats"))
        update.callback_query.edit_message_text.assert_called_once()
        self.assertEqual(
            update.callback_query.edit_message_text.call_args.kwargs["reply_markup"],
            stats_menu_keyboard(),
        )

    def test_overview_queries_db_and_renders(self):
        update = self._make_update()
        ctx = self._make_context()
        with patch(
            "handlers.admin_stats.db.count_users_overview",
            return_value={"total": 42, "onboarded": 40, "blocked": 2},
        ):
            import asyncio
            asyncio.run(admin_stats.handle_admin_stats(update, ctx, "stats:overview"))
        text = update.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("کل کاربران: 42", text)
        self.assertIn("بلاک کرده: 2", text)

    def test_activity_queries_db_and_renders(self):
        update = self._make_update()
        ctx = self._make_context()
        with patch("handlers.admin_stats.db.count_active_users_since", return_value=5), \
             patch("handlers.admin_stats.db.count_saved_words_total", return_value=1000), \
             patch("handlers.admin_stats.db.count_llm_requests_since", return_value=3):
            import asyncio
            asyncio.run(admin_stats.handle_admin_stats(update, ctx, "stats:activity"))
        text = update.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("فعال امروز:", text)
        self.assertIn("درخواست‌های AI امروز: 3", text)

    def test_unknown_subaction_answers_invalid(self):
        update = self._make_update()
        ctx = self._make_context()
        import asyncio
        asyncio.run(admin_stats.handle_admin_stats(update, ctx, "stats:nope"))
        answer = update.callback_query.answer.call_args
        self.assertIn("نامعتبر", answer[0][0])


if __name__ == "__main__":
    unittest.main()
