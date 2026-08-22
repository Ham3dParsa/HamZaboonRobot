---
name: plan-freeze-prompt-reveal-phase-03-persist
description: Persist prompt/reveal on first render, reveal, and advance + daily discard
created: 2026-08-22
base_commit: 51690d0bf305772ed05d01e7fa5ef4edd1a49c4f
branch: fix/freeze-prompt-reveal
status: pending
---

STATE: phase 3/4 — status: pending — focus: persistence lifecycle

## Blocking Edges
- Depends On: phase 01 (can run in parallel with phase 02, but merge after both)

## Scope
- `handlers/study_handler.py`
  - `handle_study_start` fresh build: init revealed=False, active_prompt_type=None
  - `_render_and_send_first_card`: after `_build_card_text_and_keyboard` (which now sets frozen fields), call `_persist_session` with new study_msg_id (already does; ensure frozen fields included)
  - `_resume_existing_session`: rely on phase 02 deterministic render; after send, persist updated study_msg_id (keep revealed/prompt untouched)
  - `advance_session`: pop old node → reset revealed=False, active_prompt_type=None, active_prompt_word_id=None for next card; next `_build_card_text_and_keyboard` will set new frozen values; persist after successful edit. On edit failure rollback, also rollback frozen fields.
- `handlers/srs_handler.py`
  - `_handle_srs_reveal`: after successful `send_pretty.edit`, set state.revealed=True (keep active_prompt_type), call `_persist_session(user_id, state)`, also set `user_data[f"revealed_{word_id}"]=True`
  - Guard: if already revealed, idempotent (already handled) — still persist no-op
- Daily discard already exists in `_restore_persisted_session` date check; verify phase 01 fields don't leak (new day = cleared)

## Contract Rules
- R1,R2,R3,R5,R6

## Tests
- New integration `tests/test_integration/test_freeze_prompt_reveal_flow.py`:
  - front → reveal → resume (callback) → still back
  - front → resume (no reveal) → same front prompt (assert text equality)
  - front → reveal → restart (clear user_data, restore from DB) → still back
  - yesterday persisted session not resumed (date ≠ today → fresh build)
- Existing: `test_srs_staged_reveal.py::TestRevealHandler::test_reveal_idempotent` still passes and also checks DB field

## Gates
- DB: no DDL, JSON only
- Restart-safe: fake restart test (drop current_session from user_data, call get_active_study_session)

## Wiring Rows
| Dependency type | Items | Disposition |
|---|---|---|
| Persistence | _persist_session calls in study_handler + srs_handler | update (add call in reveal) |
| Session grade | advance_session reset logic | update |

## Acceptance Criteria
- `study_sessions.state_json` after first render contains active_prompt_type; after reveal contains revealed=true; after grade next card gets new prompt
- Fake restart after reveal resumes as back stage
- Yesterday row not resumed (assert new nodes)

## Evidence
- TBD
