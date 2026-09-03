---
name: plan-zero-hardcode-phase-02-model-fallback
description: Consolidate _model into resolve (candidate B)
created: 2026-09-04
base_commit: 6ad2fb6ca704bd8c624339c62130c7e59522a87c
branch: fix/preset-zero-hardcode
status: pending
---
STATE: phase 2/4 — status: complete — evidence: commit fix(ai) T2; tests/test_ai_model_fallback.py 4 passed (red-first: empty-resolve failed pre-fix inventing env model); pytest focused files 31 passed + 20 subtests; compile_all OK; ruff F821/F811 clean; git diff --check clean; grep DEFAULT_AI_MODEL in services/ai/ai.py → 0 hits

## Blocking edges
- Phase 1 reviewed (order only; no code overlap).

## Scope
- `services/ai/ai.py:115-123` → `_model` returns `resolve` only; drop `or DEFAULT_AI_MODEL`.
- `services/ai/ai.py:26-27` → drop `DEFAULT_AI_*` imports if unused.
- Keep `timeout/temperature/max_tokens` env defaults (out of scope).

## Tests
- `tests/test_preset_fields.py` untouched in this phase (config_default still present until phase 3).
- Add/adjust unit test: empty-model preset returns `""` (never invents `gapgpt-qwen-3.6`); `preset=None` still raises `NoActivePresetError` via `get_active_preset`.
- Run: `pytest tests/test_preset_fields.py tests/test_ai_preset_manager.py`.

## Gates
- Satisfies R2. `hamzaban-reviewer` after implement.

## Acceptance
- `grep -rn "DEFAULT_AI_MODEL" services/ai/ai.py` → zero hits.
- Empty model surfaces provider/validation error, never silent gapgpt call.
