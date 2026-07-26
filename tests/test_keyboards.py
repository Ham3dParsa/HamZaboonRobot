import unittest
from config.keyboards import (
    main_menu,
    settings_inline_keyboard,
    settings_back_keyboard,
    admin_awaiting_inline_keyboard,
    srs_hidden_keyboard,
    srs_revealed_keyboard,
    srs_review_keyboard,
    daily_card_keyboard,
    lang_inline_keyboard,
    goal_inline_keyboard,
    level_inline_keyboard,
    presentation_settings_keyboard,
    BTN_STUDY_SESSION,
    BTN_ASK_WORD,
    BTN_SETTINGS,
    BTN_ADMIN,
    IBTN_REMEMBERED,
    IBTN_REVEAL,
    IBTN_CONFIRM_CORRECT,
    IBTN_REMIND_AGAIN,
    IBTN_TRANSLATIONS,
    IBTN_PRONOUNCE,
    IBTN_PREV_CARD,
    IBTN_NEXT_CARD,
    IBTN_NEXT_CARD_NEW,
    IBTN_CLOSE,
    IBTN_BACK_TO_SETTINGS,
)


class TestMainMenuKeyboard(unittest.TestCase):
    def test_non_admin_has_exact_rows_and_labels(self):
        markup = main_menu(False)
        rows = markup.keyboard
        self.assertEqual(len(rows), 3)
        self.assertEqual([b.text for b in rows[0]], [BTN_STUDY_SESSION])
        self.assertEqual([b.text for b in rows[1]], [BTN_ASK_WORD])
        self.assertEqual([b.text for b in rows[2]], [BTN_SETTINGS])

    def test_admin_appends_extra_row(self):
        markup = main_menu(True)
        rows = markup.keyboard
        self.assertEqual(len(rows), 4)
        self.assertEqual([b.text for b in rows[3]], [BTN_ADMIN])

    def test_non_admin_has_no_admin_button(self):
        markup = main_menu(False)
        labels = [b.text for row in markup.keyboard for b in row]
        self.assertNotIn(BTN_ADMIN, labels)

    def test_old_buttons_removed(self):
        markup = main_menu(False)
        labels = [b.text for row in markup.keyboard for b in row]
        self.assertNotIn("📊 وضعیت من", labels)
        self.assertNotIn("🌐 تغییر زبان", labels)
        self.assertNotIn("🎯 تغییر هدف", labels)
        self.assertNotIn("📚 تنظیم سطح زبان", labels)
        self.assertNotIn("📝 تنظیم نمایش کارت", labels)


class TestSettingsInlineKeyboard(unittest.TestCase):
    def test_layout_and_callback_data(self):
        markup = settings_inline_keyboard("English", "General", "B2")
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][0].text, "🌐 زبان: English")
        self.assertEqual(rows[0][0].callback_data, "settings:lang")
        self.assertEqual(rows[0][1].text, "🎯 هدف: General")
        self.assertEqual(rows[0][1].callback_data, "settings:goal")
        self.assertEqual(rows[1][0].text, "📚 سطح: B2")
        self.assertEqual(rows[1][0].callback_data, "settings:level")
        self.assertEqual(rows[1][1].text, "📝 نوع نمایش کارت")
        self.assertEqual(rows[1][1].callback_data, "settings:presentation")
        self.assertEqual(rows[2][0].text, "👤 وضعیت اشتراک و آمار")
        self.assertEqual(rows[2][0].callback_data, "settings:status")

    def test_close_button_exists(self):
        markup = settings_inline_keyboard("English", "General", "B2")
        rows = markup.inline_keyboard
        self.assertEqual(rows[3][0].text, IBTN_CLOSE)
        self.assertEqual(rows[3][0].callback_data, "settings:close")


class TestSettingsBackKeyboard(unittest.TestCase):
    def test_single_back_button(self):
        markup = settings_back_keyboard()
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0].text, IBTN_BACK_TO_SETTINGS)
        self.assertEqual(rows[0][0].callback_data, "settings:back")


