"""Benchmark runner — executes AI card generation in non-batched and batched modes.

Supports retry with backoff, per-model cost calculation, and detailed telemetry.
"""

import logging
import time
import concurrent.futures
from dataclasses import dataclass, field
from typing import Any

from services.ai import ai as ai_module
from services.ai.prompts import daily_card_system_prompt, daily_batch_system_prompt
from services import db

log = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 3
DEFAULT_LANG = "en"
DEFAULT_GOAL = "general"
DEFAULT_LEVEL = "intermediate"

# Approximate per-model pricing (USD per 1M tokens).
# Source: Google AI published pricing (July 2026). Verify with your provider.
MODEL_COST_MAP = {
    "gemini-3.6-flash":         {"in": 1.50,  "out": 7.50},
    "gemini-3.5-flash":         {"in": 0.15,  "out": 0.60},
    "gemini-3.5-flash-lite":    {"in": 0.075, "out": 0.30},
    "gemini-flash-lite-latest": {"in": 0.25,  "out": 1.50},
    "gemini-3.1-flash-lite":    {"in": 0.25,  "out": 1.50},
    "gemma-4-31b-it":           {"in": 0.50,  "out": 2.00},
    "gemma-4-26b-a4b-it":       {"in": 0.30,  "out": 1.50},
}
DEFAULT_MODEL_COST = {"in": 0.25, "out": 1.50}

USD_TO_IRR = 2_000_000

DEFAULT_WORDS = [
    "run", "break a leg", "actually", "get up", "however", "cozy",
    "procrastinate", "book", "ironic", "RSVP", "couch potato", "appreciate",
]


@dataclass
class WordAttempt:
    """Result of a single attempt at generating a card for a word."""
    word: str
    success: bool
    latency_ms: float
    attempt_number: int
    card: dict | None = None
    error_class: str | None = None
    error_message: str | None = None


@dataclass
class WordResult:
    """Final result for a word (after all retries)."""
    word: str
    success: bool
    attempts: list[WordAttempt] = field(default_factory=list)
    final_card: dict | None = None
    total_latency_ms: float = 0.0

    @property
    def total_attempts(self) -> int:
        return len(self.attempts)

    @property
    def first_attempt_success(self) -> bool:
        return len(self.attempts) == 1 and self.attempts[0].success


@dataclass
class ModeResult:
    """Aggregate results for one preset in one mode (single or batch)."""
    preset_name: str
    model: str
    mode: str
    compact: bool
    word_results: list[WordResult] = field(default_factory=list)
    batch_latency_ms: float | None = None
    batch_card_count: int | None = None
    batch_total_tokens: int | None = None

    @property
    def total_words(self) -> int:
        return len(self.word_results)

    @property
    def success_count(self) -> int:
        return sum(1 for w in self.word_results if w.success)

    @property
    def fail_count(self) -> int:
        return sum(1 for w in self.word_results if not w.success)

    @property
    def total_api_calls(self) -> int:
        if self.mode == "batch":
            return 1 if self.batch_card_count else 0
        return sum(w.total_attempts for w in self.word_results)

    @property
    def total_calls_with_failures(self) -> int:
        return sum(
            1 for w in self.word_results
            for att in w.attempts
        )


def get_model_cost(model: str) -> dict:
    """Get cost per 1M tokens for a model. Falls back to DEFAULT_MODEL_COST."""
    return MODEL_COST_MAP.get(model, DEFAULT_MODEL_COST)


def _benchmark_single_prompt(lang: str, goal: str, level: str, word: str, *, compact: bool) -> str:
    """Generate a system prompt that forces a specific word for non-batched mode."""
    base = daily_card_system_prompt(lang, goal, level=level, compact=compact)
    return (
        f"{base.rstrip()}\n\n"
        f"مهم: فقط و فقط برای واژهٔ «{word}» کارت واژه بساز. "
        f"هیچ واژهٔ دیگری انتخاب نکن."
    )


def _benchmark_batch_prompt(lang: str, goal: str, level: str, words: list[str], *, compact: bool) -> str:
    """Generate a system prompt that forces specific words for batched mode."""
    base = daily_batch_system_prompt(lang, goal, level, len(words), compact=compact)
    word_list = "، ".join(words)
    return (
        f"{base.rstrip()}\n\n"
        f"مهم: فقط و فقط برای این واژه‌ها کارت بساز و دقیقاً به همین ترتیب:\n{word_list}\n"
        f"همهٔ {len(words)} کارت را در یک آرایه JSON برگردان."
    )


