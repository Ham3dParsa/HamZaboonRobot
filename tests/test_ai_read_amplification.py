"""G4 (BOT-1/2/3/4): proof-metric tests for AI read-amplification reduction.

Locks the contract rules against the audit proof metrics (2026-08-16):
- R1-B: the fallback chain is read once across AI calls (chain TTL cache);
  the active preset is resolved once per request; the preset cost is read from
  the already-loaded dict instead of a redundant re-query.
- R2-A: get_llm_cost_profile runs once across many calls (cost TTL + invalidate).
- R3-A: get_hourly_usage_many reads the whole chain in one query; the old
  per-preset get_hourly_usage is not called on the chain hot path.
- R4-A: the _log_llm_request main log line is compact (bounded length).
"""

from __future__ import annotations

import logging
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from config import COST
from services import db as db_module
from services.db import schema as db_schema
from services.ai import ai, ai_read_cache, llm_services
from services.ai.llm_services import _call_ai_limited


def _seed_preset(name: str, **overrides):
    db_module.set_preset(
        name=name,
        base_url=overrides.get("base_url", "http://test.local/v1"),
        model=overrides.get("model", "test-model"),
        api_key=overrides.get("api_key", "sk-test"),
        max_concurrency=overrides.get("max_concurrency", 2),
        max_rpm=overrides.get("max_rpm", 30),
        max_tpm=overrides.get("max_tpm", 0),
        max_daily_req=overrides.get("max_daily_req", 0),
        input_cost_per_million=overrides.get("input_cost_per_million", 5.0),
        output_cost_per_million=overrides.get("output_cost_per_million", 6.0),
        is_emergency=overrides.get("is_emergency", 0),
        in_fallback_chain=overrides.get("in_fallback_chain", 1),
    )
    db_module.set_preset_priority(name, overrides.get("priority", 0))
    db_module.set_preset_enabled(name, overrides.get("enabled", 1))
    return db_module.get_preset(name)


