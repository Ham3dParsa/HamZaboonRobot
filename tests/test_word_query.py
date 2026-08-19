import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.utils.validation import ERR_INVALID_CHARS
from services.word_query import (
    AskResult,
    ToggleResult,
    ask,
    toggle_save,
)


async def _ok_generate(**kwargs):
    return {
        "word": "apple",
        "phonetic": "/ˈæp.əl/",
        "fa_meaning": "سیب",
        "fa_explanation": "میوه",
        "synonyms": [],
        "antonyms": [],
        "examples": [],
        "example_translations": [],
        "grammar_tip": "",
    }


class WordQueryAskTest(unittest.TestCase):
    def _complete_user(self):
        return {
            "id": 1,
            "plan": "free",
            "target_lang": "en",
            "goal": "general",
            "level": "beginner",
            "words_asked_today": 3,
            "words_asked_date": "2026-01-01",
        }

    def test_invalid_input_releases_nothing_and_returns_error_key(self):
        with patch("services.word_query.db") as db, patch(
            "services.word_query.validate_word_query", return_value=ERR_INVALID_CHARS
        ):
            db.get_user.return_value = self._complete_user()
            import asyncio

            result = asyncio.run(
                ask(user_id=1, text="123", generate_card=_ok_generate)
            )
            db.reserve_word_query.assert_not_called()
            db.release_word_query.assert_not_called()
            self.assertEqual(result.kind, "invalid_input")
            self.assertEqual(result.error_key, ERR_INVALID_CHARS)

    def test_registration_required_when_user_missing(self):
        with patch("services.word_query.db") as db:
            db.get_user.return_value = None
            generate = AsyncMock(return_value={})
            import asyncio

            result = asyncio.run(
                ask(user_id=1, text="apple", generate_card=generate)
            )
            self.assertEqual(result.kind, "registration_required")
            self.assertIsInstance(result, AskResult)
            db.reserve_word_query.assert_not_called()
            generate.assert_not_called()

    def test_registration_required_when_profile_incomplete(self):
        for missing in ("target_lang", "goal", "level"):
            with self.subTest(missing=missing):
                with patch("services.word_query.db") as db:
                    row = self._complete_user()
                    row[missing] = None
                    db.get_user.return_value = row
                    import asyncio

                    result = asyncio.run(
                        ask(user_id=1, text="apple", generate_card=_ok_generate)
                    )
                    self.assertEqual(result.kind, "registration_required")
                    db.reserve_word_query.assert_not_called()

    def test_quota_exhausted_when_reserve_returns_false(self):
        with patch("services.word_query.db") as db:
            db.get_user.return_value = self._complete_user()
            db.reserve_word_query.return_value = None
            db.release_word_query = MagicMock()
            generate = AsyncMock(return_value={})
            import asyncio

            result = asyncio.run(
                ask(user_id=1, text="apple", generate_card=generate)
            )
            self.assertEqual(result.kind, "quota_exhausted")
            generate.assert_not_called()
            db.release_word_query.assert_not_called()

    def test_success_returns_ok_and_persists(self):
        with patch("services.word_query.db") as db, patch(
            "services.word_query.validate_word_query", return_value=None
        ):
            db.reserve_word_query.return_value = True
            db.create_query_result.return_value = "tok123"
            db.get_user.return_value = self._complete_user()
            import asyncio

            result = asyncio.run(
                ask(user_id=1, text="apple", generate_card=_ok_generate)
            )
            db.reserve_word_query.assert_called_once()
            db.create_query_result.assert_called_once()
            db.touch_streak.assert_called_once()
            db.release_word_query.assert_not_called()
            self.assertEqual(result.kind, "ok")
            self.assertEqual(result.token, "tok123")
            self.assertEqual(result.card_data["word"], "apple")
            self.assertIsInstance(result, AskResult)

    def test_usage_text_reflects_post_reservation_count(self):
        # The displayed usage count must be read from a FRESH row after the
        # quota was reserved, not the pre-reservation snapshot (off-by-one bug).
        with patch("services.word_query.db") as db, patch(
            "services.word_query.validate_word_query", return_value=None
        ):
            db.reserve_word_query.return_value = True
            db.create_query_result.return_value = "tok123"
            from config import _app_today
            before = self._complete_user()  # words_asked_today = 3
            after = self._complete_user()
            after["words_asked_today"] = 4  # reserve incremented it
            after["words_asked_date"] = _app_today()  # today, so the count is used
            db.get_user.side_effect = [before, after]
            import asyncio

            result = asyncio.run(
                ask(user_id=1, text="apple", generate_card=_ok_generate)
            )
            self.assertEqual(result.kind, "ok")
            self.assertIn("4/", result.usage_text, "usage must show the post-reserve count")

    def test_empty_ai_card_is_not_persisted_and_quota_released(self):
        with patch("services.word_query.db") as db, patch(
            "services.word_query.validate_word_query", return_value=None
        ):
            db.get_user.return_value = self._complete_user()
            db.reserve_word_query.return_value = True

            async def empty(**kwargs):
                return {"fa_meaning": "هیچ"}  # no "word" => unusable card

            import asyncio

            result = asyncio.run(
                ask(user_id=1, text="apple", generate_card=empty)
            )
            self.assertEqual(result.kind, "persist_error")
            db.release_word_query.assert_called_once()
            db.create_query_result.assert_not_called()
            db.touch_streak.assert_not_called()

    def test_persist_failure_releases_quota(self):
        with patch("services.word_query.db") as db, patch(
            "services.word_query.validate_word_query", return_value=None
        ):
            db.get_user.return_value = self._complete_user()
            db.reserve_word_query.return_value = True
            db.create_query_result.side_effect = RuntimeError("database is locked")
            import asyncio

            result = asyncio.run(
                ask(user_id=1, text="apple", generate_card=_ok_generate)
            )
            self.assertEqual(result.kind, "persist_error")
            db.release_word_query.assert_called_once()

    def test_ai_timeout_releases_quota(self):
        import asyncio

        async def timeout_generate(**kwargs):
            raise asyncio.TimeoutError()

        with patch("services.word_query.db") as db, patch(
            "services.word_query.validate_word_query", return_value=None
        ):
            db.get_user.return_value = self._complete_user()
            db.reserve_word_query.return_value = True

            result = asyncio.run(
                ask(user_id=1, text="apple", generate_card=timeout_generate)
            )
            self.assertEqual(result.kind, "ai_timeout")
            db.release_word_query.assert_called_once()
            db.create_query_result.assert_not_called()

    def test_card_prep_error_releases_quota(self):
        from services.utils.formatting import CardPreparationError

        async def prep_generate(**kwargs):
            raise CardPreparationError()

        with patch("services.word_query.db") as db, patch(
            "services.word_query.validate_word_query", return_value=None
        ):
            db.get_user.return_value = self._complete_user()
            db.reserve_word_query.return_value = True
            import asyncio

            result = asyncio.run(
                ask(user_id=1, text="apple", generate_card=prep_generate)
            )
            self.assertEqual(result.kind, "card_prep_error")
            db.release_word_query.assert_called_once()
            db.create_query_result.assert_not_called()

    def test_generic_ai_error_releases_quota(self):
        async def err_generate(**kwargs):
            raise RuntimeError("boom")

        with patch("services.word_query.db") as db, patch(
            "services.word_query.validate_word_query", return_value=None
        ):
            db.get_user.return_value = self._complete_user()
            db.reserve_word_query.return_value = True
            import asyncio

            result = asyncio.run(
                ask(user_id=1, text="apple", generate_card=err_generate)
            )
            self.assertEqual(result.kind, "ai_error")
            db.release_word_query.assert_called_once()
            db.create_query_result.assert_not_called()


