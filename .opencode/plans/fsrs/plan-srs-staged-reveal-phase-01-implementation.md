---
name: srs-staged-reveal-phase-01-implementation
description: Execution plan for #338 — randomized staged-reveal prompts, display-toggle system, delete-with-confirm, telemetry (R1-R12)
created: 2026-08-15
base_commit: b735c5d
branch: feat/srs-staged-reveal
status: in-progress
---

STATE: phase 1/3 — status: MERGED via PR #353 (squash `c920edb`, 2026-08-15) — R6 (physical delete) + R9 (explanation = high-value) + PHONETIC-KNOB clarified & LOCKED (2026-08-15); Phase-1 RED→GREEN complete; independent review (hamzaboon-reviewer) no confirmed findings; Kilo review clean (No Issues Found); full suite 927 passed/162 subtests; ruff/compile/diff-check clean — Phase 2/3 pending

## Phonetic-knob decision (owner, 2026-08-15)

The legacy global admin `phonetic_show_ipa` setting + `get_phonetic_display_settings()`
are **removed** (dead/ambiguous: never consumed by the render path). The `phonetic`
display toggle becomes the single source of truth, behaving exactly like the other
toggles: admin-global default (`settings.display_toggle_defaults["phonetic"]`) →
per-user override (`users.display_toggles["phonetic"]`) → admin-forced
(`users.display_toggles_forced["phonetic"]`). Admin panel "phonetics" section rewired
to edit the admin-global default. `DEFAULT_PHONETIC_SHOW_IPA` removed from config.

# #338 SRS Staged-Reveal — Implementation Plan

Spec: `../session/plan-srs-staged-reveal-spec.md` (LOCKED, R1-R12). Tracking issue: #338.

## Launch gates (verified closed 2026-08-15)
- FSRS T09 (#309) closed: `0391eea`.
- AI-preset Persistence + Admin seams released: phases 4/5 merged (`f185822`, `0d9a491`, `b735c5d`); no AI-preset claim remains.
- Parallel claims: ours (seams 1,3,4,5,6,8) + per-language-goals (seam 7). Disjoint.

## Phases

### Phase 1 — Prompt engine + display-toggle resolution (pure logic)
Files: `services/utils/formatting.py`, `services/db/users.py`+`settings.py` (toggle storage/resolution).
- Toggle fields: explanation, synonyms, antonyms, examples, example_translations, grammar_tip, phonetic.
- Resolution precedence: admin-forced per-user > per-user > admin-global defaults.
- Prompt types: standard / fill_blank / meaning / synonym / direct_translate. Injectable seeded RNG.
- Eligibility guards (R11): synonym needs draw; fill_blank needs example w/ exact word; standard always eligible.
- RED: `tests/test_srs_prompt_engine.py`, toggle tests in `tests/test_reliability.py`/`test_config.py`.

### Phase 2 — Session flow staging + callbacks + keyboards
Files: `handlers/study_handler.py`, `config/keyboards.py`, `bot.py` router.
- srs_review → front stage (prompt + reveal/delete keyboard); reveal → back stage (grades).
- first_exposure → full card directly (badge `کارت جدید ✨`).
- New callbacks: `srs:reveal:`, `srs:delete:`, `srs:delete:yes:`, `srs:delete:no:`.
- RED: `tests/test_wiring.py`, `tests/test_study_handler.py`, `tests/test_integration/test_srs_staged_reveal_flow.py`.

### Phase 3 — SRS handler telemetry + delete + user/admin toggle UI
Files: `handlers/srs_handler.py`, `handlers/user.py`, `handlers/admin.py`.
- raw_signal += prompt_type + revealed (R8); response_time_ms from prompt→grade (R12).
- Delete with confirm (R6): permanent remove-from-review.
- Per-user toggle editing + warning popup (R7/R9); admin-global defaults + optional override (R10).
- RED: `tests/test_srs_staged_reveal.py`, admin integration tests, wiring.

## Verification gates
`tests/test_wiring.py` (new srs: prefixes), `tests/test_dead_code_guard.py` (orphaned `format_srs_prompt`), `tests/test_formatting.py`, full §6 suite.

## Blocked Questions
None.