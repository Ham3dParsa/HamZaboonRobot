---
name: plan-ai-presets-audit-spec
description: Locked contract + spec for the consolidated AI-presets admin-panel audit fixes (3 external audits: Gemini #1, Gemini #2, Claude).
created: 2026-08-09
base_commit: <fill after branch cut>
branch: fix/admin-ai-presets-audit
status: pending
---

# SPEC — AI Presets Admin Panel Audit Fixes

Source findings:
- `docs/audit/` (external audits consolidated via `hamzaboon-reviewer`)
- Gemini audit #1 (DB tx, name validation, 64-byte callbacks, escaping, cost)
- Gemini audit #2 (fallback-rank state trap, redundant routing)
- Claude audit (HTML escaping gap, unbounded length, cancel state leak, awaiting Back bug)

## Problem Statement

From the owner's perspective: the admin AI Presets panel (Fallback Chain, AI Settings,
Preset Lists) has several latent bugs that surface as hard Telegram crashes
(`BUTTON_DATA_INVALID`, `can't parse entities`) and silent state corruption (pending
text input being misapplied to the wrong flow). These make the admin panel unreliable
to operate.

## Solution

From the owner's perspective: the admin panel becomes crash-safe and state-safe — every
callback stays within Telegram's 64-byte limit, every dynamic value renders safely in
its parse mode, and entering/exiting editing flows always clears leftover state so no
later message is misread.

## User Stories

1. As an owner, I want to edit any field of a preset (including the long cost fields),
   so that the edit menu renders without a `BUTTON_DATA_INVALID` crash.
2. As an owner, I want to use Persian group labels in the fallback chain and group
   manager, so that the picker/rename/clear menus render without overflowing the
   callback payload.
3. As an owner, I want to view current AI settings, so that the "Current Settings"
   panel renders without a MarkdownV2/HTML parse crash.
4. As an owner, I want to tap "Back" from any text-input prompt (new name, group
   key, group label, rank), so that the pending text state is cleared and my next
   message is not silently treated as input to that prompt.
5. As an owner, I want to tap "Cancel" from an editing flow, so that all in-memory
   state (pending edits, full-edit wizard) is cleared and cannot resurface later.
6. As an owner, I want to enter a preset name or group label with a typo or special
   character, so that invalid names (`my_preset!`) are rejected, and names/labels
   longer than a safe length are rejected with a clear message.
7. As an owner, I want to see my API key always masked in the settings summary, so
   that the full key is never displayed even for short keys.
8. As an owner, I want preset `base_url`, `model`, and `group_label` values that
   contain `&`, `<`, or `>` to render safely, so that the panel does not crash on
   legitimate query-string URLs.
9. As a maintainer, I want all escaping centralized in `services/utils/formatting.py`,
   so that escaping rules are maintained in one place.
10. As an owner, I want the DB layer to roll back cleanly on a mid-transaction error,
    so that the preset registry stays consistent under concurrent admin actions.

## Implementation Decisions

### R1 — Scope-limited DB transaction hardening (preset_registry only)
- Convert the multi-statement writers (`rename_group_label`, `clear_group_label`,
  `set_fallback_active`, `reindex_preset_priority`) to explicit try/except/rollback +
  re-raise. Single-statement writers may stay (self-healing via `get_conn` close).
- **Not changed:** repo-wide `BEGIN IMMEDIATE` pattern in other db modules.

### R3 — 64-byte callback_data fix (hash long identifiers)
- Add a short **field-alias map** for the closed set of `WIZARD_FIELDS` (e.g.
  `output_cost_per_million` → `outc`, `input_cost_per_million` → `inc`,
  `max_output_tokens` → `mot`).
- For **preset names** and **Persian group labels** (unbounded), use a deterministic
  hash (reuse the existing `_key_hash` sha256[:12] style) in callback payloads.
- **Reverse-resolve on routing** by scanning `db.get_presets()` /
  `db.get_group_labels()` for a matching hash (matches the existing grouped-view
  pattern; restart-safe, no registry needed).
