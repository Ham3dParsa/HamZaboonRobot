---
name: hamzaban-validation
description: Execute the full AGENTS.md §6 validation suite in one atomic command: pytest -n tests, compile_all.py, ruff F821/F811, generate_dashboard.py, git diff --check. Load when preparing to commit, before PR creation, or when asked to validate. For non-behavioral changes (docs, tooling, formatting), use the lightweight path instead.
license: MIT
compatibility: opencode
metadata:
  category: validation
  gate: pre-commit
  tier: full | lightweight
author: Ham3dParsa
author_url: https://github.com/Ham3dParsa
---
# HamZaban Validation Skill

## When to load
- Before any commit (AGENTS.md §7)
- Before `gh pr create` (CI must pass)
- When asked to "validate" or "run tests"

## Validation Tier Selection

### Full suite (behavioral changes)
Changes that touch: handlers, database, callbacks, AI contracts, quotas, schemas, module boundaries, or any production `.py` code.

```powershell
python -m pytest tests/ -n 14
python scripts\compile_all.py
python -m ruff check --select F821,F811
python scripts\generate_dashboard.py
git diff --check
```

### Lightweight path (non-behavioral changes)
Changes that touch only: docs, skill files, agent definitions, plan files, formatting, comments, or test files that do not change production logic.

```powershell
git diff --check
```

## Behavior
- Choose tier based on change scope before running any command.
- Full suite: run all 5 steps in sequence; report consolidated PASS/FAIL.
- Lightweight path: run only `git diff --check`; report PASS/FAIL.
- On failure, capture relevant error output in readable format.
- If PR open on current branch, confirm `gh pr checks` status.
- Return single verdict with actionable guidance.

## Notes
- `compile_all.py` compiles all production `.py` (excludes `tests/`)
- `ruff --select F821,F811` catches undefined names and redefinitions only (F401 not yet enforced — see AGENTS.md §7 note)
- `generate_dashboard.py` must regenerate `issues/project_status.html` from `project_status.json`
- `git diff --check` validates no whitespace errors in working tree AND staging area
- The lightweight path exists specifically to avoid the bottleneck of running pytest/compile/ruff on doc/tooling-only changes.