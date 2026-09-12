import logging
import time

from services.ai import ai, ai_read_cache, limiter, preset_fields
from services import db
from services.utils.formatting import CardPreparationError

logger = logging.getLogger(__name__)


class AllPresetsExhausted(Exception):
    """Raised when all enabled AI presets have been tried and none succeeded."""


class AIRequestTimedOut(Exception):
    """Raised when a preset attempt exceeds the caller-provided deadline."""


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


def _get_active_preset() -> dict:
    """Get the currently active AI preset (considers fallback)."""
    return db.get_active_preset()


# NOTE (REF5-T4): _get_limiter_for_preset + _preset_in_backoff moved verbatim
# to services/ai/limiter.py; llm_services.* remain as thin re-export aliases.


def _is_daily_exhausted(preset: dict, usage_map: dict[str, tuple[int, int]] | None = None) -> bool:
    """Check if a preset has reached its 24h request cap (RPD, owner-fixed scope).

    Counts only successful provider calls (usage is recorded only on success),
    prunes rows older than the 24h window first so stale data can't wrongly hold
    the cap open or closed, and performs the read + cap decision atomically.

    ``usage_map`` is the batched result of ``get_hourly_usage_many`` computed
    once per AI call (BOT-3); when absent it falls back to the single-preset
    read so standalone callers keep working unchanged.
    """
    max_daily = preset_fields.resolve(preset, "max_daily_req")
    if max_daily <= 0:
        return False
    _maybe_prune_hourly_usage()
    if usage_map is not None:
        req_count = usage_map.get(preset["name"], (0, 0))[0]
    else:
        req_count, _ = db.get_hourly_usage(preset["name"], hours_back=24)
    return req_count >= max_daily


def _is_preset_rate_limited(preset: dict, usage_map: dict[str, tuple[int, int]] | None = None) -> bool:
    """Check if a preset is currently rate-limited (RPM, TPM, or daily cap).

    RPM/TPM limits are read lazily from the preset on each call so admin edits
    apply immediately (BUG-5).
    """
    limiter = _get_limiter_for_preset(preset)
    now = time.monotonic()
    max_rpm = _limiter_store._max_rpm(preset)
    max_tpm = _limiter_store._max_tpm(preset)
    # RPM check
    with limiter["request_lock"]:
        while limiter["request_times"] and now - limiter["request_times"][0] >= 60:
            limiter["request_times"].popleft()
        rpm_count = len(limiter["request_times"])
    if rpm_count >= max_rpm:
        return True
    # TPM check
    if max_tpm > 0:
        with limiter["token_lock"]:
            while limiter["token_times"] and now - limiter["token_times"][0][0] >= 60:
                limiter["token_times"].popleft()
            tpm_count = sum(tc for _, tc in limiter["token_times"])
        if tpm_count >= max_tpm:
            return True
    # Daily cap check
    if _is_daily_exhausted(preset, usage_map=usage_map):
        return True
    return False


def _log_preset_usage(preset: dict, result):
    """Record usage for a preset after a successful request.

    Reads real token usage from the ``TrackedResult`` telemetry (BUG-1), so
    ``token_count`` is the actual provider usage rather than always 0 and the
    TPM cap is enforced.
    """
    telemetry = result.telemetry if isinstance(result, ai.TrackedResult) else {}
    total_tokens = 0
    usage = telemetry.get("usage")
    if usage:
        total_tokens = getattr(usage, "total_tokens", 0) or 0
    hour_bucket = time.strftime("%Y-%m-%dT%H:00:00", time.gmtime())
    db.increment_hourly_usage(preset["name"], hour_bucket, req_count=1, token_count=total_tokens)
    # Track TPM in-memory
    if total_tokens > 0:
        limiter = _get_limiter_for_preset(preset)
        with limiter["token_lock"]:
            limiter["token_times"].append((time.monotonic(), total_tokens))


