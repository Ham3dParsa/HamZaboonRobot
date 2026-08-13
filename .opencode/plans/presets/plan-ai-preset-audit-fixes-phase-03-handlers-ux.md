# Phase 03 — New handlers / UX (R3, R4, R5, R7)

**STATUS: completed** — locked 2026-08-13; implemented on `feat/ai-preset-handlers-ux` (base `main@a38841a`, Phase 2 merged), PR pending. Owner-added decisions during gate:
R4 duplicate forces `is_custom_override=True` so any clone is immediately editable; R5 wizard shows BOTH stored (مقدار فعلی, or خالی when empty) AND in-progress draft (پیشنویس / در انتظار ذخیره). Verified by full suite (805 pass) + routing/formatting guards.

- R3 A: two-step delete confirm, inline on detail page (✅/❌), matching `confirm_save_yes/no`.
- R4 A: `db.clone_preset(name, new_name, is_custom_override=None)` clones all fields except name; Duplicate Preset default `<old> (copy)`. DONE — duplicate preset only.
- R5 A: add `IBTN_FULL_EDIT_BACK` → `admin:ai_preset:full_edit_back` to the ai_preset wizard; back only shown when `field_idx > 0`; re-renders current+draft.
- R7 A: `_show_fallback_usage_details` paginate `per_page=5`, ‹ قبلی / بعدی › callbacks (`admin:fallback:usage_page:<abs_idx>:prev|next`), edit-in-place (no re-send).

**Deliberately NOT changed (owner chose to defer to Phase 4):** `is_custom`/built-in field is still present (Phase 4 removes it entirely); the `is_custom` conditional in `ai_preset_view_keyboard` (EDIT/DELETE vs EDIT_COPY) remains. **Duplicate Group** sub-flow (prompt new group name/key/URL then clone members) was not implemented — out of the locked R4 owner scope (preset duplication only). No `bot.py` `callback_router` change was needed: new `admin:ai_preset:*` / `admin:fallback:usage_page:*` routes are covered by the existing `data.startswith("admin:")` branch delegating to `_handle_admin_callback` → `handle_ai_callback`. No `handlers/admin.py` awaiting change needed (new prefixes are callback-only, no new text-await state).

- **Blocking edges:** R14 create flow (Phase 02) exists for R4 clone; R8 render (Phase 01) for detail pages.
- **Scope (files):**
  - `handlers/admin_ai.py` — R3 `_delete_ai_preset` confirm + `_confirm_delete_yes/no`; R4 `_duplicate_ai_preset` (clone + is_custom_override=True); R5 `_handle_full_edit_back` + `_show_wizard_field` current+draft display; R7 `_show_fallback_usage_details`/`_show_usage_page` pagination.
  - `config/keyboards.py` — `IBTN_DELETE_CONFIRM`, `IBTN_DELETE_CANCEL`, `IBTN_DUPLICATE`; `IBTN_DUPLICATE` button in `ai_preset_view_keyboard`.
  - `services/db/preset_registry.py` (+ re-export in `services/db/__init__.py`) — `clone_preset` gains optional `is_custom_override`.
  - `tests/test_integration/test_ai_preset_handlers_ux.py` — R3/R4/R5/R7 integration harness + 8 tests.
  - No `bot.py` / `handlers/admin.py` change (existing routing covers all new prefixes).
- **Tests:** `tests/test_wiring.py` (new prefixes routed ✓); `tests/test_integration/test_ai_preset_handlers_ux.py` (delete confirm, duplicate + is_custom, edit nav + current/draft, pagination ✓); `tests/test_dead_code_guard.py` ✓.
- **Gates:** R3, R4, R5, R7.
- **Wiring rows:** AI Config (handlers) update; callback prefixes add; Admin (awaiting) update.
- **Acceptance:** delete requires confirm; duplicate preset works and forces editable custom; edit nav consistent + shows current and draft; usage paginated, no re-send overflow.
