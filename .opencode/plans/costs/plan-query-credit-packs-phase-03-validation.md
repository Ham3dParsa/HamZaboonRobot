---
name: query-credit-packs-phase-03-validation
description: Validate the credit-pack dashboard model, persistence, and user-facing presentation.
created: 2026-08-10
base_commit: e76c572f63dfb26f661dd52656219dd0ad86147e
branch: feat/financial-model-ui
status: complete
---
STATE: phase 3/3 — status: complete — focus: model, persistence, and presentation integrity verified

## Blocking Edges

- Phase 1 and Phase 2 must be complete.

## Scope

- Focused tests or browser/DOM smoke checks for the single-file dashboard.
- JSON export/import and localStorage regression checks.
- `git diff --check` and targeted static inspection.

## Contract Rules

- All Rules 1–9.

## Tests / Validation

- Export/import round-trip preserves `plans` and `creditPacks` independently.
- Partial import does not erase the unselected product collection.
- Reset restores both default packs and plans.
- Legacy data loads without exceptions.
- Financial outputs remain finite for zero/edge purchase rates.
- Charts use separate plan and pack series where applicable.
- No Telegram/backend files are modified.

## Wiring Rows

| Source | Consumer | Disposition | Verification |
|--------|----------|-------------|--------------|
| export sections | JSON export/import | update | round-trip test |
| localStorage | initialization | update | legacy-load test |
| reset action | defaults | update | reset assertion |
| dashboard charts | financial outputs | update | chart-data inspection |

## Acceptance Criteria

1. The dashboard can be used as a repeatable planning tool without manual repair of saved data.
2. The model is understandable to a non-accountant.
3. The stochastic simulation is bounded and reproducible.
4. The implementation remains dashboard-only and does not imply bot functionality.

## Evidence

- `tests/test_financial_model_dashboard.py`: 7 focused checks passed.
- `node --check`: inline application script syntax passed.
- `python -m pytest tests/ -n 14 --ignore=tests/test_inspect_db_notebook.py`: 601 passed.
- `python scripts\\compile_all.py`: passed.
- `python -m ruff check --select F821,F811`: passed.
- `python scripts\\generate_dashboard.py`: passed.
- `git diff --check`: passed.
- Full suite caveat remains limited to the pre-existing Windows SQLite URI defect in `tests/test_inspect_db_notebook.py`.
