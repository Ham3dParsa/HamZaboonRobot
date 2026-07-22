import logging
import threading
import time
from collections import deque

from services.ai import ai
from services.ai import ai_presets
from services import db
from services.utils.formatting import CardPreparationError

logger = logging.getLogger(__name__)


class AllPresetsExhausted(Exception):
    """Raised when all enabled AI presets have been tried and none succeeded."""


def _get_active_preset() -> dict:
    """Get the currently active AI preset (considers fallback)."""
    return db.get_active_preset()


def _get_limiter_for_preset(preset: dict):
    """Create or reuse limiter state for a preset."""
    key = preset.get("name", "default")
    if not hasattr(_get_limiter_for_preset, "_states"):
        _get_limiter_for_preset._states = {}
    if key not in _get_limiter_for_preset._states:
        _get_limiter_for_preset._states[key] = {
            "slots": threading.BoundedSemaphore(preset.get("max_concurrency", 2)),
            "request_times": deque(),
            "request_lock": threading.Lock(),
            "token_times": deque(),
            "token_lock": threading.Lock(),
            "consecutive_failures": 0,
        }
    return _get_limiter_for_preset._states[key]


def _is_daily_exhausted(preset: dict) -> bool:
    """Check if a preset has reached its daily request cap."""
    max_daily = preset.get("max_daily_req", 0)
    if max_daily <= 0:
        return False
    req_count, _ = db.get_hourly_usage(preset["name"], hours_back=24)
    return req_count >= max_daily


def _is_preset_rate_limited(preset: dict) -> bool:
    """Check if a preset is currently rate-limited (RPM, TPM, or daily cap)."""
    limiter = _get_limiter_for_preset(preset)
    now = time.monotonic()
    max_rpm = preset.get("max_rpm", 30)
    max_tpm = preset.get("max_tpm", 0)
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
    if _is_daily_exhausted(preset):
        return True
    return False


def _log_preset_usage(preset: dict, result):
    """Record usage for a preset after a successful request."""
    telemetry = getattr(result, "_telemetry", {}) if hasattr(result, "_telemetry") else {}
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


def _call_ai_limited(function, *args, **kwargs):
    """Execute an AI function with automatic fallback across the preset chain.

    For each preset in the chain (ordered by priority):
      1. Skip if rate-limited (RPM/TPM/daily)
      2. Acquire concurrency slot
      3. Wait for RPM slot
      4. Execute the function with this preset
      5. On RateLimitError: skip to next preset
      6. On other error: increment failures; skip if threshold reached
      7. On success: record usage, return result
    """
    chain = db.get_enabled_presets_ordered()
    if not chain:
        raise AllPresetsExhausted("No enabled presets available")

    last_error: Exception | None = None
    for preset in chain:
        if _is_preset_rate_limited(preset):
            logger.info("Skipping rate-limited preset: %s", preset.get("name"))
            continue

        limiter = _get_limiter_for_preset(preset)
        if not limiter["slots"].acquire(timeout=30):
            continue
        try:
            while True:
                now = time.monotonic()
                with limiter["request_lock"]:
                    while limiter["request_times"] and now - limiter["request_times"][0] >= 60:
                        limiter["request_times"].popleft()
                    if len(limiter["request_times"]) < preset.get("max_rpm", 30):
                        limiter["request_times"].append(now)
                        break
                time.sleep(0.25)

            result = function(*args, preset=preset, **kwargs)

            limiter["consecutive_failures"] = 0
            _log_preset_usage(preset, result)
            return result

        except ai.RateLimitError as exc:
            logger.warning("Preset %s rate-limited (429), skipping: %s", preset.get("name"), exc)
            last_error = exc
            continue

        except Exception as exc:
            limiter["consecutive_failures"] += 1
            last_error = exc
            if limiter["consecutive_failures"] >= 2:
                logger.warning("Preset %s failed consecutively, skipping: %s", preset.get("name"), exc)
                continue
            raise

        finally:
            limiter["slots"].release()

    raise AllPresetsExhausted(
        f"All enabled presets exhausted. Last error: {last_error}" if last_error
        else "All enabled presets exhausted"
    )


def _ask_batch_limited(*args, **kwargs):
    return _call_ai_limited(ai.ask_batch, *args, **kwargs)


def _prepare_cached_card(card, *, lang, user_id, plan, source, persist_patch):
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
    primary_name = db.get_setting("ai_primary_preset", db.get_active_preset_name())
    preset = db.get_preset(primary_name)
    if not preset:
        logger.warning("Primary preset %s not found for retry", primary_name)
        return
    api_key = ai_presets.resolve_api_key(preset)
    if not api_key:
        logger.warning("No API key for primary preset %s, skipping retry", primary_name)
        return
    result = ai.test_connection(
        base_url=preset.get("base_url", ""),
        api_key=api_key,
        model=preset.get("model", ""),
        timeout=preset.get("timeout_seconds", 30.0),
    )
    if result["success"]:
        db.set_bool_setting("ai_fallback_active", False)
        db.set_setting("ai_fallback_since", "")
        logger.info("Primary preset %s restored via periodic retry", primary_name)
    else:
        logger.info("Primary preset %s retry failed: %s", primary_name, result.get("error_message", "unknown"))
