---
name: plan-freeze-prompt-reveal-phase-02-render
description: Deterministic front/back render using frozen state
created: 2026-08-22
base_commit: 51690d0bf305772ed05d01e7fa5ef4edd1a49c4f
branch: fix/freeze-prompt-reveal
status: pending
---

STATE: phase 2/4 — status: pending — focus: render determinism

## Blocking Edges
- Depends On: phase 01

## Scope
- File: `handlers/study_handler.py`
  - `_build_card_text_and_keyboard`: if state.revealed and state.active_prompt_word_id==word_id and staged mode → render back_stage + grade keyboard (review/FE) via `format_srs_back_stage`; else if not revealed but active_prompt_type matches word_id → reuse that prompt_type (no new random), set user_data stashes; else (first time seeing this card) → pick prompt via `select_srs_prompt_type`, store in state.active_prompt_type/active_prompt_word_id/revealed=False (caller persists)
  - `_render_first_exposure`: same logic for FE staged branch (share helper or inline)
  - Remove unconditional `user_data.pop(f"revealed_{word_id}")` re-arm on resume — only re-arm when advancing to next card
- File: `handlers/srs_handler.py` — no edit in this phase (reveal handler edits next phase)
- Behavior: resume no longer re-rolls, immediate mode still bypasses

## Contract Rules
- R1,R2,R3

## Tests
- Update `tests/test_study_handler.py::TestStagedRevealRender::test_front_stage_re_render_re_arms_reveal` — now expects NOT re-armed when same word_id frozen
- New: `tests/test_study_handler.py::TestFreezePromptDeterminism` — second call with same state returns identical text/callbacks
- Integration: `tests/test_integration/test_study_session_restart_flow.py` — add resumeKeepsSamePrompt test

## Gates
- Wiring integrity: callbacks unchanged, no new prefixes

## Wiring Rows
| Dependency type | Items | Disposition |
|---|---|---|
| Handler function | _build_card_text_and_keyboard, _render_first_exposure | update |
| Formatting helper | select_srs_prompt_type, format_srs_front_stage | keep (called conditionally) |

## Acceptance Criteria
- Two consecutive `_build_card_text_and_keyboard` with same frozen state produce identical front text and `srs:reveal:{uid}:{wid}` (no random drift)
- If state.revealed=True, call returns back_stage + `srs:{1..4}` / `srs:fe:{1..4}` keyboard
- Existing prompt-engine tests still pass

## Evidence
- TBD
