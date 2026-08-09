# Phase 03 — Callback 64-byte fix: hash long identifiers + field aliases (R3)

## Blocking edges
- Must run after Phase 02 only if length caps change which values can reach keyboards
  (informational — callbacks must still be safe for all valid lengths).

## Scope
- `config/keyboards.py` — `ai_preset_edit_keyboard` (and any other overflow-prone
  builders): emit short field aliases + hashed preset names / group labels.
- `handlers/admin_ai.py`:
  - Add a **field-alias map** for `WIZARD_FIELDS` closed set.
  - Reuse `_key_hash`-style deterministic hash (sha256[:12]) for preset names and
    Persian group labels.
  - `handle_ai_callback` / `_handle_full_edit_pick_group` / `_handle_group_manager_*
    /_show_wizard_field` — reverse-resolve hashes by scanning `db.get_presets()` /
    `db.get_group_labels()`.
- **Static prefixes must remain unchanged** (test_wiring guard).

## Tests
- `tests/test_keyboards.py` — add a ≤64-byte assertion on every `ai_preset_edit_field:*`
  (and overflow-prone) callback.
- New integration test: hash→value round-trip through the real routing path resolves
  to the correct preset/label and edits the intended field.

## Gates
- R3 (hash long callback identifiers).

## Wiring rows
| Dependency type | Items | Disposition |
|---|---|---|
| Callback prefixes | `edit_field`, `full_edit_pick_group`, `group_manager_rename`, `group_manager_clear`, and audited `view/activate/edit/delete/full_edit*/confirm_save_*/discard_all/save`, `fallback:move_*`, `fallback:toggle/rank/set_emergency`, `ai_fallback:pick_*` | keep static prefix; update payload |
| Router branches | `handle_ai_callback`, `_handle_full_edit_pick_group`, `_handle_group_manager_rename/clear` | update (resolve hash) |
| Keyboard builders | `ai_preset_edit_keyboard`, `ai_presets_list_keyboard`, `ai_preset_view_keyboard` | update |
| Tests | `test_keyboards.py`, integration callback round-trip | update/add |
| Wiring guard | `tests/test_wiring.py` | keep (static prefixes unchanged) |

## Acceptance criteria
- Every callback in the panel ≤64 bytes; hash resolution returns the correct value;
  wiring guard still green.