class _ReadAmplificationIsolatedDb(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db = db_module.DB_PATH
        self.old_schema = db_schema.DB_PATH
        db_module.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db_module.DB_PATH
        db_module.init_db()
        for existing in db_module.get_presets():
            db_module.delete_preset(existing["name"])
        ai_read_cache.reset_read_cache()
        llm_services.get_limiter_store().reset()

    def tearDown(self):
        ai_read_cache.reset_read_cache()
        llm_services.get_limiter_store().reset()
        db_module.DB_PATH = self.old_db
        db_schema.DB_PATH = self.old_schema
        self.tempdir.cleanup()


class ChainReadOnceTest(_ReadAmplificationIsolatedDb):
    """R1-B — the fallback chain is read once across AI calls."""

    def test_chain_read_once_across_two_calls(self):
        _seed_preset("pa", priority=0)
        _seed_preset("pb", priority=1)
        calls: list[int] = []
        real_chain_loader = db_module.get_fallback_chain_presets

        def counting_chain_loader():
            calls.append(1)
            return real_chain_loader()

        def ok_fn(*args, **kwargs):
            return ai.TrackedResult(value={"ok": True}, telemetry={"usage": SimpleNamespace(
                prompt_tokens=1, completion_tokens=1, total_tokens=2
            )})

        with mock.patch("services.ai.llm_services._is_preset_rate_limited", return_value=False), \
             mock.patch("services.ai.ai_read_cache.db.get_fallback_chain_presets", side_effect=counting_chain_loader):
            _call_ai_limited(ok_fn, request_kind="card")
            _call_ai_limited(ok_fn, request_kind="card")

        self.assertEqual(len(calls), 1, "chain loader must run once across two AI calls")

    def test_chain_loader_called_after_cache_reset(self):
        _seed_preset("pa", priority=0)
        calls: list[int] = []
        real_chain_loader = db_module.get_fallback_chain_presets

        def counting_chain_loader():
            calls.append(1)
            return real_chain_loader()

        def ok_fn(*args, **kwargs):
            return ai.TrackedResult(value={"ok": True}, telemetry={})

        with mock.patch("services.ai.ai_read_cache.db.get_fallback_chain_presets", side_effect=counting_chain_loader):
            with mock.patch("services.ai.llm_services._is_preset_rate_limited", return_value=False):
                _call_ai_limited(ok_fn, request_kind="card")
            ai_read_cache.reset_read_cache()
            with mock.patch("services.ai.llm_services._is_preset_rate_limited", return_value=False):
                _call_ai_limited(ok_fn, request_kind="card")

        self.assertEqual(len(calls), 2, "cache reset must force a chain refetch")


class UsageBatchReadTest(_ReadAmplificationIsolatedDb):
    """R3-A — one usage query for the whole chain, never one per preset."""

    def test_hourly_usage_read_once_for_whole_chain(self):
        _seed_preset("pa", priority=0, max_daily_req=5)
        _seed_preset("pb", priority=1, max_daily_req=5)

        def ok_fn(*args, **kwargs):
            return ai.TrackedResult(value={"ok": True}, telemetry={"usage": SimpleNamespace(
                prompt_tokens=1, completion_tokens=1, total_tokens=2
            )})

        def forbidden_per_preset_usage(*args, **kwargs):
            raise AssertionError("get_hourly_usage must not be called on the chain hot path")

        usage_many = mock.MagicMock(return_value={"pa": (0, 0), "pb": (0, 0)})
        with mock.patch("services.db.get_hourly_usage", side_effect=forbidden_per_preset_usage), \
             mock.patch("services.db.get_hourly_usage_many", usage_many):
            _call_ai_limited(ok_fn, request_kind="card")

        usage_many.assert_called_once()
        args = usage_many.call_args.args
        self.assertEqual(sorted(args[0]), ["pa", "pb"], "one batched read covers the whole chain")


class CostProfileCacheTest(_ReadAmplificationIsolatedDb):
    """R2-A / R1-B — cost reads are deduplicated in _log_llm_request."""

    def test_log_llm_request_reuses_preset_cost_and_cached_profile(self):
        preset = _seed_preset("pa", input_cost_per_million=5.0, output_cost_per_million=6.0)
        profile = {
            "input_cost_usd_per_million": 0.25,
            "output_cost_usd_per_million": 1.5,
            "usd_to_toman_rate": 28000.0,
        }
        telemetry = {
            "usage": SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            "latency_ms": 123.0,
        }
        get_preset_cost = mock.MagicMock()
        get_profile = mock.MagicMock(return_value=profile)

        with mock.patch("services.ai.ai.db.get_preset_cost", get_preset_cost), \
             mock.patch("services.ai.ai.db.get_llm_cost_profile", get_profile):
            for _ in range(3):
                ai._log_llm_request(
                    request_kind="card",
                    user_id=1,
                    plan="free",
                    model="m",
                    telemetry=telemetry,
                    outcome="success",
                    preset=preset,
                )

        get_preset_cost.assert_not_called()
        self.assertEqual(get_profile.call_count, 1, "cost profile must be cached across calls")

        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT input_cost_usd_per_million, output_cost_usd_per_million FROM llm_requests"
            ).fetchone()
        self.assertEqual(row["input_cost_usd_per_million"], 5.0, "ledger uses the preset cost")
        self.assertEqual(row["output_cost_usd_per_million"], 6.0, "ledger uses the preset cost")

    def test_cost_profile_invalidation_refetches(self):
        profile = {
            "input_cost_usd_per_million": 0.25,
            "output_cost_usd_per_million": 1.5,
            "usd_to_toman_rate": 28000.0,
        }
        calls: list[int] = []
        preset = {"name": "pa", "input_cost_per_million": None, "output_cost_per_million": None}

        def profile_loader():
            calls.append(1)
            return profile

        telemetry = {"usage": SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)}
        with mock.patch("services.ai.ai.db.get_preset_cost", mock.MagicMock()), \
             mock.patch("services.ai.ai.db.get_llm_cost_profile", side_effect=profile_loader):
            ai._log_llm_request(
                request_kind="card", user_id=1, plan="free", model="m",
                telemetry=telemetry, outcome="success", preset=preset,
            )
            ai_read_cache.invalidate_cost_profile()
            ai._log_llm_request(
                request_kind="card", user_id=1, plan="free", model="m",
                telemetry=telemetry, outcome="success", preset=preset,
            )

        self.assertEqual(len(calls), 2, "invalidation must refetch the cost profile")


