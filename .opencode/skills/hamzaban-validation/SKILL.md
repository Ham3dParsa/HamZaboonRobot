---
name: hamzaban-validation
description: Execute the full AGENTS.md §6 validation suite in one atomic command: pytest -n tests, compile_all.py, ruff F821/F811, generate_dashboard.py, git diff --check. Load when preparing to commit, before PR creation, or when asked to validate.
license: MIT
compatibility: opencode
metadata:
  category: validation
  gate: pre-commit
author: Ham3dParsa
author_url: https://github.com/Ham3dParsa
---
# HamZaban Full Validation Skill

## When to load
- Before any commit (AGENTS.md §7)
- Before `gh pr create` (CI must pass)
- When asked to "validate" or "run tests"

## Validation Suite (exact commands per AGENTS.md §6)

### Windows PowerShell
```powershell
python -m pytest tests/ -n 14
python scripts\compile_all.py
python -m ruff check --select F821,F811
python scripts\generate_dashboard.py
git diff --check
```

### Linux/macOS (CI)
```bash
.venv/bin/python -m pytest tests/ -n 4
.venv/bin/python -m py_compile $(git ls-files '*.py' | grep -v 'tests/')
.venv/bin/python -m ruff check --select F821,F811
python scripts/generate_dashboard.py
git diff --check
```

## Behavior
- Run all 5 steps in sequence
- Report consolidated PASS/FAIL with the specific command that failed (if any)
- On failure, capture relevant error output in readable format
- If PR open on current branch, confirm `gh pr checks` status
- Return single verdict with actionable guidance

## Notes
- `compile_all.py` compiles all production `.py` (excludes `tests/`)
- `ruff --select F821,F811` catches undefined names and redefinitions only (F401 not yet enforced — see AGENTS.md §7 note)
- `generate_dashboard.py` must regenerate `issues/project_status.html` from `project_status.json`
- `git diff --check` validates no whitespace errors in working tree AND staging area