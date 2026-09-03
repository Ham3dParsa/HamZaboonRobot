---
name: plan-zero-hardcode-phase-03-defaults
description: Zero config/seed defaults (R3)
created: 2026-09-04
base_commit: 6ad2fb6ca704bd8c624339c62130c7e59522a87c
branch: fix/preset-zero-hardcode
status: pending
---
STATE: phase 3/4 — status: complete — implemented 2026-09-04 on fix/preset-zero-hardcode; evidence: TDD red (3 failures showing live gapgpt defaults) -> green; full pytest 1675 passed + 1 pre-existing failure (test_custom_test_ab_runs_via_to_thread_twice, fails at HEAD be6ddff too); compile_all ok; ruff F821/F811 ok; git diff --check clean; grep gapgpt -> 1 hit left (schema.py HpOF comment, phase-4 scope, untouched).

## Blocking edges
- Phases 1, 2 reviewed (clean ground; `resolve` is the only reader).

## Scope
- `config/__init__.py:9,11` → `os.getenv("AI_BASE_URL","")`, `os.getenv("AI_MODEL","")`.
- `config/catalog.py:6,213` → `ai_model` default `""` (drop import if unused).
- `services/ai/preset_fields.py:25-26,41,47` → drop `config_default` for `base_url`/`model` (keep timeout/temperature/max_tokens).
- `services/db/schema.py:16-18,748-750` → drop 3 `ai_*` seed entries + imports.
- `.env.example:13` → placeholder URL + "set via admin preset" comment.
- `scripts/benchmark_format_comparison.py:28`, `scripts/xray/update_subscription.sh:16` → env/placeholder, no gapgpt literal.

## Tests
- Update `tests/test_preset_fields.py:68-77` (`resolve({})` → `""` for base_url/model).
- Update `tests/test_integration/test_custom_test_prompt_flow.py:35` (rename `gapgpt` fixture).
- Run full: `pytest tests/ -n 14`, `compile_all.py`, `ruff F821/F811`, `git diff --check`.

## Gates
- Satisfies R3. `hamzaban-reviewer` after implement.

## Acceptance
- `grep -rni "gapgpt" config/ services/ handlers/ bot.py .env.example` → zero hits (tests/docs-history excluded).
- Fresh DB: zero presets, `get_active_preset` raises, admin prompts to create — no invented URL/model.
