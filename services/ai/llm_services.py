import logging

from services.ai import ai, ai_read_cache, fallback_router, limiter
from services import db
from services.utils.formatting_cards import CardPreparationError

logger = logging.getLogger(__name__)


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
# aliases (see above). _ask_batch_limited + _prepare_cached_card stay here
# until REF5-T7 (generation) places them.


def _get_active_preset() -> dict:
    """Get the currently active AI preset (considers fallback)."""
    return db.get_active_preset()


# NOTE (REF5-T4): _get_limiter_for_preset + _preset_in_backoff moved verbatim
# to services/ai/limiter.py; llm_services.* remain as thin re-export aliases.


def _ask_batch_limited(*args, **kwargs):
    return _call_ai_limited(ai.ask_batch, *args, **kwargs)


def _prepare_cached_card(card, *, lang, user_id, plan, source, persist_patch, deadline=None):
    try:
        return ai.validate_card(card)
    except ai.CardValidationError as validation_error:
        fields = ai.card_repair_fields(card)
        if not fields:
            raise CardPreparationError(
                f"{source} card has no repairable fields"
            ) from validation_error
        try:
            patch = _call_ai_limited(
                ai.repair_card,
                card,
                fields,
                lang,
                user_id=user_id,
                plan=plan,
                deadline=deadline,
            )
            merged = dict(card) if isinstance(card, dict) else {}
            merged.update(patch)
            repaired = ai.validate_card(merged)
            if not persist_patch(patch):
                raise CardPreparationError(
                    f"{source} card repair could not be persisted"
                )
            logger.info(
                "cached card repaired source=%s user_id=%s fields=%s",
                source,
                user_id,
                fields,
            )
            return repaired
        except Exception as repair_error:
            logger.exception(
                "cached card repair failed source=%s user_id=%s fields=%s",
                source,
                user_id,
                fields,
            )
            raise CardPreparationError(
                f"{source} card could not be repaired safely"
            ) from repair_error
