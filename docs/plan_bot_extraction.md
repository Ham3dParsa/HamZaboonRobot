# Plan: Staged `bot.py` Module Extraction

**Status:** Locked implementation plan; Stage 1 (`formatting.py`) completed; Stage 2 (`helpers.py`) completed; Stage 3 (`user.py`) requires contract lock
**Canonical references:** this file, issue #96
**Last updated:** 2026-07-18 (updated after Stage 2 implementation)

## Problem

`bot.py` has grown to 2,905 lines (currently ~2,829 post-Stage-1 extraction) spanning 14 responsibility areas: onboarding,
daily card generation, scheduled delivery, custom-word queries, grammar tips,
SRS reminders with staged self-test reveal, translation-prep callbacks, review
history navigation, the LLM cost dashboard, admin controls, MarkdownV2 escaping,
card rendering, job orchestration, retry logic, and the main entry point.

This monolithic structure creates risks:

- A change in one flow (e.g., card rendering) can accidentally affect another
  (e.g., SRS reminders) through shared mutable state or misplaced edits.
- A future Telegram parse-mode migration (MarkdownV2 → something else) would
  require touching handler code instead of one formatting module.
- Onboarding new contributors requires understanding the entire file.
- Testing handler behavior requires either mocking everything or running the
  full Telegram application.

## Goal

Extract 5 focused modules from `bot.py` while preserving all handler and
callback contracts. No behavioral change to any learner-facing or
admin-facing flow. Each extraction stage must pass the full validation suite
and be independently reviewable.

## Target Architecture

```
formatting.py       helpers.py
      │                 │
      └──────┬──────────┘
             ▼
    ┌──── bot.py ─────────┐
    │ routers, jobs, AI   │
    │ limiter, generation,│
    │ global state, main()│
    ├──► user.py          │
    ├──► srs_handler.py   │
    └──► admin.py         │
         (all leaf modules)
         (bot.py never imported by a leaf)
```

### Module Boundaries

| Module | Responsibility | Depends on |
|--------|---------------|------------|
| `formatting.py` | MarkdownV2 escaping, card/SRS message rendering, `CardPreparationError` | stdlib only |
| `helpers.py` | Shared Telegram plumbing (`_edit_or_send`, `_exit_awaiting_flow`, wait-state helpers, callback-safe answer) | telegram, keyboards (constants) |
| `user.py` | User-facing command/state handlers (onboarding, settings, daily-card UI, grammar tip, custom word, translation prepare, review menu) | helpers, formatting, db, ai, prompts, keyboards, config |
| `srs_handler.py` | SRS review/ reveal/ add-to-review callback handlers | helpers, formatting, db, config |
| `admin.py` | Admin panel, admin callbacks, LLM cost dashboard and pricing, admin text awaiting handlers | helpers, formatting, db, keyboards, config |
| `bot.py` | Module globals, AI limiter, date/usage helpers, `_phonetic_lines`, daily card generation and caching, `_prepare_cached_card`, queue planning and dispatch, all jobs (`daily_job`, `srs_job`, `delivery_dispatch_job`, etc.), `text_router`, `callback_router`, `error_handler`, `main()` | all of the above, plus db, ai, prompts, keyboards, config, scheduling |

## Stage 1 — `formatting.py`

**Status:** Completed (2026-07-18)

### What moved

| Function/Constant | Signature (after extraction) | Notes |
|-------------------|------------------------------|-------|
| `escape_mdv2(text: str) -> str` | Unchanged | |
| `escape_mdv2_code(text: str) -> str` | Unchanged | |
| `format_card(data: dict, footer: str = "", *, presentation: str = "detailed", translations_prepared: bool = False, phonetic_lines: list[str] | None = None) -> str` | **Refactored**: accepts `phonetic_lines` parameter instead of calling `_phonetic_lines()` → `db.get_phonetic_display_settings()` | |
| `format_srs_prompt(data: dict, *, phonetic_lines: list[str] | None = None) -> str` | **Refactored**: same pattern — accepts `phonetic_lines` parameter | Also refactored (original plan said "Unchanged", but it had the same `db` dependency) |
| `CardPreparationError` | Exception class, unchanged | |
| `SRS_HIDDEN_INSTRUCTION` | String constant | |
| `SRS_REVEAL_QUESTION` | String constant | |

### Refactoring detail

