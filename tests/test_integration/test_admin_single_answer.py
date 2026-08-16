"""B1 catching test: every admin callback is answered exactly once.

The double-notify bug (B1) made ``admin:`` / ``llm:`` callbacks produce two
``answer_callback_query`` calls — a redundant bare ack in ``bot.py`` plus the
handler's own ack. Routing these domains through the central registry
(``services.routing.dispatch``) must answer each callback exactly once.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.routing import dispatch


class AdminSingleAnswerTest(unittest.IsolatedAsyncioTestCase):
    def _callback_update(self, user_id: int = 1):
        query = MagicMock()
        query.answer = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = user_id
        update.callback_query = query
        return update, query

    def _context(self):
        context = MagicMock()
        context.user_data = {}
        context.bot = AsyncMock()
        return context

    async def test_admin_back_is_routed_and_answered_exactly_once(self):
        """admin:back routes through dispatch to _handle_admin_callback (B1 catcher).

        Asserting on the leaf ``_edit_or_send`` (not the handler) proves the
        registered ``admin`` route matched and dispatched — so the test fails if
        registration is removed (which would hit the unknown fallback instead).
        """
        update, query = self._callback_update()
        context = self._context()

        with (
            patch("services.routing.is_owner", return_value=True),
            patch("handlers.admin.is_owner", return_value=True),
            patch("handlers.admin._edit_or_send", new_callable=AsyncMock) as edit,
        ):
            await dispatch(update, context, "admin:back")

        edit.assert_awaited()
        query.answer.assert_awaited_once()

    async def test_llm_callback_is_answered_exactly_once(self):
        """llm: route through dispatch to one ack (non-self-answering branch)."""
        update, query = self._callback_update()
        context = self._context()

        with (
            patch("services.routing.is_owner", return_value=True),
            patch("handlers.admin_cost._show_llm_cost_dashboard", new_callable=AsyncMock),
        ):
            await dispatch(update, context, "llm:pricing")

        query.answer.assert_awaited_once()

    async def test_unknown_prefix_is_answered_exactly_once(self):
        """A prefix matching no route gets a single unknown ack from dispatch."""
        update, query = self._callback_update()
        context = self._context()

        # "zzz:back" matches no registered route, exercising the route-is-None path.
        await dispatch(update, context, "zzz:back")

        query.answer.assert_awaited_once()

    async def test_non_owner_admin_callback_single_answer(self):
        """A non-owner admin callback is rejected once, not twice."""
        update, query = self._callback_update(user_id=1234)
        context = self._context()

        with patch("services.routing.is_owner", return_value=False):
            await dispatch(update, context, "admin:back")

        query.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()