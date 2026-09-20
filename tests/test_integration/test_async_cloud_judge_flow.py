"""RED Phase 1 (contract R1/R6 + integration-test-proto): async cloud-judge flow.

Behavior: 3 rows through run_judge_async with a MOCKED async transport
(zero tokens, zero network) produce frozen-shape votes, telemetry attempt
rows with key_idx only, and a progress file that makes the second run skip
done rows (resume, no duplicate votes). Preset rows live ONLY in a temp DB
copy (helpers snapshot isolation — production DB never touched).

MUST FAIL until factory.precard.transport_async exists (TDD red).
"""

import asyncio
import json
import os
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


if __name__ == "__main__":
    unittest.main()
