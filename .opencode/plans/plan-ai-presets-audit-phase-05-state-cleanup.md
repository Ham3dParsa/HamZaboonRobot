# Phase 05 — State cleanup: redundant routing + awaiting + cancel (R5, R8, R9)

## Blocking edges
- None.

## Scope
- `handlers/admin_ai.py` `_show_ai_settings` — delete the `if update.callback_query:`
  branch; call `_edit_or_send(...)` directly (R5).
- `handlers/admin.py` `_handle_admin_callback`:
  - `admin:back` (line 183-185) — pop any pending admin awaiting state before
    re-rendering (R8). Cover `ai_fallback_rank:*`, `admin_group_batch_key`,
    `admin_group_set_label`, `admin_group_manager_rename` (and the generic admin path).
  - `admin:cancel` (line 186-189) — also pop `preset_edits` and `full_edit` (R9).
- Coordinate with issue #136 item 3/#136-4b (awaiting-flow family) to avoid divergent
  changes to `_handle_admin_text_input` / `_handle_admin_callback`.

## Tests
- Integration (routing seam): while `awaiting = ai_fallback_rank:...`, dispatch
  `admin:back` and unrelated admin nav; assert `awaiting` is popped.
- Integration: dispatch `admin:cancel` after entering field edits; assert
  `preset_edits`/`full_edit` cleared.

## Gates
- R5 (redundant routing), R8 (general awaiting cleanup), R9 (cancel clears all state).

## Wiring rows
| Dependency type | Items | Disposition |
|---|---|---|
| Handlers | `_show_ai_settings`, `_handle_admin_callback` (back/cancel) | update |
| Awaiting state keys | `ai_fallback_rank:*`, `admin_group_batch_key:*`, `admin_group_set_label:*`, `admin_group_manager_rename:*` | update (cleared on back/nav) |
| Tests | integration awaiting-cleanup, cancel-cleans-state | add |
| Issue #136 | items 3/4b | coordinate / reference |

## Acceptance criteria
- Tapping Back from any awaiting prompt clears the state; next message is not
  misapplied; Cancel clears all in-memory state.
