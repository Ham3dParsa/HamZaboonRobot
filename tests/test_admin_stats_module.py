"""Focused tests for the admin_stats expand module (Finding #7, task 7.1).

Task 7.1 establishes the stats domain seam by re-exporting the standalone stats
keyboard builders verbatim, with no behavior change and no routing changes yet.
"""

import unittest

from config.keyboards import stats_back_keyboard, stats_menu_keyboard


class TestAdminStatsModule(unittest.TestCase):
    def test_reexports_stats_keyboards_verbatim(self):
        from handlers import admin_stats

        self.assertIs(admin_stats.stats_menu_keyboard, stats_menu_keyboard)
        self.assertIs(admin_stats.stats_back_keyboard, stats_back_keyboard)

    def test_all_is_explicit(self):
        from handlers import admin_stats

        self.assertEqual(admin_stats.__all__, ["stats_back_keyboard", "stats_menu_keyboard"])


if __name__ == "__main__":
    unittest.main()
