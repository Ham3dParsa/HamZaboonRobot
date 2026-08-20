"""G4 (BOT-1/2/5): TTL read-cache for slow-changing AI config reads.

Locks the contract rules:
- R1-B: the fallback chain is cached for a short TTL (chain_ttl) so the AI hot
  path reads it once instead of on every call.
- R2-A: the cost profile is cached for cost_ttl and is invalidatable so an
  admin save is reflected immediately (cost ledger exactness).
- R5-A: the cache lives in services/ai/ai_read_cache.py and is injectable.
"""

from __future__ import annotations

import time
import unittest

from services.ai import ai_read_cache


class ReadCacheTest(unittest.TestCase):
    def setUp(self):
        # Tiny TTLs so expiry is testable without sleeping long.
        self.cache = ai_read_cache.ReadCache(chain_ttl=0.05, cost_ttl=0.05)

    def test_chain_loader_called_once_within_ttl(self):
        calls: list[int] = []

        def loader():
            calls.append(1)
            return [{"name": "a"}, {"name": "b"}]

        first = self.cache.get_chain(loader)
        second = self.cache.get_chain(loader)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1, "chain loader must run once within TTL")

    def test_chain_loader_runs_again_after_ttl(self):
        calls: list[int] = []

        def loader():
            calls.append(1)
            return [{"name": "a"}]

        self.cache.get_chain(loader)
        time.sleep(0.06)
        self.cache.get_chain(loader)
        self.assertEqual(len(calls), 2, "chain loader must refetch after TTL")

    def test_cost_profile_cached_and_invalidated(self):
        calls: list[int] = []

        def loader():
            calls.append(1)
            return {
                "input_cost_usd_per_million": 1.0,
                "output_cost_usd_per_million": 2.0,
                "usd_to_toman_rate": 3.0,
            }

        self.cache.get_cost_profile(loader)
        self.cache.get_cost_profile(loader)
        self.assertEqual(len(calls), 1, "cost profile loader must run once within TTL")

        self.cache.invalidate_cost_profile()
        self.cache.get_cost_profile(loader)
        self.assertEqual(len(calls), 2, "invalidation must force a refetch")

    def test_invalidation_does_not_evict_chain(self):
        chain_calls: list[int] = []
        cost_calls: list[int] = []

        def chain_loader():
            chain_calls.append(1)
            return [{"name": "x"}]

        def cost_loader():
            cost_calls.append(1)
            return {
                "input_cost_usd_per_million": 1.0,
                "output_cost_usd_per_million": 1.0,
                "usd_to_toman_rate": 1.0,
            }

        self.cache.get_chain(chain_loader)
        self.cache.get_cost_profile(cost_loader)
        self.cache.invalidate_cost_profile()
        self.cache.get_cost_profile(cost_loader)
        self.cache.get_chain(chain_loader)
        self.assertEqual(len(chain_calls), 1, "chain stays cached after cost invalidation")
        self.assertEqual(len(cost_calls), 2)

    def test_reset_drops_all_cached_values(self):
        calls: list[int] = []

        def loader():
            calls.append(1)
            return [{"name": "a"}]

        self.cache.get_chain(loader)
        self.cache.reset()
        self.cache.get_chain(loader)
        self.assertEqual(len(calls), 2, "reset must clear the cached chain")


if __name__ == "__main__":
    unittest.main()