class TestLangInlineKeyboard(unittest.TestCase):
    def test_back_to_settings_appended(self):
        markup = lang_inline_keyboard(back_to_settings=True)
        rows = markup.inline_keyboard
        last_row = rows[-1]
        self.assertEqual(last_row[0].text, IBTN_BACK_TO_SETTINGS)
        self.assertEqual(last_row[0].callback_data, "settings:back")

    def test_no_back_by_default(self):
        markup = lang_inline_keyboard()
        rows = markup.inline_keyboard
        labels = [b.text for row in rows for b in row]
        self.assertNotIn(IBTN_BACK_TO_SETTINGS, labels)


class TestGoalInlineKeyboard(unittest.TestCase):
    def test_back_to_settings_appended(self):
        markup = goal_inline_keyboard(back_to_settings=True)
        rows = markup.inline_keyboard
        last_row = rows[-1]
        self.assertEqual(last_row[0].text, IBTN_BACK_TO_SETTINGS)
        self.assertEqual(last_row[0].callback_data, "settings:back")

    def test_no_back_by_default(self):
        markup = goal_inline_keyboard()
        rows = markup.inline_keyboard
        labels = [b.text for row in rows for b in row]
        self.assertNotIn(IBTN_BACK_TO_SETTINGS, labels)


class TestLevelInlineKeyboard(unittest.TestCase):
    def test_back_to_settings_appended(self):
        markup = level_inline_keyboard(back_to_settings=True)
        rows = markup.inline_keyboard
        last_row = rows[-1]
        self.assertEqual(last_row[0].text, IBTN_BACK_TO_SETTINGS)
        self.assertEqual(last_row[0].callback_data, "settings:back")

    def test_no_back_by_default(self):
        markup = level_inline_keyboard()
        rows = markup.inline_keyboard
        labels = [b.text for row in rows for b in row]
        self.assertNotIn(IBTN_BACK_TO_SETTINGS, labels)


class TestPresentationKeyboard(unittest.TestCase):
    def test_back_to_settings_appended(self):
        markup = presentation_settings_keyboard("brief", back_to_settings=True)
        rows = markup.inline_keyboard
        last_row = rows[-1]
        self.assertEqual(last_row[0].text, IBTN_BACK_TO_SETTINGS)
        self.assertEqual(last_row[0].callback_data, "settings:back")

    def test_no_back_by_default(self):
        markup = presentation_settings_keyboard("brief")
        rows = markup.inline_keyboard
        labels = [b.text for row in rows for b in row]
        self.assertNotIn(IBTN_BACK_TO_SETTINGS, labels)


class TestAdminAwaitingInlineKeyboard(unittest.TestCase):
    def test_labels_are_persian(self):
        markup = admin_awaiting_inline_keyboard()
        rows = markup.inline_keyboard
        self.assertEqual(rows[0][0].text, "↩️ بازگشت")
        self.assertEqual(rows[0][0].callback_data, "admin:back")
        self.assertEqual(rows[0][1].text, "❌ لغو")
        self.assertEqual(rows[0][1].callback_data, "admin:cancel")


class TestSRSHiddenKeyboard(unittest.TestCase):
    def test_hidden_stage_has_remember_and_reveal(self):
        markup = srs_hidden_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0].text, IBTN_REMEMBERED)
        self.assertEqual(rows[0][0].callback_data, "srs:remember:1:10")
        self.assertEqual(rows[0][1].text, IBTN_REVEAL)
        self.assertEqual(rows[0][1].callback_data, "srs:reveal:1:10")

    def test_hidden_stage_with_pronounce(self):
        markup = srs_hidden_keyboard(1, 10, show_pronounce=True)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0].text, IBTN_PRONOUNCE)
        self.assertEqual(rows[1][0].callback_data, "tts:pronounce:s:1:10")


class TestSRSRevealedKeyboard(unittest.TestCase):
    def test_revealed_stage_layout(self):
        markup = srs_revealed_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0].text, IBTN_TRANSLATIONS)
        self.assertEqual(rows[0][0].callback_data, "srs:prepare:1:10")
        self.assertEqual(rows[1][0].text, IBTN_CONFIRM_CORRECT)
        self.assertEqual(rows[1][0].callback_data, "srs:confirm:1:10")
        self.assertEqual(rows[1][1].text, IBTN_REMIND_AGAIN)
        self.assertEqual(rows[1][1].callback_data, "srs:again:1:10")

    def test_revealed_stage_with_pronounce(self):
        markup = srs_revealed_keyboard(1, 10, show_pronounce=True)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(rows[0][1].text, IBTN_PRONOUNCE)


