"""Unit probes for tools/load_sim/resources.py (5k harness, no production).

Covers the explicit sys.platform RSS branch (Linux KiB vs macOS bytes) at
both scales — including raw values above 1 GiB where magnitude sniffing
returned wrong bytes on Linux — plus the db_file_sizes None/non-str guard.
"""

import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


def _rss_with_fake_resource(platform, maxrss):
    """Drive rss_bytes with psutil absent and a stubbed resource module."""
    import tools.load_sim.resources as res

    fake = types.ModuleType("resource")
    fake.RUSAGE_SELF = 0
    fake.getrusage = MagicMock(return_value=MagicMock(ru_maxrss=maxrss))
    with (
        patch.dict(sys.modules, {"resource": fake}),
        patch.object(sys, "platform", platform),
        patch.object(res, "psutil", None),
    ):
        return res.rss_bytes()


class LoadSimResourcesTests(unittest.TestCase):
    def test_linux_scales_kib_at_small_scale(self):
        self.assertEqual(_rss_with_fake_resource("linux", 500_000), 500_000 * 1024)

    def test_linux_scales_kib_above_1gib_raw(self):
        # Old magnitude sniff returned raw bytes here (wrong by 1024x).
        self.assertEqual(_rss_with_fake_resource("linux", 2_000_000), 2_000_000 * 1024)

    def test_darwin_reports_bytes_at_small_scale(self):
        self.assertEqual(_rss_with_fake_resource("darwin", 500_000), 500_000)

    def test_darwin_reports_bytes_above_1gib_raw(self):
        self.assertEqual(_rss_with_fake_resource("darwin", 2_000_000), 2_000_000)

    def test_nonpositive_maxrss_reports_zero(self):
        self.assertEqual(_rss_with_fake_resource("linux", 0), 0)
        self.assertEqual(_rss_with_fake_resource("linux", -5), 0)

    def test_db_file_sizes_none_and_non_str_report_zero(self):
        from tools.load_sim.resources import db_file_sizes

        self.assertEqual(db_file_sizes(None), (0, 0))
        self.assertEqual(db_file_sizes(123), (0, 0))
        self.assertEqual(db_file_sizes(""), (0, 0))

    def test_db_file_sizes_missing_path_reports_zero(self):
        from tools.load_sim.resources import db_file_sizes

        missing = os.path.join(tempfile.gettempdir(), "load-sim-no-such-db.sqlite")
        if os.path.exists(missing):
            os.remove(missing)
        self.assertEqual(db_file_sizes(missing), (0, 0))

    def test_db_file_sizes_real_file_reports_size(self):
        from tools.load_sim.resources import db_file_sizes

        with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite") as fh:
            fh.write(b"x" * 100)
            path = fh.name
        try:
            db_bytes, wal_bytes = db_file_sizes(path)
            self.assertEqual(db_bytes, 100)
            self.assertEqual(wal_bytes, 0)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
