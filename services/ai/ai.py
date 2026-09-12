import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse as _urlparse

import httpx
from openai import OpenAI

try:
    from openai import DefaultHttpxClient as _HttpxClient  # type: ignore
except ImportError:
    try:
        from openai._httpx2 import Client as _HttpxClient  # type: ignore
    except ImportError:
        _HttpxClient = httpx.Client  # type: ignore

from config import (
    AI_MAX_OUTPUT_TOKENS,
    AI_PROXY_STRICT,
    AI_PROXY_URL,
    AI_TEMPERATURE,
    AI_TIMEOUT_SECONDS,
    COST,
)
from services import db
from services.ai import ai_read_cache, card_validation, preset_fields, prompts, telemetry
from services.ai.json_codec import _extract_json  # REF5-T1 alias: canonical def lives in json_codec.py

log = logging.getLogger(__name__)


# REF5-T2: pure-first split — card validation lives in card_validation.py (a
# stdlib-only leaf that never imports this module). The names below are
# re-export aliases so existing callers keep working unchanged; the canonical
# definitions were removed from this module in the same change.
CardValidationError = card_validation.CardValidationError
BatchValidationError = card_validation.BatchValidationError
_COMPACT_CARD_FIELDS = card_validation._COMPACT_CARD_FIELDS
_PHONETIC_LINE_RE = card_validation._PHONETIC_LINE_RE
normalize_phonetic = card_validation.normalize_phonetic
_expand_card_aliases = card_validation._expand_card_aliases
_required_text = card_validation._required_text
_text_list = card_validation._text_list
_validate_optional_rich_list = card_validation._validate_optional_rich_list
validate_card = card_validation.validate_card
card_repair_fields = card_validation.card_repair_fields
validate_card_patch = card_validation.validate_card_patch
validate_batch = card_validation.validate_batch


def create_client(preset: dict | None = None, *, api_key_override: str | None = None) -> OpenAI:
    """Create an OpenAI client for a preset (defaults to the active preset).

    This is the single seam for constructing an OpenAI client. ``base_url`` and
    ``timeout`` are resolved from the preset row via ``preset_fields.resolve``;
    the model is resolved separately via ``_model``; API keys are resolved
    **only** through ``db.resolve_preset_key(preset)`` (fail-closed — no
    ``settings`` ``ai_base_url``/``ai_api_key``/``ai_model`` fallback, R17).
    The explicit ``api_key_override`` is reserved for admin connection probes
    (``test_connection``) where the caller intentionally supplies credentials;
    it is never inferred. ``_client`` is a thin alias to this seam.
    """
    if preset is None:
        preset = db.get_active_preset()
    base_url = _normalize_base_url(preset_fields.resolve(preset, "base_url"))
    # A falsy override (empty string) is treated as "not provided" so the caller
    # falls through to the fail-closed key resolution instead of sending an
    # explicit empty key (SUGGESTION from review: never bypass resolution with
    # a blank override).
    api_key = (
        api_key_override
        if api_key_override
        else db.resolve_preset_key(preset)
    )
    timeout = preset_fields.resolve(preset, "timeout_seconds")
    # Optional proxy for geoblock bypass (e.g. Hetzner DE -> clean exit).
    # Env-driven (AI_PROXY_URL) only - no per-preset column (keeps single source).
    # Telegram traffic is unaffected (only this OpenAI client uses it).
    http_client = None
    if AI_PROXY_URL:
        try:
            http_client = _HttpxClient(
                proxy=AI_PROXY_URL,
                timeout=httpx.Timeout(timeout),
                trust_env=False,
            )
        except (httpx.ProxyError, httpx.InvalidURL, ImportError) as exc:
            # Narrow: only proxy/URL/import errors. Fallback to direct is intentional
            # to avoid total outage when proxy is temporarily bad, but emit error-level
            # so operator knows geoblock bypass is off. Strict mode fails fast.
            try:
                _p = _urlparse(AI_PROXY_URL)
                _redacted = f"{_p.scheme}://{_p.hostname or '?'}:{_p.port or ''}".rstrip(":")
            except Exception:
                _redacted = "<invalid proxy>"
            log.error(
                "AI_PROXY_URL %s invalid (%s), falling back to direct (geoblock bypass disabled)",
                _redacted,
                type(exc).__name__,
            )
            if AI_PROXY_STRICT:
                raise
        except Exception as exc:
            # Unexpected bug during proxy setup - fail-fast after redacted log
            try:
                _p = _urlparse(AI_PROXY_URL)
                _redacted = f"{_p.scheme}://{_p.hostname or '?'}:{_p.port or ''}".rstrip(":")
            except Exception:
                _redacted = "<invalid proxy>"
            log.error(
                "AI_PROXY_URL %s unexpected error (%s), failing AI call",
                _redacted,
                type(exc).__name__,
            )
            raise

    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        http_client=http_client,
    )


