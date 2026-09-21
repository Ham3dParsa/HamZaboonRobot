"""Module-aware caller resolution for scripts/review_blast_radius.py.

Regression cover for the PR #735 false positives: bare-name matching
attributed ``_RowFailed.__init__`` / ``_JsonLog.close`` call sites to
unrelated modules. Qualified call sites (same file, ``from <mod> import``,
``<alias>.<name>(``) keep the caller and get ``(qualified)``; bare-name-only
matches survive solely as the unknown-module fallback ``(approx)``.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "review_blast_radius.py"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "review_blast_radius", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rbr = _load_script()


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


class CallerResolutionTest(unittest.TestCase):
    """Qualified vs approx caller attribution against a synthetic tree."""

    def _repo(self, tmp: str) -> Path:
        root = Path(tmp)
        _write(root, "services/mod_a.py",
               "def helper():\n    return 1\n")
        _write(root, "handlers/caller.py",
               "from services.mod_a import helper\n"
               "x = helper()\n")
        return root

    def test_same_file_call_is_qualified(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "services/m.py",
                   "def helper():\n"
                   "    return 1\n"
                   "def run():\n"
                   "    return helper()\n")
            with mock.patch.object(rbr, "REPO_ROOT", root):
                callers, _capped = rbr.callers_of(
                    "helper", "services/m.py")
                self.assertEqual(callers, ["services/m.py:4"])
                rows, _trunc = rbr.build_blast_radius(
                    [{"name": "helper", "file": "services/m.py",
                      "kind": "def"}],
                    {}, False,
                )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["callers"], ["services/m.py:4"])
        self.assertTrue(rows[0]["via"].startswith("ast-scan"))
        self.assertTrue(rows[0]["via"].endswith("(qualified)"),
                        rows[0]["via"])

    def test_from_import_call_is_qualified(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp)
            with mock.patch.object(
                    rbr, "REPO_ROOT", Path(tmp)):
                callers, _capped = rbr.callers_of(
                    "helper", "services/mod_a.py")
        self.assertEqual(callers, ["handlers/caller.py:2"])

    def test_module_alias_call_is_qualified(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "services/mod_a.py",
                   "def helper():\n    return 1\n")
            _write(root, "handlers/caller.py",
                   "import services.mod_a as ma\n"
                   "x = ma.helper()\n")
            with mock.patch.object(rbr, "REPO_ROOT", root):
                callers, _capped = rbr.callers_of(
                    "helper", "services/mod_a.py")
                rows, _trunc = rbr.build_blast_radius(
                    [{"name": "helper", "file": "services/mod_a.py",
                      "kind": "def"}],
                    {}, False,
                )
        self.assertEqual(callers, ["handlers/caller.py:2"])
        self.assertTrue(rows[0]["via"].endswith("(qualified)"))

    def test_from_package_import_submodule_call_is_qualified(self):
        """`from <pkg> import <mod>` + `<mod>.<bare>(` resolves via parent."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "services/db/users.py",
                   "def get_user():\n    return 1\n")
            _write(root, "handlers/caller.py",
                   "from services import db\n"
                   "x = db.get_user()\n")
            _write(root, "handlers/caller2.py",
                   "from services.db import users\n"
                   "x = users.get_user()\n")
            _write(root, "handlers/caller3.py",
                   "import services.db\n"
                   "x = services.db.get_user()\n")
            with mock.patch.object(rbr, "REPO_ROOT", root):
                callers, _capped = rbr.callers_of(
                    "get_user", "services/db/users.py")
        self.assertEqual(callers, [
            "handlers/caller.py:2",
            "handlers/caller2.py:2",
            "handlers/caller3.py:2",
        ])

    def test_bare_fallback_without_module_is_approx(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            _write(root, "handlers/unrelated.py", "x = helper()\n")
            with mock.patch.object(rbr, "REPO_ROOT", root):
                callers, _capped = rbr.callers_of("helper")
                rows, _trunc = rbr.build_blast_radius(
                    [{"name": "helper", "file": "services/mod_a.py",
                      "kind": "def"}],
                    {}, False,
                )
        # Unknown module: every bare hit is kept (old behavior preserved).
        self.assertIn("handlers/caller.py:2", callers)
        self.assertIn("handlers/unrelated.py:1", callers)
        # Known module: the unrelated bare hit is filtered out.
        self.assertEqual(rows[0]["callers"], ["handlers/caller.py:2"])
        self.assertTrue(rows[0]["via"].startswith("ast-scan"))

    def test_regression_same_method_name_right_module_only(self):
        """Mirror of the _JsonLog.close false positive on PR #735."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "services/mod_a.py",
                   "class JsonLog:\n"
                   "    def close(self):\n"
                   "        return 1\n")
            _write(root, "services/mod_b.py",
                   "class JsonLog:\n"
                   "    def close(self):\n"
                   "        return 2\n")
            _write(root, "handlers/caller.py",
                   "from services.mod_a import JsonLog\n"
                   "JsonLog.close(log)\n")
            with mock.patch.object(rbr, "REPO_ROOT", root):
                callers_a, _ = rbr.callers_of(
                    "JsonLog.close", "services/mod_a.py")
                callers_b, _ = rbr.callers_of(
                    "JsonLog.close", "services/mod_b.py")
                rows, _trunc = rbr.build_blast_radius(
                    [{"name": "JsonLog.close",
                      "file": "services/mod_a.py", "kind": "def"},
                     {"name": "JsonLog.close",
                      "file": "services/mod_b.py", "kind": "def"}],
                    {}, False,
                )
        self.assertEqual(callers_a, ["handlers/caller.py:2"])
        self.assertEqual(callers_b, [],
                         "unrelated module must not claim the caller")
        row_a = rows[0]
        row_b = rows[1]
        self.assertEqual(row_a["callers"], ["handlers/caller.py:2"])
        self.assertTrue(row_a["via"].endswith("(qualified)"))
        self.assertEqual(row_b["callers"], [])
        self.assertTrue(row_b["via"].startswith("ast-scan"))
        self.assertTrue(row_b["via"].endswith("(approx)"))

    def test_unrelated_importer_is_excluded(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "services/mod_a.py",
                   "def helper():\n    return 1\n")
            _write(root, "services/other.py",
                   "def helper():\n    return 2\n")
            _write(root, "handlers/caller.py",
                   "from services.other import helper\n"
                   "x = helper()\n")
            with mock.patch.object(rbr, "REPO_ROOT", root):
                callers, _capped = rbr.callers_of(
                    "helper", "services/mod_a.py")
        self.assertEqual(callers, [])


if __name__ == "__main__":
    unittest.main()
