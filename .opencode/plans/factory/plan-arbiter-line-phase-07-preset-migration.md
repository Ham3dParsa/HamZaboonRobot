# Phase 07 — P6 judge→AI-preset migration (D5/D6)

Gates: D5/D6. Blocking: none (independent of P0–P5; own PR).
Scope: full rename across the console — preset store
(`factory/webui` preset helpers + data files), routes
(`/api/judge_presets*` → `/api/ai_presets*`, no aliases), UI strings +
JS (`preset_catalog_controller.js`, provider form, batch/arbiter
panels), tests, RUN_GUIDE. Step prompts stay cabin-owned and untouched
(`arbitration_prompt.py`, precard prompts). Bot presets
(`services/ai`, `handlers/admin_ai*`) explicitly OUT (D5: unrelated).
Tests: grep-zero `judge_preset`/`judge-preset`/`پریست داوری` outside
changelog/history — EXCEPT stable element IDs (`btn-save-judge-preset`,
kept intentionally as DOM hooks; user-facing strings and routes are
fully renamed). full factory suite green.
Acceptance: console manages AI presets usable by precard + linking +
future pilot; no behavior change besides names.