def _call_ai_limited(function, *args, deadline=None, **kwargs):
    """Execute an AI function with automatic fallback across the preset chain.

    For each preset in the chain (ordered by priority):
      1. Skip if rate-limited (RPM/TPM/daily)
      2. Acquire concurrency slot
      3. Wait for RPM slot
      4. Execute the function with this preset
      5. On RateLimitError: skip to next preset
      6. On other error: increment failures; skip if threshold reached
      7. On success: record usage, return result

    `deadline` is a `time.monotonic()` timestamp. When set, the function
    aborts with `AIRequestTimedOut` once the deadline passes instead of
    waiting indefinitely (e.g. inside the RPM wait loop), so abandoned
    threads cannot pin executor workers for long.

    Logs preset-to-preset switches at WARNING level with the reason.
    """
    chain = ai_read_cache.get_chain()
    if not chain:
        raise AllPresetsExhausted("No enabled presets available")
    # One batched usage read covers the whole chain (BOT-3): the daily-cap check
    # below evaluates each preset against this single result instead of issuing
    # one query per preset tried.
    usage_map = db.get_hourly_usage_many([p.get("name", "?") for p in chain], hours_back=24)

    def _raise_if_deadline_exceeded():
        if deadline is not None and time.monotonic() >= deadline:
            raise AIRequestTimedOut("AI request exceeded caller deadline")

    def _log_switch(from_name: str, to_name: str, reason: str):
        logger.warning("Preset switch: %s → %s (reason: %s)", from_name, to_name, reason)

    last_error: Exception | None = None
    for i, preset in enumerate(chain):
        current_name = preset.get("name", "?")

        _raise_if_deadline_exceeded()

        limiter = _get_limiter_for_preset(preset)
        if _preset_in_backoff(limiter):
            if i + 1 < len(chain):
                _log_switch(current_name, chain[i + 1].get("name", "?"), "temporary backoff")
            logger.info("Skipping preset in backoff: %s", current_name)
            continue

        if _is_preset_rate_limited(preset, usage_map=usage_map):
            if i + 1 < len(chain):
                _log_switch(current_name, chain[i + 1].get("name", "?"), "rate-limited")
            logger.info("Skipping rate-limited preset: %s", current_name)
            continue

        limiter = _get_limiter_for_preset(preset)
        # Capture the semaphore instance we actually acquire so an admin edit
        # that rebuilds the limiter's semaphore mid-flight cannot make the
        # finally-block release a different (never-acquired) semaphore.
        slot = limiter["slots"]
        if not slot.acquire(timeout=30):
            if i + 1 < len(chain):
                _log_switch(current_name, chain[i + 1].get("name", "?"), "concurrency slot timeout (30s)")
            continue
        limiter["in_flight"] += 1

        try:
            while True:
                _raise_if_deadline_exceeded()
                now = time.monotonic()
                with limiter["request_lock"]:
                    while limiter["request_times"] and now - limiter["request_times"][0] >= 60:
                        limiter["request_times"].popleft()
                    if len(limiter["request_times"]) < _limiter_store._max_rpm(preset):
                        limiter["request_times"].append(now)
                        break
                time.sleep(0.25)

            result = function(*args, preset=preset, **kwargs)

            limiter["consecutive_failures"] = 0
            limiter["backoff_until"] = 0.0
            _log_preset_usage(preset, result)
            value = result.value if isinstance(result, ai.TrackedResult) else result
            return value

        except AIRequestTimedOut:
            raise

        except Exception as exc:
            limiter["consecutive_failures"] += 1
            last_error = exc
            if limiter["consecutive_failures"] >= FAILURE_THRESHOLD:
                limiter["backoff_until"] = time.monotonic() + BACKOFF_SECONDS
                limiter["consecutive_failures"] = 0
                logger.warning(
                    "Preset %s reached %d failures, sidelined for %ds: %s",
                    current_name, FAILURE_THRESHOLD, BACKOFF_SECONDS, exc,
                )
            if i + 1 < len(chain):
                _log_switch(current_name, chain[i + 1].get("name", "?"), f"failure: {exc}")
            continue

        finally:
            limiter["in_flight"] = max(0, limiter["in_flight"] - 1)
            slot.release()

    if last_error is not None:
        raise AllPresetsExhausted(
            f"All enabled presets exhausted. Last error: {last_error}"
        ) from last_error
    raise AllPresetsExhausted("All enabled presets exhausted")


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


def _retry_primary_preset():
    """Try primary preset connection and restore if it succeeds while fallback is active."""
    if not db.get_bool_setting("ai_fallback_active", False):
        return
    primary_name = db.get_setting("ai_primary_preset", "") or db.get_active_preset_name()
    preset = db.get_preset(primary_name)
    if not preset:
        logger.warning("Primary preset %s not found for retry", primary_name)
        return
    api_key = db.resolve_preset_key(preset)
    if not api_key:
        logger.warning("No API key for primary preset %s, skipping retry", primary_name)
        return
    result = ai.test_connection(
        base_url=preset.get("base_url", ""),
        api_key=api_key,
        model=preset.get("model", ""),
        timeout=preset_fields.resolve(preset, "timeout_seconds"),
        reasoning_effort=preset_fields.resolve(preset, "reasoning_effort"),
    )
    if result["success"]:
        db.set_bool_setting("ai_fallback_active", False)
        db.set_setting("ai_fallback_since", "")
        logger.info("Primary preset %s restored via periodic retry", primary_name)
    else:
        logger.info("Primary preset %s retry failed: %s", primary_name, result.get("error_message", "unknown"))
