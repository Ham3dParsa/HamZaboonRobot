"""Integration tests for scripts/review_blast_radius.py (REV-2 + REV-4).

Covers the review-context.json shape plus a validation case mirroring the
PR-732 sampler bugs (falsy {} vs None default, one-sided casefold, NaN
guard), showing the producer edge probes surface each as a hold.
"""

from __future__ import annotations

import importlib.util
import json
import math
import tempfile
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

EXPECTED_KEYS = {
    "base",
    "head_sha",
    "built_at_commit",
    "fresh",
    "changed_symbols",
    "blast_radius",
    "wiring_delta",
    "dead_refs",
    "edge_probes",
    "truncated",
}


# --------------------------------------------------------------------------
# PR-732 sampler bug mirrors (buggy vs fixed pairs)
# --------------------------------------------------------------------------

_SAMPLER_DEFAULT = {"topics": ["general"]}


def buggy_opts_or_fallback(opts=None):
    return opts or _SAMPLER_DEFAULT


def fixed_opts_is_none(opts=None):
    if opts is None:
        return _SAMPLER_DEFAULT
    return opts


def buggy_tag_match_one_sided(tag, wanted="MIXED-CASE"):
    return tag.casefold() == wanted


def fixed_tag_match_both_sides(tag, wanted="MIXED-CASE"):
    return tag.casefold() == wanted.casefold()


def buggy_zipf_bucket(zipf):
    return "rare" if zipf < 1.0 else "common"


def fixed_zipf_bucket(zipf):
    if not isinstance(zipf, float) or math.isnan(zipf):
        raise ValueError("non-finite zipf")
    return "rare" if zipf < 1.0 else "common"


class ReviewBlastRadiusShapeTest(unittest.TestCase):
    """The emitted JSON carries exactly the contracted keys."""

    def test_main_emits_exact_schema_without_graph_or_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "review-context.json")
            code = rbr.main(["--base", "HEAD", "--out", out,
                             "--no-graph", "--no-probes"])
            self.assertEqual(code, 0)
            context = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertEqual(set(context.keys()), EXPECTED_KEYS)
        self.assertFalse(context["fresh"])
        self.assertIsNone(context["built_at_commit"])
        for row in context["blast_radius"]:
            self.assertEqual(set(row.keys()),
                             {"symbol", "callers", "callees", "via"})
        self.assertEqual(set(context["wiring_delta"].keys()),
                         {"added_prefixes", "removed_prefixes", "orphaned"})
        self.assertEqual(set(context["dead_refs"].keys()), {"hits"})
        for row in context["edge_probes"]:
            self.assertEqual(set(row.keys()), {"function", "input", "output"})

    def test_stale_graph_means_nonzero_exit_with_rerun_message(self):
        import io
        from contextlib import redirect_stderr

        with tempfile.TemporaryDirectory() as tmp:
            graph = Path(tmp) / "graph.json"
            graph.write_text(json.dumps({"built_at_commit": "deadbeef"}),
                             encoding="utf-8")
            out = str(Path(tmp) / "review-context.json")
            buf = io.StringIO()
            # Hermetic w.r.t. the graphify binary (absent in CI): an explicit
            # --graph file must be honored without the binary on PATH.
            with mock.patch.object(rbr.shutil, "which",
                                   return_value=None), \
                    redirect_stderr(buf):
                code = rbr.main(["--base", "HEAD", "--out", out,
                                 "--no-update", "--no-probes",
                                 "--graph", str(graph)])
            self.assertEqual(code, 2)
            self.assertIn("re-run `graphify update .`", buf.getvalue())
            context = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertFalse(context["fresh"])
        self.assertEqual(context["built_at_commit"], "deadbeef")
        # F1: working-tree/untracked files are visible, so blast_radius is
        # AST-scan rows (possibly non-empty) -- never graph-corroborated.
        self.assertIsInstance(context["blast_radius"], list)
        for row in context["blast_radius"]:
            self.assertEqual(set(row.keys()),
                             {"symbol", "callers", "callees", "via"})
            self.assertTrue(row["via"].startswith("ast-scan"))


class ChangedSymbolExtractionTest(unittest.TestCase):
    """AST extraction mirrors the test_wiring.py collector patterns."""

    def test_extracts_def_class_register_callback_import(self):
        source = (
            "from services.routing import register\n"
            "from handlers.x import handle_x\n"
            "def my_handler():\n"
            "    pass\n"
            "class MyClass:\n"
            "    def method(self):\n"
            "        pass\n"
            "register(\"admin\", my_handler)\n"
            "btn = InlineKeyboardButton(\"x\", callback_data=\"admin:plans:list\")\n"
            "btn2 = InlineKeyboardButton(\"y\", callback_data=f\"srs:reveal:{wid}\")\n"
        )
        symbols = {(s["name"], s["kind"])
                   for s in rbr.symbols_in_source(source, "handlers/x.py")}
        self.assertIn(("my_handler", "def"), symbols)
        self.assertIn(("MyClass", "class"), symbols)
        self.assertIn(("MyClass.method", "def"), symbols)
        self.assertIn(("admin", "register"), symbols)
        self.assertIn(("admin:plans:list", "callback"), symbols)
        self.assertIn(("srs:reveal", "callback"), symbols)
        self.assertIn(("handlers.x.handle_x", "import"), symbols)

    def test_prefix_matcher_covers_coarse_registry_prefix(self):
        self.assertTrue(rbr._prefix_matches_handler(
            "admin:plans:list", {"admin", "study:start"}))
        self.assertFalse(rbr._prefix_matches_handler(
            "query:add:tok", {"admin", "study:start"}))

    def test_diff_prefix_sets_reports_added_removed(self):
        added, removed = rbr.diff_prefix_sets(
            {"a", "b"}, {"b", "c"})
        self.assertEqual((added, removed), (["c"], ["a"]))


