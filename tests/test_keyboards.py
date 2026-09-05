import unittest
from telegram.constants import KeyboardButtonStyle
from config.keyboards import (
    main_menu,
    settings_inline_keyboard,
    settings_back_keyboard,
    admin_awaiting_inline_keyboard,
    get_review_keyboard,
    get_first_exposure_keyboard,
    get_srs_front_keyboard,
    get_srs_delete_confirm_keyboard,
    display_toggles_keyboard,
    user_display_toggles_keyboard,
    display_toggle_confirm_keyboard,
    IBTN_SRS_REVEAL,
    lang_inline_keyboard,
    goal_inline_keyboard,
    level_inline_keyboard,
    presentation_settings_keyboard,
    BTN_STUDY_SESSION,
    BTN_ASK_WORD,
    BTN_SETTINGS,
    BTN_HELP,
    BTN_ADMIN,
    IBTN_SRS_AGAIN_REVIEW,
    IBTN_SRS_HARD_REVIEW,
    IBTN_SRS_GOOD_REVIEW,
    IBTN_SRS_EASY_REVIEW,
    IBTN_SRS_AGAIN_FE,
    IBTN_SRS_HARD_FE,
    IBTN_SRS_GOOD_FE,
    IBTN_SRS_EASY_FE,
    IBTN_SRS_DELETE,
    IBTN_PRONOUNCE,
    IBTN_CLOSE,
    IBTN_BACK_TO_SETTINGS,
)


class TestMainMenuKeyboard(unittest.TestCase):
    def test_non_admin_has_exact_rows_and_labels(self):
        markup = main_menu(False)
        rows = markup.keyboard
        self.assertEqual(len(rows), 2)
        self.assertEqual([b.text for b in rows[0]], [BTN_ASK_WORD, BTN_STUDY_SESSION])
        self.assertEqual([b.text for b in rows[1]], [BTN_HELP, BTN_SETTINGS])

    def test_admin_appends_extra_row(self):
        markup = main_menu(True)
        rows = markup.keyboard
        self.assertEqual(len(rows), 3)
        self.assertEqual([b.text for b in rows[0]], [BTN_ASK_WORD, BTN_STUDY_SESSION])
        self.assertEqual([b.text for b in rows[1]], [BTN_HELP, BTN_SETTINGS])
        self.assertEqual([b.text for b in rows[2]], [BTN_ADMIN])

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
        self.assertEqual(rows[1][1].text, "🎛 نمایش کارت")
        self.assertEqual(rows[1][1].callback_data, "settings:display_toggles")
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
        self.assertEqual(rows[0][1].text, "🚫 لغو")
        self.assertEqual(rows[0][1].callback_data, "admin:cancel")


