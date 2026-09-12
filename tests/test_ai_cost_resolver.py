"""REF5-T5 (chain/cost only): TTLCache + cost_resolver contract.

Locks:
- cache.TTLCache is the generic pattern (moved, not redesigned) behind the
  chain (short TTL) + cost-profile (60s TTL + instant bust) hot path.
- cost_resolver.resolve_costs is preset-dict-first -> profile fallback,
  verbatim from telemetry._log_llm_request.
- cost_resolver.client_pool_key is (name, base_url, model, timeout, proxy,
  generation) with NO key material and never logged.
- Admin display paths bypass the cache (raw db accessors).
- Name/group-key cache is explicitly rejected-deferred (no such cache exists).
"""

from __future__ import annotations

import time
import unittest


class TTLCacheContractTest(unittest.TestCase):
    def test_generic_ttl_cache_loader_once_within_ttl(self):
        from services.ai.cache import TTLCache

        cache = TTLCache()
        calls: list[int] = []

        def loader():
            calls.append(1)
            return {"v": 1}

        first = cache.get("k", loader, ttl=60.0)
        second = cache.get("k", loader, ttl=60.0)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)

    def test_generic_ttl_cache_refetch_after_ttl(self):
        from services.ai.cache import TTLCache

        cache = TTLCache()
        calls: list[int] = []

        def loader():
            calls.append(1)
            return {"v": 1}

        cache.get("k", loader, ttl=0.05)
        time.sleep(0.06)
        cache.get("k", loader, ttl=0.05)
        self.assertEqual(len(calls), 2)

    def test_generic_ttl_cache_invalidate_and_reset(self):
        from services.ai.cache import TTLCache

        cache = TTLCache()
        calls: list[int] = []

        def loader():
            calls.append(1)
            return {"v": 1}

        cache.get("k", loader, ttl=60.0)
        cache.invalidate("k")
        cache.get("k", loader, ttl=60.0)
        self.assertEqual(len(calls), 2)
        cache.get("other", loader, ttl=60.0)
        cache.reset()
        cache.get("k", loader, ttl=60.0)
        self.assertEqual(len(calls), 4)


class CostResolverContractTest(unittest.TestCase):
    def test_preset_dict_first_profile_fallback(self):
        from services.ai.cost_resolver import resolve_costs

        profile = {
            "input_cost_usd_per_million": 0.25,
            "output_cost_usd_per_million": 1.5,
            "usd_to_toman_rate": 28000.0,
        }
        preset = {"name": "pa", "input_cost_per_million": 5.0, "output_cost_per_million": 6.0}
        inp, outp, rate = resolve_costs(preset, profile)
        self.assertEqual((inp, outp, rate), (5.0, 6.0, 28000.0))

        preset_none = {"name": "pa", "input_cost_per_million": None, "output_cost_per_million": None}
        inp2, outp2, rate2 = resolve_costs(preset_none, profile)
        self.assertEqual((inp2, outp2, rate2), (0.25, 1.5, 28000.0))

        inp3, outp3, rate3 = resolve_costs(None, profile)
        self.assertEqual((inp3, outp3, rate3), (0.25, 1.5, 28000.0))

    def test_pool_key_shape_no_key_material(self):
        from services.ai.cost_resolver import client_pool_key

        preset = {
            "name": "pa",
            "base_url": "http://test.local/v1",
            "model": "m",
            "timeout_seconds": 30,
            "api_key": "DUMMY-KEY-MATERIAL",
            "group_label": "g",
        }
        key = client_pool_key(preset, proxy="", generation=0)
        self.assertEqual(len(key), 6)
        self.assertEqual(key[0], "pa")
        flat = " ".join(str(part) for part in key)
        self.assertNotIn("DUMMY-KEY-MATERIAL", flat)

    def test_pool_key_busts_on_edit(self):
        from services.ai.cost_resolver import client_pool_key

        base = {
            "name": "pa",
            "base_url": "http://a.local/v1",
            "model": "m1",
            "timeout_seconds": 30,
        }
        k1 = client_pool_key(base, proxy="", generation=0)
        edited = dict(base, model="m2")
        k2 = client_pool_key(edited, proxy="", generation=0)
        self.assertNotEqual(k1, k2)
        k3 = client_pool_key(base, proxy="", generation=1)
        self.assertNotEqual(k1, k3)

    def test_no_name_group_key_cache(self):
        # Rejected-deferred: no name/group-key cache module or symbol may exist.
        import services.ai.cost_resolver as cr

        for banned in ("NameKeyCache", "GroupKeyCache", "get_cached_key", "get_group_key_cached"):
            self.assertFalse(hasattr(cr, banned), f"{banned} must not exist (rejected-deferred)")
        import services.ai.cache as c

        for banned in ("NameKeyCache", "GroupKeyCache", "get_cached_key"):
            self.assertFalse(hasattr(c, banned), f"{banned} must not exist (rejected-deferred)")


class ReadCacheFacadeContractTest(unittest.TestCase):
    def test_facade_still_exposes_chain_and_cost_seams(self):
        from services.ai import ai_read_cache

        self.assertTrue(hasattr(ai_read_cache, "ReadCache"))
        self.assertTrue(hasattr(ai_read_cache, "get_chain"))
        self.assertTrue(hasattr(ai_read_cache, "get_cost_profile"))
        self.assertTrue(hasattr(ai_read_cache, "invalidate_cost_profile"))
        self.assertTrue(hasattr(ai_read_cache, "reset_read_cache"))
        self.assertEqual(ai_read_cache.CHAIN_TTL_SECONDS, 10.0)
        self.assertEqual(ai_read_cache.COST_PROFILE_TTL_SECONDS, 60.0)


if __name__ == "__main__":
    unittest.main()