def _client(preset: dict | None = None) -> OpenAI:
    """Thin compatibility alias delegating to the single ``create_client`` seam."""
    return create_client(preset)


def _model(preset: dict | None = None) -> str:
    if preset is None:
        preset = db.get_active_preset()
    # R17: the preset row is the single source of truth; the legacy flat
    # settings copy (ai_model/ai_base_url/ai_api_key) is no longer written by
    # activate_preset and must not be read as a fallback. R2: no env-model
    # fallback - an empty model is returned as-is so the absence surfaces as
    # an explicit provider/validation error (never a silent invented call).
    model = preset_fields.resolve(preset, "model") if preset else ""
    # Strip opencode/ prefix if present (Zen API expects raw id)
    if model.startswith("opencode/"):
        model = model[len("opencode/") :]
    return model


def _is_responses_preset(preset: dict | None, model: str | None = None) -> bool:
    """True if this preset must use OpenAI Responses API (Muse/GPT on Zen)."""
    if preset is None and model is None:
        return False
    base = ""
    m = model or ""
    if preset is not None:
        base = preset_fields.resolve(preset, "base_url") or ""
        if not m:
            m = preset_fields.resolve(preset, "model") or ""
    base_l = base.lower().strip()
    m_l = m.lower().strip()
    # Explicit /responses base always means responses (path segment)
    if base_l.rstrip("/").lower().endswith("/responses"):
        return True
    # Muse Spark and GPT on Zen are always responses (chat/completions 404s); require Zen base
    if "opencode.ai/zen" in base_l and ("muse-spark" in m_l or "gpt-" in m_l):
        # Exclude Groq gpt-oss which is not Zen (base would be groq, not zen)
        return True
    return False


def _normalize_base_url(base_url: str) -> str:
    """Strip trailing /responses so OpenAI SDK doesn't double-append."""
    b = (base_url or "").strip().rstrip("/")
    if b.lower().endswith("/responses"):
        b = b[: -len("/responses")].rstrip("/")
    return b


def test_connection(
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = AI_TIMEOUT_SECONDS,
    reasoning_effort: str | None = None,
) -> dict:
    """Lightweight connection test (not tracked in llm_requests).

    Routes client construction through ``create_client`` so the connection
    probe shares the same fail-closed/key-resolution seam (BUG-3). The
    ``api_key`` here is the explicit override the caller intends to test.
    Auto-routes Muse/GPT on Zen to Responses API (same base_url).
    Mirrors preset reasoning (none -> minimal for Muse) so probe doesn't
    hide a real xhigh 400.
    """
    # Strip opencode/ prefix for API
    if model.startswith("opencode/"):
        model = model[len("opencode/") :]
    tmp_preset = {"base_url": base_url, "model": model}
    use_responses = _is_responses_preset(tmp_preset, model)
    # Mirror preset reasoning for Muse; default none->minimal for probe
    probe_reasoning = reasoning_effort
    if use_responses and "muse-spark" in model.lower() and probe_reasoning in (None, "", "none"):
        probe_reasoning = "minimal"
    if probe_reasoning is None:
        probe_reasoning = "minimal" if use_responses and "muse-spark" in model.lower() else None
    client = create_client(
        {"base_url": base_url, "model": model, "timeout_seconds": timeout},
        api_key_override=api_key,
    )
    started = time.monotonic()
    try:
        if use_responses:
            # Reasoning models need headroom: 5 tokens always 500s (reasoning alone exceeds it)
            resp_kwargs: dict = dict(model=model, input="ping", max_output_tokens=64)
            if probe_reasoning not in (None, "", "none"):
                resp_kwargs["reasoning"] = {"effort": probe_reasoning}
            resp = client.responses.create(**resp_kwargs)
            latency_ms = (time.monotonic() - started) * 1000
            # Responses usage shape differs; try to extract
            usage = getattr(resp, "usage", None)
            return {
                "success": True,
                "latency_ms": round(latency_ms),
                "model": getattr(resp, "model", model),
                "usage": {
                    "prompt_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
                    "completion_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
                },
            }
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        latency_ms = (time.monotonic() - started) * 1000
        return {
            "success": True,
            "latency_ms": round(latency_ms),
            "model": resp.model,
            "usage": {
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                "total_tokens": resp.usage.total_tokens if resp.usage else 0,
            },
        }
    except Exception as exc:
        latency_ms = (time.monotonic() - started) * 1000
        # Log full cause at ERROR so `diva service logs` shows it even without DEBUG
        try:
            base_host = _urlparse(base_url).hostname or base_url
        except Exception:
            base_host = base_url
        log.error(
            "test_connection failed model=%s base=%s responses=%s err=%s: %s",
            model,
            base_host,
            use_responses,
            type(exc).__name__,
            str(exc)[:500],
        )
        return {
            "success": False,
            "latency_ms": round(latency_ms),
            "error_class": type(exc).__name__,
            "error_message": str(exc)[:500],
        }
    finally:
        try:
            client.close()
        except Exception:
            pass


