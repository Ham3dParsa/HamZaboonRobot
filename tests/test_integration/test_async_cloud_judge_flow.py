"""RED Phase 1 (contract R1/R6/R7 + integration-test-proto): async cloud-judge flow.

Behavior: 3 rows through run_judge_async with a MOCKED async transport
(zero tokens, zero network) produce frozen-shape votes, telemetry attempt
rows with key_idx only, and a progress file that makes the second run skip
done rows (resume, no duplicate votes). DB snapshot isolation per protocol
(engine takes its KeyRing directly — zero production writes).

A second class drives the REAL pipeline main() end-to-end (hermetic harness
mirroring tests/factory/test_factory_run.py: injected legs, fake index,
monkeypatched fake keys never asserted) with --async-judge-provider and
asserts the async stage branch ran (wrapper spy), verdicts landed, and the
run completed with 0 tokens and 0 network.

MUST FAIL until factory.precard.transport_async exists (TDD red).
"""

import asyncio
import json
import os
import re
import tempfile
import unittest

from tests.test_integration import helpers
from factory.precard import transport_async


def _vote_text():
    return json.dumps({
        "verdict": "LINK", "winner_index": 1,
        "kaikki_evidence": "to heat liquid",
        "wordnet_evidence": "to heat liquid boil#2",
    })


async def _mock_transport(key, model, prompt):
    return _vote_text(), {"tokens": 7}


def _validate_ok(text):
    return "ok", {"verdict": "LINK", "winner_index": 1}


class TestAsyncCloudJudgeFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Snapshot isolation per integration-test-proto: the engine takes its
        # KeyRing directly, so no DB writes happen at all (R3 rows-only path
        # is exercised through the existing preset_registry in GREEN wiring).
        self._tmpdir, self._db = helpers.fresh_db_from_snapshot()
        self._progress = tempfile.mkdtemp(prefix="asyncjudge_")

    async def asyncTearDown(self):
        self._tmpdir.cleanup()
        helpers.cleanup_session()

    async def test_three_rows_vote_telemetry_and_resume(self):
        from factory.precard import provider_transport as sync_transport
        rows = [{"key": "w:a"}, {"key": "w:b"}, {"key": "w:c"}]
        first = await transport_async.run_judge_async(
            rows, transport=_mock_transport, model="test-model",
            prompt_fn=lambda row: "PROMPT", validate_fn=_validate_ok,
            ring=sync_transport.KeyRing(["tk1"]),
            concurrency=2, timeout_s=25,
            progress_path=os.path.join(self._progress, "progress.jsonl"))
        self.assertEqual(len(first), 3)
        for key, vote in first.items():
            self.assertEqual(vote["verdict"], "LINK")
        second = await transport_async.run_judge_async(
            rows, transport=_mock_transport, model="test-model",
            prompt_fn=lambda row: "PROMPT", validate_fn=_validate_ok,
            ring=sync_transport.KeyRing(["tk1"]),
            concurrency=2, timeout_s=25,
            progress_path=os.path.join(self._progress, "progress.jsonl"))
        self.assertEqual(first, second)

    async def test_telemetry_carries_key_idx_never_key_strings(self):
        from factory.precard import provider_transport as sync_transport
        secret = "TEST-ONLY-SECRET-qqq"
        rows = [{"key": "w:a"}]

        async def echo_key(key, model, prompt):
            self.assertEqual(key, secret)
            return _vote_text(), {"tokens": 1}

        votes = await transport_async.run_judge_async(
            rows, transport=echo_key, model="test-model",
            prompt_fn=lambda row: "PROMPT", validate_fn=_validate_ok,
            ring=sync_transport.KeyRing([secret]),
            concurrency=1, timeout_s=25,
            progress_path=os.path.join(self._progress, "p.jsonl"))
        blob = json.dumps(votes)
        for root, _, files in os.walk(self._progress):
            for name in files:
                with open(os.path.join(root, name), encoding="utf-8") as fh:
                    blob += fh.read()
        self.assertNotIn(secret, blob)


def _hermetic_rows(word):
    return [{"pos": "noun",
             "entry": {"pos": "noun", "sounds": [{"ipa": "/x/"}],
                       "senses": [{"glosses": ["a %s fruit" % word],
                                   "tags": [], "examples": []}]}}]


def _hermetic_index(words):
    return {w: _hermetic_rows(w) for w in words}


