---
name: hamzaban-validation
description: Execute the full AGENTS.md §7 validation suite in one atomic command: pytest -n tests, compile_all.py, ruff F821/F811, git diff --check. Load when preparing to commit, before PR creation, or when asked to validate. For non-behavioral changes (docs, tooling, formatting), use the lightweight path instead.
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
python -m pytest tests/ -n 8
python scripts\compile_all.py
python -m ruff check --select F821,F811
git diff --check
```

Local full-suite runs must go through `python scripts/run_with_ram_gate.py [-n 8]` (not bare `pytest -n 8`): the wrapper enforces the RAM budget plus a fail-fast preflight that serializes the full parallel suite against a LOADED LM-Studio model — it refuses only when `/v1/models` on 127.0.0.1:1234 is non-empty (or unreadable, fail-closed) while workers > 4, or when free RAM is below 20% of total. An idle server (port open, zero models) is allowed — so stop or unload the model(s) before re-running only when the refusal names loaded models. R&D-only tests (marked `research`, e.g. SRS-simulation quarantines) are excluded unless `HAMZABAN_INCLUDE_RESEARCH=1` or the caller passes its own `-m`.

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
- `git diff --check` validates no whitespace errors in working tree AND staging area
- The lightweight path exists specifically to avoid the bottleneck of running pytest/compile/ruff on doc/tooling-only changes.