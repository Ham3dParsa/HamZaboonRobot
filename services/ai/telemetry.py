"""Tracked LLM-request telemetry for AI provider calls (REF5-T3).

Verbatim home of ``_log_llm_request``, ``_call_tracked`` and ``TrackedResult``
previously defined in ``services/ai/ai.py``. This module owns the
fn-to-value-to-``TrackedResult`` shape, the ``finally`` writer, the model
fallback, the billed/zero-cost classification and the ``log_target`` seam;
``services/ai/ai.py`` keeps thin re-export aliases so existing callers keep
working unchanged.

Cost discipline: the per-request cost is resolved preset-dict-first from the
preset already in hand, falling back to the cached LLM cost profile. The
cost-resolver itself is NOT merged here (REF5-T5 scope — don't rewire).
Zero AI-volume delta: no prompts, no new provider calls, timeouts untouched.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from config import COST
from services import db
from services.ai import ai_read_cache

log = logging.getLogger(__name__)


_COST_OUTCOME_ICON = {
    "success": "✓",
    "failure_billed": "✕",
    "failure_zero_cost": "⚪",
}


def _log_llm_request(
    *,
    request_kind: str,
    user_id: int | None,
    plan: str | None,
    model: str,
    telemetry: dict[str, object],
    outcome: str,
    preset: dict | None = None,
    error: Exception | None = None,
):
    usage = telemetry.get("usage")
    latency_ms = telemetry.get("latency_ms")
    latency_value = round(float(latency_ms)) if isinstance(latency_ms, (int, float)) else None
    if usage is None:
        prompt_tokens = completion_tokens = total_tokens = None
    else:
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)

    preset_name = preset.get("name", "?") if preset else "?"

    # Resolve cost per-million from the preset dict already in hand (it came
    # from the chain/active read, so no re-query), falling back to the global
    # profile. The profile read is served from a TTL cache (BOT-2) invalidated
    # on admin save. Preset-level cost edits via admin_ai take effect at the
    # chain TTL (~10s); the profile fallback is invalidated instantly.
    if preset:
        input_cost = preset.get("input_cost_per_million")
        output_cost = preset.get("output_cost_per_million")
    else:
        input_cost = None
        output_cost = None

    profile = ai_read_cache.get_cost_profile()
    input_cost_per_million = input_cost if input_cost is not None else profile["input_cost_usd_per_million"]
    output_cost_per_million = output_cost if output_cost is not None else profile["output_cost_usd_per_million"]

    if prompt_tokens and completion_tokens:
        cost_usd = (
            prompt_tokens * input_cost_per_million
            + completion_tokens * output_cost_per_million
        ) / 1_000_000
    else:
        cost_usd = 0.0
    outcome_icon = _COST_OUTCOME_ICON.get(outcome, "?")
    outcome_label = f"{outcome_icon} {outcome.removeprefix('failure_').removeprefix('billed_') if outcome.startswith('failure') else outcome}"
    tokens_str = f"{total_tokens} tok" if total_tokens is not None else "———"
    cost_str = f"${cost_usd:.6f}" if cost_usd > 0 else "———"

    log.log(
        COST,
        "kind=%s user=%s preset=%s outcome=%s tokens=%s latency=%sms cost=%s",
        request_kind,
        str(user_id or "?"),
        preset_name,
        outcome_label,
        tokens_str,
        latency_value if latency_value is not None else "?",
        cost_str,
    )

    batch_validation = telemetry.get("batch_validation")
    if isinstance(batch_validation, dict):
        log.log(
            COST,
            "batch validation: received=%-4s accepted=%-4s rejected=%-4s "
            "duplicates=%-3s avoid_dup=%-3s batch_dup=%-3s avoid_words=%-3s",
            batch_validation.get("received", 0),
            batch_validation.get("accepted", 0),
            batch_validation.get("validation_rejected", 0),
            batch_validation.get("duplicates", 0),
            batch_validation.get("duplicates_against_avoid", 0),
            batch_validation.get("duplicates_within_batch", 0),
            batch_validation.get("avoid_words", 0),
        )
    rejection_reasons = telemetry.get("batch_validation_reasons")
    if isinstance(rejection_reasons, dict) and rejection_reasons:
        log.log(
            COST,
            "rejection reasons: kind=%s reasons=%s",
            request_kind,
            rejection_reasons,
        )

    db.add_llm_request(
        user_id=user_id or 0,
        plan=plan or "unknown",
        request_kind=request_kind,
        model=model,
        outcome=outcome,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        input_cost_usd_per_million=input_cost_per_million,
        output_cost_usd_per_million=output_cost_per_million,
        usd_to_toman_rate=profile["usd_to_toman_rate"],
        latency_ms=latency_value,
        error_class=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
        preset_name=preset_name,
    )


def _call_tracked(
    fn,
    *,
    request_kind: str,
    user_id: int | None = None,
    plan: str | None = None,
    preset: dict | None = None,
    log_target: Callable[..., None] | None = None,
):
    """Run a tracked AI call, owning the telemetry/error/outcome lifecycle.

    ``fn(telemetry)`` must describe the request, perform the model call
    (populating ``telemetry``), and return the validated value. On any
    exception the error is captured and re-raised; the ``finally`` block logs
    the request and classifies the cost outcome (success vs billed vs
    zero-cost) based on whether ``usage`` was recorded.

    ``log_target`` overrides where the request record is written. It defaults
    to ``_log_llm_request`` (the ``llm_requests`` table); a test-only caller
    may pass a different writer (e.g. to the ``config_tests`` table) so that
    throwaway/test calls do not pollute the cost dashboard.

    Returns a ``TrackedResult`` wrapping the value and the telemetry so the
    AI limiter can read real token usage (BUG-1). Callers that do not need the
    telemetry read ``.value``.
    """
    telemetry: dict[str, object] = {}
    error: Exception | None = None
    writer = log_target if log_target is not None else _log_llm_request
    try:
        value = fn(telemetry)
    except Exception as exc:
        error = exc
        raise
    finally:
        # Lazy import: _model lives in services.ai.ai (which re-exports this
        # module), so a top-level import would cycle. Resolved per call so a
        # test patch on ai._model still takes effect.
        from services.ai.ai import _model as _resolve_model

        writer(
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            model=str(telemetry.get("model") or _resolve_model(preset)),
            telemetry=telemetry,
            outcome="success" if error is None else (
                "failure_billed" if telemetry.get("usage") is not None else "failure_zero_cost"
            ),
            preset=preset,
            error=error,
        )
    return TrackedResult(value=value, telemetry=telemetry)


@dataclass
class TrackedResult:
    """Return value of a tracked AI call, carrying its telemetry.

    The limiter reads ``.telemetry`` to apply real TPM enforcement (BUG-1) and
    unwraps ``.value`` before handing the result to callers, so the public
    functions keep returning their plain dict/list value to callers while the
    token usage stays visible to the quota layer.
    """

    value: object
    telemetry: dict[str, object] = field(default_factory=dict)