class EdgeProbe732ValidationTest(unittest.TestCase):
    """Probes surface the three PR-732 sampler bug shapes as holds."""

    def _outputs(self, fn) -> dict[str, str]:
        rows = rbr.probe_function("sampler", fn)
        return {row["input"]: row["output"] for row in rows}

    def test_falsy_empty_dict_vs_none_default(self):
        buggy = self._outputs(buggy_opts_or_fallback)
        # Hold evidence: {} is silently replaced by the default, exactly
        # like None -- the probe rows are indistinguishable.
        self.assertEqual(buggy["buggy_opts_or_fallback({})"],
                         buggy["buggy_opts_or_fallback(None)"])
        self.assertIn(repr(_SAMPLER_DEFAULT),
                      buggy["buggy_opts_or_fallback({})"])
        fixed = self._outputs(fixed_opts_is_none)
        self.assertNotEqual(fixed["fixed_opts_is_none({})"],
                            fixed["fixed_opts_is_none(None)"])
        self.assertIn("return: {}", fixed["fixed_opts_is_none({})"])

    def test_one_sided_casefold(self):
        buggy = self._outputs(buggy_tag_match_one_sided)
        # Hold evidence: mixed-case query against a lowercase want never
        # matches -- recorded as False instead of True.
        self.assertIn(
            "return: False",
            buggy["buggy_tag_match_one_sided('MiXeD-CaSe')"],
        )
        fixed = self._outputs(fixed_tag_match_both_sides)
        self.assertIn(
            "return: True",
            fixed["fixed_tag_match_both_sides('MiXeD-CaSe')"],
        )

    def test_nan_guard(self):
        buggy = self._outputs(buggy_zipf_bucket)
        nan_key = next(k for k in buggy if "nan" in k)
        # Hold evidence: NaN is misclassified as "common" (every comparison
        # with NaN is False, so the else-branch wins silently).
        self.assertIn("return: 'common'", buggy[nan_key])
        fixed = self._outputs(fixed_zipf_bucket)
        nan_key = next(k for k in fixed if "nan" in k)
        self.assertIn("raise: ValueError", fixed[nan_key])

    def test_probe_crash_is_data_never_hidden(self):
        def _boom(x):
            raise RuntimeError("kablam")

        rows = rbr.probe_function("sampler", _boom)
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertEqual(set(row.keys()), {"function", "input", "output"})
            if row["input"] != "_boom()":
                self.assertIn("raise: RuntimeError: kablam", row["output"])


class UntrackedDiffRegressionTest(unittest.TestCase):
    """F1: untracked .py files must appear in _diff_py_files (not just HEAD)."""

    def test_untracked_py_file_is_included(self):
        import uuid

        name = f"tmp_untracked_rbr_{uuid.uuid4().hex[:8]}.py"
        path = REPO_ROOT / name
        path.write_text("def tmp_probe_fn():\n    return 1\n",
                        encoding="utf-8")
        try:
            files, _err = rbr._diff_py_files("HEAD")
            self.assertIn(name, files)
            symbols = rbr.collect_changed_symbols([name])
            self.assertTrue(
                any(s["name"] == "tmp_probe_fn" for s in symbols),
                "untracked file symbols must be extractable",
            )
        finally:
            path.unlink(missing_ok=True)


class RiskyProbeGuardTest(unittest.TestCase):
    """R6: denylist skip + per-call timeout are recorded as data."""

    def test_is_risky_module_denylist(self):
        self.assertTrue(rbr.is_risky_module("handlers.x"))
        self.assertTrue(rbr.is_risky_module("services.db.words"))
        self.assertTrue(rbr.is_risky_module("bot"))
        self.assertFalse(rbr.is_risky_module("services.scheduling"))
        self.assertFalse(rbr.is_risky_module("config.catalog"))

    def test_risky_modules_skipped_by_default_and_recorded(self):
        symbols = [
            {"name": "foo", "file": "handlers/x.py", "kind": "def"},
            {"name": "bar", "file": "services/db/words.py", "kind": "def"},
            {"name": "baz", "file": "bot.py", "kind": "def"},
        ]
        rows, _trunc = rbr.run_edge_probes(symbols)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(set(row.keys()),
                             {"function", "input", "output"})
            self.assertEqual(row["input"], "skipped: risky-module")
            self.assertIn("--allow-risky", row["output"])
        mods = {row["function"] for row in rows}
        self.assertEqual(mods, {"handlers.x", "services.db.words", "bot"})

    def test_allow_risky_bypasses_skip_rows(self):
        symbols = [
            {"name": "nope", "file": "handlers/_nonexistent_rbr_probe.py",
             "kind": "def"},
        ]
        rows, _trunc = rbr.run_edge_probes(symbols, allow_risky=True)
        self.assertTrue(rows)
        self.assertFalse(
            any(row["input"] == "skipped: risky-module" for row in rows))
        self.assertTrue(
            any(row["output"].startswith("import-failed:") for row in rows))

    def test_probe_timeout_is_recorded_as_data(self):
        import time as _time

        def _hang(x=None):
            _time.sleep(30)
            return 1

        out = rbr.probe_call(_hang, (None,), {}, timeout=0.2)
        self.assertTrue(out.startswith("timeout:"),
                        f"expected timeout data, got: {out}")


if __name__ == "__main__":
    unittest.main()
