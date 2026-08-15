---
name: query-credit-packs-phase-02-ui
description: Separate authoritative product editors from synchronized pricing and share analysis.
created: 2026-08-10
base_commit: e76c572f63dfb26f661dd52656219dd0ad86147e
branch: feat/financial-model-ui
status: complete
---
STATE: phase 2/3 — status: complete — focus: single-source-of-truth product editing UX verified

## Blocking Edges

- Phase 1 model fields and computed outputs exist.

## Scope

- `tools/financial_model/financial_model_dashboard.html`
- Keep plan editing authoritative in Plan Management.
- Add Credit Pack Management as the authoritative pack editor.
- Remove duplicate editable plan fields from Pricing & Share.
- Convert Pricing & Share into a synchronized read-only comparison view.
- Show separate plan upgrade mix and pack sales mix.
- Add clear pack summaries, notes, active state, and migration assumption copy.

## Contract Rules

- Rules 6, 8, and 9.

## Tests / Validation

- Editing a plan updates all analytical plan summaries.
- Editing a pack updates all pack summaries and financial outputs.
- Plan share changes do not alter pack sales share.
- Pack sales share changes do not alter plan upgrade mix.
- No duplicate editable price/quota controls remain in the analytical view.
- Mobile and desktop layouts remain usable.

## Wiring Rows

| Source | Consumer | Disposition | Verification |
|--------|----------|-------------|--------------|
| Plan Management | plan analysis | update | DOM/data synchronization check |
| Credit Pack Management | pack analysis | add | DOM/data synchronization check |
| plan upgrade mix | plan projections | keep/update | independent-value assertion |
| pack sales mix | pack projections | add | independent-value assertion |

## Acceptance Criteria

1. Each product type has exactly one editing source.
2. Analytical views update immediately after edits.
3. Users can understand the difference between a plan and a credit pack.
4. Non-expiring credits and the premium migration assumption are clearly labeled as simulation assumptions.

## Evidence

- `tests/test_financial_model_dashboard.py`: 6 focused checks passed.
- `node --check`: inline application script syntax passed.
- `python -m pytest tests/ -n 14 --ignore=tests/test_inspect_db_notebook.py`: 600 passed.
- `python scripts\\compile_all.py`: passed.
- `python -m ruff check --select F821,F811`: passed.
- `python scripts\\generate_dashboard.py`: passed.
- `git diff --check`: passed.
