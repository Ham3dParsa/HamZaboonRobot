---
name: query-credit-packs-phase-01-model
description: Add the independent credit-pack model and lightweight stochastic financial simulation.
created: 2026-08-10
base_commit: e76c572f63dfb26f661dd52656219dd0ad86147e
branch: feat/financial-model-ui
status: complete
---
STATE: phase 1/3 — status: complete — focus: credit-pack financial inputs verified

## Blocking Edges

- Main contract `plan-query-credit-packs.md` must remain locked.
- No dependency on Telegram or backend work.

## Scope

- `tools/financial_model/financial_model_dashboard.html`
- Add `creditPacks` defaults and safe migration.
- Add pack purchase, sales-mix, usage, repeat-purchase, and bounded-noise assumptions.
- Add deterministic seeded computation for scenario comparisons.
- Add one-time pack revenue and estimated Query cost to the financial series.

## Contract Rules

- Rules 1–8, especially Rule 7 lightweight stochastic simulation.

## Tests / Validation

- Fresh defaults contain Query 40 and Query 100.
- Existing saved data without `creditPacks` loads safely.
- Pack sales shares remain independent from plan upgrade shares.
- Same seed produces the same projection.
- Different seeds produce bounded variation.
- Pack revenue and Query cost affect monthly revenue and profit.
- Zero purchase rate produces zero pack revenue.

## Wiring Rows

| Source | Consumer | Disposition | Verification |
|--------|----------|-------------|--------------|
| `creditPacks` | financial projection | update | seeded projection assertions |
| pack assumptions | KPI calculations | update | revenue/cost assertions |
| legacy saved state | migration | update | missing-field load test |

## Acceptance Criteria

1. The financial model distinguishes plans from credit packs.
2. The default scenario includes 9,000/40 and 19,000/100 products.
3. Pack revenue is modeled as one-time revenue.
4. Usage is estimated through configurable rates and bounded noise.
5. The model does not introduce runtime bot behavior.

## Evidence

- `tests/test_financial_model_dashboard.py`: 5 focused checks passed.
- `node --check`: inline application script syntax passed.
- `python scripts\\compile_all.py`: passed.
- `python -m ruff check --select F821,F811`: passed.
- `python scripts\\generate_dashboard.py`: passed.
- `git diff --check`: passed.
- Full suite caveat: 603 passed; 4 pre-existing `test_inspect_db_notebook.py` failures use invalid Windows SQLite `file:C:\\...` URIs and are unrelated to this phase.