Current call chain in `format_card`:
```
format_card → _phonetic_lines(data.get("phonetic", "")) → _phonetic_display_settings() → db.get_phonetic_display_settings()
```

After extraction, `format_card` receives pre-rendered lines:
```python
def format_card(
    data: dict,
    footer: str = "",
    *,
    presentation: str = "detailed",
    translations_prepared: bool = False,
    phonetic_lines: list[str] | None = None,
) -> str:
    ...
    if phonetic_lines:
        lines.extend(phonetic_lines)
```

Callers in `bot.py` (or `user.py`, `srs_handler.py`) render phonetic lines
before calling `format_card`:
```python
phon_lines = _phonetic_lines(data.get("phonetic", ""))
msg = format_card(data, phonetic_lines=phon_lines, ...)
```

This keeps `formatting.py` free of any `db` or `bot` imports.

### Verification

```bash
python -m py_compile formatting.py bot.py
python -m unittest discover -s tests -v
```

### Caller migration (bot.py)

Every call site (`_send_card_from_store`, `_send_next_daily_card`,
`send_grammar_tip`, `ask_for_ask_word`, `_handle_daily_prepare`,
`_handle_query_prepare`, `_handle_srs_prepare`, `_handle_srs_reveal`,
`_dispatch_queue`, `srs_job`) must be updated to:

1. Render `_phonetic_lines(data.get("phonetic", ""))` before calling `format_card`.
2. Pass the result as `phonetic_lines=phon_lines`.
3. Update the import from the local definition to `from formatting import format_card, format_srs_prompt, escape_mdv2, escape_mdv2_code, CardPreparationError`.

### Stage 1 completion summary

- `formatting.py`: 115 lines created with 7 exported symbols
- `bot.py`: 2,905 → ~2,829 lines (removed ~120 lines of escaping/rendering)
- 9 `format_card` call sites + 1 `format_srs_prompt` call site updated with `phonetic_lines` parameter
- Tests updated: `test_custom_word_query.py`, `test_srs_staged_reveal.py`, `test_reliability.py`
- Validation: 140/140 tests pass, `py_compile` clean, no whitespace errors
- All imports satisfy the circularity guard: `formatting.py` imports only `re` (stdlib)

---

## Stage 2 — `helpers.py`

**Status:** Completed (2026-07-18)

### What moved

| Function/Constant | Notes |
|-------------------|-------|
| `_start_llm_wait_state` | Underscore kept; uses `logger` instead of `log` |
| `_finish_llm_wait_state` | Underscore kept; uses `logger` instead of `log` |
| `_exit_awaiting_flow` | **Refactored**: inline `OWNER_ID` check (`user_id == OWNER_ID`) instead of calling `is_owner()` from `bot.py` |
| `_edit_or_send` | Underscore kept; uses `logger` instead of `log` |
| `_answer_callback_safely` | Underscore kept; uses `logger` instead of `log` |
| `_message_has_prepared_translations` | Unchanged |
| `_is_cancel_input` | Unchanged |
| `_normalize_custom_word_input` | Unchanged |
| `_CANCEL_INPUTS` | Unchanged |
| `_CUSTOM_WORD_MAX_CHARS` | Unchanged |
| `_CUSTOM_WORD_MAX_WORDS` | Unchanged |

### Dependencies

- `re` (stdlib)
- `logging.getLogger(__name__)` (own logger named `helpers`)
- `telegram.Update`, `telegram.ext.ContextTypes`
- `telegram.error.BadRequest`
- `config.OWNER_ID`
- `keyboards.main_menu`, `keyboards.awaiting_inline_keyboard`, `BTN_CANCEL`, `BTN_BACK`

### Refactoring detail

`_exit_awaiting_flow` originally called `main_menu(is_owner(user_id))` where `is_owner` was in `bot.py`. To avoid a circular import (helpers importing bot), the check was inlined:
```python
reply_markup = main_menu(user_id == OWNER_ID)
```

Module-level logger was changed from `log` (shared bot.py logger) to `logger` (module-scoped to helpers).

### Verification

```bash
python -m py_compile helpers.py bot.py
python -m unittest discover -s tests -v
```
All 140 tests pass, `py_compile` clean.

### Stage 2 completion summary

