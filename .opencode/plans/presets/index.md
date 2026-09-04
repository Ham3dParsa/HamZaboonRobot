---
name: presets
Scope: Admin AI Preset panel audit fixes (R1–R15, F1/F2) + R16 (reasoning-effort #241) + R17 (activation/preferred)
---
## Plans & Dependency Edges

| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-ai-preset-audit-fixes.md` | 1..7 | — | in-progress |
| `plan-ai-preset-audit-fixes-phase-01-cosmetic.md` | 1 | — | complete (PR #333 merged) |
| `plan-ai-preset-audit-fixes-phase-02-db-correctness.md` | 2 | R2 before R14 | complete (PR #333 merged) |
| `plan-ai-preset-audit-fixes-phase-03-handlers-ux.md` | 3 | Phase 2, Phase 1 | complete (PR #334/#335 merged) |
| `plan-ai-preset-audit-fixes-phase-04-builtin-removal.md` | 4 | Phase 2 | complete (PR #337 merged) |
| `plan-ai-preset-audit-fixes-phase-05-secure-keys.md` | 5 | Phase 2, Phase 4 | complete (PR #339 merged; archived to docs/archive/) |
| `plan-ai-preset-audit-fixes-phase-06-activation-preferred.md` | 6 | Phase 2,4,5 | pending |
| `plan-ai-preset-audit-fixes-phase-07-reasoning-effort.md` | 7 | Phase 5, Phase 2 | pending |
| `plan-admin-ai-labels-and-back.md` | — | — | complete (PR #352 merged; archived to docs/archive/) |
| `plan-zero-hardcode.md` | 1..4 | `presets/plan-zero-hardcode-phase-NN` | in-progress |
| `plan-zero-hardcode-phase-01-display-fallbacks.md` | 1 | — | in-progress |
| `plan-zero-hardcode-phase-02-model-fallback.md` | 2 | Phase 1 | pending |
| `plan-zero-hardcode-phase-03-defaults.md` | 3 | Phase 1, 2 | pending |
| `plan-zero-hardcode-phase-04-migrations.md` | 4 | Phase 3 | complete (T4 committed, unpushed) |
| `plan-preset-save-preview.md` | 1..3 | `presets/plan-preset-save-preview-phase-NN` | in-progress |
| `plan-preset-save-preview-phase-01-helper.md` | 1 | — | pending |
| `plan-preset-save-preview-phase-02-edit-menu.md` | 2 | Phase 1 | complete (uncommitted) |
| `plan-preset-save-preview-phase-03-confirm.md` | 3 | Phase 1, 2 | pending |
| `plan-preset-save-preview-phase-04-display-value.md` | 4 | Phase 3 | pending |
| `plan-preset-save-preview-phase-05-render-seam.md` | 5 | Phase 4 | pending |
| `plan-preset-save-preview-phase-06-keyboard-diffs.md` | 6 | Phase 4, 5 | pending |
| `plan-preset-panel-ux.md` | 7..10 | `presets/plan-preset-panel-ux-phase-NN` | in-progress |
| `plan-preset-panel-ux-phase-07-keyboard.md` | 7 | — | pending |
| `plan-preset-panel-ux-phase-08-view-stats.md` | 8 | Phase 7 | pending |
| `plan-preset-panel-ux-phase-09-feedback-notes.md` | 9 | Phase 7 | pending |
| `plan-preset-panel-ux-phase-10-wizard.md` | 10 | Phase 7 | pending |
