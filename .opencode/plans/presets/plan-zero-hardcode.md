---
name: plan-zero-hardcode
description: Zero hardcoded AI presets + retire dead migrations (R17 enforcement)
created: 2026-09-04
base_commit: 6ad2fb6ca704bd8c624339c62130c7e59522a87c
branch: fix/preset-zero-hardcode
status: in-progress
---
STATE: phase 4/4 — status: complete — focus: PR + kilo-ci-loop until mergeable

## Contract Lock (GATE STATUS = LOCKED, 2026-09-04, owner chose per rule)
- R1 display fallback: اسم واقعی + خطای صریح (locked).
- R2 model fallback: خالی برگردد (locked).
- R3 empty defaults: همه خالی شود (locked).
- R4 reconcile block: کامل حذف شود (locked).
- R5 old migrations: الان حذف شود (locked).

<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE> — satisfied: owner answered each rule independently above.

## Goal
Single source of truth: presets live only in DB via admin panel. No gapgpt literals, no seeded ai_* settings, no every-boot legacy→preset reconcile. Reinforces R17 (preset row is the only source).

## Order (deepening-first, per architecture review)
| Phase | Ticket | Depends On | Status |
|-------|--------|------------|--------|
| 1 | `plan-zero-hardcode-phase-01-display-fallbacks.md` (candidate A) | — | pending |
| 2 | `plan-zero-hardcode-phase-02-model-fallback.md` (candidate B) | Phase 1 | pending |
| 3 | `plan-zero-hardcode-phase-03-defaults.md` (zero-hardcode) | Phase 1, 2 | pending |
| 4 | `plan-zero-hardcode-phase-04-migrations.md` (candidate C) | Phase 3 | pending |

## Rules (lock each independently)
- R1: display fallbacks `'gapgpt'` → real active name or explicit no-preset error (alt: `"—"` placeholder).
- R2: `_model` returns `resolve` only, drop `or DEFAULT_AI_MODEL` (alt: keep env fallback for model only — rejected, violates R17).
- R3: config/seed defaults to `""`, stop seeding `ai_base_url/ai_api_key/ai_model` (alt: keep env binding with empty default — same thing).
- R4: delete reconcile block `schema.py:839-880` entirely (alt: gate behind marker — keeps dead code).
- R5: delete `is_custom` rebuild + HpOF fix now (alt: defer to later cleanup).

## Gates per phase
- Each phase: focused tests + `test_wiring.py` if callbacks touched + `hamzaban-reviewer` (0 confirmed findings) + `git diff --check` + full suite for behavioral.
- Single PR at the end; PR comment cycle until mergeable.

## Deliberately Not Done
- Pointer keys (`ai_primary_preset`, `ai_fallback_*`) stay — live routing state.
- `preset_groups` + orphan cleanup stays — live.
- `_encrypt_key_columns` stays until prod proven `v1:`-only.
- Docs/history files untouched (only `.env.example:13` placeholder).
