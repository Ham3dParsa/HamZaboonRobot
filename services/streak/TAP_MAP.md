# Streak Boolean-Tap Debt Map (REF6-T2, docs-only)

> No behavior change. This file registers the current Boolean per-tap streak
> behavior as tech debt and points to the future RULE-001 fix
> (SessionCompleted-only streak). See `services/streak/__init__.py` for the
> canonical in-code map.

## Ownership

- Pure date math single owner: `services/streak/__init__.py:next_streak`
- Thin delegates: `services/db/users.py:265-289` (`touch_streak_in_txn`, `touch_streak`)
- Grade bodies: `services/db/words.py:441-517` (`grade_word_review`) and `services/db/words.py:520-584` (`grade_first_exposure`)
- Facade: `services/grade_service.py:61-98` (`grade(..., with_streak=False)`)

## Map

| # | Location | Transaction shape | Debt | Why not fixed here |
|---|----------|-------------------|------|--------------------|
| 1 | `services/word_query.py:286-295` | `create_query_result` (txn 1) + `touch_streak` (txn 2) — two separate `transaction()` blocks | Crash between txns leaves card without streak; streak not atomic with card | Merging would change quota/streak accounting and mask separate-txn failure mode (naive risk) |
| 2 | `services/db/words.py:511-512` (`grade_word_review`) | `touch_streak_in_txn(conn, user_id)` on same `transaction()` as FSRS update + `mark_word_graded` + optional `insert_review_event` when `with_streak=True` | Boolean — even `grade=1` (Again) advances streak when caller passes `with_streak=True` | Adding grade gate (`grade >= 2`) would change product semantics before owner lock |
| 3 | `services/db/words.py:578-579` (`grade_first_exposure`) | Same single-txn folding as #2, `activity_type="first_exposure"` | Same Boolean debt; familiarity rating still taps streak | Same gate prohibition |

## Call sites (`with_streak=True`)

- `handlers/srs_handler.py:414-423` — `_handle_srs_review` → `grade_service.grade(..., activity="srs_review", with_streak=True)`
- `handlers/srs_handler.py:586-595` — `_handle_first_exposure_grade` → `grade_service.grade(..., activity="first_exposure", with_streak=True)`
- `services/word_query.py:295` — `ask()` → `db.touch_streak(user_id)` (standalone, always taps on successful card persist)
- `handlers/user.py` — no direct streak tap (settings/onboarding only)
- `services/grade_service.py:70,88,97` — default stays `with_streak=False`; facade does not flip

## Constraints (REF6-T2)

- NO default flip (`with_streak` stays `False` in both grade bodies and facade)
- NO grade gate (`grade >= 2` or any value filter)
- NO txn merge for word_query card+streak
- `next_streak` keeps fail-closed `fromisoformat` propagation (no try/except) so rollback semantics are byte-identical
- Future: RULE-001 will advance streak only on `SessionCompleted` (drained `advance_session` before clear) and remove all per-tap `touch_streak` calls — BLOCKED until owner says "locked"

## Verification

- `test_word_query.py:116` (touch called) / `:167` (not called on failure)
- `test_grade_write_batch.py:84-287` (single-txn batch incl. streak, day-boundary, `with_streak` parity)
- `test_integration/test_study_session_grade_restart.py` (streak touch via `words.py:touch_streak_in_txn` mock)
- `pytest`, `compile_all.py`, `ruff F821/F811` — lightweight docs path uses `git diff --check` only (no behavior change)