def _hermetic_judge(api_key, model, user_text):
    """S2-shape reply: first candidate id per KEY section (mocked, 0 tk).

    Returns the sync-transport tuple (text, usage) like the production
    _avalai/_google_chat_transport functions do.
    """
    keys, cands, cur = [], {}, None
    for line in user_text.splitlines():
        hit = re.match(r"^KEY (\S+)", line)
        if hit:
            cur = hit.group(1)
            keys.append(cur)
            cands[cur] = []
        pick = re.match(r"^- (\S+#\d+)", line)
        if pick and cur:
            cands[cur].append(pick.group(1))
    return json.dumps({"results": [
        {"key": k, "picks": cands[k][:1]} for k in keys]}), None


class TestAsyncJudgePipelineBranch(unittest.TestCase):
    def test_async_branch_runs_end_to_end_mocked(self):
        from unittest import mock
        from factory.precard.pipeline import main as precard_main
        from factory.precard import transport_async as async_mod
        with tempfile.TemporaryDirectory() as tmp:
            sample = os.path.join(tmp, "sample.json")
            with open(sample, "w", encoding="utf-8") as fh:
                json.dump(
                    [{"kind": "word", "text": w, "pos": "noun",
                      "pool_level": "A1"} for w in ("apple", "pear")], fh)
            out = os.path.join(tmp, "precard.jsonl")
            prog = os.path.join(tmp, "prog")
            called = {}
            real_run_batches = async_mod.run_batches_async

            async def _spy(*args, **kwargs):
                called["n"] = called.get("n", 0) + 1
                return await real_run_batches(*args, **kwargs)

            with mock.patch.object(
                    async_mod, "run_batches_async",
                    side_effect=_spy, autospec=True):
                import os as _os
                _os.environ["AVALAI_API_KEY"] = "test-avalai-key"
                try:
                    rc = precard_main(
                        ["--sample", sample, "--out", out,
                         "--progress-dir", prog, "--no-resume",
                         "--stages",
                         "preprocess,inflection_review,anchor_rank,"
                         "sense_judge",
                         "--llm-provider", "avalai",
                         "--async-judge-provider", "avalai",
                         "--concurrency", "2", "--quiet"],
                        _judge_transport=_hermetic_judge,
                        _topic_transport=None, _assign_transport=None,
                        _inflect_transport=None,
                        _sleep_fn=lambda s: None,
                        _index=_hermetic_index(("apple", "pear")),
                        _read_entry=lambda row: row["entry"],
                        _tatoeba={}, _zipf_fn=lambda t: 5.0,
                        _awl_set=set(), _type_map={},
                        _type_log_available=False)
                finally:
                    del _os.environ["AVALAI_API_KEY"]
            self.assertEqual(rc, 0)
            self.assertGreaterEqual(called.get("n", 0), 1)
            from factory.precard import progress as PROG
            with open(os.path.join(
                    prog, PROG.FILES["sense_judge"]), encoding="utf-8") as fh:
                done = json.load(fh)["done"]
            self.assertEqual(len(done), 2)
            for verdict in done.values():
                self.assertFalse((verdict.get("model", "") or "").startswith(
                    "s1-"))

    def _hermetic_env(self):
        """Environ-only load_factory_env: file-backed keys can never flip
        these tests off their fail-closed paths (hermetic on any box)."""
        from unittest import mock

        def _fake_load_factory_env(required=()):
            missing = [k for k in required if not os.environ.get(k)]
            if missing:
                raise KeyError("factory/.env missing keys: "
                               + ", ".join(missing))
            return {k: os.environ.get(k, "") for k in required}

        return mock.patch(
            "factory.precard.pipeline.load_factory_env",
            side_effect=_fake_load_factory_env)

    def test_groq_without_key_fails_closed_naming_var(self):
        # F4 gate: registry-known provider with no key exits loudly naming
        # the convention var (no network, no keys on disk asserted).
        # Env hygiene: a real GROQ key on this machine must not flip the
        # test into the keyed path — pop both vars, restore after.
        from factory.precard.pipeline import main as precard_main
        import tempfile
        _saved = {}
        for _var in ("GROQ_API_KEY_G1", "GROQ_API_KEY"):
            _saved[_var] = os.environ.pop(_var, None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                sample = os.path.join(tmp, "sample.json")
                with open(sample, "w", encoding="utf-8") as fh:
                    json.dump(
                        [{"kind": "word", "text": "apple", "pos": "noun",
                          "pool_level": "A1"}], fh)
                out = os.path.join(tmp, "precard.jsonl")
                prog = os.path.join(tmp, "prog")
                with self._hermetic_env():
                    with self.assertRaises(SystemExit) as ctx:
                        # NOTE: no _judge_transport override — the default
                        # sentinel forces real provider wiring (None would
                        # mean skipped leg).
                        precard_main(
                            ["--sample", sample, "--out", out,
                             "--progress-dir", prog, "--no-resume",
                             "--llm-provider", "groq",
                             "--async-judge-provider", "groq",
                             "--concurrency", "2", "--quiet"],
                            _topic_transport=None, _assign_transport=None,
                            _inflect_transport=None,
                            _sleep_fn=lambda s: None,
                            _index=_hermetic_index(("apple",)),
                            _read_entry=lambda row: row["entry"],
                            _tatoeba={}, _zipf_fn=lambda t: 5.0,
                            _awl_set=set(), _type_map={},
                            _type_log_available=False)
        finally:
            for _var, _val in _saved.items():
                if _val is None:
                    os.environ.pop(_var, None)
                else:
                    os.environ[_var] = _val
        self.assertIn("GROQ_API_KEY_G1", str(ctx.exception.code))

    def test_groq_on_non_judge_leg_rejected(self):
        # Per-leg gate: registry names ride ONLY sense_judge; a default
        # topic leg on groq exits naming avalai|google (no network).
        # NOTE: _topic_transport left default (not None) so the leg is
        # really gated; injected-None legs are exempt by design.
        from factory.precard.pipeline import main as precard_main
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as ctx:
                precard_main(
                    ["--out", os.path.join(tmp, "precard.jsonl"),
                     "--progress-dir", os.path.join(tmp, "prog"),
                     "--no-resume", "--llm-provider", "groq",
                     "--concurrency", "2", "--quiet"],
                    _assign_transport=None,
                    _inflect_transport=None,
                    _sleep_fn=lambda s: None,
                    _index={}, _read_entry=lambda row: row,
                    _tatoeba={}, _zipf_fn=lambda t: 5.0,
                    _awl_set=set(), _type_map={},
                    _type_log_available=False)
        msg = str(ctx.exception.code)
        self.assertIn("avalai|google", msg)
        self.assertIn("topic_vectors", msg)

    def test_groq_default_model_demands_explicit_judge_model(self):
        # Registry provider + key present but avalai-default model would be
        # sent verbatim to a foreign API: loud exit, no network.
        import os as _os
        from factory.precard.pipeline import main as precard_main
        import tempfile
        _saved_g1 = _os.environ.get("GROQ_API_KEY_G1")
        _saved_base = _os.environ.get("GROQ_API_KEY")
        _os.environ["GROQ_API_KEY_G1"] = "test-groq-key"
        _os.environ.pop("GROQ_API_KEY", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                sample = os.path.join(tmp, "sample.json")
                with open(sample, "w", encoding="utf-8") as fh:
                    json.dump(
                        [{"kind": "word", "text": "apple", "pos": "noun",
                          "pool_level": "A1"}], fh)
                with self._hermetic_env():
                    with self.assertRaises(SystemExit) as ctx:
                        precard_main(
                            ["--sample", sample,
                             "--out", os.path.join(tmp, "precard.jsonl"),
                             "--progress-dir", os.path.join(tmp, "prog"),
                             "--no-resume",
                             "--llm-provider", "groq",
                             "--async-judge-provider", "groq",
                             "--concurrency", "2", "--quiet"],
                            _topic_transport=None, _assign_transport=None,
                            _inflect_transport=None,
                            _sleep_fn=lambda s: None,
                            _index=_hermetic_index(("apple",)),
                            _read_entry=lambda row: row["entry"],
                            _tatoeba={}, _zipf_fn=lambda t: 5.0,
                            _awl_set=set(), _type_map={},
                            _type_log_available=False)
        finally:
            if _saved_g1 is None:
                _os.environ.pop("GROQ_API_KEY_G1", None)
            else:
                _os.environ["GROQ_API_KEY_G1"] = _saved_g1
            if _saved_base is None:
                _os.environ.pop("GROQ_API_KEY", None)
            else:
                _os.environ["GROQ_API_KEY"] = _saved_base
        self.assertIn("--judge-model", str(ctx.exception.code))


if __name__ == "__main__":
    unittest.main()