- `helpers.py`: 81 lines created with 11 exported symbols
- `bot.py`: ~2,829 → ~2,743 lines (removed ~86 lines of shared Telegram plumbing)
- All call sites updated in `bot.py` — 0 behavioural changes
- Tests updated: `test_custom_word_query.py` (import from helpers), `test_reliability.py` (import helpers, call through `helpers._answer_callback_safely`)
- Validation: 140/140 tests pass, `py_compile` clean, no whitespace errors
- All imports satisfy the circularity guard: `helpers.py` imports only `re`, `logging`, `telegram.*`, `config`, `keyboards` (no `bot`)

---

## Stage 3 — `user.py`

**Status:** Requires contract lock before implementation

### What moves

| Function | Group | Called from |
|----------|-------|-------------|
| `cmd_start` | Onboarding | `main()` handler registration |
| `on_lang_selected` | Onboarding | `callback_router` |
| `on_goal_selected` | Onboarding | `callback_router` |
| `on_level_selected` | Onboarding | `callback_router` |
| `change_lang_start` | Settings | `text_router` |
| `change_goal_start` | Settings | `text_router` |
| `change_level_start` | Settings | `text_router` |
| `change_presentation_start` | Settings | `text_router` |
| `on_lang_changed` | Settings | `callback_router` |
| `on_goal_changed` | Settings | `callback_router` |
| `on_level_changed` | Settings | `callback_router` |
| `send_daily_card_now` | Daily action | `text_router` |
| `send_grammar_tip` | Daily action | `text_router` |
| `ask_for_ask_word` | User action | `text_router` |
| `show_status` | User action | `text_router` |
| `_handle_query_prepare` | Translation reveal | `callback_router` |
| `_handle_daily_prepare` | Translation reveal | `callback_router` |
| `_handle_srs_prepare` | Translation reveal | `callback_router` |
| `_show_review_menu` | Review | `callback_router` |
| `_show_review_date` | Review | `callback_router` |
| `_custom_word_input_error` | Validation | `text_router` |

### Router delegation pattern

In `bot.py`'s `text_router`:
```python
# Before
if text == BTN_TODAY_CARD:
    await send_daily_card_now(update, context)
elif text == BTN_CHANGE_LANG:
    await change_lang_start(update, context)
# After
from user import send_daily_card_now, change_lang_start, ...
if text == BTN_TODAY_CARD:
    await send_daily_card_now(update, context)
```

In `bot.py`'s `callback_router`:
```python
from user import on_lang_changed, on_lang_selected, _show_review_menu, ...
# existing routing logic unchanged, only the function location changes
```

### Dependencies

`helpers`, `formatting`, `db`, `ai`, `prompts`, `keyboards`, `config`

---

## Stage 4 — `srs_handler.py`

**Status:** Requires contract lock before implementation

### What moves

| Function | Notes |
|----------|-------|
| `_handle_srs_review(update, action, target_user_id_text, word_id_text)` | Called from `callback_router` for `srs:remember`, `srs:confirm`, `srs:again` |
| `_handle_srs_reveal(update, context, target_user_id_text, word_id_text)` | Called from `callback_router` for `srs:reveal:` |
| `_handle_query_add(update, context, token)` | Called from `callback_router` for `query:add:` |
| `_saved_word_card(row) -> dict` | Helper used by all three above |

### Router delegation pattern

```python
# In bot.py's callback_router
from srs_handler import _handle_srs_review, _handle_srs_reveal, _handle_query_add

elif data.startswith("srs:reveal:"):
    await _handle_srs_reveal(update, context, parts[2], parts[3])
elif data.startswith("srs:"):
    await _handle_srs_review(update, parts[1], parts[2], parts[3])
elif data.startswith("query:add:"):
    await _handle_query_add(update, context, parts[2])
```

### Dependencies

`helpers`, `formatting`, `db`, `config`

---

## Stage 5 — `admin.py`

**Status:** Requires contract lock before implementation

### What moves

