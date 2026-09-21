"""RED Phase 1 (contract R1/R2/R4/R6): async cloud-judge transport seam.

Locked behavior: new module factory.precard.transport_async reuses the sync
path's domain exceptions (KeyRing, RateLimited, ProviderCooldown, AuthError),
the shared classify table (factory.core.llm_json), and the frozen envelope
(judge.arbiter_validate_multi). Route modes mirror
provider_lease_policy.TARGETS tunnel flags.
Secrets never leave key_idx form. CLI gains --concurrency (default 8).

Every test here MUST FAIL until the module exists (TDD red).
"""

import asyncio
import json
import os
import tempfile
import unittest

from factory.precard import provider_transport as transport
from factory.precard import transport_async


def _vote_text(pick="boil#2"):
    return json.dumps({
        "verdict": "LINK", "winner_index": 1,
        "kaikki_evidence": "to heat liquid",
        "wordnet_evidence": "to heat liquid %s" % pick,
    })


class TestResolveRoute(unittest.TestCase):
    def test_google_rides_tunnel_like_net_targets(self):
        self.assertEqual(transport_async.resolve_route("google"), "tunnel")

    def test_avalai_rides_direct_like_net_targets(self):
        self.assertEqual(transport_async.resolve_route("avalai"), "direct")

    def test_openrouter_rides_tunnel_like_net_targets(self):
        self.assertEqual(transport_async.resolve_route("openrouter"), "tunnel")

    def test_unknown_provider_fails_closed_to_direct(self):
        self.assertEqual(transport_async.resolve_route("nope"), "direct")

    def test_route_modes_are_exactly_direct_and_tunnel(self):
        self.assertEqual(tuple(transport_async.ROUTE_MODES),
                         ("direct", "tunnel"))


class TestConcurrencyBounds(unittest.TestCase):
    def test_default_concurrency_is_8(self):
        self.assertEqual(transport_async.DEFAULT_CONCURRENCY, 8)

    def test_concurrency_clamped_to_1_10(self):
        self.assertEqual(transport_async.clamp_concurrency(0), 1)
        self.assertEqual(transport_async.clamp_concurrency(99), 10)
        self.assertEqual(transport_async.clamp_concurrency(5), 5)


class TestSleepUnlocked(unittest.IsolatedAsyncioTestCase):
    async def test_slot_is_free_while_backing_off(self):
        sem = asyncio.BoundedSemaphore(1)
        seen = {}

        async def fake_sleep(delay):
            held = sem.locked()
            seen["locked_during_sleep"] = held

        await sem.acquire()
        try:
            await transport_async.sleep_unlocked(sem, 5.0, fake_sleep)
            self.assertFalse(seen["locked_during_sleep"])
            self.assertTrue(sem.locked())
        finally:
            if sem.locked():
                sem.release()


class _Http429(Exception):
    status = 429


class _Http401(Exception):
    status = 401


