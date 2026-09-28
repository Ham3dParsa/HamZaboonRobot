# Phase 06 — Clean wiring + flow tests + run guide (P07 + P08 + P09, W3 ∥)

Gates: R4 (progress/history), R6 (mechanical path + gallery in path).

## P07 — clean-wiring pass + mechanical-only verify

- Audit every control on screening → handoff → linking → TSV → gallery: working, or disabled with stated reason (no silent dead buttons).
- Verify mechanical-only route to supervised arbitration (screened + mechanical candidates, zero AI verdicts) against current linker logic; if a gate forces AI, REPORT (do not bypass) as follow-up with file:line evidence.

## P08 — flow integration tests

- `tests/test_integration/test_supervised_arbitration.py` (load `integration-test-proto`): batch issue→import→approve flow through routing layer with DB snapshot isolation; gallery build flow; import-rejection flow. From behavior spec + locked contract, not internals.

## P09 — run guide (Persian)

- `factory/webui/RUN_GUIDE.md`: screening → handoff → linking → TSV → gallery, every step with the exact replayable receipt command; local-provider registration; batch export/import loop with an AI chat; honest limits (key-gated listing, leased-route supervisor, no model execution in this phase).

## Acceptance

P07 checklist clean (or follow-up filed); P08 green in full suite; P09 reviewed for plain Persian; full validation (`pytest`, `compile_all.py`, `ruff F821/F811`, `git diff --check`) green before wave commit.
