# Rule 3: Admin Navigation + TTS Toggle Implementation Plan

## Project
HamZaboon — Telegram Persian language-learning bot (Python 3.13, python-telegram-bot v21.6, SQLite, OpenAI-compatible AI)

## Branch
`fix/admin-nav-tts-toggle` (from `main` at commit `ec2bc07`)

## Files to modify
- `bot.py` — line numbers may have shifted from PR #134 edits
- `keyboards.py`
- `admin.py` — has 6 duplicate function pairs (lines ~1302–1417 dead, ~1420–1516 live)
- `db.py`
- `tests/test_wiring.py` — may need ALLOWLIST update if new callback prefixes added

---

## B1 — Fix Add Preset Awaiting Routing

**Root cause:** `_add_ai_preset` (admin.py ~1034) sets `awaiting = "ai_preset_new_name"`. But `text_router` (bot.py ~666) only routes awaiting starting with `"admin_"`, `"llm_cost_"`, or `"llm_price_"`. `"ai_preset_new_name"` falls through → user gets main menu reply.

**Fix:**
1. `admin.py:1036`: change `"ai_preset_new_name"` → `"admin_ai_preset_new_name"`
2. `admin.py` `_handle_admin_text_input`: add `elif awaiting == "admin_ai_preset_new_name":` that calls `_handle_ai_preset_new_name(update, context, text)` and returns

---

## B2 — Delete 6 Duplicate Function Pairs

**6 functions defined twice in admin.py (lines ~1302–1417 first def, ~1420–1516 second def):**
- `_show_ai_pending`
- `_apply_ai_pending`
- `_rollback_ai_pending`
- `_show_ai_fallback`
- `_handle_ai_fallback`
- `_show_fallback_preset_picker`

**Fix:** Delete lines 1302–1417. Keep 1420–1516+.

---

## B3 — Delete 5 Unused Keyboard Functions

**Defined in keyboards.py but never called (handlers build inline keyboards):**
1. `ai_settings_keyboard`
2. `ai_presets_list_keyboard`
3. `ai_preset_view_keyboard`
4. `ai_preset_edit_keyboard`
5. `ai_custom_test_wizard_keyboard`

**Fix:** Delete each function definition.

---

## N1 — Add Back Buttons to LLM Dashboard

**Fix keyboards.py:**
1. `llm_cost_dashboard_keyboard()` — add row: `InlineKeyboardButton("↩️ Back to Cost Menu", callback_data="admin:cost_dashboard")`
2. `llm_cost_plan_keyboard()` — add: `InlineKeyboardButton("↩️ Back", callback_data="admin:cost_dashboard")`
3. `llm_cost_kind_keyboard()` — same
4. `llm_cost_status_keyboard()` — same

---

## N2 — Stats Back Button

**Fix admin.py `action == "stats"` handler:**
Add `reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back to Admin Panel", callback_data="admin:back")]])`

---

## N3 — Show Settings Back Button

**Fix admin.py `action == "show_settings"` handler:**
Same approach as N2 — add keyboard with `admin:back` button.

---

## N4 — Admin Awaiting Keyboard

**Fix keyboards.py:**
Create `admin_awaiting_inline_keyboard()` returning:
- `[InlineKeyboardButton("↩️ Back", callback_data="admin:back")]`
- `[InlineKeyboardButton("❌ Cancel", callback_data="admin:cancel")]`

**Fix admin.py:**
Add `admin:cancel` handler (clears awaiting, shows admin panel via `_edit_or_send`).
Replace `awaiting_inline_keyboard` → `admin_awaiting_inline_keyboard` in all admin handlers:
- `set_plan`, `broadcast`, `set_model`, `set_base_url`, `set_api_key`
- `_add_ai_preset`, `_edit_ai_preset_field`
- `_handle_llm_callback` pricing inputs
- `llm:set:user`, `llm:set:model`

---

## E1 — Global TTS Toggle

**db.py:** Add `tts_access` setting via existing `get_setting`/`set_setting`. Values: `"none"` | `"premium"` | `"all"`. Default: `"premium"`.

**keyboards.py:** `phonetic_settings_keyboard()` — add a row cycling through 3 TTS states: `callback_data="admin:tts_access:toggle"`

**admin.py:**
- `_phonetic_settings_text()` — show current TTS state
- Add `"tts_access:toggle"` handler cycling: none → premium → all → none

**bot.py:**
- TTS button rendering (lines ~227, 476, 657, 1034, 1143): also check `db.get_setting("tts_access", "premium")`
- `_handle_tts_pronounce` (line ~1159): gate by global setting before plan check
- Logic: `"none"` → never; `"premium"` → Silver/Gold only; `"all"` → everyone

---

## E2 — TTS Voice Replies to Source

**Fix bot.py `_handle_tts_pronounce` send_voice:**
Add `reply_to_message_id=update.callback_query.message.message_id`

---

## E3 — Delete Button for All Presets

**keyboards.py:**
- `ai_presets_list_keyboard`: add delete button for all presets (if not active)
- `ai_preset_view_keyboard`: same

**db.py `delete_preset()`:**
Remove `AND is_custom=1` from SQL `DELETE FROM ai_presets WHERE name=?`

**admin.py `_delete_ai_preset`:**
Remove `is_custom` guard. Add: forbid deleting the currently active preset.
