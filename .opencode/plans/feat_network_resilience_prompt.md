# OpenCode Session Prompt: Network Resilience Feature

## Before starting

Read `AGENTS.md`, `ROADMAP.md`, `.opencode/plans/feat_network_resilience.md`, and this prompt fully before doing anything.

This feature was planned and **contract-locked** with the owner (Hamed) in a prior session. The owner has chosen **Option C** (circuit breaker + retry expansion + edit_with_retry), requested error messages in chat during disconnection, and approved `_edit_with_retry` for callbacks. No re-negotiation is needed — proceed directly to implementation.

## Context

HamZaboon is a Telegram Persian-language bot that runs locally on a Windows machine with an unstable internet/VPN connection. The main problem: when the Telegram API is unreachable, `ConnectTimeout` / `TimedOut` errors cascade through every user-facing handler, generating long traceback chains and failing silently.

## What to do

Implement the network resilience feature per `.opencode/plans/feat_network_resilience.md`.

### Implementation order (strict)

1. **Phase 1** — `helpers.py`: Add `_edit_with_retry`, `_delete_with_retry`, `_send_voice_with_retry`; modify `_send_with_retry` to accept `**kwargs`; modify `_answer_callback_safely` to catch `TimedOut`/`NetworkError`
2. **Phase 2** — `bot.py`: Add circuit breaker globals, modify `connection_health_job`, add offline check at top of `text_router` and `callback_router`, replace raw API calls with retry wrappers
3. **Phase 3** — `user.py`: Replace all `update.message.reply_text()` with `_send_with_retry`; replace `edit_message_text` with `_edit_with_retry`
4. **Phase 4** — `srs_handler.py`: Add imports, replace `edit_message_text` with `_edit_with_retry`
5. **Phase 5** — `helpers.py`: Fix `_finish_llm_wait_state` to use `_delete_with_retry`

### Offline message (Persian)

When circuit breaker activates, send (best-effort):
```
⚠️ اتصال ربات به اینترنت قطع شده. به محض وصل شدن، دوباره تلاش کن.
```

### Verification (run before any commit)

```powershell
python -m unittest discover -s tests -v
python -m ruff check --select F821,F811
python scripts/compile_all.py
git diff --check
```

### Git workflow

1. Create branch from `main`: `git checkout main && git pull && git checkout -b feat/network-resilience`
2. Implement phases in order
3. Write focused tests (at minimum: `_edit_with_retry` retry count, `_delete_with_retry` basic flow, circuit breaker flag behavior)
4. Stage explicitly: `git add helpers.py bot.py user.py srs_handler.py tests/<test_file>`
5. Commit with Conventional Commits: `feat(network): add circuit breaker and retry wrappers`
6. Push, create PR via `gh pr create --fill --base main`

## Key details

- `_telegram_offline` is a module-level `bool` in `bot.py`
- `_consecutive_health_failures` resets on ANY success in `connection_health_job`
- Only catch `TimedOut` / `NetworkError` for retries — `BadRequest` always re-raises
- `ruff.toml` only checks `F821` and `F811` — don't worry about other lint rules
- Tests use `unittest.IsolatedAsyncioTestCase` for async tests
- The `_telegram_slots` semaphore (from `helpers.py`) must be used in all new retry wrappers

## Files to change

- `helpers.py` + `bot.py` + `user.py` + `srs_handler.py`
- Test file: `tests/test_reliability.py` (add to existing class) or a new test file

## Don't

- Don't change `ai.py`, `db.py`, `config.py`, `catalog.py`, `keyboards.py`, `prompts.py`, `formatting.py`, `llm_services.py`, `admin.py`, or any files not listed above
- Don't remove existing error handling — only augment it
- Don't change AI call timeout/retry logic
- Don't run `git add .` — use explicit file paths