class TestSRSReviewKeyboard(unittest.TestCase):
    def test_review_stage_layout(self):
        markup = srs_review_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0].text, IBTN_REMEMBERED)
        self.assertEqual(rows[0][0].callback_data, "srs:remember:1:10")
        self.assertEqual(rows[0][1].text, IBTN_REMIND_AGAIN)
        self.assertEqual(rows[0][1].callback_data, "srs:again:1:10")

    def test_review_stage_with_translations_and_pronounce(self):
        markup = srs_review_keyboard(1, 10, show_translations=True, show_pronounce=True)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(rows[0][0].text, IBTN_TRANSLATIONS)
        self.assertEqual(rows[0][1].text, IBTN_PRONOUNCE)
        self.assertEqual(rows[1][0].text, IBTN_REMEMBERED)
        self.assertEqual(rows[1][1].text, IBTN_REMIND_AGAIN)


class TestDailyCardKeyboard(unittest.TestCase):
    def test_prev_next_navigation_seen(self):
        markup = daily_card_keyboard(1, "2026-07-25", 1, has_next=True, has_prev=True, next_card_is_new=False)
        rows = markup.inline_keyboard
        nav_row = rows[-1]
        self.assertEqual(nav_row[0].text, IBTN_PREV_CARD)
        self.assertEqual(nav_row[0].callback_data, "daily:prev:1:2026-07-25:1")
        self.assertEqual(nav_row[1].text, IBTN_NEXT_CARD)
        self.assertEqual(nav_row[1].callback_data, "daily:next:1:2026-07-25:1")

    def test_prev_next_navigation_new(self):
        markup = daily_card_keyboard(1, "2026-07-25", 0, has_next=True, has_prev=True, next_card_is_new=True)
        rows = markup.inline_keyboard
        nav_row = rows[-1]
        self.assertEqual(nav_row[0].text, IBTN_PREV_CARD)
        self.assertEqual(nav_row[1].text, IBTN_NEXT_CARD_NEW)
        self.assertEqual(nav_row[1].callback_data, "daily:next:1:2026-07-25:0")

    def test_default_next_card_is_new(self):
        markup = daily_card_keyboard(1, "2026-07-25", 0, has_next=True)
        rows = markup.inline_keyboard
        nav_row = rows[-1]
        self.assertEqual(nav_row[0].text, IBTN_NEXT_CARD_NEW)

    def test_first_card_no_prev(self):
        markup = daily_card_keyboard(1, "2026-07-25", 0, has_next=True, has_prev=False)
        rows = markup.inline_keyboard
        nav_row = rows[-1]
        self.assertEqual(len(nav_row), 1)
        self.assertEqual(nav_row[0].text, IBTN_NEXT_CARD_NEW)

    def test_last_card_no_next(self):
        markup = daily_card_keyboard(1, "2026-07-25", 2, has_next=False, has_prev=True)
        rows = markup.inline_keyboard
        nav_row = rows[-1]
        self.assertEqual(len(nav_row), 1)
        self.assertEqual(nav_row[0].text, IBTN_PREV_CARD)

    def test_returns_none_when_no_buttons(self):
        markup = daily_card_keyboard(1, "2026-07-25", 0, has_next=False, has_prev=False)
        self.assertIsNone(markup)

    def test_translations_and_pronounce_row(self):
        markup = daily_card_keyboard(1, "2026-07-25", 0, has_next=True, show_translations=True, show_pronounce=True)
        rows = markup.inline_keyboard
        top_row = rows[0]
        self.assertEqual(top_row[0].text, IBTN_TRANSLATIONS)
        self.assertEqual(top_row[1].text, IBTN_PRONOUNCE)

    def test_review_prefix_for_next(self):
        markup = daily_card_keyboard(1, "2026-07-25", 0, has_next=True, callback_prefix="review:next", has_prev=True, next_card_is_new=False)
        rows = markup.inline_keyboard
        nav_row = rows[-1]
        self.assertEqual(nav_row[1].text, IBTN_NEXT_CARD)
        self.assertEqual(nav_row[1].callback_data, "review:next:1:2026-07-25:0")
