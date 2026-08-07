---
name: plan-test-pytest-config
description: Add pytest.ini so bare `pytest` scopes to tests/ and stops collecting broken tools/ simulation test files.
created: 2026-08-08
base_commit: a8f9529
branch: chore/test-pytest-config
status: in-progress
---

# Plan: pytest.ini collection scoping

## Locked decisions (owner approved)

- **Rule 1 (Q1 — DB I/O):** Leave DB setup as-is. Measured `init_db()` = ~10 ms; the in-RAM DB rewrite would save <2% and risk cross-test isolation. NOT implemented.
- **Rule 2 (Q2 — pytest collection):** Add `pytest.ini` with `testpaths = tests` and `norecursedirs` excluding `tools*`, so bare `pytest` no longer collects the broken `tools/**/test_*.py` files. Approved.
- **Rule 3 (Q3 — tools/ housekeeping):** Leave the committed `tools/srs_simulation_v4` + `tools/Fsrs_simulation_v5` test files excluded (not removed / not gitignored). Approved.

## Rationale (evidence)

- Bare `pytest` recursed the repo and hit tracked-but-broken simulation tests:
  - `tools/Fsrs_simulation_v5/test_v5_dsr.py` → `ModuleNotFoundError: No module named 'v5_dsr'`
  - duplicate `test_simulator_v4.py` basenames → `import file mismatch`
- CI runs `pytest tests/` explicitly, so it is unaffected by this change.
- No `pytest.ini`/`pyproject.toml`/`setup.cfg` exists today; change is purely additive.

## Steps

| # | Action | Status |
|---|--------|--------|
| 1 | Create branch `chore/test-pytest-config` from `origin/main` | done |
| 2 | Create `pytest.ini` with `testpaths = tests` + `norecursedirs = tools* ...` | done |
| 3 | Validate bare `pytest -n 4 -q` → 453 passed, 0 errors | done |
| 4 | Validate `pytest tests/ -n 14` still green (no regression) | done |
| 5 | Full validation (compile_all, ruff F821/F811, dashboard, git diff --check) | done |
| 6 | Commit `chore(test): scope pytest collection to tests/` + PR | in-progress |

## Out of scope

- No production code, DB schema, callbacks, or module-boundary changes.
- No removal/gitignore of `tools/` files.

## Update Log

- 2026-08-08: Plan locked by owner. Beginning implementation.