class TestReviewKeyboard(unittest.TestCase):
    def test_review_keyboard_has_4_grade_buttons(self):
        markup = get_review_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 3)  # 2 grade rows + one 🔊/🗑 row
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(len(rows[1]), 2)
        # Row 0: Hard, Again
        self.assertEqual(rows[0][0].text, IBTN_SRS_HARD_REVIEW)
        self.assertEqual(rows[0][0].callback_data, "srs:2:1:10")
        self.assertEqual(rows[0][1].text, IBTN_SRS_AGAIN_REVIEW)
        self.assertEqual(rows[0][1].callback_data, "srs:1:1:10")
        # Row 1: Easy, Good
        self.assertEqual(rows[1][0].text, IBTN_SRS_EASY_REVIEW)
        self.assertEqual(rows[1][0].callback_data, "srs:4:1:10")
        self.assertEqual(rows[1][1].text, IBTN_SRS_GOOD_REVIEW)
        self.assertEqual(rows[1][1].callback_data, "srs:3:1:10")
        # Row 2: 🗑 delete + 🔊 pronounce (same row)
        self.assertEqual(len(rows[2]), 2)
        self.assertEqual(rows[2][0].text, IBTN_SRS_DELETE)
        self.assertEqual(rows[2][0].callback_data, "srs:delete:1:10")
        self.assertEqual(rows[2][1].text, IBTN_PRONOUNCE)
        self.assertEqual(rows[2][1].callback_data, "tts:pronounce:s:1:10")

    def test_review_keyboard_with_pronounce(self):
        markup = get_review_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 3)  # 2 grade + one 🗑/🔊 row
        self.assertEqual(rows[2][0].text, IBTN_SRS_DELETE)
        self.assertEqual(rows[2][0].callback_data, "srs:delete:1:10")
        self.assertEqual(rows[2][1].text, IBTN_PRONOUNCE)
        self.assertEqual(rows[2][1].callback_data, "tts:pronounce:s:1:10")

    def test_all_callbacks_match_pattern(self):
        markup = get_review_keyboard(123, 456)
        rows = markup.inline_keyboard
        for row in rows[:-1]:  # grade rows only; last row is 🔊 + 🗑
            for btn in row:
                self.assertTrue(btn.callback_data.startswith("srs:"))
                parts = btn.callback_data.split(":")
                self.assertEqual(len(parts), 4)
                self.assertIn(parts[1], {"1", "2", "3", "4"})  # grade 1-4
                self.assertEqual(parts[2], "123")
                self.assertEqual(parts[3], "456")
        last = rows[-1]
        self.assertEqual(len(last), 2)
        self.assertEqual(last[0].callback_data, "srs:delete:123:456")
        self.assertEqual(last[1].callback_data, "tts:pronounce:s:123:456")

    def test_review_grade_styles_l1(self):
        # U1: all 4 review grades neutral (no color bias).
        markup = get_review_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(rows[0][1].callback_data, "srs:1:1:10")
        self.assertIsNone(rows[0][1].style)
        self.assertEqual(rows[0][0].callback_data, "srs:2:1:10")
        self.assertIsNone(rows[0][0].style)
        self.assertEqual(rows[1][1].callback_data, "srs:3:1:10")
        self.assertIsNone(rows[1][1].style)
        self.assertEqual(rows[1][0].callback_data, "srs:4:1:10")
        self.assertIsNone(rows[1][0].style)

    def test_review_row3_stays_neutral_l1(self):
        # L1: pronounce + Delete ENTRY neutral (confirm from Q3/L3 carries red).
        markup = get_review_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(rows[2][0].callback_data, "srs:delete:1:10")
        self.assertIsNone(rows[2][0].style)
        self.assertEqual(rows[2][1].callback_data, "tts:pronounce:s:1:10")
        self.assertIsNone(rows[2][1].style)


class TestSrsFrontKeyboard(unittest.TestCase):
    def test_front_review_keyboard_has_reveal_button(self):
        markup = get_srs_front_keyboard(123, 456)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0].text, IBTN_SRS_REVEAL)
        self.assertEqual(rows[0][0].callback_data, "srs:reveal:123:456")

    def test_front_keyboard_callback_under_srs_prefix(self):
        markup = get_srs_front_keyboard(1, 10)
        cb = markup.inline_keyboard[0][0].callback_data
        self.assertTrue(cb.startswith("srs:"))
        self.assertEqual(cb.split(":")[0:2], ["srs", "reveal"])


class TestFirstExposureKeyboard(unittest.TestCase):
    def test_first_exposure_keyboard_has_4_grade_buttons(self):
        markup = get_first_exposure_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 3)  # 2 grade rows + one 🔊/🗑 row
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(len(rows[1]), 2)
        # Row 0: Hard, Again
        self.assertEqual(rows[0][0].text, IBTN_SRS_HARD_FE)
        self.assertEqual(rows[0][0].callback_data, "srs:fe:2:1:10")
        self.assertEqual(rows[0][1].text, IBTN_SRS_AGAIN_FE)
        self.assertEqual(rows[0][1].callback_data, "srs:fe:1:1:10")
        # Row 1: Easy, Good
        self.assertEqual(rows[1][0].text, IBTN_SRS_EASY_FE)
        self.assertEqual(rows[1][0].callback_data, "srs:fe:4:1:10")
        self.assertEqual(rows[1][1].text, IBTN_SRS_GOOD_FE)
        self.assertEqual(rows[1][1].callback_data, "srs:fe:3:1:10")
        # Row 2: 🗑 delete + 🔊 pronounce (same row)
        self.assertEqual(len(rows[2]), 2)
        self.assertEqual(rows[2][0].text, IBTN_SRS_DELETE)
        self.assertEqual(rows[2][0].callback_data, "srs:delete:1:10")
        self.assertEqual(rows[2][1].text, IBTN_PRONOUNCE)
        self.assertEqual(rows[2][1].callback_data, "tts:pronounce:s:1:10")

    def test_first_exposure_keyboard_with_pronounce(self):
        markup = get_first_exposure_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), 3)  # 2 grade + one 🗑/🔊 row
        self.assertEqual(rows[2][0].text, IBTN_SRS_DELETE)
        self.assertEqual(rows[2][0].callback_data, "srs:delete:1:10")
        self.assertEqual(rows[2][1].text, IBTN_PRONOUNCE)
        self.assertEqual(rows[2][1].callback_data, "tts:pronounce:s:1:10")

    def test_all_callbacks_match_fe_pattern(self):
        markup = get_first_exposure_keyboard(123, 456)
        rows = markup.inline_keyboard
        for row in rows[:-1]:  # grade rows only; last row is 🔊 + 🗑
            for btn in row:
                self.assertTrue(btn.callback_data.startswith("srs:fe:"))
                parts = btn.callback_data.split(":")
                self.assertEqual(len(parts), 5)
                self.assertIn(parts[2], {"1", "2", "3", "4"})  # grade 1-4
                self.assertEqual(parts[3], "123")
                self.assertEqual(parts[4], "456")
        last = rows[-1]
        self.assertEqual(len(last), 2)
        self.assertEqual(last[0].callback_data, "srs:delete:123:456")
        self.assertEqual(last[1].callback_data, "tts:pronounce:s:123:456")

    def test_first_exposure_grade_styles_l2(self):
        # U1: all 4 first-exposure grades neutral (no color bias).
        markup = get_first_exposure_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(rows[0][1].callback_data, "srs:fe:1:1:10")
        self.assertIsNone(rows[0][1].style)
        self.assertEqual(rows[0][0].callback_data, "srs:fe:2:1:10")
        self.assertIsNone(rows[0][0].style)
        self.assertEqual(rows[1][1].callback_data, "srs:fe:3:1:10")
        self.assertIsNone(rows[1][1].style)
        self.assertEqual(rows[1][0].callback_data, "srs:fe:4:1:10")
        self.assertIsNone(rows[1][0].style)

    def test_first_exposure_row3_stays_neutral_l2(self):
        # L2: pronounce + Delete ENTRY neutral (confirm from Q3/L3 carries red).
        markup = get_first_exposure_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(rows[2][0].callback_data, "srs:delete:1:10")
        self.assertIsNone(rows[2][0].style)
        self.assertEqual(rows[2][1].callback_data, "tts:pronounce:s:1:10")
        self.assertIsNone(rows[2][1].style)