def _attempt_one_word(
    word: str,
    preset: dict,
    compact: bool,
    attempt_num: int,
    lang: str,
    goal: str,
    level: str,
) -> WordAttempt:
    """Make a single AI call for one word. Returns a WordAttempt."""
    model = preset.get("default_model", "?")
    system_prompt = _benchmark_single_prompt(lang, goal, level, word, compact=compact)
    user_prompt = f"واژه: {word}"

    start = time.monotonic()
    try:
        card = ai_module.ask_card(
            system_prompt,
            user_prompt=user_prompt,
            request_kind="benchmark",
            user_id=0,
            plan="benchmark",
            preset=preset,
        )
        latency_ms = (time.monotonic() - start) * 1000
        return WordAttempt(
            word=word,
            success=True,
            latency_ms=latency_ms,
            attempt_number=attempt_num,
            card=card,
        )
    except ai_module.RateLimitError as exc:
        latency_ms = (time.monotonic() - start) * 1000
        return WordAttempt(
            word=word,
            success=False,
            latency_ms=latency_ms,
            attempt_number=attempt_num,
            error_class="RateLimitError",
            error_message=str(exc)[:500],
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000
        return WordAttempt(
            word=word,
            success=False,
            latency_ms=latency_ms,
            attempt_number=attempt_num,
            error_class=type(exc).__name__,
            error_message=str(exc)[:500],
        )


def _retry_backoff(preset: dict, attempt: int) -> float:
    """Calculate backoff seconds before retry based on preset max_rpm."""
    max_rpm = preset.get("max_rpm", 10)
    base_wait = max(60.0 / max_rpm, 1.5)
    return base_wait * attempt


def _run_non_batched(
    preset: dict,
    words: list[str],
    compact: bool,
    lang: str,
    goal: str,
    level: str,
) -> ModeResult:
    """Run non-batched benchmark: one AI call per word, concurrent with ThreadPoolExecutor.

    Retries failed words (up to MAX_RETRY_ATTEMPTS) with backoff based on preset max_rpm.
    """
    preset_name = preset.get("name", "?")
    model = preset.get("default_model", "?")
    max_concurrency = preset.get("max_concurrency", 2)
    result = ModeResult(
        preset_name=preset_name,
        model=model,
        mode="single",
        compact=compact,
    )

    pending = set(words)
    final_results: dict[str, WordResult] = {w: WordResult(word=w, success=False) for w in words}

    for attempt_num in range(1, MAX_RETRY_ATTEMPTS + 1):
        if not pending:
            break

        if attempt_num > 1:
            backoff = _retry_backoff(preset, attempt_num)
            log.info("Retry %d for %d words, waiting %.1fs...", attempt_num, len(pending), backoff)
            time.sleep(backoff)

        attempt_results: list[WordAttempt] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            futures = {
                pool.submit(
                    _attempt_one_word, w, preset, compact, attempt_num, lang, goal, level
                ): w
                for w in pending
            }
            for future in concurrent.futures.as_completed(futures):
                attempt = future.result()
                attempt_results.append(attempt)

        pending.clear()
        for att in attempt_results:
            wr = final_results[att.word]
            wr.attempts.append(att)
            wr.total_latency_ms += att.latency_ms

            if att.success:
                wr.success = True
                wr.final_card = att.card
            else:
                pending.add(att.word)

    result.word_results = list(final_results.values())
    return result


def _run_batched(
    preset: dict,
    words: list[str],
    compact: bool,
    lang: str,
    goal: str,
    level: str,
) -> ModeResult:
    """Run batched benchmark: one AI call with ask_batch for all words.

    No per-word retry in batch mode (the call either succeeds or fails as a whole).
    """
    preset_name = preset.get("name", "?")
    model = preset.get("default_model", "?")
    result = ModeResult(
        preset_name=preset_name,
        model=model,
        mode="batch",
        compact=compact,
    )

    system_prompt = _benchmark_batch_prompt(lang, goal, level, words, compact=compact)

    start = time.monotonic()
    try:
        cards = ai_module.ask_batch(
            system_prompt,
            expected_count=len(words),
            request_kind="benchmark",
            user_id=0,
            plan="benchmark",
            preset=preset,
        )
        result.batch_latency_ms = (time.monotonic() - start) * 1000
        result.batch_card_count = len(cards)

        for word in words:
            matched = None
            for c in cards:
                if c.get("word", "").strip().casefold() == word.strip().casefold():
                    matched = c
                    break
            if matched:
                result.word_results.append(WordResult(
                    word=word,
                    success=True,
                    final_card=matched,
                    attempts=[WordAttempt(
                        word=word, success=True, latency_ms=0,
                        attempt_number=1, card=matched,
                    )],
                ))
            else:
                result.word_results.append(WordResult(
                    word=word,
                    success=False,
                    attempts=[WordAttempt(
                        word=word, success=False, latency_ms=0,
                        attempt_number=1,
                        error_class="BatchMismatch",
                        error_message=f"Batch did not generate card for '{word}'",
                    )],
                ))

    except Exception as exc:
        result.batch_latency_ms = (time.monotonic() - start) * 1000
        for word in words:
            result.word_results.append(WordResult(
                word=word,
                success=False,
                attempts=[WordAttempt(
                    word=word, success=False, latency_ms=0,
                    attempt_number=1,
                    error_class=type(exc).__name__,
                    error_message=str(exc)[:500],
                )],
            ))

    return result


def query_benchmark_telemetry(model: str) -> dict:
    """Query llm_requests for aggregate telemetry from this benchmark run.

    Returns dict with prompt_tokens, completion_tokens, total_tokens,
    request_count, avg_latency_ms, etc.
    """
    filters = {
        "request_kind": "benchmark",
        "model": model,
        "user_id": 0,
        "plan": "benchmark",
    }
    summary = db.summarize_llm_requests(filters)
    return dict(summary)


def recalculate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
    usd_to_irr: int = USD_TO_IRR,
) -> dict:
    """Recalculate cost using MODEL_COST_MAP instead of DB cost profile."""
    rates = get_model_cost(model)
    cost_usd = (
        (prompt_tokens / 1_000_000) * rates["in"]
        + (completion_tokens / 1_000_000) * rates["out"]
    )
    cost_irr = cost_usd * usd_to_irr
    return {
        "cost_usd": round(cost_usd, 6),
        "cost_irr": round(cost_irr),
        "input_rate": rates["in"],
        "output_rate": rates["out"],
        "usd_to_irr": usd_to_irr,
    }