def custom_test_card(
    system_prompt: str,
    user_prompt: str,
    lang: str,
    goal: str,
    level: str,
    preset: dict | None = None,
    *,
    request_kind: str = "custom_test",
    user_id: int | None = None,
    plan: str | None = None,
) -> dict:
    """Run a real ask_card call for preview/testing.

    Goes through the full validation pipeline. Not tracked in cost dashboard.
    """
    telemetry: dict[str, object] = {}
    error: Exception | None = None
    client = None
    try:
        if preset is None:
            preset = db.get_active_preset()
        client = _client(preset)
        model = _model(preset)
        started = time.monotonic()
        use_responses = _is_responses_preset(preset, model)
        if use_responses:
            reasoning = preset_fields.resolve(preset or {}, "reasoning_effort")
            if "muse-spark" in model.lower() and reasoning in (None, "", "none"):
                reasoning = "minimal"
            kwargs: dict = dict(
                model=model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_output_tokens=preset_fields.resolve(preset or {}, "max_output_tokens"),
            )
            if reasoning not in (None, "", "none"):
                kwargs["reasoning"] = {"effort": reasoning}
            resp = client.responses.create(**kwargs)
            raw_usage = getattr(resp, "usage", None)
            if raw_usage is not None:
                try:
                    pt = getattr(raw_usage, "input_tokens", None)
                    ct = getattr(raw_usage, "output_tokens", None)
                    tt = getattr(raw_usage, "total_tokens", None)
                    if isinstance(raw_usage, dict):
                        pt = raw_usage.get("input_tokens", pt)
                        ct = raw_usage.get("output_tokens", ct)
                        tt = raw_usage.get("total_tokens", tt)
                    class _U2:
                        pass
                    norm2 = _U2()
                    norm2.prompt_tokens = pt or 0
                    norm2.completion_tokens = ct or 0
                    norm2.total_tokens = tt or 0
                    telemetry["usage"] = norm2
                except Exception:
                    telemetry["usage"] = raw_usage
            else:
                telemetry["usage"] = None
            telemetry["latency_ms"] = (time.monotonic() - started) * 1000
            telemetry["model"] = model
            telemetry["request_kind"] = request_kind
            content = getattr(resp, "output_text", None)
            if not content:
                try:
                    content = resp.output[0].content[0].text  # type: ignore
                except Exception:
                    content = ""
            content = content or ""
        else:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=preset_fields.resolve(preset or {}, "temperature"),
                max_tokens=preset_fields.resolve(preset or {}, "max_output_tokens"),
            )
            telemetry["usage"] = resp.usage
            telemetry["latency_ms"] = (time.monotonic() - started) * 1000
            telemetry["model"] = model
            telemetry["request_kind"] = request_kind
            content = resp.choices[0].message.content or ""
        value = _extract_json(content)
        return validate_card(value)
    except Exception as exc:
        error = exc
        raise
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        # Log to config_tests table instead of llm_requests
        db.log_config_test(
            test_type="custom",
            preset_name=preset.get("name") if preset else db.get_active_preset_name(),
            prompt=user_prompt,
            result={
                "success": error is None,
                "error_class": type(error).__name__ if error else None,
                "error_message": str(error)[:500] if error else None,
            },
        )


