---
name: plan-preset-draft-indicator
description: Show staged preset_edits drafts in edit menu (single-field flow)
created: 2026-09-04
base_commit: 6ad2fb6ca704bd8c624339c62130c7e59522a87c
branch: fix/preset-draft-indicator
status: pending
---
STATE: phase 1/1 — status: complete — evidence: 29 passed (test_admin_ai_render_flow) + 25 passed test_wiring; compile_all clean; ruff F821/F811 clean; git diff --check clean; callback_data byte-identical (test asserts); reviewer subagent unavailable in this env — manual self-review only (no callback changes, no secrets, single caller updated).

## Contract Lock (GATE STATUS = LOCKED, 2026-09-04, owner chose per rule)
- R1 confirm text: پیشنویس + نیازمند ذخیره (locked).
- R2 draft marker: علامت + شمارنده (locked).
- R3 key masking: همان ماسک (locked).
- R4 callbacks: بدون تغییر callback (locked).

<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE> — satisfied: owner answered each rule independently above.

## Why separate PR (not in 549)
- PR 549 is MERGEABLE/CLEAN + APPROVED. Adding behavior churn would invalidate both bot reviews and re-trigger the full cycle.
- AGENTS.md §6.6: one logical change per PR. 549 = zero-hardcode; this = edit-menu UX.
- Base: implement AFTER 549 merges (rebase onto new main), because 549 touches the same handler file.

## Bug (reported 2026-09-04, screenshot)
Single-field edit stages the value in `preset_edits` (memory) but:
1. Confirm text `handlers/admin_ai.py:536` says «ثبت شد» with no draft/unsaved hint (contrast correct pattern at `:1093`).
2. `_edit_ai_preset` (`:415-426`) re-reads DB only; staged edits never passed to the keyboard.
3. `ai_preset_edit_keyboard` (`config/keyboards/admin.py:571-611`) renders DB values only; no `edits` param, no marker, no pending count.
4. Only draft visibility is the wizard summary (`:840`, different `full_edit.values` path).
5. Proof: `grep preset_edits handlers/admin_ai.py` → stage/save/discard only, never display.

## Rules (lock each independently before code)
- R1: confirm text → «به‌صورت پیشنویس ثبت شد، نیازمند ذخیره» via formatting spans (alt: keep text + add save hint line).
- R2: staged fields get `✏️` marker + draft value in keyboard; header shows «N پیشنویس در انتظار ذخیره» (alt: marker only, no count).
- R3: api_key draft masked with the same mask as stored (alt: show `***` unconditionally).
- R4: no callback_data changes (keyboard signature change only, internal).

## Scope
- `handlers/admin_ai.py:415-426` (fetch + pass edits, header count), `:536-541` (confirm text).
- `config/keyboards/admin.py:571-611` (new optional `edits` param, marker rendering).
- Tests: `tests/test_integration/test_admin_ai_render_flow.py` (staged field shows marker + draft; count header; api_key masked).
- Gates: hamzaban-reviewer (0 findings), full suite, wiring (no prefix change — verify).

## Acceptance
- Staged Model shows new value with `✏️`; unstaged rows unchanged; header count correct; save persists, discard clears (existing paths).
- `grep preset_edits` now includes a display read.

## Deliberately Not Done
- Wizard `full_edit.values` display already exists — untouched.
- View panel (`_show_ai_preset_view`) stays DB-only — untouched.
