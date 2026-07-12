# Daily-card batching and LLM wait-state UX audit

## Scope
Reviewed the current batching mechanism for:

- the manual `🃏 فلش‌کارت امروز` flow
- the scheduled automatic delivery flow

## Current state

### Scheduled delivery
- The scheduled path already batches generation.
- `plan_sessions()` splits a day’s allowance into multiple delivery sessions.
- `_ensure_scheduled_session_cards()` asks `_generate_daily_batch()` for up to 6 cards at a time while filling a session.
- Result: the auto path already reduces LLM calls compared with generating each card independently.

### Manual daily-card flow
- The manual flow still generates one card at a time.
- `_ensure_next_daily_card()` calls `_generate_daily_batch(..., 1, used_words)`.
- There is no shared batch reservoir that lets the first manual request prime a 2–6 card batch for later requests.
- Result: repeated manual clicks still incur fresh LLM work instead of reusing a pre-generated batch.

### Waiting-state UX
- The main LLM-backed manual paths already call `chat_action("typing")` before waiting.
- That gives a subtle Telegram signal, but it is not a user-visible loading message or animation.
- There is no shared helper that standardizes the waiting experience across all LLM-backed commands.

## Findings

1. **Auto flow is partially batched and already efficient enough for MVP delivery.**
   - Good: batching exists and is isolated from the rest of the delivery queue.
   - Caveat: the batch size is session-driven, not a reusable reservoir.

2. **Manual flow is the remaining gap.**
   - Each request fetches one card.
   - Token savings are therefore limited when users repeatedly press `🃏 فلش‌کارت امروز`.

3. **The two flows are not yet unified behind a shared batch cache.**
   - That keeps the current implementation simple.
   - It also means the manual path cannot benefit from the same batch efficiency as scheduled delivery.

4. **The waiting experience is only partially addressed.**
   - `typing` is good baseline feedback, but it is easy to miss.
   - A shared helper could add a short visible “در حال تولید…” style response and keep the UX consistent across daily cards, grammar tips, and custom-word lookups.

## Recommendation

- Keep the current scheduled batching behavior.
- Add a shared daily-card batch reservoir for manual requests so the first interaction can prime a small batch, then later clicks read from storage.
- Reuse the same generation helper, but keep manual and automatic consumption separate so user-triggered and auto-delivery state do not leak into each other.
- Add a shared waiting-state helper for all user-triggered LLM calls so the user sees a clear “still working” signal while the model responds.

## Related roadmap / issue notes

- `ROADMAP.md` now calls out a shared batch reservoir as a reliability follow-up.
- `ROADMAP.md` now also calls out a shared LLM wait-state UX helper for manual learning flows.
- `issues/issues.json` records the manual daily-card batching gap as issue `29` and the loading-feedback gap as issue `30`.