class WordQueryToggleTest(unittest.TestCase):
    def test_expired_when_row_missing(self):
        with patch("services.word_query.db") as db:
            db.get_query_result.return_value = None
            import asyncio

            result = asyncio.run(
                toggle_save(token="tok123", user_id=1)
            )
            self.assertEqual(result.kind, "expired")
            db.toggle_review_word.assert_not_called()

    def test_saves_and_marks(self):
        with patch("services.word_query.db") as db:
            db.get_query_result.return_value = {
                "token": "tok1",
                "lang": "fa",
                "word": "apple",
                "result_json": '{"word":"apple"}',
            }
            db.toggle_review_word.return_value = "saved"
            import asyncio

            result = asyncio.run(
                toggle_save(token="tok1", user_id=1)
            )
            self.assertEqual(result.kind, "ok")
            self.assertTrue(result.saved)
            db.mark_query_result_saved.assert_called_once_with("tok1")
            db.clear_query_result_saved.assert_not_called()
            self.assertIn("ذخیره", result.message)

    def test_removes_and_clears(self):
        with patch("services.word_query.db") as db:
            db.get_query_result.return_value = {
                "token": "tok1",
                "lang": "fa",
                "word": "apple",
                "result_json": '{"word":"apple"}',
            }
            db.toggle_review_word.return_value = "removed"
            import asyncio

            result = asyncio.run(
                toggle_save(token="tok1", user_id=1)
            )
            self.assertEqual(result.kind, "ok")
            self.assertFalse(result.saved)
            db.clear_query_result_saved.assert_called_once_with("tok1")
            db.mark_query_result_saved.assert_not_called()
            self.assertIn("حذف", result.message)
            self.assertIsInstance(result, ToggleResult)

    def test_corrupt_result_json_refuses_and_returns_expired(self):
        with patch("services.word_query.db") as db:
            db.get_query_result.return_value = {
                "token": "tok1",
                "lang": "fa",
                "word": "apple",
                "result_json": "{not-json",
            }
            import asyncio

            result = asyncio.run(
                toggle_save(token="tok1", user_id=1)
            )
            self.assertEqual(result.kind, "expired")
            db.toggle_review_word.assert_not_called()


if __name__ == "__main__":
    unittest.main()