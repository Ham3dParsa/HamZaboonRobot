---
name: integration-test-proto
description: Enforce AGENTS.md Integration Test Protocol — handler-level integration tests in tests/test_integration/ simulating real user flows through routing layer with DB snapshot isolation, mocked Telegram, and AI token budget. Load when adding/modifying handler logic, keyboards, callbacks, DB writes, quota enforcement, or AI interaction.
license: MIT
compatibility: opencode
metadata:
  category: testing
  gate: behavioral-change
---
# Integration Test Protocol Skill

## When to load
- Behavioral change: callback routing, handler logic, keyboard construction, DB writes, quota enforcement, AI interaction
- Adding/modifying any user-facing flow

## Protocol Requirements (AGENTS.md §6)

### Scope & Coverage
Each integration test follows a user-facing flow:
1. Construct realistic `Update` (text message or callback query) and `Context`
2. Call appropriate router (`text_router`, `callback_router`, or sub-router)
3. Assert on Telegram output (`reply_text`, `edit_message_text`, `answer`) AND resulting DB state
4. Assert returned keyboard contains expected `callback_data` prefixes and labels

### Database Isolation
- Before test session: backup real SQLite DB (`db.DB_PATH`) to timestamped snapshot (once per session, never modified)
- Each test class: fresh copy of snapshot in temp dir; set `db.DB_PATH` to copy
- After session: remove all temp copies and session snapshot
- **No production data ever read/written via production `db.DB_PATH`**

### AI Interaction in Tests
- Default: ALL AI calls mocked with controlled, pre-defined responses
- `AI_TEST_REAL=true`: real AI calls with dedicated test preset (`_is_test_preset=True`)
- **Hard budget: 1000 tokens per test session** — track via `db.log_llm_request`, abort at 1000 tokens
- Real AI mode only for targeted verification of prompt changes / new content schemas

### Telegram Interface
- **No real bot token** — mock `Context.bot` via `AsyncMock`
- Verify handler response by inspecting mock call args: `reply_text.call_args`, `edit_message_text.call_args`, `answer.call_args`

### File Conventions
- Location: `tests/test_integration/`
- Naming: `test_<feature>_flow.py`
- Class: `unittest.IsolatedAsyncioTestCase`
- Helpers: `tests/test_integration/helpers.py` (update factory, context factory, DB snapshot management)

### Contract Lock Gate for New Tests
Before writing an integration test, include in contract lock summary:
- AI cost impact (expected token count, purpose if real AI)
- Database safety plan

## Broken/Outdated Test Handling
- **DO NOT** silently delete, disable, or ignore failing tests
- **DO NOT** revert correct code modifications to make outdated test pass
- Determine: bug or intentional logic change?
  - Intentional → update/rewrite test to reflect new canonical behavior
  - Uncertain → HALT and ask owner (AGENTS.md §2.4 fallback)