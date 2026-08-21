import os
import unittest

from services.utils import helpers


class TestRetryBackoffBase(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("HAMZABAN_RETRY_BACKOFF_BASE")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("HAMZABAN_RETRY_BACKOFF_BASE", None)
        else:
            os.environ["HAMZABAN_RETRY_BACKOFF_BASE"] = self._prev

    def test_default_is_one(self):
        os.environ.pop("HAMZABAN_RETRY_BACKOFF_BASE", None)
        self.assertEqual(helpers._retry_backoff_base(), 1.0)

    def test_valid_value(self):
        os.environ["HAMZABAN_RETRY_BACKOFF_BASE"] = "0.1"
        self.assertEqual(helpers._retry_backoff_base(), 0.1)

    def test_negative_fallback(self):
        os.environ["HAMZABAN_RETRY_BACKOFF_BASE"] = "-1"
        with self.assertLogs(level="WARNING"):
            self.assertEqual(helpers._retry_backoff_base(), 1.0)

    def test_nan_fallback(self):
        os.environ["HAMZABAN_RETRY_BACKOFF_BASE"] = "nan"
        with self.assertLogs(level="WARNING"):
            self.assertEqual(helpers._retry_backoff_base(), 1.0)

    def test_inf_fallback(self):
        os.environ["HAMZABAN_RETRY_BACKOFF_BASE"] = "inf"
        with self.assertLogs(level="WARNING"):
            self.assertEqual(helpers._retry_backoff_base(), 1.0)

    def test_invalid_fallback(self):
        os.environ["HAMZABAN_RETRY_BACKOFF_BASE"] = "abc"
        with self.assertLogs(level="WARNING"):
            self.assertEqual(helpers._retry_backoff_base(), 1.0)

    def test_large_clamped(self):
        os.environ["HAMZABAN_RETRY_BACKOFF_BASE"] = "120"
        with self.assertLogs(level="WARNING"):
            val = helpers._retry_backoff_base()
        self.assertEqual(val, 60.0)

    def test_sleep_capped(self):
        os.environ["HAMZABAN_RETRY_BACKOFF_BASE"] = "60"
        # attempt 1 => 60*2=120 but capped to 30
        self.assertEqual(helpers._retry_sleep(1), 30.0)
        self.assertEqual(helpers._retry_sleep(0), 30.0)  # 60*1=60 capped
        os.environ["HAMZABAN_RETRY_BACKOFF_BASE"] = "0.1"
        self.assertAlmostEqual(helpers._retry_sleep(0), 0.1)
        self.assertAlmostEqual(helpers._retry_sleep(1), 0.2)
