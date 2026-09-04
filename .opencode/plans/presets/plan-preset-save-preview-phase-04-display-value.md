---
name: plan-preset-save-preview-phase-04-display-value
phase: 4
gates: [D1]
blocking: [phase-03]
status: pending
---
STATE: phase 4 — status: pending — focus: single display-value owner

## Rule D1 (locked — owner "انجام بده" 2026-09-04, deepening #2)

One owner for preset display values: `display_value(preset, field, staged=None) -> str`
in `services/ai/preset_fields.py` (owns secret/cost flags + resolve/write_value).
Migrates all 6 render sites in `handlers/admin_ai.py` (+ `handlers/admin.py:451`
quick view) to it: `_preset_edit_diffs`, `_show_wizard_field`, `_show_wizard_summary`,
`_show_ai_preset_view`, `_edit_ai_preset_field:497` (currently unmasked — bug fix),
group panels. Empty → "—". api_key masked via `db.mask_key` inside (preset_fields
already bridges ai+db? if layering forbids, inject mask fn — implementer picks the
cleaner seam and states it; reviewer checks §3).
Alternatives rejected: leave 6 dialects (audit risk); owner in services/utils/
(violates §3 domain-agnostic rule).
Owner Confirmation: "انجام بده".
GATE STATUS: LOCKED
<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE> — satisfied.

## Acceptance

- [ ] one function, 6 sites migrated, `:497` masked
- [ ] unit tests through new interface (mask/empty/label cases, no Telegram/DB)
- [ ] full suite green; `hamzaban-reviewer` 0 confirmed findings
