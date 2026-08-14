# Phase 04 — Builtin removal (F1)

**STATUS: implementing — impl+tests done, full suite passing (848) — pending independent review + PR.** contract LOCKED 2026-08-13 (owner chose Option A for all 6 rules: "proceed").
- **Reviewer note:** R6 sweep extended to `tools/AI_preset_manager/index.html` (removed `is_custom` filter chip, filter branch, view/panel field, edit input, and boolFields entry) after independent review flagged the web-UI gap. ROADMAP Phase 4 entry updated.
- **Full removal:** drop the `is_custom` column from `ai_presets` (schema migration), not just stop using it. All presets become custom; DB is the single source of truth; admin panel is the sole input source.
- **T06 Persistence done:** T06 Phase 03 FSRS grade transitions merged (#336, `f77214c`) + docs `3e71170`, then owner pushed `d257a1a`. Phase 4 base = `d257a1a` (origin/main).
- **Worktree:** `.worktrees/preset-phase4-builtin` on branch `feat/ai-preset-phase4-builtin-removal`.
- **Claims acquired:** Persistence, Telegram UI -> Admin, Telegram UI -> AI Config (P4-R1..P4-R6).

- **Blocking edges:** Phase 02 (preset model stable) before removing builtins; T06 Persistence completion before Phase 4 schema migration.
- **Scope (files):**
  - `services/ai/ai_presets.py` — remove `BUILTIN_PRESETS` seed + refs (`get_builtin_preset`, `list_builtin_presets`).
  - `services/db/schema.py` — remove builtin seed INSERT / `seed_presets()` call (line 431 `gapgpt_gemini_lite` setting) + DROP `is_custom` column migration. **[Persistence-blocked — wait for T06]**
  - `services/db/preset_registry.py` — remove `gapgpt_gemini_lite` fallback literal defaults (lines 28, 464); remove `is_custom` from clone/copy field handling (already forced to 1 in Phase 3). **[Persistence-blocked]**
  - `handlers/admin_ai.py` — remove `gapgpt_gemini_lite` emergency builtin refs; remove `is_custom` guards (all presets editable/deletable); rely on `is_emergency` flag.
  - `config/keyboards.py` — remove `is_custom` conditionals in `ai_presets_list_keyboard` / `ai_preset_view_keyboard` (always show EDIT/DELETE).
  - `bot.py` + `tools/benchmark/__init__.py` — remove `get_builtin_preset` refs.
- **Tests:** `tests/test_preset_registry.py` (no builtins seeded); `tests/test_integration` (custom-only presets); `tests/test_db_migrations.py` (schema upgrade DROP is_custom on fresh + prior schema); `tests/test_wiring.py` (keyboard/route updates).
- **Gates:** F1.
- **Wiring rows:** Persistence (seed removal, DROP column) remove; AI Config (builtin refs) remove; keyboard builders update (remove is_custom branches).
- **Acceptance:** no hardcoded builtins; `is_custom` column gone; existing DB rows become ordinary presets; emergency = `is_emergency` flag; no references to `gapgpt_gemini_lite`; fresh + upgraded DB both tested.
