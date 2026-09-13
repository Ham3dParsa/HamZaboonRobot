from services.ai import ai, ai_read_cache, fallback_router, generation, limiter
from services import db


# REF5-T4: sync limiter state lives in limiter.py (verbatim move of the
# constants + LimiterStore with its swap guard/reset seam + the module store
# + _maybe_prune_hourly_usage + _get_limiter_for_preset + _preset_in_backoff;
# stay-sync: BoundedSemaphore + in_flight + deadline + slot capture, no async
# rewrite). The names below are re-export aliases so existing callers keep
# working unchanged; the canonical definitions were removed from this module
# in the same change.
FAILURE_THRESHOLD = limiter.FAILURE_THRESHOLD
BACKOFF_SECONDS = limiter.BACKOFF_SECONDS
_PRUNE_INTERVAL_SECONDS = limiter._PRUNE_INTERVAL_SECONDS
_prune_lock = limiter._prune_lock
LimiterStore = limiter.LimiterStore
_limiter_store = limiter._limiter_store
get_limiter_store = limiter.get_limiter_store
_maybe_prune_hourly_usage = limiter._maybe_prune_hourly_usage
_get_limiter_for_preset = limiter._get_limiter_for_preset
_preset_in_backoff = limiter._preset_in_backoff

# NOTE (REF5-T4): LimiterStore + prune throttle + backoff predicate moved
# verbatim to services/ai/limiter.py; llm_services.* remain as thin re-export
# aliases (see above). The mutable prune clock (_last_hourly_prune) is owned
# ONLY by limiter (no value-copy here — a copy would go stale on reassign);
# callers must read/write limiter._last_hourly_prune.


# REF5-T6: fallback routing lives in fallback_router.py (verbatim move of
# AllPresetsExhausted + AIRequestTimedOut + _is_daily_exhausted +
# _is_preset_rate_limited + _log_preset_usage + _call_ai_limited +
# _retry_primary_preset as one unit — chain + single usage_map BOT-3 +
# backoff skip + deadline + slot finally + AllPresetsExhausted chain,
# including the lazy primary-name fix; the frozen limiter (T4) + chain/cost
# (T5) seams are consumed, not moved). The names below are re-export aliases
# so existing callers keep working unchanged; the canonical definitions were
# removed from this module in the same change.
AllPresetsExhausted = fallback_router.AllPresetsExhausted
AIRequestTimedOut = fallback_router.AIRequestTimedOut
_is_daily_exhausted = fallback_router._is_daily_exhausted
_is_preset_rate_limited = fallback_router._is_preset_rate_limited
_log_preset_usage = fallback_router._log_preset_usage
_call_ai_limited = fallback_router._call_ai_limited
_retry_primary_preset = fallback_router._retry_primary_preset

# NOTE (REF5-T6): the router unit moved verbatim to
# services/ai/fallback_router.py; llm_services.* remain as thin re-export
# aliases (see above). _ask_batch_limited + _prepare_cached_card moved to
# generation.py under REF5-T7 (see below).


# REF5-T7: card generation lives in generation.py (verbatim move of
# _get_active_preset + _ask_batch_limited + _prepare_cached_card as one unit —
# validate -> repair -> merge -> revalidate -> persist order, 3
# CardPreparationError paths, dict(card) merge copy; the router seam
# (_call_ai_limited) is consumed from fallback_router, not moved;
# _retry_primary_preset stays owned by fallback_router (T6)). The names below
# are re-export aliases so existing callers keep working unchanged; the
# canonical definitions were removed from this module in the same change.
_get_active_preset = generation._get_active_preset
_ask_batch_limited = generation._ask_batch_limited
_prepare_cached_card = generation._prepare_cached_card

# NOTE (REF5-T7): the generation unit moved verbatim to
# services/ai/generation.py; llm_services.* remain as thin re-export aliases
# (see above). llm_services.py now defines zero canonical symbols.
