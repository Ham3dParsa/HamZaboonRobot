# OpenCode Session Prompt: Network Resilience V2

## Before starting

Read `AGENTS.md`, `ROADMAP.md`, and `.opencode/plans/feat_network_resilience_v2.md` fully before doing anything.

This feature was **contract-locked** with the owner (Hamed) in a prior session. All 6 rules were chosen as Option A (Recommended). No re-negotiation is needed — proceed directly to implementation.

Working directory: `C:\Python_Programming\#T-Bot\HamZaban`

---

## Locked Rules Summary

| # | Decision | What to do |
|---|----------|------------|
| 1 | Reset CB on retry success | Add `_reset_telegram_cb()` in helpers.py; call at end of all 4 retry wrappers |
| 2 | BG jobs skip when offline | `_dispatch_queue`, `srs_job`, `daily_job` check `_telegram_offline` at top |
| 3 | Faster health check | Change interval to 30s, threshold to 1 failure |
| 4 | Replace raw reply_text | Convert 10+ `update.message.reply_text()` in text_router to `_send_with_retry` |
| 5 | SRS retry queue | Add `retry_at` + `srs_retry_attempts` columns; functions for fail/query/clear; `srs_retry_job` every 15min |
| 6 | Startup CB check | `startup_catch_up_job` tests connection before running jobs |

---

## Implementation order (strict)

1. **Phase 1** — `helpers.py`: Add `_reset_telegram_cb()` that sets `bot._telegram_offline = False` and `bot._consecutive_health_failures = 0`. Call it in the `try` block after successful API call in all 4 retry functions (`_send_with_retry`, `_edit_with_retry`, `_delete_with_retry`, `_send_voice_with_retry`).

2. **Phase 2** — `bot.py`:
   - Change `_OFFLINE_THRESHOLD = 1`, `CONNECTION_HEALTH_INTERVAL_SECONDS = 30` in config or inline
   - Change schedule interval to 30s
   - Add offline guard at top of `_dispatch_queue`, `srs_job`, `daily_job`
   - Replace 10+ `update.message.reply_text()` with `_send_with_retry(context.bot, update.effective_chat.id, ...)`
   - Add connection check at top of `startup_catch_up_job`

3. **Phase 3** — `db/__init__.py`: Add migration for `retry_at` and `srs_retry_attempts` columns on `saved_words`. Add functions: `mark_srs_send_failed`, `get_due_srs_failed`, `clear_srs_retry`.

4. **Phase 4** — `bot.py`: Add `srs_retry_job`. Register with `run_repeating(interval=900, first=900)`.

---

## Key design decisions

- SRS retry backoff: `min(300 * 2^attempts, 3600)` seconds (5min, 10min, 20min, then capped at 1h)
- Max SRS retry attempts: 5
- SRS retry queue uses the same `_send_with_retry` + same card preparation as original `srs_job`
- `_reset_telegram_cb` imports `bot` module — circular import is safe because `bot.py` imports `helpers.py`, and `_reset_telegram_cb` is only called at runtime, not at import time
- `get_due_srs_failed`: filters `review_status='idle'` and `retry_at <= now`, ordered by `retry_at`, max 50 per batch
- When SRS retry succeeds: call `clear_srs_retry(word_id)` then `mark_word_review_pending(word_id)`

## Verification (run before any commit)

```powershell
python -m unittest discover -s tests -v
python -m ruff check --select F821,F811
python scripts/compile_all.py
git diff --check
```

## Git workflow

1. `git checkout main && git pull && git checkout -b feat/network-resilience-v2`
2. Implement phases 1–4
3. Write focused tests
4. `git add helpers.py bot.py db/__init__.py tests/<test_file>`
5. `git commit -m "feat(network): circuit breaker reset, SRS retry queue, raw call migration"`
6. `git push -u origin feat/network-resilience-v2`
7. `gh pr create --fill --base main`

## Don't

- Don't change `user.py`, `srs_handler.py`, `admin.py`, `config/*` (except config/\_\_init\_\_.py if needed for interval constant), `services/ai/*`, `keyboards.py`
- Don't refactor existing SRS job — only add error path in catch blocks
- Don't run `git add .` — use explicit file paths
- Don't change the delivery_queue retry logic (already works well)