class TestSrsDeleteConfirmStyle(unittest.TestCase):
    def test_delete_confirm_yes_is_danger_l3(self):
        # L3 (Q3 LOCKED): study delete-confirm YES=DANGER (irreversible delete).
        markup = get_srs_delete_confirm_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(rows[0][0].callback_data, "srs:delete:yes:1:10")
        self.assertEqual(rows[0][0].style, KeyboardButtonStyle.DANGER)

    def test_delete_confirm_no_stays_neutral_l3(self):
        # L3: cancel stays neutral (retreat).
        markup = get_srs_delete_confirm_keyboard(1, 10)
        rows = markup.inline_keyboard
        self.assertEqual(rows[0][1].callback_data, "srs:delete:no:1:10")
        self.assertIsNone(rows[0][1].style)


class TestDisplayToggleStylesL4(unittest.TestCase):
    def test_admin_on_rows_primary_off_neutral_l4(self):
        # L4 (applied precedent): ON (✅) = PRIMARY, OFF (⭕) = neutral.
        from config.catalog import DISPLAY_TOGGLE_FIELDS

        current = {f: True for f in DISPLAY_TOGGLE_FIELDS}
        current[DISPLAY_TOGGLE_FIELDS[0]] = False
        markup = display_toggles_keyboard(current)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), len(DISPLAY_TOGGLE_FIELDS) + 2)
        for row, field in zip(rows, DISPLAY_TOGGLE_FIELDS):
            btn = row[0]
            self.assertEqual(btn.callback_data, f"admin:display_toggle:{field}")
            if current[field]:
                self.assertTrue(btn.text.startswith("✅"))
                self.assertEqual(btn.style, KeyboardButtonStyle.PRIMARY)
            else:
                self.assertTrue(btn.text.startswith("⭕"))
                self.assertIsNone(btn.style)
        self.assertEqual(rows[-2][0].callback_data, "admin:back")
        self.assertIsNone(rows[-2][0].style)
        self.assertEqual(rows[-1][0].callback_data, "admin:close")
        self.assertIsNone(rows[-1][0].style)

    def test_user_on_rows_primary_forced_lock_kept_l4(self):
        # L4: ON incl. 🔒 forced = PRIMARY; OFF = neutral; lock label kept.
        from config.catalog import DISPLAY_TOGGLE_FIELDS

        on_field = DISPLAY_TOGGLE_FIELDS[1]
        off_field = DISPLAY_TOGGLE_FIELDS[0]
        current = {f: True for f in DISPLAY_TOGGLE_FIELDS}
        current[off_field] = False
        forced = {on_field: True, off_field: False}
        markup = user_display_toggles_keyboard(current, forced)
        rows = markup.inline_keyboard
        self.assertEqual(len(rows), len(DISPLAY_TOGGLE_FIELDS) + 1)
        by_cb = {row[0].callback_data: row[0] for row in rows[:-1]}
        on_btn = by_cb[f"settings:display_toggle:{on_field}"]
        self.assertIn("🔒", on_btn.text)
        self.assertTrue(on_btn.text.startswith("✅"))
        self.assertEqual(on_btn.style, KeyboardButtonStyle.PRIMARY)
        off_btn = by_cb[f"settings:display_toggle:{off_field}"]
        self.assertIn("🔒", off_btn.text)
        self.assertTrue(off_btn.text.startswith("⭕"))
        self.assertIsNone(off_btn.style)
        self.assertEqual(rows[-1][0].callback_data, "settings:back")
        self.assertIsNone(rows[-1][0].style)

    def test_confirm_yes_success_cancel_neutral_l4(self):
        # L4: `بله، خاموش کن` (reversible disable) = SUCCESS; cancel neutral.
        for is_admin in (False, True):
            markup = display_toggle_confirm_keyboard("synonyms", is_admin=is_admin)
            rows = markup.inline_keyboard
            prefix = "admin:display_toggle" if is_admin else "settings:display_toggle"
            self.assertEqual(rows[0][0].text, "✅ بله، خاموش کن")
            self.assertEqual(rows[0][0].callback_data, f"{prefix}:confirm:synonyms")
            self.assertEqual(rows[0][0].style, KeyboardButtonStyle.SUCCESS)
            self.assertEqual(rows[0][1].callback_data, f"{prefix}:cancel")
            self.assertIsNone(rows[0][1].style)
            if is_admin:
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[1][0].callback_data, "admin:close")
                self.assertIsNone(rows[1][0].style)
            else:
                self.assertEqual(len(rows), 1)


