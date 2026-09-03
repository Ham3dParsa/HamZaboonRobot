---
name: plan-zero-hardcode-phase-01-display-fallbacks
description: Remove 'gapgpt' display/logic fallbacks (candidate A)
created: 2026-09-04
base_commit: 6ad2fb6ca704bd8c624339c62130c7e59522a87c
branch: fix/preset-zero-hardcode
status: complete
---
STATE: phase 1/4 — status: complete — focus: done (commit c188db9)

## Blocking edges
- None (first).

## Scope (exact files/lines)
- `handlers/admin_ai.py:124` → real active name or `"—"`, no `'gapgpt'`.
- `handlers/admin_ai.py:1680` → same.
- `handlers/admin_ai.py:1724-1725` → no `get_preset("gapgpt")`; missing candidate = explicit error.
- `handlers/admin.py:456` → same as :124.
- No callback_data change (labels/logic only).

## Tests
- Update `tests/test_integration/test_admin_ai_render_flow.py:293` (asserts `Candidate (gapgpt)`).
- Focused run: `pytest tests/test_integration/test_admin_ai_render_flow.py tests/test_integration/test_custom_test_prompt_flow.py tests/test_wiring.py`.
- TDD: red (assert no-preset error) → green → refactor.

## Gates
- Satisfies R1. Callback impact: none (no prefix change). `hamzaban-reviewer` after implement.

## Acceptance
- `grep -rn "gapgpt" handlers/` → zero hits.
- No-preset custom-test shows explicit error, never invents a preset.
- Reviewer: 0 confirmed findings.

## Evidence (T1 complete, commit c188db9)
- `test_custom_test_results_escapes_card_fields` (real `cand_real` candidate) — PASS.
- `test_custom_test_missing_candidate_shows_explicit_error` (red before fix, green after) — PASS.
- Focused suite: `test_admin_ai_render_flow.py + test_custom_test_prompt_flow.py + test_wiring.py` — 51 passed, 10 subtests passed.
- `scripts/compile_all.py` — clean; `ruff --select F821,F811` on touched files — clean; `git diff --check` — clean.