class TestJudgeRowAsync(unittest.IsolatedAsyncioTestCase):
    def _engine_kwargs(self, **over):
        kw = dict(
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            model="m", semaphore=asyncio.BoundedSemaphore(8),
            ring=transport.KeyRing(["k1", "k2"]),
            ring_lock=asyncio.Lock(), timeout_s=25,
            sleep_fn=None, state={},
        )
        kw.update(over)
        return kw

    async def test_429_rotates_and_retries_same_call(self):
        calls = []

        async def flaky(key, model, prompt):
            calls.append(key)
            if len(calls) == 1:
                raise transport.RateLimited("r429")
            return _vote_text(), {"tokens": 3}

        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=flaky, **self._engine_kwargs())
        self.assertEqual(vote["verdict"], "LINK")
        self.assertEqual(calls, ["k1", "k2"])

    async def test_exhausted_ring_raises_rate_limited(self):
        async def always429(key, model, prompt):
            raise transport.RateLimited("r429")

        with self.assertRaises(transport.RateLimited):
            await transport_async.judge_row_async(
                {"key": "w:x"}, transport=always429,
                **self._engine_kwargs(
                    ring=transport.KeyRing(["only"])) )

    async def test_401_aborts_after_single_attempt(self):
        calls = []

        async def denied(key, model, prompt):
            calls.append(key)
            raise transport.AuthError("no GOOGLE_X (set it)")

        with self.assertRaises(transport.AuthError):
            await transport_async.judge_row_async(
                {"key": "w:x"}, transport=denied,
                **self._engine_kwargs())
        self.assertEqual(len(calls), 1)

    async def test_cooldown_stops_without_rotation(self):
        ring = transport.KeyRing(["k1", "k2"])

        async def cooled(key, model, prompt):
            raise transport.ProviderCooldown("project quota")

        with self.assertRaises(transport.ProviderCooldown):
            await transport_async.judge_row_async(
                {"key": "w:x"}, transport=cooled,
                **self._engine_kwargs(ring=ring))
        self.assertEqual(ring.idx, 0)

    async def test_timeout_fails_item_closed(self):
        async def hung(key, model, prompt):
            await asyncio.sleep(60)

        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=hung,
            **self._engine_kwargs(timeout_s=0.05))
        self.assertEqual(vote["verdict"], "FAILED")

    async def test_concurrency_cap_holds(self):
        active = {"now": 0, "max": 0}

        async def slow(key, model, prompt):
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            await asyncio.sleep(0.02)
            active["now"] -= 1
            return _vote_text(), None

        rows = [{"key": "w:%d" % i} for i in range(6)]
        sem = asyncio.BoundedSemaphore(2)
        await asyncio.gather(*[
            transport_async.judge_row_async(
                r, transport=slow, **self._engine_kwargs(semaphore=sem))
            for r in rows])
        self.assertLessEqual(active["max"], 2)


class TestSecretsHygiene(unittest.IsolatedAsyncioTestCase):
    async def test_key_strings_never_enter_telemetry(self):
        secret = "SECRET-KEY-VALUE-zzz"

        async def ok(key, model, prompt):
            self.assertEqual(key, secret)
            return _vote_text(), {"tokens": 1}

        ring = transport.KeyRing([secret])
        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=ok,
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            model="m", semaphore=asyncio.BoundedSemaphore(8),
            ring=ring, ring_lock=asyncio.Lock(), timeout_s=25,
            sleep_fn=None, state={})
        blob = json.dumps(vote) + json.dumps(ring.attempt_log
                                             if hasattr(ring, "attempt_log")
                                             else [])
        self.assertNotIn(secret, blob)


class TestCliConcurrencyFlag(unittest.TestCase):
    def test_concurrency_flag_parses(self):
        from factory.precard.pipeline import parse_args
        self.assertEqual(parse_args(["--concurrency", "5"]).concurrency, 5)

    def test_concurrency_flag_defaults_to_8(self):
        from factory.precard.pipeline import parse_args
        self.assertEqual(parse_args([]).concurrency, 8)


