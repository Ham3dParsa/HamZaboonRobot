"""Unit tests for the help module (builders + content registry)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from handlers.help_command import (
    HELP_SECTIONS,
    _back_keyboard,
    _build_intro,
    _build_section_detail,
    _panel_keyboard,
    _visible_sections,
)


class HelpBuildersTest(unittest.TestCase):
    def test_intro_is_markdownv2_safe(self):
        intro = _build_intro()
        # The bot name must be wrapped in literal (unescaped) bold markers.
        self.assertIn("*هم‌زبان*", intro)
        self.assertIn("/start", intro)
        # Literal MarkdownV2 special chars in the intro (. ! ( )) must be
        # escaped, otherwise Telegram rejects the message with "can't parse
        # entities". escape_mdv2 escapes these, so they appear as \. \! \( \).
        self.assertIn("\\.", intro)
        self.assertIn("\\!", intro)
        self.assertIn("\\(", intro)
        self.assertIn("\\)", intro)
        # No RAW special char should survive (would break MDV2 parsing).
        self.assertNotIn("نکنی.", intro)
        self.assertNotIn("سلام!", intro)
        self.assertNotIn("(زبان، هدف، سطح)", intro)

    def test_all_sections_produce_nonempty_detail(self):
        for section in HELP_SECTIONS:
            detail = _build_section_detail(section["id"])
            self.assertTrue(detail, f"empty detail for {section['id']}")
            self.assertIn("*", detail)

    def test_unknown_section_returns_none(self):
        self.assertIsNone(_build_section_detail("does_not_exist"))

    def test_panel_keyboard_emits_help_section_prefixes(self):
        with patch("handlers.help_command.is_owner", return_value=False):
            kb = _panel_keyboard(123)
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertTrue(all(c.startswith("help:section:") for c in callbacks))
        self.assertNotIn(
            "help:section:admin",
            callbacks,
            "admin section must be hidden from non-owners",
        )

    def test_owner_sees_admin_section(self):
        with patch("handlers.help_command.is_owner", return_value=True):
            kb = _panel_keyboard(1)
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("help:section:admin", callbacks)

    def test_visible_sections_respects_owner_only(self):
        with patch("handlers.help_command.is_owner", return_value=False):
            self.assertFalse(
                any(s["id"] == "admin" for s in _visible_sections(123))
            )
        with patch("handlers.help_command.is_owner", return_value=True):
            self.assertTrue(any(s["id"] == "admin" for s in _visible_sections(1)))

    def test_back_keyboard_prefix(self):
        kb = _back_keyboard()
        self.assertEqual(kb.inline_keyboard[0][0].callback_data, "help:back")

    def test_hidden_section_excluded_from_panel_for_all(self):
        with patch("handlers.help_command.is_owner", return_value=False):
            kb = _panel_keyboard(1)
        self.assertNotIn(
            "help:section:review",
            [b.callback_data for row in kb.inline_keyboard for b in row],
        )
        with patch("handlers.help_command.is_owner", return_value=True):
            kb = _panel_keyboard(1)
        self.assertNotIn(
            "help:section:review",
            [b.callback_data for row in kb.inline_keyboard for b in row],
        )


if __name__ == "__main__":
    unittest.main()
