# Plan: Network Resilience (feat/network-resilience)

**Status:** Locked — ready for implementation
**Owner locked:** 2026-07-20
**Target branch:** `feat/network-resilience`
**Base branch:** `main`

---

## Problem

The bot runs locally on a machine with frequent internet/VPN disconnections. When the Telegram API becomes unreachable via the HTTP proxy:

- `ConnectTimeout` propagates through every handler, generating cascading traceback chains
- Only `_send_with_retry` (used in delivery/SRS jobs) has retry logic — all user-facing handlers (`cmd_start`, `send_grammar_tip`, `ask_for_ask_word`, callback edits, etc.) call `bot.send_message()` / `edit_message_text()` directly
- `_finish_llm_wait_state` (delete wait message) has no retry
- No circuit breaker exists to stop futile attempts during prolonged disconnection

## Scope

Only Telegram API network errors (`TimedOut`, `NetworkError`, `ConnectTimeout`). AI provider calls already have their own timeout/retry. SQLite errors are excluded.

---

## Implementation Phases

### Phase 1: `helpers.py` — New retry utilities

**Add `_edit_with_retry(query, text, **kwargs)`:**
- 3 attempts, exponential backoff (`2**attempt` seconds)
- Catch `TimedOut` / `NetworkError` → retry
- Re-raise `BadRequest` immediately (don't retry)
- Wrap in `_telegram_slots` semaphore

**Add `_delete_with_retry(bot, chat_id, message_id, **kwargs)`:**
- Same retry policy as `_edit_with_retry`
- Used by `_finish_llm_wait_state`

**Add `_send_voice_with_retry(bot, chat_id, voice, **kwargs)`:**
- Same retry policy as `_send_with_retry`
- Wrap in `_telegram_slots`

**Modify `_send_with_retry`:**
- Change signature to accept `**kwargs` instead of hardcoded `parse_mode`/`reply_markup`
- Backward compatible: `parse_mode` and `reply_markup` still work as keyword args

**Modify `_answer_callback_safely`:**
- Add `TimedOut` / `NetworkError` to the caught exception list (currently only `BadRequest`)
- Log at `warning` level instead of silently dropping

---

### Phase 2: `bot.py` — Circuit breaker

**Add globals (~line 171):**
```python
_telegram_offline: bool = False
_consecutive_health_failures: int = 0
_OFFLINE_THRESHOLD: int = 2
```

**Modify `connection_health_job`:**
- On exception → increment `_consecutive_health_failures`; if >= `_OFFLINE_THRESHOLD`, set `_telegram_offline = True`; log with consecutive count
- On success → reset both to 0/False; if was offline, log "Telegram connection restored"

**Modify `text_router`:**
- At top (before any processing): if `_telegram_offline`, attempt one `_send_with_retry` with offline message; if that fails, just log; return immediately

**Modify `callback_router`:**
- At top (before any processing): if `_telegram_offline`, attempt `_answer_callback_safely` + one `_send_with_retry`; log; return immediately

**Replace raw `send_message` with `_send_with_retry` at:**
- `_send_next_daily_card` (lines ~451, ~461)
- `send_daily_card_now` error paths (lines ~485, ~505)
- `callback_router` > daily:next error path (~line 844)
- `callback_router` > review:next error path (~line 899)
- `_send_card_from_store` (~line 211)
- `_handle_tts_pronounce` error paths (~lines 1277-1280)

**Replace raw `send_voice` with `_send_voice_with_retry` at:**
- `_handle_tts_pronounce` (~line 1271)

**Replace raw `edit_message_text` with `_edit_with_retry` at:**
- `callback_router` > presentation:set: (~line 762)

---

### Phase 3: `user.py` — Raw → retry for all handlers

**Replace every `update.message.reply_text(...)` call with `_send_with_retry(context.bot, chat_id=update.effective_chat.id, text=..., reply_to_message_id=update.message.message_id)` in:**

- `cmd_start` (~lines 126, 135)
- `send_grammar_tip` (~lines 311, 321, 353, 373, 376)
- `ask_for_ask_word` (~lines 392, 397, 567, 577, 605, 623, 642, 660)
- `show_status` (~lines 407, 418)
- `on_lang_selected`, `on_goal_selected`, `on_level_selected` (via `_edit_or_send`)

**Replace `_edit_or_send` callbacks with `_edit_with_retry` at:**
- `_handle_daily_prepare` (~line 538) — edit_message_text
- `_handle_query_prepare` (~line 613) — edit_message_text

---

### Phase 4: `srs_handler.py` — Raw → retry

**Add imports:** `TimedOut`, `NetworkError` from `telegram.error`

**Replace `edit_message_text` with `_edit_with_retry` at:**
- `_handle_srs_reveal` (~line 161)
- `_handle_srs_prepare` (~line 235)

---

### Phase 5: `helpers.py` — Fix `_finish_llm_wait_state`

- Replace `await wait_message.delete()` with `await _delete_with_retry(context.bot, wait_message.chat_id, wait_message.message_id)`
- Note: `_finish_llm_wait_state` currently only takes `wait_message` — need signature change or access to bot/chat_id

---

## Offline user message (Persian)

When circuit breaker is active, the bot sends (best-effort, single attempt):
```
⚠️ اتصال ربات به اینترنت قطع شده. به محض وصل شدن، دوباره تلاش کن.
```

---

## Test Plan

### Unit tests (new file or add to `test_reliability.py`)

1. **`_edit_with_retry` success on 3rd attempt** — mock `edit_message_text` to raise `TimedOut` twice then succeed; assert retry count and final success
2. **`_edit_with_retry` re-raises `BadRequest`** — verify `BadRequest` is not retried
3. **`_delete_with_retry` success** — similar pattern
4. **`_telegram_offline` set by `connection_health_job` after 2 consecutive failures** — mock `get_me` to fail twice; verify flag is True
5. **`_telegram_offline` reset on health check success** — mock `get_me` to succeed; verify flag is False
6. **`_telegram_offline` not set on single failure** — mock to fail once; verify flag is still False

### Integration verification
- Run full test suite: `python -m unittest discover -s tests -v`
- Run ruff: `python -m ruff check --select F821,F811`
- Run compile check: `python scripts/compile_all.py`

---

## Files changed

| File | Changes |
|---|---|
| `helpers.py` | +3 functions, 2 modified |
| `bot.py` | ~15 call sites + circuit breaker globals |
| `user.py` | ~20 call sites |
| `srs_handler.py` | 2 call sites + imports |
| `tests/test_reliability.py` or new test file | +6 test methods |

---

## Edge cases & risks

| Edge case | Mitigation |
|---|---|
| `edit_message_text` succeeds on retry but message state changed | Retry uses the same query object; if callback is stale, `BadRequest` ("query ID is invalid") is caught by `_answer_callback_safely` |
| Circuit breaker false positive (health check fails but individual request succeeds) | Rare — health check is lightweight `get_me()`. If it happens, user request proceeds after one extra health check interval |
| `_edit_with_retry` timeout on last attempt | Exception propagates to the caller's existing except (already handles errors) or `error_handler` |
| `_send_voice_with_retry` fails on all 3 attempts | Falls through to caller's except, same as `_send_with_retry` |