class TestUserPlanPickerKeyboard(unittest.TestCase):
    def test_picker_contains_real_plans_and_distinct_emojis(self):
        from config.keyboards.admin import user_plan_picker_keyboard
        from config.keyboards.constants import IBTN_CANCEL, IBTN_CLOSE

        # distinct emojis: cancel uses 🚫, close uses ❌
        self.assertNotEqual(IBTN_CANCEL, IBTN_CLOSE)
        self.assertIn("🚫", IBTN_CANCEL)
        self.assertIn("❌", IBTN_CLOSE)

        fake_plans = [
            {"name": "free", "display_name": "Free"},
            {"name": "bronze", "display_name": "Bronze"},
            {"name": "silver", "display_name": "Silver"},
            {"name": "gold", "display_name": "Gold"},
            {"name": "emerald", "display_name": "Emerald"},
        ]
        markup = user_plan_picker_keyboard(12345, fake_plans)
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        texts = [b.text for row in markup.inline_keyboard for b in row]
        for p in fake_plans:
            self.assertIn(f"admin:user:plan_select:12345:{p['name']}", cbs)
            self.assertIn(p["display_name"], texts)
        # picker footer row must show distinct cancel vs close
        self.assertIn("🚫 لغو", texts)
        self.assertIn("❌ بستن", texts)

    def test_picker_uses_display_name(self):
        from config.keyboards.admin import user_plan_picker_keyboard

        fake_plans = [{"name": "silver", "display_name": "نقره‌ای"}]
        markup = user_plan_picker_keyboard(1, fake_plans)
        texts = [b.text for row in markup.inline_keyboard for b in row]
        self.assertIn("نقره‌ای", texts)

    def test_picker_empty_plans(self):
        from config.keyboards.admin import user_plan_picker_keyboard

        markup = user_plan_picker_keyboard(1, [])
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        # only back/cancel/close remain
        self.assertNotIn("admin:user:plan_select:", "".join(cbs))
        # footers present
        texts = [b.text for row in markup.inline_keyboard for b in row]
        self.assertIn("🚫 لغو", texts)
        self.assertIn("❌ بستن", texts)

    def test_picker_truncates_long_display_name(self):
        from config.keyboards.admin import user_plan_picker_keyboard

        long_label = "A" * 50
        fake_plans = [{"name": "silver", "display_name": long_label}]
        markup = user_plan_picker_keyboard(1, fake_plans)
        texts = [b.text for row in markup.inline_keyboard for b in row]
        # truncated to 30 + …
        self.assertTrue(any(len(t) <= 31 for t in texts if t.startswith("A")))
        self.assertTrue(any("…" in t for t in texts if t.startswith("A")))


if __name__ == "__main__":
    unittest.main()