# REF5-T3: tracked-request telemetry lives in telemetry.py (verbatim move of
# _log_llm_request + _call_tracked + TrackedResult + _COST_OUTCOME_ICON, a
# leaf that never imports this module at top level — the model fallback uses
# a lazy import). The names below are re-export aliases so existing callers
# keep working unchanged; the canonical definitions were removed from this
# module in the same change.
_COST_OUTCOME_ICON = telemetry._COST_OUTCOME_ICON
_log_llm_request = telemetry._log_llm_request
_call_tracked = telemetry._call_tracked
TrackedResult = telemetry.TrackedResult

# NOTE (REF5-T3): _log_llm_request + _call_tracked moved verbatim to
# services/ai/telemetry.py; ai.* remain as thin re-export aliases (see above).


class RateLimitError(Exception):
    """Raised when an AI provider returns HTTP 429 (rate limited)."""


# NOTE (REF5-T3): TrackedResult moved verbatim to services/ai/telemetry.py;
# ai.TrackedResult remains as a thin re-export alias (see above).


# NOTE (REF5-T1): _extract_json moved verbatim to services/ai/json_codec.py;
# ai._extract_json remains as a thin re-export alias (see top-level import).
# NOTE (REF5-T2): validate_card, card_repair_fields, validate_card_patch,
# validate_batch (+ helpers, alias sets, error types) moved verbatim to
# services/ai/card_validation.py; ai.* remain as thin re-export aliases.


def repair_card(
    card: object,
    fields: list[str],
    lang: str,
    *,
    user_id: int | None = None,
    plan: str | None = None,
    preset: dict | None = None,
) -> TrackedResult:
    def _run(telemetry: dict[str, object]) -> dict:
        value = _request_json(
            prompts.card_repair_system_prompt(lang, card, fields),
            user_prompt="فقط patch حداقلی فیلدهای درخواست‌شده را بساز.",
            request_kind="card_repair",
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
            preset=preset,
        )
        return validate_card_patch(value, fields)

    return _call_tracked(
        _run,
        request_kind="card_repair",
        user_id=user_id,
        plan=plan,
        preset=preset,
    )


