import unittest
from unittest.mock import MagicMock, patch

from services.activity_log import log_user_activity


def _make_update(user_id=1, full_name="Alice", username="alice"):
    user = MagicMock()
    user.id = user_id
    user.full_name = full_name
    user.username = username
    update = MagicMock()
    update.effective_user = user
    return update


class ActivityLogTest(unittest.TestCase):
    def test_no_op_when_feature_disabled(self):
        update = _make_update()
        with patch("services.db.get_setting", return_value="off") as gs, \
                patch("services.db.get_user", return_value={"plan": "free", "target_lang": "en", "goal": "general", "level": "A2"}), \
                patch("services.activity_log.logger.log") as log_mock:
            log_user_activity(update, action="start", outcome="new")
        log_mock.assert_not_called()
        gs.assert_called_once_with("user_activity_log", "off")

    def test_emits_line_with_full_fields_when_enabled(self):
        update = _make_update()
        row = {"plan": "silver", "target_lang": "en", "goal": "general", "level": "A2"}
        with patch("services.db.get_setting", return_value="on"), \
                patch("services.db.get_user", return_value=row), \
                patch("services.activity_log.logger.log") as log_mock:
            log_user_activity(update, action="start", outcome="new")
        log_mock.assert_called_once()
        line = log_mock.call_args.args[2]
        self.assertIn("silver", line)
        self.assertIn("en", line)
        self.assertIn("general", line)
        self.assertIn("A2", line)
        self.assertIn("alice", line)

    def test_no_op_when_no_effective_user(self):
        update = MagicMock()
        update.effective_user = None
        with patch("services.db.get_setting") as gs, \
                patch("services.activity_log.logger.log") as log_mock:
            log_user_activity(update, action="start", outcome="new")
        log_mock.assert_not_called()
        gs.assert_not_called()


if __name__ == "__main__":
    unittest.main()