| Function | Group |
|----------|-------|
| `open_admin_panel` | Panel entry |
| `admin_callback` | All admin callbacks |
| `_phonetic_settings_text` | Helper |
| `_llm_cost_default_state` | Dashboard state |
| `_llm_cost_state` | Dashboard state |
| `_llm_cost_set_state` | Dashboard state |
| `_llm_cost_range_bounds` | Dashboard query |
| `_llm_cost_query_filters` | Dashboard query |
| `_llm_cost_currency_text` | Dashboard formatting |
| `_llm_cost_projection` | Dashboard projection |
| `_llm_cost_filter_label` | Dashboard formatting |
| `_llm_cost_state_label` | Dashboard formatting |
| `_llm_cost_percent` | Dashboard formatting |
| `_llm_cost_status_icon` | Dashboard formatting |
| `_llm_cost_report_text` | Dashboard report |
| `_llm_pricing_text` | Pricing display |
| `_show_llm_cost_dashboard` | Dashboard render |
| Admin awaiting handlers from `text_router` | `admin_set_plan`, `admin_set_model`, `admin_set_base_url`, `admin_set_api_key`, `admin_broadcast`, `llm_cost_user`, `llm_cost_model`, `llm_price_input`, `llm_price_output`, `llm_price_rate` |
| Admin callback branches from `callback_router` | `llm:` prefix callbacks (range, set, pricing, plan, kind, status, clear, refresh, recent) |

### Router delegation pattern

`text_router` admin branches become:
```python
from admin import _handle_admin_text_input
if awaiting.startswith("admin_") or awaiting.startswith("llm_cost_") or awaiting.startswith("llm_price_"):
    await _handle_admin_text_input(update, context, awaiting, text)
    return
```

`callback_router` admin branches become:
```python
from admin import _handle_admin_callback
elif data.startswith("admin:"):
    await _handle_admin_callback(update, context, data.split(":", 1)[1])
elif data.startswith("llm:"):
    await _handle_llm_callback(update, context, data)
```

### Dependencies

`helpers`, `formatting`, `db`, `keyboards`, `config`

---

## What Stays in `bot.py`

After all 5 stages, `bot.py` retains:

| Category | Functions/Globals |
|----------|------------------|
| **Globals** | `_app_timezone`, `_daily_locks`, `_ai_slots`, `_ai_request_times`, `_ai_request_lock`, `_telegram_slots`, `_MANUAL_DAILY_BATCH_SIZE`, logging config |
| **AI limiter** | `_call_ai_limited`, `_ask_batch_limited` |
| **Date/usage helpers** | `_app_today`, `_word_query_usage`, `_word_query_usage_text`, `_grammar_tip_usage`, `_grammar_tip_usage_text` |
| **Owner helpers** | `is_owner`, `_user_plan`, `_user_plan_label`, `_user_presentation` |
| **Phonetic helpers** | `_phonetic_display_settings`, `_phonetic_lines` (needs `db`) |
| **Card sending** | `_send_card_from_store`, `_send_next_daily_card` |
| **Generation** | `_generate_daily_batch`, `_daily_avoid_words`, `_daily_card_session_profile`, `_ensure_daily_cards`, `_ensure_scheduled_session_cards`, `_ensure_next_daily_card` |
| **Card preparation** | `_prepare_cached_card` |
| **Review history** | `_review_history_page` |
| **Queue/jobs** | `_plan_daily_queue`, `_send_with_retry`, `_dispatch_queue`, `daily_job`, `startup_catch_up_job`, `delivery_dispatch_job`, `connection_health_job`, `srs_job` |
| **Routers** | `text_router` (delegates), `callback_router` (delegates) |
| **Entry points** | `error_handler`, `main()` |

---

## Import and Circularity Guard

The following rule must be enforced at every stage and verified by `py_compile`:

- `formatting.py`: may import only from stdlib, `catalog`, `config`. Must never import `bot`, `db`, `ai`, `prompts`, `keyboards`, `helpers`, `user`, `admin`, `srs_handler`.
- `helpers.py`: may import from `telegram`, `logging`, `keyboards`. Must never import `bot`, `formatting`, `db`, `ai`, `prompts`, `user`, `admin`, `srs_handler`.
- `user.py`, `srs_handler.py`, `admin.py`: may import from `helpers`, `formatting`, `db`, `ai`, `prompts`, `keyboards`, `config`, `catalog`, `scheduling`. Must never import `bot`.
- `bot.py`: may import from any module. No module imports from `bot.py`.

## Verification per Stage

Each stage must pass:
```bash
.venv/bin/python -m py_compile formatting.py helpers.py user.py srs_handler.py admin.py bot.py
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## Issue Update Procedure

After each stage is implemented, tested, and reviewed:

1. Update GitHub issue #96 with the completed stage, evidence (final line count, test output), and next planned stage.
2. If the stage resolves a sub-tracked issue, update or close that issue.
3. Update this plan document's "Last updated" date and the status of the completed stage.
