"""T2 (F2) regression: study start must not block the event loop.

The study start path performs sync SQLite reads/writes (user row, quota
slot, session build, grade-ledger clear, session persist). They must run in
worker threads via asyncio.to_thread so a slow build for one user does not
stall a concurrent second user (srs_handler pattern).

Fails before the fix (sync build serializes both starts and stalls the
heartbeat); passes after (builds overlap in workers, heartbeat stays flat).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from services.session import SessionNode


def _card(word: str) -> dict:
    return {
        "word": word,
        "phonetic": "/w/",
        "fa_meaning": "سلام",
        "fa_explanation": "توضیح",
        "synonyms": ["hi"],
        "antonyms": ["bye"],
        "examples": [f"{word} there!"],
        "example_translations": ["سلام!"],
        "grammar_tip": "نکته",
    }


class StudyStartOffLoopTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new
        db_schema.DB_PATH = new
        db.init_db()
        self.wids: dict[int, int] = {}
        for uid, word in ((11, "offloop-one"), (22, "offloop-two")):
            db.create_user_if_needed(uid, f"learner{uid}")
            db.set_user_lang_goal(uid, "en", "general")
            db.set_user_level(uid, "beginner")
            db.add_saved_word(uid, word, "en", _card(word))
            with db.get_conn() as conn:
                self.wids[uid] = conn.execute(
                    "SELECT id FROM saved_words WHERE user_id=? AND word=?",
                    (uid, word),
                ).fetchone()["id"]

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.edit_message_reply_markup = AsyncMock()
        return ctx

    def _update(self, uid: int):
        update = MagicMock()
        update.effective_user.id = uid
        update.effective_chat.id = 1000 + uid
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.message = None
        return update

    def test_concurrent_starts_overlap_and_heartbeat_stays_flat(self):
        from handlers.study_handler import handle_study_start

        def slow_build(user_id, lang=None, goal=None, level=None, plan="free",
                       max_nodes=5):
            # Blocking sync sleep: stalls the loop if run inline, overlaps
            # harmlessly when run in a worker thread via asyncio.to_thread.
            time.sleep(0.4)
            wid = self.wids[user_id]
            node = SessionNode(
                activity_type="first_exposure",
                source_tier=2,
                card_data={"word": "w"},
                source_id=wid,
                activity_meta={"user_id": user_id},
                grade_policy_ref="first_exposure",
            )
            return ([node], {})

        async def _run():
            loop = asyncio.get_running_loop()
            ticks: list[float] = []

            async def heartbeat():
                for _ in range(12):
                    t0 = loop.time()
                    await asyncio.sleep(0.05)
                    ticks.append(loop.time() - t0)

            ctx1, ctx2 = self._context(), self._context()
            with patch(
                "handlers.study_handler.build_session_list",
                side_effect=slow_build,
            ):
                hb = asyncio.create_task(heartbeat())
                t0 = loop.time()
                await asyncio.gather(
                    handle_study_start(self._update(11), ctx1),
                    handle_study_start(self._update(22), ctx2),
                )
                elapsed = loop.time() - t0
                await hb
            # Both sessions delivered (zero behavior change).
            self.assertIn("current_session", ctx1.user_data)
            self.assertIn("current_session", ctx2.user_data)
            # Sequential blocking builds would take >= 0.8s; overlapped
            # worker builds finish well under that.
            self.assertLess(
                elapsed, 0.7,
                f"study starts serialized on the loop (elapsed={elapsed:.2f}s)",
            )
            # A blocked loop stalls the heartbeat; off-loop keeps it flat.
            self.assertLess(
                max(ticks), 0.3,
                f"loop stalled during study build (max_tick={max(ticks):.2f}s)",
            )

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