def run_preset_benchmark(
    preset: dict,
    words: list[str] | None = None,
    mode: str = "both",
    compact: bool = True,
    lang: str = DEFAULT_LANG,
    goal: str = DEFAULT_GOAL,
    level: str = DEFAULT_LEVEL,
) -> dict:
    """Run benchmark for a single preset in the specified mode(s).

    Args:
        preset: AI preset dict from ai_presets or DB.
        words: List of words to benchmark. Defaults to DEFAULT_WORDS.
        mode: 'single', 'batch', or 'both' (default).
        compact: Use compact JSON format (short keys).
        lang: Language code (default: 'en').
        goal: Goal code (default: 'general').
        level: Level code (default: 'intermediate').

    Returns:
        dict with keys: 'preset_name', 'model', 'modes' (dict of mode -> ModeResult),
        'telemetry' (per-model aggregate from DB), 'cost' (recalculated).
    """
    if words is None:
        words = DEFAULT_WORDS

    preset_name = preset.get("name", "?")
    model = preset.get("default_model", "?")
    log.info("Benchmarking preset '%s' (model=%s, mode=%s, compact=%s)...",
             preset_name, model, mode, compact)

    modes: dict[str, ModeResult] = {}

    if mode in ("both", "single"):
        log.info("  Phase 1: non-batched (%d words, concurrent=%d)...",
                 len(words), preset.get("max_concurrency", 2))
        modes["single"] = _run_non_batched(preset, words, compact, lang, goal, level)

    if mode in ("both", "batch"):
        log.info("  Phase 2: batched (%d words in one call)...", len(words))
        modes["batch"] = _run_batched(preset, words, compact, lang, goal, level)

    telemetry = query_benchmark_telemetry(model)

    cost = recalculate_cost(
        prompt_tokens=telemetry.get("prompt_tokens", 0) or 0,
        completion_tokens=telemetry.get("completion_tokens", 0) or 0,
        model=model,
    )

    return {
        "preset_name": preset_name,
        "model": model,
        "modes": modes,
        "telemetry": telemetry,
        "cost": cost,
    }


def delete_benchmark_data(model: str | None = None) -> int:
    """Delete all benchmark-related llm_requests entries.

    Args:
        model: If provided, only delete entries for this model.

    Returns number of deleted rows.
    """
    filters: dict[str, object] = {
        "request_kind": "benchmark",
        "user_id": 0,
        "plan": "benchmark",
    }
    if model:
        filters["model"] = model
    return db.delete_llm_requests(filters)
