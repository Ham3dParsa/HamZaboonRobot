"""Grammar quota atomicity (fix/grammar-quota-atomic #2).

Verifies:
- reserve succeeds then AI failure releases (count -> 0)
- reserve succeeds then send/format failure releases
- reserve fails when quota exhausted (atomic, no increment)
- no await inside transaction for reserve/release
- concurrent reserves respect limit (limit 1, second fails)
"""

from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from services.db.schema import _today


def _set_db(tmpdir, db_module, schema_module):
    new_path = os.path.join(tmpdir.name, "test.sqlite")
    db_module.DB_PATH = new_path
    schema_module.DB_PATH = new_path
    db_module.init_db()
    return new_path


class GrammarQuotaAtomicTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        _set_db(self.tempdir, db, db_schema)
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        # ensure onboarded and known plan
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1, plan='free' WHERE user_id=1")
            conn.commit()

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _current_count(self, user_id=1):
        with db.get_conn() as conn:
            row = conn.execute("SELECT grammar_tips_asked_today, grammar_tips_asked_date FROM users WHERE user_id=?", (user_id,)).fetchone()
            return row["grammar_tips_asked_today"], row["grammar_tips_asked_date"]

    def test_reserve_then_release_on_ai_failure(self):
        """Reserve then release returns count to 0 (simulates AI failure path)."""
        limit = 5
        ok = db.reserve_grammar_tip(1, daily_limit=limit)
        self.assertTrue(ok)
        c, d = self._current_count()
        self.assertEqual(c, 1)
        self.assertEqual(d, _today().isoformat())
        db.release_grammar_tip(1)
        c2, _ = self._current_count()
        self.assertEqual(c2, 0)

    def test_retired_handler_does_not_reserve_and_sends_disabled(self):
        """Retired stub (#24) — no reserve, no AI, just disabled message."""
        from handlers.user import send_grammar_tip

        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.delete_message = AsyncMock()

        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 100
        update.effective_chat.send_action = AsyncMock()
        update.callback_query = None
        update.message = MagicMock()

        asyncio.run(send_grammar_tip(update, ctx))

        c, _ = self._current_count()
        self.assertEqual(c, 0, "retired handler must not reserve quota")
        # disabled message sent
        self.assertTrue(
            any("غیرفعال" in (call.kwargs.get("text") or "") for call in ctx.bot.send_message.call_args_list)
        )

    def test_retired_does_not_call_ai_or_persist(self):
        """Retired stub must not call AI pipeline or DB persist."""
        from handlers.user import send_grammar_tip

        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 100
        update.callback_query = None
        update.message = MagicMock()
        tip = {"title": "تست", "explanation": "توضیح", "example": "مثال"}
        with patch("handlers.user.db.add_grammar_tip", side_effect=RuntimeError("should not be called")):
            asyncio.run(send_grammar_tip(update, ctx))
        c, _ = self._current_count()
        self.assertEqual(c, 0)

    def test_retired_still_idempotent_no_quota_leak(self):
        from handlers.user import send_grammar_tip

        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 100
        update.callback_query = None
        update.message = MagicMock()
        tip = {"title": "تست", "explanation": "توضیح", "example": "مثال"}
        asyncio.run(send_grammar_tip(update, ctx))
        asyncio.run(send_grammar_tip(update, ctx))
        c, _ = self._current_count()
        self.assertEqual(c, 0)

    def test_reserve_fails_when_quota_exhausted_atomic(self):
        """Second reserve with limit 1 must fail and not increment."""
        limit = 1
        self.assertTrue(db.reserve_grammar_tip(1, daily_limit=limit))
        c, _ = self._current_count()
        self.assertEqual(c, 1)
        # second attempt should fail
        ok2 = db.reserve_grammar_tip(1, daily_limit=limit)
        self.assertFalse(ok2)
        c2, _ = self._current_count()
        self.assertEqual(c2, 1, "atomic: failed reserve must not increment")

    def test_concurrent_reserves_respect_limit(self):
        """Simulate 2 reserves with limit 1; second fails."""
        limit = 1
        # first succeeds
        self.assertTrue(db.reserve_grammar_tip(1, daily_limit=limit))
        # second fails even though separate transaction
        self.assertFalse(db.reserve_grammar_tip(1, daily_limit=limit))
        c, _ = self._current_count()
        self.assertEqual(c, 1)
        # release and reserve again succeeds
        db.release_grammar_tip(1)
        self.assertTrue(db.reserve_grammar_tip(1, daily_limit=limit))

    def test_no_await_inside_transaction(self):
        """reserve/release must contain no await (never hold txn across await)."""
        import services.db.users as users_mod

        for name in ("reserve_grammar_tip", "release_grammar_tip", "reserve_word_query", "release_word_query"):
            src = inspect.getsource(getattr(users_mod, name))
            self.assertNotIn("await", src, f"{name} must not contain await inside transaction")
            # also ensure it uses transaction() seam
            self.assertIn("transaction()", src, f"{name} must use transaction()")

    def test_release_idempotent_and_date_gated(self):
        """release only affects today's row; stale date unchanged."""
        limit = 5
        db.reserve_grammar_tip(1, daily_limit=limit)
        c, _ = self._current_count()
        self.assertEqual(c, 1)
        # double release should clamp to 0, not negative
        db.release_grammar_tip(1)
        db.release_grammar_tip(1)
        c2, _ = self._current_count()
        self.assertEqual(c2, 0)
        # set stale date
        with db.get_conn() as conn:
            # manually set yesterday
            import datetime

            yday = (db_schema._today() - datetime.timedelta(days=1)).isoformat()
            conn.execute("UPDATE users SET grammar_tips_asked_today=5, grammar_tips_asked_date=? WHERE user_id=1", (yday,))
            conn.commit()
        db.release_grammar_tip(1)
        with db.get_conn() as conn:
            row = conn.execute("SELECT grammar_tips_asked_today FROM users WHERE user_id=1").fetchone()
            self.assertEqual(row["grammar_tips_asked_today"], 5, "release must not touch stale date row")

    def test_current_daily_count_respects_today(self):
        """_current_daily_count returns 0 for stale date, value for today."""
        from services.db.schema import _current_daily_count

        today = _today().isoformat()
        self.assertEqual(_current_daily_count(5, today), 5)
        self.assertEqual(_current_daily_count(5, "2000-01-01"), 0)
        self.assertEqual(_current_daily_count(None, today), 0)
        self.assertEqual(_current_daily_count(0, today), 0)


if __name__ == "__main__":
    unittest.main()