class ActivePresetDedupTest(_ReadAmplificationIsolatedDb):
    """R1-B — the active preset is resolved once per request."""

    def test_request_json_resolves_active_preset_once(self):
        preset = {
            "name": "pa",
            "base_url": "http://test.local/v1",
            "model": "m",
            "timeout_seconds": 30,
            "temperature": 0.5,
            "max_output_tokens": 100,
        }
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"k": 1}'))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )
        active_calls: list[int] = []

        def counting_active():
            active_calls.append(1)
            return dict(preset)

        with mock.patch("services.ai.ai.db.get_active_preset", side_effect=counting_active), \
             mock.patch("services.ai.ai._client", return_value=fake_client), \
             mock.patch("services.ai.ai._model", return_value="m"):
            value = ai._request_json("sys", "user")

        self.assertEqual(value, {"k": 1})
        self.assertEqual(len(active_calls), 1, "active preset must be resolved once per request")


class HourlyUsageManyDbTest(_ReadAmplificationIsolatedDb):
    """R3-A — db.get_hourly_usage_many returns all names in one query."""

    def _seed_usage(self, name: str, bucket: str, req: int, tok: int):
        db_module.increment_hourly_usage(name, bucket, req_count=req, token_count=tok)

    def test_returns_usage_for_all_names(self):
        _seed_preset("pa")
        _seed_preset("pb")
        _seed_preset("pc")
        self._seed_usage("pa", "2026-08-20T10:00:00", 3, 100)
        self._seed_usage("pb", "2026-08-20T10:00:00", 2, 50)

        result = db_module.get_hourly_usage_many(["pa", "pb", "pc"], hours_back=24)
        self.assertEqual(result["pa"], (3, 100))
        self.assertEqual(result["pb"], (2, 50))
        self.assertEqual(result["pc"], (0, 0), "untouched preset reports zero usage")

    def test_single_query_for_multiple_names(self):
        _seed_preset("pa")
        _seed_preset("pb")
        self._seed_usage("pa", "2026-08-20T10:00:00", 1, 1)
        self._seed_usage("pb", "2026-08-20T10:00:00", 1, 1)

        query_count: list[int] = []
        real_get_conn = db_module.get_conn

        class _CountingConn:
            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            def execute(self, statement, *a, **kw):
                query_count.append(statement)
                return self._real.execute(statement, *a, **kw)

        from contextlib import contextmanager

        @contextmanager
        def counting_get_conn(*args, **kwargs):
            with real_get_conn(*args, **kwargs) as real:
                yield _CountingConn(real)

        with mock.patch("services.db.preset_registry.get_conn", counting_get_conn):
            db_module.get_hourly_usage_many(["pa", "pb"], hours_back=24)

        selects = [s for s in query_count if s.lstrip().upper().startswith("SELECT")]
        self.assertEqual(len(selects), 1, "one batched SELECT serves the whole chain")

    def test_empty_names_returns_empty_map(self):
        result = db_module.get_hourly_usage_many([], hours_back=24)
        self.assertEqual(result, {})


class LogLineCompactionTest(_ReadAmplificationIsolatedDb):
    """R4-A — the _log_llm_request main line is compact (bounded length)."""

    def test_main_log_line_is_compact(self):
        records: list[logging.LogRecord] = []
        handler = _CaptureHandler(records)
        ai.log.addHandler(handler)
        ai.log.setLevel(1)
        self.addCleanup(ai.log.removeHandler, handler)
        self.addCleanup(ai.log.setLevel, logging.NOTSET)

        preset = _seed_preset("pa")
        telemetry = {
            "usage": SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            "latency_ms": 123.0,
        }
        with mock.patch("services.ai.ai.db.get_preset_cost", mock.MagicMock()), \
             mock.patch("services.ai.ai.db.get_llm_cost_profile", mock.MagicMock(return_value={
                 "input_cost_usd_per_million": 0.25,
                 "output_cost_usd_per_million": 1.5,
                 "usd_to_toman_rate": 28000.0,
             })):
            ai._log_llm_request(
                request_kind="card", user_id=1, plan="free", model="m",
                telemetry=telemetry, outcome="success", preset=preset,
            )

        cost_records = [r for r in records if r.levelno == COST]
        self.assertTrue(cost_records, "expected a COST-level log record")
        line = cost_records[0].getMessage()
        self.assertIn("kind=", line)
        self.assertLessEqual(len(line), 120, "main log line must stay compact")


class _CaptureHandler(logging.Handler):
    def __init__(self, records: list[logging.LogRecord]):
        super().__init__(level=1)
        self.records = records

    def emit(self, record: logging.LogRecord):
        self.records.append(record)


if __name__ == "__main__":
    unittest.main()