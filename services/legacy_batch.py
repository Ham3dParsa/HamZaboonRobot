"""Legacy daily-card batch generation — extracted, unwired (Q-25).

This module preserves the daily-card batching logic that was previously
scattered across prompts/ai for future use, but is intentionally NOT
imported or called by any live code. Product is pull-based (ROADMAP);
push/batch delivery is retired. Keeping the code here avoids losing the
batching investment while guaranteeing zero live calls/cost.

No handler, scheduler, or bot imports this module. Re-wiring requires
explicit owner decision.
"""

from __future__ import annotations

# Re-export the batch prompt builder for future wiring — kept here so the
# canonical prompt definition is not lost when live code stops using it.
# Intentionally no runtime side effects.

try:
    from services.ai.prompts import daily_card_system_prompt  # noqa: F401
except ImportError:
    daily_card_system_prompt = None  # type: ignore

# Placeholder for future batch-pool assembly logic.
# Previously: build daily pool per (target_lang, goal, level) segment
# with avoid-words, duplicate filtering, and partial retry.
# Extracted as stub — no scheduler calls it.

def build_daily_batch_stub(*_args, **_kwargs):
    """Unwired stub — not called by live code (Q-25)."""
    raise NotImplementedError("legacy batch is unwired — wire explicitly if needed")
