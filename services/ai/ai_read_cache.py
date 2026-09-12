"""In-memory TTL read caches for slow-changing AI config reads (G4/BOT-1/2).

Thin facade over ``services/ai/cache.TTLCache`` (REF5-T5: pattern moved, not
redesigned). Owns two keys on the AI hot path:
- Fallback chain (R1-B): a short TTL so ``_call_ai_limited`` reads the chain
  once instead of on every call.
- LLM cost profile (R2-A): a 60s TTL that is invalidatable, so an admin save
  is reflected immediately (the cost ledger is never recorded with stale
  prices).

Admin *display* paths do NOT read through this cache — they keep calling the
raw db accessors directly so the panel is always fresh. The chain TTL is a
pure hot-path optimization: an admin chain edit applies within the TTL on the
routing path (enable/disable/reorder), while the admin panel shows the edit
immediately.
"""

from services import db
from services.ai.cache import TTLCache

CHAIN_TTL_SECONDS = 10.0
COST_PROFILE_TTL_SECONDS = 60.0

_CHAIN_KEY = "chain"
_COST_PROFILE_KEY = "cost_profile"


class ReadCache:
    """Thread-safe TTL cache for the fallback chain and LLM cost profile.

    Each value is loaded on first access and re-loaded only after its TTL has
    elapsed. The cost profile can be invalidated out-of-band so an admin save
    takes effect on the very next read.
    """

    def __init__(
        self,
        *,
        chain_ttl: float = CHAIN_TTL_SECONDS,
        cost_ttl: float = COST_PROFILE_TTL_SECONDS,
    ):
        self._chain_ttl = chain_ttl
        self._cost_ttl = cost_ttl
        self._entries = TTLCache()

    def get_chain(self, loader=None) -> list[dict]:
        loader = loader or db.get_fallback_chain_presets
        return self._entries.get(_CHAIN_KEY, loader, ttl=self._chain_ttl)

    def get_cost_profile(self, loader=None) -> dict[str, float]:
        loader = loader or db.get_llm_cost_profile
        return self._entries.get(_COST_PROFILE_KEY, loader, ttl=self._cost_ttl)

    def invalidate_cost_profile(self) -> None:
        """Clear the cached cost profile so the next read refetches it."""
        self._entries.invalidate(_COST_PROFILE_KEY)

    def reset(self) -> None:
        """Drop all cached values (test/restart seam)."""
        self._entries.reset()


# Module-level default instance, bound to the real db accessors. Tests inject
# their own ReadCache instances or reset the module one.
_read_cache = ReadCache()


def get_read_cache() -> ReadCache:
    """Return the module-level read cache (injectable in tests)."""
    return _read_cache


def reset_read_cache() -> None:
    """Drop the module-level cache state (test/restart seam)."""
    _read_cache.reset()


def get_chain() -> list[dict]:
    """Cached fallback chain for the AI hot path (R1-B)."""
    return _read_cache.get_chain()


def get_cost_profile() -> dict[str, float]:
    """Cached LLM cost profile for the AI hot path (R2-A)."""
    return _read_cache.get_cost_profile()


def invalidate_cost_profile() -> None:
    """Bust the cached cost profile after an admin save."""
    _read_cache.invalidate_cost_profile()