class TestReviewFixes(unittest.IsolatedAsyncioTestCase):
    def _engine_kwargs(self, **over):
        kw = dict(
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            model="m", semaphore=asyncio.BoundedSemaphore(8),
            ring=transport.KeyRing(["k1", "k2"]),
            ring_lock=asyncio.Lock(), timeout_s=25,
            sleep_fn=None, state={},
        )
        kw.update(over)
        return kw

    async def test_backoff_sleeps_unlocked_with_slot_free(self):
        sem = asyncio.BoundedSemaphore(1)
        seen = {}
        order = []

        async def rec_sleep(delay):
            order.append(delay)
            seen["locked_during_sleep"] = sem.locked()

        calls = []

        async def flaky(key, model, prompt):
            calls.append(key)
            if len(calls) == 1:
                raise transport.RateLimited("r429")
            return _vote_text(), None

        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=flaky,
            **self._engine_kwargs(semaphore=sem, sleep_fn=rec_sleep,
                                  backoff_s=2.5))
        self.assertEqual(vote["verdict"], "LINK")
        self.assertEqual(order, [2.5])
        self.assertFalse(seen["locked_during_sleep"])
        self.assertEqual(calls, ["k1", "k2"])

    async def test_generic_transport_error_fails_closed_not_aborts(self):
        async def boom(key, model, prompt):
            raise ConnectionError("dns")

        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=boom, **self._engine_kwargs())
        self.assertEqual(vote["verdict"], "FAILED")
        self.assertIn("ConnectionError", vote["reason"])

    async def test_validator_raise_fails_closed(self):
        def bad_validate(text):
            raise ValueError("nope")

        async def ok(key, model, prompt):
            return _vote_text(), None

        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=ok,
            **self._engine_kwargs(validate_fn=bad_validate))
        self.assertEqual(vote["verdict"], "FAILED")
        self.assertIn("ValueError", vote["reason"])

    async def test_non_dict_vote_fails_envelope(self):
        async def ok(key, model, prompt):
            return _vote_text(), None

        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=ok,
            **self._engine_kwargs(
                validate_fn=lambda text: ("ok", ["not", "a", "dict"])))
        self.assertEqual(vote["verdict"], "FAILED")
        self.assertEqual(vote["reason"], "envelope")

    async def test_attempt_vocab_and_http_status_present(self):
        async def ok(key, model, prompt):
            return _vote_text(), None

        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=ok, **self._engine_kwargs())
        attempts = vote["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["outcome"], "settled")
        for name in ("model", "attempt", "latency_s", "key_idx"):
            self.assertIn(name, attempts[0])
        self.assertNotIn("http_status", attempts[0])

    async def test_to_thread_adapter_delegates(self):
        seen = []

        def sync_fn(key, model, prompt):
            seen.append((key, model, prompt))
            return "TEXT", {"tokens": 1}

        adapted = transport_async.to_thread_adapter(sync_fn)
        text, usage = await adapted("k", "m", "p")
        self.assertEqual((text, usage), ("TEXT", {"tokens": 1}))
        self.assertEqual(seen, [("k", "m", "p")])

    async def test_run_batches_returns_maps_plus_terminal(self):
        async def ok(key, model, prompt):
            return _batch_reply(), None

        maps, terminal = await transport_async.run_batches_async(
            [{"batch_items": _batch_items(), "anchor_map": _anchor_map()}],
            transport=ok, model="m",
            semaphore=asyncio.BoundedSemaphore(2),
            ring=transport.KeyRing(["tk1"]),
            ring_lock=asyncio.Lock(), timeout_s=25,
            sleep_fn=None, state={})
        self.assertIsNone(terminal)
        self.assertEqual(maps[0]["w:boil"]["sense_id"], "boil#2")

    async def test_run_batches_surfaces_terminal_auth(self):
        async def denied(key, model, prompt):
            raise transport.AuthError("no X (set it)")

        maps, terminal = await transport_async.run_batches_async(
            [{"batch_items": _batch_items(), "anchor_map": _anchor_map()}],
            transport=denied, model="m",
            semaphore=asyncio.BoundedSemaphore(2),
            ring=transport.KeyRing(["tk1"]),
            ring_lock=asyncio.Lock(), timeout_s=25,
            sleep_fn=None, state={})
        self.assertEqual(maps, {})
        self.assertIsInstance(terminal, transport.AuthError)

    async def test_run_batches_empty_units(self):
        maps, terminal = await transport_async.run_batches_async(
            [], transport=_never_called, model="m",
            semaphore=asyncio.BoundedSemaphore(2),
            ring=transport.KeyRing(["tk1"]),
            ring_lock=asyncio.Lock(), timeout_s=25,
            sleep_fn=None, state={})
        self.assertEqual((maps, terminal), ({}, None))

    async def test_gather_reraises_cancellation(self):
        async def cancelled(key, model, prompt):
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await transport_async.run_batches_async(
                [{"batch_items": _batch_items(),
                  "anchor_map": _anchor_map()}],
                transport=cancelled, model="m",
                semaphore=asyncio.BoundedSemaphore(2),
                ring=transport.KeyRing(["tk1"]),
                ring_lock=asyncio.Lock(), timeout_s=25,
                sleep_fn=None, state={})


async def _never_called(key, model, prompt):  # pragma: no cover
    raise AssertionError("must not be called")


class TestHttpErrorMapping(unittest.IsolatedAsyncioTestCase):
    def _engine_kwargs(self, **over):
        kw = dict(
            model="m", semaphore=asyncio.BoundedSemaphore(8),
            ring=transport.KeyRing(["k1", "k2"]),
            ring_lock=asyncio.Lock(), timeout_s=25,
            sleep_fn=None, state={},
        )
        kw.update(over)
        return kw

    def _http_error(self, code, body=b""):
        import io
        import urllib.error
        return urllib.error.HTTPError(
            "http://x/", code, "reason", {}, io.BytesIO(body))

    async def test_http_429_rotates_like_rate_limited(self):
        calls = []

        async def http429(key, model, prompt):
            calls.append(key)
            if len(calls) == 1:
                raise self._http_error(429)
            return _vote_text(), None

        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=http429,
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            **self._engine_kwargs(provider="avalai"))
        self.assertEqual(vote["verdict"], "LINK")
        self.assertEqual(calls, ["k1", "k2"])

    async def test_http_401_aborts_auth(self):
        async def http401(key, model, prompt):
            raise self._http_error(401, b"invalid_api_key")

        with self.assertRaises(transport.AuthError):
            await transport_async.judge_row_async(
                {"key": "w:x"}, transport=http401,
                prompt_fn=lambda row: "PROMPT",
                validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
                **self._engine_kwargs(provider="avalai"))

    async def test_http_500_fails_closed(self):
        async def http500(key, model, prompt):
            raise self._http_error(500)

        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=http500,
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            **self._engine_kwargs(provider="avalai"))
        self.assertEqual(vote["verdict"], "FAILED")
        self.assertEqual(len(vote["attempts"]), 1)

    async def test_google_resource_exhausted_cools_without_rotation(self):
        ring = transport.KeyRing(["k1", "k2"])

        async def http_quota(key, model, prompt):
            raise self._http_error(
                429, b'{"error": {"status": "RESOURCE_EXHAUSTED"}}')

        with self.assertRaises(transport.ProviderCooldown):
            await transport_async.judge_row_async(
                {"key": "w:x"}, transport=http_quota,
                prompt_fn=lambda row: "PROMPT",
                validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
                **self._engine_kwargs(ring=ring, provider="google"))
        self.assertEqual(ring.idx, 0)


