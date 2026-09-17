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
    """R6: allowlist skip + per-call timeout are recorded as data."""

    def test_is_risky_module_allowlist(self):
        # Non-pure surface: skipped by default (incl. DB/state writers that
        # the old wildcard/prefix used to admit).
        self.assertTrue(rbr.is_risky_module("handlers.x"))
        self.assertTrue(rbr.is_risky_module("services.db.words"))
        self.assertTrue(rbr.is_risky_module("services.ai.generation"))
        self.assertTrue(rbr.is_risky_module("services.ai.fallback_router"))
        self.assertTrue(rbr.is_risky_module("bot"))
        self.assertTrue(rbr.is_risky_module("scripts.review_blast_radius"))
        self.assertTrue(rbr.is_risky_module("services.scheduling"))
        self.assertTrue(rbr.is_risky_module("services.session"))
        self.assertTrue(rbr.is_risky_module("services.session.store"))
        self.assertTrue(rbr.is_risky_module("services.session.__init__"))
        # Known-pure: probed by default.
        self.assertFalse(rbr.is_risky_module("services.fsrs_core"))
        self.assertFalse(rbr.is_risky_module("services.utils.helpers"))
        self.assertFalse(rbr.is_risky_module("services.session.assembly"))
        self.assertFalse(rbr.is_risky_module("services.session.grade_policy"))
        self.assertFalse(rbr.is_risky_module("services.session.summary"))
        self.assertFalse(rbr.is_risky_module("services.session.tier_registry"))
        self.assertFalse(rbr.is_risky_module("config.catalog"))
        self.assertFalse(rbr.is_risky_module("config.catalog_languages"))
        self.assertFalse(rbr.is_risky_module("tests.fake_pure"))

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

    def test_allowlist_probes_pure_and_skips_rest(self):
        import sys
        import types

        mod = types.ModuleType("tests.fake_pure_rbr")

        def pure_fn(x=None):
            return {"ok": True}

        mod.pure_fn = pure_fn
        sys.modules["tests.fake_pure_rbr"] = mod
        try:
            symbols = [
                {"name": "pure_fn", "file": "tests/fake_pure_rbr.py",
                 "kind": "def"},
                {"name": "gen", "file": "services/ai/generation.py",
                 "kind": "def"},
            ]
            rows, _trunc = rbr.run_edge_probes(symbols)
        finally:
            del sys.modules["tests.fake_pure_rbr"]
        probed = [row for row in rows
                  if row["function"] == "tests.fake_pure_rbr.pure_fn"]
        self.assertTrue(probed, "allowlisted module must be probed")
        for row in probed:
            self.assertNotEqual(row["input"], "skipped: risky-module")
            self.assertEqual(set(row.keys()),
                             {"function", "input", "output"})
        skipped = [row for row in rows
                   if row["function"] == "services.ai.generation"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["input"], "skipped: risky-module")
        self.assertIn("--allow-risky", skipped[0]["output"])

    def test_probe_timeout_is_recorded_as_data(self):
        import time as _time

        def _hang(x=None):
            _time.sleep(4)
            return 1

        out = rbr.probe_call(_hang, (None,), {}, timeout=0.2)
        self.assertTrue(out.startswith("timeout:"),
                        f"expected timeout data, got: {out}")

    def test_writer_names_skipped_even_in_allowlisted_modules(self):
        import sys
        import types

        mod = types.ModuleType("tests.fake_pure_writers_rbr")

        def save_session(x=None):
            return {"ok": True}

        def consume_session_slot(x=None):
            return {"ok": True}

        def pure_fn(x=None):
            return {"ok": True}

        mod.save_session = save_session
        mod.consume_session_slot = consume_session_slot
        mod.pure_fn = pure_fn
        sys.modules["tests.fake_pure_writers_rbr"] = mod
        try:
            symbols = [
                {"name": "save_session",
                 "file": "tests/fake_pure_writers_rbr.py", "kind": "def"},
                {"name": "consume_session_slot",
                 "file": "tests/fake_pure_writers_rbr.py", "kind": "def"},
                {"name": "pure_fn",
                 "file": "tests/fake_pure_writers_rbr.py", "kind": "def"},
            ]
            rows, _trunc = rbr.run_edge_probes(symbols)
        finally:
            del sys.modules["tests.fake_pure_writers_rbr"]
        by_fn = {}
        for row in rows:
            self.assertEqual(set(row.keys()),
                             {"function", "input", "output"})
            by_fn.setdefault(row["function"], []).append(row)
        for risky in ("tests.fake_pure_writers_rbr.save_session",
                      "tests.fake_pure_writers_rbr.consume_session_slot"):
            self.assertIn(risky, by_fn)
            for row in by_fn[risky]:
                self.assertEqual(row["input"], "skipped: risky-module")
                self.assertIn("--allow-risky", row["output"])
        probed = by_fn.get("tests.fake_pure_writers_rbr.pure_fn", [])
        self.assertTrue(probed, "pure function must still probe")
        for row in probed:
            self.assertNotEqual(row["input"], "skipped: risky-module")

    def test_db_writer_modules_skipped_by_default(self):
        symbols = [
            {"name": "save_session",
             "file": "services/session/store.py", "kind": "def"},
            {"name": "consume_session_slot",
             "file": "services/scheduling.py", "kind": "def"},
        ]
        rows, _trunc = rbr.run_edge_probes(symbols)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(set(row.keys()),
                             {"function", "input", "output"})
            self.assertEqual(row["input"], "skipped: risky-module")
            self.assertIn("--allow-risky", row["output"])


