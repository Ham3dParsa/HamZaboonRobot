import logging
import threading
import time
from collections import deque

from services.ai import ai
from services import db
from services.utils.formatting import CardPreparationError

logger = logging.getLogger(__name__)


class AllPresetsExhausted(Exception):
    """Raised when all enabled AI presets have been tried and none succeeded."""


class AIRequestTimedOut(Exception):
    """Raised when a preset attempt exceeds the caller-provided deadline."""


# Consecutive failures before a preset is temporarily sidelined (backoff), and
# the length of that backoff window. Owner decision (R13): ALL failures count
# (429, connection drop, timeout, etc.), and after the window a preset recovers
# so routing can return to the preferred/highest-priority target.
FAILURE_THRESHOLD = 3
BACKOFF_SECONDS = 60

# Prune-at-most-once-per-hour guard for the R13 hourly-usage window. Pruning
# is a write transaction; on the quota hot path this must not fire on every
# preset per request, so it is throttled to ~1x/hour per process.
_PRUNE_INTERVAL_SECONDS = 3600
_prune_lock = threading.Lock()
_last_hourly_prune: float = 0.0


def _maybe_prune_hourly_usage():
    """Run the R13 prune at most once per hour per process."""
    global _last_hourly_prune
    now = time.monotonic()
    if now - _last_hourly_prune < _PRUNE_INTERVAL_SECONDS:
        return
    with _prune_lock:
        if now - _last_hourly_prune >= _PRUNE_INTERVAL_SECONDS:
            db.prune_preset_hourly_usage(hours_back=24)
            _last_hourly_prune = now


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
            "backoff_until": 0.0,
        }
    return _get_limiter_for_preset._states[key]


def _preset_in_backoff(limiter: dict, now: float | None = None) -> bool:
    """True while a preset is temporarily sidelined after a failure streak."""
    if now is None:
        now = time.monotonic()
    return bool(limiter["backoff_until"]) and now < limiter["backoff_until"]


def _is_daily_exhausted(preset: dict) -> bool:
    """Check if a preset has reached its 24h request cap (RPD, owner-fixed scope).

    Counts only successful provider calls (usage is recorded only on success),
    prunes rows older than the 24h window first so stale data can't wrongly hold
    the cap open or closed, and performs the read + cap decision atomically.
    """
    max_daily = preset.get("max_daily_req", 0)
    if max_daily <= 0:
        return False
    _maybe_prune_hourly_usage()
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
    chain = db.get_fallback_chain_presets()
    if not chain:
        raise AllPresetsExhausted("No enabled presets available")

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

        if _is_preset_rate_limited(preset):
            if i + 1 < len(chain):
                _log_switch(current_name, chain[i + 1].get("name", "?"), "rate-limited")
            logger.info("Skipping rate-limited preset: %s", current_name)
            continue

        limiter = _get_limiter_for_preset(preset)
        if not limiter["slots"].acquire(timeout=30):
            if i + 1 < len(chain):
                _log_switch(current_name, chain[i + 1].get("name", "?"), "concurrency slot timeout (30s)")
            continue

        try:
            while True:
                _raise_if_deadline_exceeded()
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
            limiter["backoff_until"] = 0.0
            _log_preset_usage(preset, result)
            return result

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
            limiter["slots"].release()

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
    primary_name = db.get_setting("ai_primary_preset", db.get_active_preset_name())
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
        timeout=preset.get("timeout_seconds", 30.0),
    )
    if result["success"]:
        db.set_bool_setting("ai_fallback_active", False)
        db.set_setting("ai_fallback_since", "")
        logger.info("Primary preset %s restored via periodic retry", primary_name)
    else:
        logger.info("Primary preset %s retry failed: %s", primary_name, result.get("error_message", "unknown"))
