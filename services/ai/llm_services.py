import logging
import threading
import time
from collections import deque

from services.ai import ai
from services.ai import ai_presets
from services import db
from services.utils.formatting import CardPreparationError

logger = logging.getLogger(__name__)


def _get_active_preset() -> dict:
    """Get the currently active AI preset (considers fallback)."""
    return db.get_active_preset()


def _get_limiter_for_preset(preset: dict):
    """Create or reuse limiter state for a preset."""
    key = preset.get("name", "default")
    # Module-level storage keyed by preset name
    if not hasattr(_get_limiter_for_preset, "_states"):
        _get_limiter_for_preset._states = {}
    if key not in _get_limiter_for_preset._states:
        _get_limiter_for_preset._states[key] = {
            "slots": threading.BoundedSemaphore(preset.get("max_concurrency", 2)),
            "request_times": deque(),
            "request_lock": threading.Lock(),
            "consecutive_failures": 0,
        }
    return _get_limiter_for_preset._states[key]


def _check_fallback_switch(preset: dict) -> bool:
    """Check if we should switch to fallback preset.

    Returns True if switched to fallback, False otherwise.
    """
    state = _get_limiter_for_preset(preset)
    if state["consecutive_failures"] >= 2:
        # Switch to fallback
        if not db.get_bool_setting("ai_fallback_active", False):
            fallback_name = db.get_setting("ai_fallback_preset", "gapgpt")
            db.set_bool_setting("ai_fallback_active", True)
            db.set_setting("ai_fallback_since", db._utc_now().isoformat())
            db.set_setting("ai_consecutive_failures", "0")
            logger.warning(
                "AI fallback activated: primary=%s -> fallback=%s",
                preset.get("name"),
                fallback_name,
            )
            return True
    return False


def _record_success(preset: dict):
    """Record a successful request, reset failure counter."""
    state = _get_limiter_for_preset(preset)
    state["consecutive_failures"] = 0
    # If fallback was active and primary succeeds, restore primary
    if db.get_bool_setting("ai_fallback_active", False):
        # Only restore if this IS the primary preset
        primary_name = db.get_setting("ai_primary_preset", "gapgpt")
        if preset.get("name") == primary_name:
            db.set_bool_setting("ai_fallback_active", False)
            db.set_setting("ai_fallback_since", "")
            logger.info("AI primary restored: %s", primary_name)


def _record_failure(preset: dict):
    """Record a failed request, increment failure counter."""
    state = _get_limiter_for_preset(preset)
    state["consecutive_failures"] += 1
    db.set_setting("ai_consecutive_failures", str(state["consecutive_failures"]))


def _call_ai_limited(function, *args, **kwargs):
    """Execute an AI function with dynamic rate limiting based on active preset."""
    preset = _get_active_preset()
    limiter = _get_limiter_for_preset(preset)

    # Acquire concurrency slot
    limiter["slots"].acquire()
    try:
        # Rate limit (RPM)
        while True:
            now = time.monotonic()
            with limiter["request_lock"]:
                # Remove timestamps older than 60 seconds
                while limiter["request_times"] and now - limiter["request_times"][0] >= 60:
                    limiter["request_times"].popleft()
                if len(limiter["request_times"]) < preset.get("max_rpm", 30):
                    limiter["request_times"].append(now)
                    break
            time.sleep(0.25)

        # Execute the AI call
        result = function(*args, **kwargs)

        # Record success
        _record_success(preset)
        return result

    except Exception as exc:
        # Record failure and check for fallback switch
        _record_failure(preset)
        _check_fallback_switch(preset)
        raise
    finally:
        limiter["slots"].release()


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
    primary_name = db.get_setting("ai_primary_preset", "gapgpt")
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