class GraphifyMissingBlastRadiusTest(unittest.TestCase):
    """W2: a missing graphify binary still yields AST-scan blast rows."""

    def test_missing_graphify_still_emits_ast_scan_rows(self):
        import tempfile

        symbols = [{"name": "my_fn", "file": "services/scheduling.py",
                    "kind": "def"}]
        with tempfile.TemporaryDirectory() as tmp:
            graph = Path(tmp) / "graph.json"
            with mock.patch.object(rbr, "_diff_py_files",
                                   return_value=(["services/scheduling.py"],
                                                 None)), \
                 mock.patch.object(rbr, "collect_changed_symbols",
                                   return_value=symbols), \
                 mock.patch.object(rbr, "compute_wiring_delta",
                                   return_value={"added_prefixes": [],
                                                 "removed_prefixes": [],
                                                 "orphaned": []}), \
                 mock.patch.object(rbr, "compute_dead_refs",
                                   return_value={"hits": {}}), \
                 mock.patch.object(rbr, "callers_of",
                                   return_value=([], False)), \
                 mock.patch.object(rbr, "callees_of",
                                   return_value=[]), \
                 mock.patch.object(rbr.shutil, "which",
                                   return_value=None):
                context, note, code = rbr.build_context(
                    base="HEAD", graph_json=graph, run_update=True,
                    run_probes=False, run_graph=True,
                    graph_explicit=False)
        self.assertEqual(code, 0)
        self.assertIn("graphify not found", note)
        self.assertEqual(len(context["blast_radius"]), 1)
        row = context["blast_radius"][0]
        self.assertEqual(set(row.keys()),
                         {"symbol", "callers", "callees", "via"})
        self.assertTrue(row["via"].startswith("ast-scan"))


class CredentialRedactionTest(unittest.TestCase):
    """W4: credential-shaped probe outputs are redacted before persisting."""

    def test_credential_shape_in_result_is_redacted(self):
        def fetch_data(x=None):
            return {"api_key": "sk-abc123def456ghi789"}

        rows = rbr.probe_function("sampler", fetch_data)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(set(row.keys()),
                             {"function", "input", "output"})
            if row["output"].startswith("return: {"):
                self.fail(f"credential leaked into probe output: {row}")
            self.assertIn("[redacted", row["output"])
            self.assertNotIn("sk-abc", row["output"])

    def test_sensitive_function_name_is_redacted(self):
        def get_auth_token(x=None):
            return "plain-value"

        rows = rbr.probe_function("sampler", get_auth_token)
        self.assertTrue(rows)
        for row in rows:
            if row["output"].startswith("return:"):
                self.assertIn("[redacted", row["output"])
                self.assertNotIn("plain-value", row["output"])


class ProbeArgsetDedupeTest(unittest.TestCase):
    """Zero-required-param functions emit one bare row, not six."""

    def test_zero_param_function_has_single_bare_row(self):
        def _noparam():
            return 1

        argsets = rbr._probe_argsets(_noparam)
        self.assertEqual(argsets, [((), {})])
        rows = rbr.probe_function("sampler", _noparam)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["input"], "_noparam()")


class WiringServicesScopeTest(unittest.TestCase):
    """services/ registers (e.g. services/routing.py) are collected."""

    def test_head_keyboard_files_includes_services(self):
        files = rbr._head_keyboard_files()
        self.assertIn("services/routing.py", files)

    def test_services_register_calls_collected_as_handlers(self):
        source = ("from services.routing import register\n"
                  "register(\"admin\", my_handler)\n")
        _prefixes, handlers = rbr._prefixes_and_handlers_from_sources(
            lambda rel: source if rel == "services/routing.py" else None,
            ["services/routing.py"],
        )
        self.assertIn("admin", handlers)


if __name__ == "__main__":
    unittest.main()