- **Static prefixes unchanged** so `tests/test_wiring.py` stays green.
- Apply to: `edit_field`, `full_edit_pick_group`, `group_manager_rename`,
  `group_manager_clear`; audit the `view/activate/edit/delete/full_edit*`
  /`confirm_save_*`/`discard_all`/`save` and `fallback:move_*`/`toggle`/`rank`
  /`set_emergency` and `ai_fallback:pick_*` callbacks for overflow and hash where
  needed.

### R4 — `show_settings` parse mode (handlers/admin.py)
- Switch the `show_settings` branch to `ParseMode.HTML`.
- **R7:** always mask the API key in that branch (`***` for ≤12-char keys).

### R5 — Remove redundant routing in `_show_ai_settings`
- Delete the `if update.callback_query:` branch; call `_edit_or_send(...)` directly.

### R6 — Name validation precedence fix
- Fix `_handle_ai_preset_new_name` (admin_ai.py:938) to the correct
  `all(c.isalnum() or c == "_" for c in name)` form, matching the other validators.

### R8 — General awaiting-state cleanup
- Make `admin:back` (and unrelated admin navigation) clear any pending admin awaiting
  state — fixes `ai_fallback_rank:*`, `admin_group_batch_key`, `admin_group_set_label`,
  `admin_group_manager_rename`.
- Reference issue #136 item 3/#136-4b which cover the same awaiting-flow family.

### R9 — Cancel clears all admin state
- `admin:cancel` also pops `preset_edits` and `full_edit` in-memory state.

### R10 — Centralized HTML escaping
- Add `html_escape()` to `services/utils/formatting.py`.
- Apply it to every dynamic value interpolated into `ParseMode.HTML` messages in
  `admin_ai.py` (~9 render sites).

### R11 — Length caps + group_label validation
- Add a max length for `name` and `group_label` at the validation layer
  (e.g. name ≤ 60, group_label ≤ 40).
- Add non-empty validation for `group_label`.

### R2 — SKIPPED (owner decision)
- `daily_batch_size` ceiling not changed; batching may become obsolete.

## Testing Decisions

- **Good test = external behavior:** a test dispatches a real callback string through
  the real routing path (`_handle_admin_callback` → `handle_ai_callback`) with a mocked
  Telegram update, then asserts the resulting `awaiting` state / `user_data` /
  `edit_message_text`/`reply_text` calls — NOT internal helper internals. See
  `tests/test_integration/test_ai_full_edit_wizard_nav.py` for the established seam.
- **Modules under test:**
  - `tests/test_keyboards.py` — add a ≤64-byte assertion on every `ai_preset_edit_field:*`
    (and overflow-prone) callback.
  - `tests/test_admin_awaiting.py` — add `my_preset!` re-arm assertion; add a
    state-cleanup assertion that a non-rank/non-cancel admin callback pops `awaiting`.
  - `tests/test_preset_registry.py` — transaction rollback on mid-transaction failure.
  - `tests/test_admin_ai_module.py` — preserved (function names / re-exports unchanged).
  - New integration test(s) in `tests/test_integration/` — awaiting-state cleanup on
    `admin:back`, cancel-all-state, escaping-with-special-chars render, 64-byte-safe
    hash resolution round-trip.
- **Prior art:** `test_ai_full_edit_wizard_nav.py` (routing seam), `test_fallback_flow.py`,
  `tests/test_admin_awaiting.py`, `tests/test_wiring.py` (static-prefix wiring guard).

## Out of Scope

- Repo-wide DB transaction refactor (only preset_registry hardenened).
- `daily_batch_size` ceiling.
- issue #136 items unrelated to presets (review-center hub #106, grammar-tip review
  flow, user-settings submenu) — tracked separately.
- Any new premium features.

## Further Notes

- Overlaps issue #136 (awaiting-flow state handling, fallback routing consistency).
  The awaiting-cleanup fix (R8/R9) should resolve #136-3's spirit without duplicating
  its full redesign; coordinate on merge to avoid conflicting changes to
  `_handle_admin_text_input` / `_handle_admin_callback`.
- Callback payload encoding change must keep static prefixes intact (test_wiring guard).
- AI Cost Discipline: these fixes add **no** new AI calls; net call volume unchanged.
