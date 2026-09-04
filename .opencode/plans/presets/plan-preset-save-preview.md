---
name: plan-preset-save-preview
description: Old-vs-draft save preview for admin preset edit (concepts B+C, Rich tables)
created: 2026-09-04
base_commit: 52302c507159089e520509674003e7c10a67c34c
branch: feat/preset-save-preview
status: in-progress
---
STATE: phase 0/3 — status: in-progress — focus: T1 shared helper

## CONTRACT LOCK TEMPLATE

Owner said (2026-09-04): "قفل با توصیه‌هات" — all recommendations accepted.

Rule #1 — Scope: preset single-field edit + confirm only, plus shared helper for later reuse (plans/fallback deferred).
Option Chosen: recommended (preset-only + helper).
Alternatives Rejected: all-admin-flows in one PR (too big, too much test surface).
Trade-offs: smaller PR, faster review; plans/fallback keep old UX until follow-up.
Owner Confirmation: "قفل با توصیه هات" (covers R1–R6).
GATE STATUS: LOCKED

Rule #2 — Edit menu (concept B): per dirty field one vertical 2-row Rich table (قبلی/جدید) under field heading; clean fields show no table.
Option Chosen: recommended. Rejected: ✏️-only markers (less informative).
Owner Confirmation: "قفل با توصیه هات".
GATE STATUS: LOCKED

Rule #3 — Confirm screen (concept C): numbered table with BOTH old and new (vertical per-field tables, mobile-safe); never new-only.
Option Chosen: recommended. Rejected: new-only compact table (violates old-vs-new requirement).
Owner Confirmation: "قفل با توصیه هات".
GATE STATUS: LOCKED

Rule #4 — Shared helper `services/utils/confirm_summary.py::build_confirm_message()` (takes prepared strings; masking/truncation stay in callers); preset adopts first.
Option Chosen: recommended. Rejected: inline-only in admin_ai.py (duplication remains).
Owner Confirmation: "قفل با توصیه هات".
GATE STATUS: LOCKED

Rule #5 — Secrets: api_key always masked (first6…last4 via mask_key); URLs shown full (Rich wraps, no truncation).
Option Chosen: recommended. Rejected: mid-truncation (hides real value).
Owner Confirmation: "قفل با توصیه هات".
GATE STATUS: LOCKED

Rule #6 — Single message edited in place; toast replaces per-field ✅ message; keyboard `[✅ ذخیره (N)] [🗑️ دور ریختن] [↩️ بازگشت]`.
Option Chosen: recommended. Rejected: keep 2-msg-per-field (clutter).
Owner Confirmation: "قفل با توصیه هات".
GATE STATUS: LOCKED

<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE> — satisfied (owner locked 2026-09-04).

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | none new (reuse `admin:ai_preset:*`) | keep |
| Router branches | `handlers/admin_ai.py` `_edit_ai_preset`, `_handle_ai_preset_field_input`, `_confirm_save_preset` | update render only |
| Keyboard builders | `config/keyboards/admin.py::ai_preset_edit_keyboard` (counter + ✏️ dots) | update labels only |
| DB tables/columns | none | keep |
| Handler functions | same three above | update |
| Imports | new `services/utils/confirm_summary.py` (formatting helper, prepared-strings-in) | add |
| Tests | `tests/test_integration/test_ai_preset_handlers_ux.py` + new `tests/test_confirm_summary.py` | add/update |
| Docs | this plan + presets/index.md | update |

Seams touched (SEAMS.md): #12 Telegram UI → AI Config (handlers/admin_ai.py). No overlap with active claim (tools/load-sim-100: Persistence/Session-Assembly/Scheduling-Quota).
Callback impact: no new prefixes → no new wiring test required; existing wiring tests must stay green.

## Tickets

- T1: `plan-preset-save-preview-phase-01-helper.md` — shared helper + unit tests.
- T2: `plan-preset-save-preview-phase-02-edit-menu.md` — edit-menu vertical tables (B).
- T3: `plan-preset-save-preview-phase-03-confirm.md` — confirm old+new + message collapse (C).