class TestEdgeInputs(unittest.TestCase):
    def test_clamp_edges(self):
        self.assertEqual(transport_async.clamp_concurrency(None), 8)
        self.assertEqual(transport_async.clamp_concurrency("5"), 5)
        self.assertEqual(transport_async.clamp_concurrency(True), 1)
        self.assertEqual(transport_async.clamp_concurrency(-5), 1)
        import math
        self.assertEqual(
            transport_async.clamp_concurrency(float("nan")), 8)
        self.assertEqual(
            transport_async.clamp_concurrency(float("inf")), 8)

    def test_resolve_route_variants(self):
        self.assertEqual(transport_async.resolve_route("Google"), "tunnel")
        self.assertEqual(transport_async.resolve_route(" AVALAI "), "direct")
        self.assertEqual(transport_async.resolve_route(None), "direct")
        self.assertEqual(transport_async.resolve_route(""), "direct")


class TestEdgeAsync(unittest.IsolatedAsyncioTestCase):
    def _engine_kwargs(self, **over):
        kw = dict(
            model="m", semaphore=asyncio.BoundedSemaphore(8),
            ring=transport.KeyRing(["k1"]),
            ring_lock=asyncio.Lock(), timeout_s=25,
            sleep_fn=None, state={},
        )
        kw.update(over)
        return kw

    async def test_row_none_fails_closed(self):
        async def never(key, model, prompt):
            raise AssertionError("must not be called")

        vote = await transport_async.judge_row_async(
            None, transport=never,
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            **self._engine_kwargs())
        self.assertEqual(
            (vote["verdict"], vote["reason"]), ("FAILED", "row"))

    async def test_nan_timeout_fails_closed_without_call(self):
        calls = []

        async def never(key, model, prompt):
            calls.append(key)
            return _vote_text(), None

        import math
        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=never,
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            **self._engine_kwargs(timeout_s=float("nan")))
        self.assertEqual(vote["verdict"], "FAILED")
        self.assertEqual(calls, [])

    async def test_empty_batch_returns_empty_mapping(self):
        async def never(key, model, prompt):
            raise AssertionError("must not be called")

        votes = await transport_async.judge_batch_async(
            [], {}, transport=never, **self._engine_kwargs())
        self.assertEqual(votes, {})

    async def test_lowercase_resumed_verdict_rejudged(self):
        calls = []

        async def ok(key, model, prompt):
            calls.append(key)
            return _vote_text(), None

        import tempfile
        path = os.path.join(tempfile.mkdtemp(prefix="edge_"), "p.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": "w:a",
                                 "vote": {"verdict": "link"}}) + "\n")
        votes = await transport_async.run_judge_async(
            [{"key": "w:a"}], transport=ok, model="m",
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            ring=transport.KeyRing(["tk1"]),
            concurrency=1, timeout_s=25, progress_path=path)
        self.assertEqual(votes["w:a"]["verdict"], "LINK")
        self.assertEqual(calls, ["tk1"])

    async def test_failed_vote_carries_attempts(self):
        async def hung(key, model, prompt):
            await asyncio.sleep(60)

        vote = await transport_async.judge_row_async(
            {"key": "w:x"}, transport=hung,
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            **self._engine_kwargs(timeout_s=0.05))
        self.assertEqual(len(vote["attempts"]), 1)
        self.assertEqual(vote["attempts"][0]["outcome"], "error")

    async def test_auth_error_names_var_and_file_not_values(self):
        async def http401(key, model, prompt):
            import io
            import urllib.error
            raise urllib.error.HTTPError(
                "http://x/", 401, "deny", {}, io.BytesIO(b"bad key"))

        with self.assertRaises(transport.AuthError) as ctx:
            await transport_async.judge_row_async(
                {"key": "w:x"}, transport=http401,
                prompt_fn=lambda row: "PROMPT",
                validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
                **self._engine_kwargs(
                    provider="avalai", key_var="AVALAI_API_KEY",
                    file_label="factory/.env"))
        self.assertIn("AVALAI_API_KEY", str(ctx.exception))
        self.assertIn("factory/.env", str(ctx.exception))

    async def test_progress_sink_called_per_settled_unit(self):
        seen = []

        async def ok(key, model, prompt):
            return _batch_reply(), None

        maps, terminal = await transport_async.run_batches_async(
            [{"batch_items": _batch_items(), "anchor_map": _anchor_map()},
             {"batch_items": _batch_items(), "anchor_map": _anchor_map()}],
            transport=ok, model="m",
            semaphore=asyncio.BoundedSemaphore(2),
            ring=transport.KeyRing(["tk1"]),
            ring_lock=asyncio.Lock(), timeout_s=25,
            sleep_fn=None, state={},
            progress_sink=lambda idx, mapping: seen.append(idx))
        self.assertIsNone(terminal)
        self.assertEqual(sorted(seen), [0, 1])
        self.assertEqual(set(maps), {0, 1})

    async def test_run_judge_reraises_cancellation(self):
        async def cancelled(key, model, prompt):
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await transport_async.run_judge_async(
                [{"key": "w:a"}], transport=cancelled, model="m",
                prompt_fn=lambda row: "PROMPT",
                validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
                ring=transport.KeyRing(["tk1"]),
                concurrency=1, timeout_s=25,
                progress_path=os.path.join(
                    tempfile.mkdtemp(prefix="cx_"), "p.jsonl"))

    async def test_run_judge_propagates_auth_error(self):
        async def denied(key, model, prompt):
            raise transport.AuthError("no X (set it)")

        with self.assertRaises(transport.AuthError):
            await transport_async.run_judge_async(
                [{"key": "w:a"}], transport=denied, model="m",
                prompt_fn=lambda row: "PROMPT",
                validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
                ring=transport.KeyRing(["tk1"]),
                concurrency=1, timeout_s=25,
                progress_path=os.path.join(
                    tempfile.mkdtemp(prefix="ax_"), "p.jsonl"))

    async def test_run_judge_skips_non_dict_rows(self):
        async def ok(key, model, prompt):
            return _vote_text(), None

        votes = await transport_async.run_judge_async(
            [None, {"key": "w:a"}, 42], transport=ok, model="m",
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            ring=transport.KeyRing(["tk1"]),
            concurrency=1, timeout_s=25,
            progress_path=os.path.join(
                tempfile.mkdtemp(prefix="nd_"), "p.jsonl"))
        self.assertEqual(sorted(votes), ["w:a"])

    async def test_raising_sink_propagates_loud(self):
        async def ok(key, model, prompt):
            return _batch_reply(), None

        def bad_sink(idx, mapping):
            raise OSError("disk gone")

        with self.assertRaises(OSError):
            await transport_async.run_batches_async(
                [{"batch_items": _batch_items(),
                  "anchor_map": _anchor_map()}],
                transport=ok, model="m",
                semaphore=asyncio.BoundedSemaphore(2),
                ring=transport.KeyRing(["tk1"]),
                ring_lock=asyncio.Lock(), timeout_s=25,
                sleep_fn=None, state={}, progress_sink=bad_sink)

    async def test_sleep_unlocked_on_free_semaphore_still_sleeps(self):
        sem = asyncio.BoundedSemaphore(1)
        seen = []
        await transport_async.sleep_unlocked(
            sem, 0.01, lambda delay: seen.append(delay) or asyncio.sleep(0))
        self.assertEqual(seen, [0.01])
        self.assertFalse(sem.locked())

    async def test_run_judge_async_dedupes_keys_and_progress_none_raises(self):
        calls = []

        async def ok(key, model, prompt):
            calls.append(key)
            return _vote_text(), None

        progress = tempfile.mkdtemp(prefix="dup_")
        path = os.path.join(progress, "p.jsonl")
        votes = await transport_async.run_judge_async(
            [{"key": "w:a"}, {"key": "w:a"}, {"key": "w:b"}],
            transport=ok, model="m",
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            ring=transport.KeyRing(["tk1"]),
            concurrency=2, timeout_s=25, progress_path=path)
        self.assertEqual(sorted(votes), ["w:a", "w:b"])
        self.assertEqual(calls.count("tk1"), 2)
        with self.assertRaises(ValueError):
            await transport_async.run_judge_async(
                [{"key": "w:z"}], transport=ok, model="m",
                prompt_fn=lambda row: "PROMPT",
                validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
                ring=transport.KeyRing(["tk1"]),
                concurrency=1, timeout_s=25, progress_path=None)

    async def test_corrupt_and_malformed_resume_rows_rejudged(self):
        calls = []

        async def ok(key, model, prompt):
            calls.append(key)
            return _vote_text(), None

        progress = tempfile.mkdtemp(prefix="resume_")
        path = os.path.join(progress, "p.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json\n")
            fh.write(json.dumps({"key": "w:ok",
                                 "vote": {"verdict": "LINK"}}) + "\n")
            fh.write(json.dumps({"key": "w:bad",
                                 "vote": {"verdict": "MAYBE"}}) + "\n")
        votes = await transport_async.run_judge_async(
            [{"key": "w:ok"}, {"key": "w:bad"}, {"key": "w:new"}],
            transport=ok, model="m",
            prompt_fn=lambda row: "PROMPT",
            validate_fn=lambda text: ("ok", {"verdict": "LINK"}),
            ring=transport.KeyRing(["tk1"]),
            concurrency=2, timeout_s=25, progress_path=path)
        self.assertEqual(votes["w:ok"]["verdict"], "LINK")
        self.assertEqual(votes["w:bad"]["verdict"], "LINK")
        self.assertEqual(votes["w:new"]["verdict"], "LINK")
        self.assertEqual(sorted(calls), ["tk1", "tk1"])

    def test_async_judge_provider_flag_defaults_to_none(self):
        from factory.precard.pipeline import parse_args
        self.assertIsNone(parse_args([]).async_judge_provider)

    def test_use_async_judge_predicate(self):
        from factory.precard import pipeline
        self.assertFalse(pipeline.use_async_judge(
            pipeline.parse_args([])))
        self.assertTrue(pipeline.use_async_judge(
            pipeline.parse_args(["--async-judge-provider", "google"])))

    def test_async_judge_provider_rejects_unknown(self):
        from factory.precard.pipeline import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["--async-judge-provider", "groq"])


