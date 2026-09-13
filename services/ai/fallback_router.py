"""AI fallback router: chain routing with rate/daily guards (REF5-T6).

Verbatim home of ``_call_ai_limited`` (+ the rate/daily checks
``_is_daily_exhausted``, ``_is_preset_rate_limited``, ``_log_preset_usage``),
``_retry_primary_preset`` (with the lazy primary-name fix) and the
``AllPresetsExhausted`` / ``AIRequestTimedOut`` chain, previously defined in
``services/ai/llm_services.py``. ``services/ai/llm_services.py`` keeps thin
re-export aliases so existing callers (bot.py, tests) keep working unchanged.

Frozen seams (consumed, never moved here):
- Limiter (REF5-T4): ``services/ai/limiter.py`` owns the sync
  ``BoundedSemaphore`` slots, ``in_flight``, the swap guard, ``reset()``, the
  ~1x/hour prune throttle and the backoff predicate.
- Chain/cost (REF5-T5): ``services/ai/ai_read_cache.py`` owns the cached
  fallback chain; ``services/ai/cost_resolver.py`` owns cost resolution.

Routing contract (owner-locked, byte-identical):
- Chain + single ``usage_map`` (BOT-3: one batched usage read per call, never
  one query per preset) + backoff skip + caller ``deadline`` + slot ``finally``
  + ``AllPresetsExhausted`` chaining the last error.
- Owner decision (R13): ALL failures count toward the streak (no per-error
  backoff reset); after the window a preset recovers to the preferred target.
- Volume unchanged: reorder across presets, never an extra retry.

Zero AI-volume delta: no prompts, no new provider calls, timeouts untouched.
"""

import logging
import time

from services import db
from services.ai import ai, ai_read_cache, preset_fields
from services.ai.limiter import (
    FAILURE_THRESHOLD,
    BACKOFF_SECONDS,
    _get_limiter_for_preset,
    _limiter_store,
    _maybe_prune_hourly_usage,
    _preset_in_backoff,
)

logger = logging.getLogger(__name__)


class AllPresetsExhausted(Exception):
    """Raised when all enabled AI presets have been tried and none succeeded."""


class AIRequestTimedOut(Exception):
    """Raised when a preset attempt exceeds the caller-provided deadline."""


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