def _request_json(
    system_prompt: str,
    user_prompt: str = "بساز.",
    *,
    request_kind: str = "json",
    user_id: int | None = None,
    plan: str | None = None,
    telemetry: dict[str, object] | None = None,
    preset: dict | None = None,
) -> object:
    """یک تماس با مدل زبانی می‌گیرد و انتظار دارد خروجی JSON خام باشد."""
    if preset is None:
        preset = db.get_active_preset()
    client = _client(preset)
    model = _model(preset)
    temp = preset_fields.resolve(preset or {}, "temperature")
    mtokens = preset_fields.resolve(preset or {}, "max_output_tokens")
    reasoning = preset_fields.resolve(preset or {}, "reasoning_effort")
    started = time.monotonic()
    telemetry = telemetry if telemetry is not None else {}
    telemetry["model"] = model
    telemetry["request_kind"] = request_kind
    use_responses = _is_responses_preset(preset, model)
    # Muse Spark is always-thinking; none would 400, so default to minimal
    if use_responses and "muse-spark" in model.lower() and reasoning in (None, "", "none"):
        reasoning = "minimal"
    extra_body = {"reasoning_effort": reasoning} if reasoning not in (None, "", "none") else None
    try:
        try:
            if use_responses:
                # OpenAI Responses API (Zen Muse/GPT) - temperature is not supported for always-thinking models
                kwargs: dict = dict(
                    model=model,
                    input=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_output_tokens=mtokens,
                )
                if reasoning not in (None, "", "none"):
                    kwargs["reasoning"] = {"effort": reasoning}
                resp = client.responses.create(**kwargs)
            else:
                kwargs: dict = dict(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temp,
                    max_tokens=mtokens,
                )
                if extra_body is not None:
                    kwargs["extra_body"] = extra_body
                resp = client.chat.completions.create(**kwargs)
        except Exception as exc:
            if getattr(exc, "status_code", None) == 429 or "RateLimitError" in type(exc).__name__:
                raise RateLimitError(str(exc)) from exc
            raise
        raw_usage = getattr(resp, "usage", None)
        if use_responses and raw_usage is not None:
            # Normalize Responses usage (input/output) to chat shape for cost/limiter
            try:
                pt = getattr(raw_usage, "input_tokens", None)
                ct = getattr(raw_usage, "output_tokens", None)
                tt = getattr(raw_usage, "total_tokens", None)
                if isinstance(raw_usage, dict):
                    pt = raw_usage.get("input_tokens", pt)
                    ct = raw_usage.get("output_tokens", ct)
                    tt = raw_usage.get("total_tokens", tt)
                # Build normalized object with expected attrs
                class _U:
                    pass
                norm = _U()
                norm.prompt_tokens = pt or 0
                norm.completion_tokens = ct or 0
                norm.total_tokens = tt or 0
                telemetry["usage"] = norm
            except Exception:
                telemetry["usage"] = raw_usage
        else:
            telemetry["usage"] = raw_usage
        telemetry["latency_ms"] = (time.monotonic() - started) * 1000
        if use_responses:
            # Responses: output_text or output[0].content[0].text
            content = getattr(resp, "output_text", None)
            if not content:
                try:
                    content = resp.output[0].content[0].text  # type: ignore
                except Exception:
                    content = ""
            content = content or ""
        else:
            content = resp.choices[0].message.content or ""
        try:
            return _extract_json(content)
        except Exception as exc:
            telemetry["error"] = exc
            raise
    finally:
        try:
            client.close()
        except Exception:
            pass


def ask_json(
    system_prompt: str,
    user_prompt: str = "بساز.",
    *,
    request_kind: str = "json",
    user_id: int | None = None,
    plan: str | None = None,
    preset: dict | None = None,
) -> TrackedResult:
    def _run(telemetry: dict[str, object]) -> dict:
        value = _request_json(
            system_prompt,
            user_prompt,
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
            preset=preset,
        )
        if not isinstance(value, Mapping):
            raise CardValidationError("Expected a JSON object")
        return dict(value)

    return _call_tracked(
        _run,
        request_kind=request_kind,
        user_id=user_id,
        plan=plan,
        preset=preset,
    )


def ask_card(
    system_prompt: str,
    user_prompt: str = "بساز.",
    *,
    request_kind: str = "card",
    user_id: int | None = None,
    plan: str | None = None,
    preset: dict | None = None,
) -> TrackedResult:
    def _run(telemetry: dict[str, object]) -> dict:
        value = _request_json(
            system_prompt,
            user_prompt,
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
            preset=preset,
        )
        try:
            return validate_card(value)
        except CardValidationError:
            log.warning("ask_card raw [%s]", json.dumps(value, ensure_ascii=False)[:500])
            raise

    return _call_tracked(
        _run,
        request_kind=request_kind,
        user_id=user_id,
        plan=plan,
        preset=preset,
    )


def ask_batch(
    system_prompt: str,
    expected_count: int,
    used_words: list[str] | None = None,
    *,
    request_kind: str = "batch",
    user_id: int | None = None,
    plan: str | None = None,
    preset: dict | None = None,
) -> TrackedResult:
    def _run(telemetry: dict[str, object]) -> list[dict]:
        diagnostics: dict[str, int] = {}
        rejection_reasons: dict[str, int] = {}
        telemetry["batch_validation"] = diagnostics
        telemetry["batch_validation_reasons"] = rejection_reasons
        value = _request_json(
            system_prompt,
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
            preset=preset,
        )
        cards = validate_batch(
            value,
            expected_count,
            used_words=used_words,
            diagnostics=diagnostics,
            rejection_reasons=rejection_reasons,
        )
        if not cards:
            raise BatchValidationError(
                "No valid cards remained after batch validation",
                diagnostics,
            )
        return cards

    return _call_tracked(
        _run,
        request_kind=request_kind,
        user_id=user_id,
        plan=plan,
        preset=preset,
    )