def _anchor_map():
    return {"w:boil": {"candidates": [
        {"sense_id": "boil#2", "gloss": "to heat liquid", "tags": []},
        {"sense_id": "boil#5", "gloss": "a swelling", "tags": []}]}}


def _batch_items():
    return [{"key": "w:boil", "kind": "word", "text": "boil",
             "pool_level": "B1"}]


def _batch_reply():
    return json.dumps({"results": [
        {"key": "w:boil", "picks": ["boil#2"]}]})


class TestJudgeBatchAsync(unittest.IsolatedAsyncioTestCase):
    def _engine_kwargs(self, **over):
        kw = dict(
            model="m", semaphore=asyncio.BoundedSemaphore(8),
            ring=transport.KeyRing(["k1", "k2"]),
            ring_lock=asyncio.Lock(), timeout_s=25,
            sleep_fn=None, state={},
        )
        kw.update(over)
        return kw

    async def test_prompt_parity_with_sync_arbiter_prompt(self):
        from factory.precard import judge as judge_mod
        seen = []

        async def spy(key, model, prompt):
            seen.append(prompt)
            return _batch_reply(), None

        await transport_async.judge_batch_async(
            _batch_items(), _anchor_map(), transport=spy,
            **self._engine_kwargs())
        self.assertEqual(
            seen[0], judge_mod.arbiter_prompt(_batch_items(), _anchor_map()))

    async def test_batch_shape_matches_sync_mapping(self):
        async def ok(key, model, prompt):
            return _batch_reply(), None

        votes = await transport_async.judge_batch_async(
            _batch_items(), _anchor_map(), transport=ok,
            **self._engine_kwargs())
        self.assertEqual(votes["w:boil"]["sense_id"], "boil#2")
        self.assertIn("picks", votes["w:boil"])

    async def test_batch_timeout_returns_empty_mapping(self):
        async def hung(key, model, prompt):
            await asyncio.sleep(60)

        votes = await transport_async.judge_batch_async(
            _batch_items(), _anchor_map(), transport=hung,
            **self._engine_kwargs(timeout_s=0.05))
        self.assertEqual(votes, {})

    async def test_batch_auth_aborts_after_single_attempt(self):
        calls = []

        async def denied(key, model, prompt):
            calls.append(key)
            raise transport.AuthError("no X (set it)")

        with self.assertRaises(transport.AuthError):
            await transport_async.judge_batch_async(
                _batch_items(), _anchor_map(), transport=denied,
                **self._engine_kwargs())
        self.assertEqual(len(calls), 1)

    async def test_batch_429_rotates_and_retries(self):
        calls = []

        async def flaky(key, model, prompt):
            calls.append(key)
            if len(calls) == 1:
                raise transport.RateLimited("r429")
            return _batch_reply(), None

        votes = await transport_async.judge_batch_async(
            _batch_items(), _anchor_map(), transport=flaky,
            **self._engine_kwargs())
        self.assertEqual(calls, ["k1", "k2"])
        self.assertEqual(votes["w:boil"]["sense_id"], "boil#2")


if __name__ == "__main__":
    unittest.main()
