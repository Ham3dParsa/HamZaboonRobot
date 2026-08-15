---
name: admin-ai-labels-and-back
description: Fix admin_ai preset field-label inconsistency (#342) and field-edit back-button wipe (#343) + systemic keyboard divergence
created: 2026-08-15
base_commit: b735c5d
branch: fix/admin-ai-labels-and-back
status: complete
---

STATE: complete — merged via PR #352 (2b1315f). All steps done; independent review clean; Kilo No Issues Found.

## Locked Contract (owner confirmed "locked" 2026-08-15)

| Rule | Decision | Option | Detail |
|---|---|---|---|
| R1 | Canonical English label map | A | One all-English `FIELD_LABELS` dict used by single-field edit prompt, full-edit wizard, and confirmation message |
| R2 | Short labels + hints | A | Short titles; validation type hints move into `_FIELD_HELP` tooltip |
| R3 | Field-edit back resumes edit | A | `admin_ai.py:395` uses `awaiting_inline_keyboard()` (flow:back resumes preset-edit menu, keeps edits) |
| R4 | Systemic fix (3 flows) | B | (1) field-edit -> awaiting; (2) create-name retries :1136/:1142 -> admin_awaiting; (3) full-edit error retry :663 -> re-render wizard field with custom nav buttons |

Dependency & Wiring Map (from gate): no new callback prefixes; no router/keyboard-builder/DB changes; call-site swaps in `handlers/admin_ai.py` only; imports already present.

## Scope (files)

- `handlers/admin_ai.py` — label map consolidation, back-button call-site swaps, full-edit retry re-render.
- `tests/test_integration/` — new flow tests.

## Steps

- [x] Gate locked (R1-R4 chosen; owner "locked").
- [x] Seam claim acquired: Seams 8 (override) + 12 (parallel-work-claims.json).
- [x] Step 1 — write failing tests (RED):
  - field-edit Back (`flow:back`) resumes preset-edit menu and keeps `preset_edits` (no wipe).
  - create-name error retry uses `admin_awaiting_inline_keyboard` (back stays in admin panel).
  - full-edit wizard validation-error retry re-renders wizard field with custom nav buttons (does not abort via flow:back).
  - confirmation message shows canonical label, not raw `field_name`; wizard uses canonical labels.
- [x] Step 2 — implement R1/R2 canonical labels.
- [x] Step 3 — implement R3 field-edit back -> awaiting.
- [x] Step 4 — implement R4 (create-name retries, full-edit error retry).
- [x] Independent review (hamzaboon-reviewer) clean.
- [x] Validation suite + wiring guards + commit + PR (links #342, #343).

## Post-review (Kilo)

- [x] Remove `WIZARD_FIELD_LABELS = FIELD_LABELS` alias; call sites use `FIELD_LABELS` directly.
- [x] Document the `awaiting_inline_keyboard()` Cancel/Back semantics (R3) at the keyboard switch.

## Completion

- Merged: PR #352 (squash `2b1315f`). Issues #342/#343 resolved. Full suite 897 passed; Kilo No Issues Found.

## Blocked Questions

(none)