import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.word_query import (
    AskResult,
    PrepareResult,
    ToggleResult,
    ask,
    prepare,
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
    def test_invalid_input_releases_nothing_and_returns_error_key(self):
        with patch("services.word_query.db") as db, patch(
            "services.word_query.validate_word_query", return_value="word_digits"
        ):
            import asyncio

            result = asyncio.run(
                ask(
                    user_id=1,
                    text="123",
                    lang="fa",
                    level="B1",
                    plan="free",

                    generate_card=_ok_generate,
                )
            )
            db.reserve_word_query.assert_not_called()
            db.release_word_query.assert_not_called()
            self.assertEqual(result.kind, "invalid_input")
            self.assertEqual(result.error_key, "word_digits")

    def test_quota_exhausted_when_reserve_returns_false(self):
        with patch("services.word_query.db") as db:
            db.reserve_word_query.return_value = None
            db.release_word_query = MagicMock()
            generate = AsyncMock(return_value={})
            import asyncio

            result = asyncio.run(
                ask(
                    user_id=1,
                    text="apple",
                    lang="fa",
                    level="B1",
                    plan="free",

                    generate_card=generate,
                )
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
            db.get_user.return_value = {
                "id": 1,
                "plan": "free",
                "words_asked_today": 3,
                "words_asked_date": "2026-01-01",
            }
            db.should_show_pronounce.return_value = True
            import asyncio

            result = asyncio.run(
                ask(
                    user_id=1,
                    text="apple",
                    lang="fa",
                    level="B1",
                    plan="free",

                    generate_card=_ok_generate,
                )
            )
            db.reserve_word_query.assert_called_once()
            db.create_query_result.assert_called_once()
            db.touch_streak.assert_called_once()
            db.should_show_pronounce.assert_called_once()
            db.release_word_query.assert_not_called()
            self.assertEqual(result.kind, "ok")
            self.assertEqual(result.token, "tok123")
            self.assertEqual(result.card_data["word"], "apple")
            self.assertEqual(result.show_pronounce, True)

    def test_ai_timeout_releases_quota(self):
        import asyncio

        async def timeout_generate(**kwargs):
            raise asyncio.TimeoutError()

        with patch("services.word_query.db") as db, patch(
            "services.word_query.validate_word_query", return_value=None
        ):
            db.reserve_word_query.return_value = True
            result = asyncio.run(
                ask(
                    user_id=1,
                    text="apple",
                    lang="fa",
                    level="B1",
                    plan="free",

                    generate_card=timeout_generate,
                )
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
            db.reserve_word_query.return_value = True
            import asyncio

            result = asyncio.run(
                ask(
                    user_id=1,
                    text="apple",
                    lang="fa",
                    level="B1",
                    plan="free",

                    generate_card=prep_generate,
                )
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
            db.reserve_word_query.return_value = True
            import asyncio

            result = asyncio.run(
                ask(
                    user_id=1,
                    text="apple",
                    lang="fa",
                    level="B1",
                    plan="free",

                    generate_card=err_generate,
                )
            )
            self.assertEqual(result.kind, "ai_error")
            db.release_word_query.assert_called_once()
            db.create_query_result.assert_not_called()


class WordQueryPrepareTest(unittest.TestCase):
    async def _run(self, db, token="tok123", prepare_card=None, row=None):
        if row is not None:
            db.get_query_result.return_value = row
        return await prepare(
            token=token,
            user_id=1,
            prepare_card=prepare_card,
        )

    def test_expired_when_row_missing(self):
        with patch("services.word_query.db") as db:
            db.get_query_result.return_value = None
            import asyncio

            result = asyncio.run(self._run(db, row=None))
            # get_query_result returned None -> expired
            self.assertEqual(result.kind, "expired")

    def test_not_found_when_user_missing(self):
        with patch("services.word_query.db") as db:
            db.get_query_result.return_value = {
                "token": "tok1",
                "lang": "fa",
                "word": "apple",
                "result_json": '{"word":"apple"}',
            }
            db.get_user.return_value = None
            import asyncio

            result = asyncio.run(self._run(db, token="tok1"))
            self.assertEqual(result.kind, "not_found")

    def test_card_prep_error(self):
        from services.utils.formatting import CardPreparationError

        async def bad(card, **kwargs):
            raise CardPreparationError()

        with patch("services.word_query.db") as db:
            db.get_query_result.return_value = {
                "token": "tok1",
                "lang": "fa",
                "word": "apple",
                "result_json": '{"word":"apple"}',
            }
            db.get_user.return_value = {"id": 1, "plan": "free"}
            import asyncio

            result = asyncio.run(self._run(db, prepare_card=bad))
            self.assertEqual(result.kind, "card_prep_error")

    def test_ok_re_renders_prepared_card(self):
        async def enrich(card, persist_patch=None, **kwargs):
            card["fa_translations"] = ["ترجمه1"]
            if persist_patch:
                persist_patch({"fa_translations": card["fa_translations"]})
            return card

        with patch("services.word_query.db") as db:
            db.get_query_result.return_value = {
                "token": "tok1",
                "lang": "fa",
                "word": "apple",
                "result_json": '{"word":"apple"}',
            }
            db.get_user.return_value = {"id": 1, "plan": "free"}
            db.should_show_pronounce.return_value = True
            import asyncio

            result = asyncio.run(self._run(db, prepare_card=enrich))
            self.assertEqual(result.kind, "ok")
            self.assertEqual(result.card_data["fa_translations"], ["ترجمه1"])
            db.update_query_result_fields.assert_called_once()
            self.assertEqual(result.show_translations, False)
            self.assertEqual(result.show_pronounce, True)


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


if __name__ == "__main__":
    unittest.main()
