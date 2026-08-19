---
name: srs-delete-card-fe-pronounce-phase-01-db
description: Phase 1 — delete_saved_word DB function (Rule 4)
created: 2026-08-19
base_commit: 6305c18
branch: feat/srs-delete-card
status: in-progress
---
STATE: phase — status: DONE (merged via PR #406) — was: add delete_saved_word to services/db/words.py

## Blocking edges
- None (first ticket).

## Scope
- `services/db/words.py`: add `delete_saved_word(word_id, user_id) -> bool` — physical `DELETE FROM saved_words WHERE id=? AND user_id=?`, normalized (returns rowcount>0), idempotent (deleting a missing row returns False, no error). Ownership enforced by the `(id, user_id)` predicate.

## Tests
- `tests/test_srs_staged_reveal.py` (or a focused DB test): delete removes the row; second delete returns False (idempotent); wrong user_id does not delete.

## Gates
- Satisfies Rule 4 (physical delete semantics).

## Wiring rows
| Dependency type | Items affected | Disposition |
|---|---|---|
| DB functions | `services/db/words.py::delete_saved_word` | add |

## Acceptance criteria
- `delete_saved_word` removes only the matching `(id, user_id)` row; idempotent; covered by a test that passes.