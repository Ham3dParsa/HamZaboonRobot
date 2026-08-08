# Plan: AI Presets Overhaul — Fallback Chain, Batching, Admin UX, Cost

**Status:** Locked — ready for implementation
**Owner locked:** 2026-07-24
**Total rules:** 13 (all individually locked by Parsa)
**Target base:** `main`
**Plan file:** `.opencode/plans/feat-ai-presets-overhaul.md`

---

## Context & Prerequisites

All 13 rules were locked via contract-lock gate protocol (AGENTS.md §2.4).
The owner (Parsa) explicitly chose each rule independently with comparison tables.

**What was NOT changed (intentionally) by this plan:**
- No new AI provider calls — all 13 rules are config/display/database only
- No changes to the batching mechanism (already works with fallback chain)
- No changes to `services/ai/prompts.py` — prompt templates stay as-is
- No changes to `bot.py` core delivery/scheduling logic
- No changes to `services/scheduling.py`

---

## Decision Record (Owner Choices)

| # | Question | Chosen Option | Rationale |
|---|----------|---------------|-----------|
| Rule #2 | Where to show last-successful-preset | **A** — in `_show_ai_settings()` | One line addition, no extra click |
| Rule #7 | How to set `group_label` | **A** — direct button in group view | One transaction for all members, no inconsistency risk |
| Rule #3 | Field order in full-edit wizard | **B** — conceptual grouping: Identity → Limits → Fallback → Cost | Easier for non-technical admin to follow |
| Rule #11 | Rank range for jump | `[1, count_in_same_group]` not total chain | Emergency group always sorts after normal; silent out-of-range is forbidden by AGENTS.md §2.2 |
| General | AI cost impact | Zero new AI calls | All 13 rules are config/display/database only; stated in every PR |

---

## Dependency Graph

```
Phase 1 (Foundation/Migrations)
  ├── no deps (starts first)
  │
  ├──▶ Phase 2 (Cost Fields)        ← needs Phase 1 columns
  │     └──▶ ─── feeds into ──▶┐
  │                             ▼
  │                      Phase 3 (Edit Keyboard)  ← needs Phase 2 field defs
  │                             │
  │                             ▼
  │                      Phase 4 (Full Edit Wizard) ← needs Phase 3 keyboards
  │
  ├──▶ Phase 5 (Group & Pagination) ← needs Phase 1 group_label
  │
  └──▶ Phase 6 (Chain UX)          ← needs Phase 1 in_fallback_chain + reindex fn
        │
        ▼
  Phase 7 (Help & Tracking)        ← can run parallel with 3-6
        │
        ▼
  Phase 8 (Integration Tests)      ← needs all production code done
        │
        ▼
  Phase 9 (Wiring + Final Val.)    ← last
```

---

## Reference: All New callback_data Prefixes

Every new callback_data introduced by this plan. Format: `prefix` — description — phase where created.

### AI Settings / Preset Edit (Phases 2-4)

| callback_data | Description | Created in |
|---------------|-------------|------------|
| `admin:ai_preset:edit_field:{name}:max_tpm` | Edit max TPM field | Phase 3 |
| `admin:ai_preset:edit_field:{name}:max_daily_req` | Edit max daily requests | Phase 3 |
| `admin:ai_preset:edit_field:{name}:is_emergency` | Toggle emergency flag | Phase 3 |
| `admin:ai_preset:edit_field:{name}:name` | Edit preset name | Phase 3 |
| `admin:ai_preset:edit_field:{name}:input_cost_per_million` | Edit input cost | Phase 3 |
| `admin:ai_preset:edit_field:{name}:output_cost_per_million` | Edit output cost | Phase 3 |
| `admin:ai_preset:edit_field:{name}:in_fallback_chain` | Edit in_fallback_chain toggle | Phase 3 |
| `admin:ai_preset:edit_field:{name}:group_label` | Edit group label | Phase 3 |
| `admin:ai_preset:discard_all:{name}` | Discard all pending edits | Phase 3 |
| `admin:ai_preset:confirm_save:{name}` | Confirm save preset | Phase 3 |
| `admin:ai_preset:confirm_save_yes:{name}` | Yes, save now | Phase 3 |
| `admin:ai_preset:confirm_save_no:{name}` | No, cancel save | Phase 3 |
| `admin:ai_preset:full_edit:{name}` | Start full edit wizard | Phase 4 |
| `admin:ai_preset:full_edit_next:{name}:{idx}` | Next field in wizard | Phase 4 |
| `admin:ai_preset:full_edit_skip:{name}:{idx}` | Skip field in wizard | Phase 4 |
| `admin:ai_preset:full_edit_cancel:{name}` | Cancel wizard | Phase 4 |
| `admin:ai_preset:full_edit_save:{name}` | Save all wizard changes | Phase 4 |

### Group & Pagination (Phase 5)

| callback_data | Description |
|---------------|-------------|
| `admin:ai_preset:page:{n}` | Go to page N of preset list |
| `admin:ai_preset:view_mode:{linear|grouped}` | Toggle view mode |
| `admin:ai_preset:group:{key_hash}` | View group detail |
| `admin:ai_preset:group_batch_key:{key_hash}` | Update API key for group |
| `admin:ai_preset:group_set_label:{key_hash}` | Set group label |

### Fallback Chain (Phase 6)

| callback_data | Description |
|---------------|-------------|
| `admin:fallback:rank:{name}` | Open rank-jump input for preset |
| `admin:fallback:usage_details` | Show consumption details view |
| `admin:ai_preset:edit_field:{name}:in_fallback_chain` | Toggle in_fallback_chain (also in Phase 3) |

### Help (Phase 7)

| callback_data | Description |
|---------------|-------------|
| `admin:help:presets` | Show preset help overview |
| `admin:help:fallback_chain` | Show fallback chain help |

---

## Reference: IBTN Constants — All New Persian Labels

All new inline button label constants that must be added to `config/keyboards.py` (alphabetically within each phase).

### Phase 3 — Extended Edit Keyboard (add after existing IBTN_FIELD_* block)

```python
# --- Admin – AI Preset Edit Fields (Phase 3 additions) ---
IBTN_FIELD_MAX_TPM = "🔢 حد توکن در دقیقه (TPM)"
IBTN_FIELD_DAILY_REQ = "📊 سقف درخواست روزانه"
IBTN_FIELD_IS_EMERGENCY = "🚨 پریست اضطراری"
IBTN_FIELD_NAME = "✏️ نام پریست"
IBTN_FIELD_INPUT_COST = "💵 هزینه ورودی ($/1M توکن)"
IBTN_FIELD_OUTPUT_COST = "💵 هزینه خروجی ($/1M توکن)"
IBTN_FIELD_IN_FALLBACK_CHAIN = "⛓️ حضور در زنجیره فال‌بک"
IBTN_FIELD_GROUP_LABEL = "🏷️ برچسب گروه"
IBTN_DISCARD_ALL = "🗑️ دور ریختن همه تغییرات"
IBTN_SAVE_CONFIRM = "✅ بله، ذخیره کن"
IBTN_SAVE_CANCEL = "❌ لغو ذخیره"
```

### Phase 4 — Full Edit Wizard

```python
# --- Admin – Full Edit Wizard ---
IBTN_FULL_EDIT_NEXT = "▶️ بعدی"
IBTN_FULL_EDIT_SKIP = "⏭️ رد کردن"
IBTN_FULL_EDIT_CANCEL_WIZARD = "❌ انصراف از ویرایش"
IBTN_FULL_EDIT_SAVE_ALL = "✅ ذخیره همه تغییرات"
```

### Phase 5 — Group & Pagination

```python
# --- Admin – Preset Group / Pagination ---
IBTN_VIEW_MODE_LINEAR = "📋 نمایش خطی"
IBTN_VIEW_MODE_GROUPED = "📁 نمایش گروهی"
IBTN_GROUP_BATCH_KEY = "🔑 آپدیت کلید این گروه"
IBTN_GROUP_SET_LABEL = "🏷️ نام‌گذاری گروه"
IBTN_GROUP_OPEN = "▶️ باز کردن گروه"
IBTN_PAGE_PREV = "◀️ صفحه قبل"
IBTN_PAGE_NEXT = "▶️ صفحه بعد"
```

### Phase 6 — Chain UX

```python
# --- Admin – Fallback Chain ---
IBTN_RANK_JUMP = "🎯 رتبه دلخواه"
IBTN_CONSUMPTION_DETAILS = "📊 جزئیات مصرف همه"
```

### Phase 7 — Help

```python
# --- Admin – Help ---
IBTN_HELP_PRESETS = "❓ راهنمای پریست‌ها"
IBTN_HELP_FALLBACK = "❓ راهنمای زنجیره فال‌بک"
```

---

## Reference: Persian Help Texts (Rule #9 — finalized)

All help texts in natural Persian. Stored as a module-level dict in `handlers/admin.py` named `_FIELD_HELP`.

```python
_FIELD_HELP = {
    "name": "نام یکتای پریست. فقط حروف انگلیسی (a-z)، اعداد (0-9) و زیرخط (_) مجاز است. بعد از ذخیره قابل تغییر نیست.",
    "api_key": "کلید API سرویس‌دهنده. می‌توانید مقدار ثابت (sk-...) یا متغیر محیطی (مثلاً $MY_KEY) وارد کنید.",
    "base_url": "آدرس سرور سازگار با OpenAI. نمونه: https://api.example.com/v1",
    "model": "نام دقیق مدل. نمونه: gpt-4o-mini یا gemini-2.0-flash-lite",
    "max_concurrency": "تعداد درخواست‌هایی که هم‌زمان به این سرویس‌دهنده فرستاده می‌شود. عدد ۲ یا ۳ معمول است.",
    "max_rpm": "بیشترین تعداد درخواست در هر دقیقه. صفر = بدون محدودیت.",
    "max_tpm": "بیشترین تعداد توکن ورودی و خروجی در هر دقیقه. صفر = بدون محدودیت.",
    "daily_batch_size": "تعداد کارت واژگان در هر دسته که یک‌جا از AI درخواست می‌شود. بین ۳ تا ۱۲.",
    "max_daily_req": "سقف تعداد درخواست به این پریست در هر روز. صفر = بدون محدودیت.",
    "timeout_seconds": "مدت زمان انتظار برای پاسخ از سرویس‌دهنده (به ثانیه). عدد اعشاری مجاز است.",
    "temperature": "میزان خلاقیت مدل. بین ۰.۰ (دقیق) تا ۲.۰ (خلاق). پیش‌فرض: ۰.۶",
    "max_output_tokens": "حداکثر تعداد توکن در هر پاسخ. پیش‌فرض: ۴۰۹۶",
    "priority": "اولویت در زنجیره فال‌بک. عدد کمتر = اولویت بیشتر. پریست با priority=۰ اولین نفری است که امتحان می‌شود.",
    "is_emergency": "آیا این پریست فقط برای مواقع اضطراری است؟ پریست‌های اضطراری همیشه بعد از پریست‌های عادی امتحان می‌شوند.",
    "in_fallback_chain": "آیا این پریست به‌صورت خودکار در زنجیره فال‌بک شرکت کند؟ اگر خاموش شود، فقط با انتخاب دستی قابل استفاده است.",
    "input_cost_per_million": "هزینه هر یک میلیون توکن ورودی (درخواست) به دلار. خالی = استفاده از مقدار سراسری تنظیم شده در داشبورد هزینه.",
    "output_cost_per_million": "هزینه هر یک میلیون توکن خروجی (پاسخ) به دلار. خالی = استفاده از مقدار سراسری.",
    "group_label": "برچسب دلخواه برای گروه‌بندی پریست‌هایی که کلید API مشترک دارند. نمونه: «سرویس‌دهنده اصلی» یا «پشتیبان رایگان»",
}
```

---

## Reference: Exact SQL for reindex_preset_priority (Rule #11)

**Signature:** `reindex_preset_priority(name: str, target_rank: int, group_is_emergency: bool)`

**Algorithm (atomic transaction, `BEGIN IMMEDIATE`):**

1. Get all presets in the same group (matching `is_emergency = group_is_emergency`), ordered by `priority ASC, name ASC`, enriched with a computed `rank` (1-based index based on order).

```sql
-- 1a. Get total count in group
SELECT COUNT(*) as cnt FROM ai_presets
WHERE enabled=1 AND is_emergency=?
  AND in_fallback_chain=1;

-- 1b. Validate 1 <= target_rank <= cnt

-- 1c. Get current rank of target preset
SELECT COUNT(*) as current_rank FROM ai_presets
WHERE enabled=1 AND is_emergency=? AND in_fallback_chain=1
  AND (priority < (SELECT priority FROM ai_presets WHERE name=?)
       OR (priority = (SELECT priority FROM ai_presets WHERE name=?) AND name < ?))
```

2. If `target_rank == current_rank`: no-op, return.

3. If `target_rank < current_rank` (moving up): shift presets between target_rank and current_rank-1 *down* by 1, then set target = target_rank.

```sql
BEGIN IMMEDIATE;

-- Shift affected presets down
UPDATE ai_presets
SET priority = priority + 1
WHERE name IN (
  SELECT name FROM (
    SELECT name FROM ai_presets
    WHERE enabled=1 AND is_emergency=? AND in_fallback_chain=1
    ORDER BY priority ASC, name ASC
    LIMIT -1 OFFSET ?  -- offset = target_rank-1, we want rows from target_rank to current_rank-1
  )
  -- subset of rows between target and current-1
);

-- Set target to target_rank-1 (0-based)
UPDATE ai_presets SET priority = ? WHERE name = ?;

COMMIT;
```

**Simpler implementation approach:**
- Read all presets in group with their current priorities into Python list
- Sort by (priority, name)
- Reassign priorities consecutively (0, 1, 2, ... )
- Move target element to target_rank position in list
- Write all priorities back in a single multi-row UPDATE or loop inside one transaction

```python
def reindex_preset_priority(name, target_rank, group_is_emergency):
    # target_rank is 1-based, convert to 0-based
    target_idx = target_rank - 1

    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")

        # Get all presets in this group, ordered
        rows = conn.execute(
            "SELECT name, priority FROM ai_presets "
            "WHERE enabled=1 AND is_emergency=? AND in_fallback_chain=1 "
            "ORDER BY priority ASC, name ASC",
            (1 if group_is_emergency else 0,)
        ).fetchall()

        count = len(rows)
        if not (1 <= target_rank <= count):
            raise ValueError(f"target_rank {target_rank} out of range [1, {count}]")

        # Find current index of target preset
        names = [r["name"] for r in rows]
        current_idx = names.index(name) if name in names else -1
        if current_idx == -1:
            raise ValueError(f"preset {name} not found in group")
        if current_idx == target_idx:
            return  # no-op

        # Move target in the list
        item = rows.pop(current_idx)
        rows.insert(target_idx, item)

        # Reassign priorities: 0, 1, 2, ...
        for i, row in enumerate(rows):
            conn.execute(
                "UPDATE ai_presets SET priority=? WHERE name=?",
                (i, row["name"])
            )

        conn.commit()
```

**Edge cases tested:**
- Target preset is already at that rank → no-op
- Moving from rank 5 → 2 (upward)
- Moving from rank 2 → 5 (downward)
- Moving only preset in group → no-op
- target_rank out of bounds → ValueError with Persian error message

---

## Reference: Rule #2 — Exact Query for "Last Successful Preset"

Displayed as one line in `_show_ai_settings()`:

```python
# One line at bottom of _show_ai_settings():
# "📇 آخرین درخواست‌ها: Daily: google_36_flash_hpof | Grammar: google_35_flash_hpof | Word: google_36_flash_hpof"

SELECT preset_name, request_kind
FROM llm_requests
WHERE request_kind IN ('daily_batch', 'grammar_tip', 'custom_word')
  AND outcome = 'success'
  AND created_at >= datetime('now', '-7 days')
GROUP BY request_kind
HAVING created_at = MAX(created_at)
```

If no successful request exists for a kind in the last 7 days, show `"—"` instead.

---

## Reference: Complete callback_data List for test_wiring.py (Phase 9)

All new prefixes to add to the ALLOWLIST and admin sub-route checks in `tests/test_wiring.py`:

### New ALLOWLIST entries (callback data static prefixes from keyboards.py)

```
admin:ai_preset:discard_all:
admin:ai_preset:confirm_save:
admin:ai_preset:confirm_save_yes:
admin:ai_preset:confirm_save_no:
admin:ai_preset:full_edit:
admin:ai_preset:full_edit_next:
admin:ai_preset:full_edit_skip:
admin:ai_preset:full_edit_cancel:
admin:ai_preset:full_edit_save:
admin:ai_preset:page:
admin:ai_preset:view_mode:
admin:ai_preset:group:
admin:ai_preset:group_batch_key:
admin:ai_preset:group_set_label:
admin:fallback:rank:
admin:fallback:usage_details
admin:help:presets
admin:help:fallback_chain
```

### New admin sub-actions (add to `_collect_admin_sub_actions()` check)

```
admin:ai_preset:edit_field:{name}:max_tpm
admin:ai_preset:edit_field:{name}:max_daily_req
admin:ai_preset:edit_field:{name}:is_emergency
admin:ai_preset:edit_field:{name}:name
admin:ai_preset:edit_field:{name}:input_cost_per_million
admin:ai_preset:edit_field:{name}:output_cost_per_million
admin:ai_preset:edit_field:{name}:in_fallback_chain
admin:ai_preset:edit_field:{name}:group_label
admin:ai_preset:discard_all:{name}
admin:ai_preset:confirm_save:{name}
admin:ai_preset:confirm_save_yes:{name}
admin:ai_preset:confirm_save_no:{name}
admin:ai_preset:full_edit:{name}
admin:ai_preset:full_edit_next:{name}:{idx}
admin:ai_preset:full_edit_skip:{name}:{idx}
admin:ai_preset:full_edit_cancel:{name}
admin:ai_preset:full_edit_save:{name}
admin:ai_preset:page:{n}
admin:ai_preset:view_mode:{mode}
admin:ai_preset:group:{key_hash}
admin:ai_preset:group_batch_key:{key_hash}
admin:ai_preset:group_set_label:{key_hash}
admin:fallback:rank:{name}
admin:fallback:usage_details
admin:help:presets
admin:help:fallback_chain
```

---

# Fase Bandi (Phased Implementation)

---

## Phase 1 — Database Migrations

**PR:** `feat/db-preset-migrations`
**Rules covered:** Foundation for #2, #6, #7, #12

### Changes

**File: `services/db/__init__.py`** — function `_init_ai_presets_table(conn)`

Add 5 columns via ALTER TABLE IF NOT EXISTS pattern (same style as existing migrations in this function):

```sql
-- ai_presets table
ALTER TABLE ai_presets ADD COLUMN input_cost_per_million REAL;
ALTER TABLE ai_presets ADD COLUMN output_cost_per_million REAL;
ALTER TABLE ai_presets ADD COLUMN group_label TEXT DEFAULT '';
ALTER TABLE ai_presets ADD COLUMN in_fallback_chain INTEGER DEFAULT 1;

-- llm_requests table
ALTER TABLE llm_requests ADD COLUMN preset_name TEXT;
```

**Note on existing migration style (db/__init__.py ~line 1630-1660):**
The `_init_ai_presets_table` function already uses a pattern like:
```python
for col in ("api_key", "max_tpm", "max_daily_req", "priority", "enabled", "is_emergency"):
    try:
        conn.execute(f"ALTER TABLE ai_presets ADD COLUMN {col} ...")
    except (sqlite3.OperativeError, sqlite3.OperationalError):
        pass  # column already exists
```

### Tests

1. **`tests/test_db_migrations.py`** (new file):
   - `test_fresh_db_has_all_new_columns()`: Create DB via `init_db()`, verify all 5 columns exist with correct types/defaults
   - `test_migration_from_prior_schema()`: Create DB *without* new columns (simulate old schema), then call `_init_ai_presets_table()`, verify columns added and defaults set
   - `test_in_fallback_chain_default_one()`: New preset row has `in_fallback_chain=1`
   - `test_cost_columns_nullable()`: New preset row has `input_cost_per_million IS NULL`, `output_cost_per_million IS NULL`
   - `test_group_label_default_empty()`: New preset row has `group_label = ''`
   - `test_llm_requests_preset_name_nullable()`: New `llm_requests` row allows `preset_name IS NULL`
   - `test_preset_name_added_to_llm_requests()`: Verify `llm_requests` has `preset_name` column after migration

### No other files changed in Phase 1
- `ai.py`, `ai_presets.py`, `llm_services.py`, `admin.py`, `keyboards.py` — NOT touched

---

## Phase 2 — Cost Fields

**PR:** `feat/preset-cost-fields`
**Rules:** #6
**Depends on:** Phase 1 (columns exist)

### Changes

**`services/ai/ai_presets.py`:**
- Add `"input_cost_per_million": None` and `"output_cost_per_million": None` to every built-in preset dict (None → fallback to global)

**`services/ai/ai.py`:**
- In `_log_llm_request()` (line ~147): add `preset_name` parameter, pass `preset.get("name", "?")` to `db.add_llm_request()`
- In `_log_llm_request()`: resolve cost per-million from preset first (`preset.get("input_cost_per_million")` etc.), fallback to global (`profile["input_cost_usd_per_million"]`)

**`services/db/__init__.py`:**
- `add_llm_request()`: add `preset_name` parameter, include in INSERT
- New function `get_preset_cost(preset_name) -> dict`: returns `{"input_cost_per_million": X, "output_cost_per_million": X}` — reads per-preset value, falls back to `get_setting("llm_input_price", ...)` / `get_setting("llm_output_price", ...)`

**`handlers/admin.py::_show_ai_preset_view()`:**
- Add lines showing `"Input Cost: {val} $/1M"` and `"Output Cost: {val} $/1M"` (with "(global fallback)" notation if using global default)

### Tests
- Cost fallback: preset with NULL cost → uses global setting
- Cost override: preset with explicit cost → uses per-preset value
- `add_llm_request` stores `preset_name` correctly
- `get_preset_cost()` with/without per-preset values

---

## Phase 3 — Extended Edit Keyboard

**PR:** `feat/preset-edit-extended`
**Rules:** #4, #5
**Depends on:** Phase 2 (cost field definitions)

### Changes

**`config/keyboards.py`:**
- Add all new IBTN_* constants listed in the Reference section for Phase 3
- `ai_preset_edit_keyboard()`: add buttons for all new fields listed below

**Field buttons to add (in order, after existing 9 fields):**

| # | Field Key | IBTN Constant | callback_data |
|---|-----------|---------------|---------------|
| 10 | `max_tpm` | `IBTN_FIELD_MAX_TPM` | `admin:ai_preset:edit_field:{preset_name}:max_tpm` |
| 11 | `max_daily_req` | `IBTN_FIELD_DAILY_REQ` | `admin:ai_preset:edit_field:{preset_name}:max_daily_req` |
| 12 | `is_emergency` | `IBTN_FIELD_IS_EMERGENCY` | `admin:ai_preset:edit_field:{preset_name}:is_emergency` |
| 13 | `name` | `IBTN_FIELD_NAME` | `admin:ai_preset:edit_field:{preset_name}:name` |
| 14 | `input_cost_per_million` | `IBTN_FIELD_INPUT_COST` | `admin:ai_preset:edit_field:{preset_name}:input_cost_per_million` |
| 15 | `output_cost_per_million` | `IBTN_FIELD_OUTPUT_COST` | `admin:ai_preset:edit_field:{preset_name}:output_cost_per_million` |
| 16 | `in_fallback_chain` | `IBTN_FIELD_IN_FALLBACK_CHAIN` | `admin:ai_preset:edit_field:{preset_name}:in_fallback_chain` |
| 17 | `group_label` | `IBTN_FIELD_GROUP_LABEL` | `admin:ai_preset:edit_field:{preset_name}:group_label` |

**New buttons in footer (before save row):**
- "🗑️ Discard All Changes" (`IBTN_DISCARD_ALL` → `admin:ai_preset:discard_all:{preset_name}`)

**Modified save button behavior:**
- "✅ ذخیره پیش‌تنظیم" → now opens confirm dialog (not direct save)
- Confirm dialog: "مطمئنید؟" with `IBTN_SAVE_CONFIRM` ("✅ بله، ذخیره کن" → `admin:ai_preset:confirm_save_yes:{name}`) and `IBTN_SAVE_CANCEL` ("❌ لغو ذخیره" → `admin:ai_preset:confirm_save_no:{name}`)

**`handlers/admin.py`:**
- `_handle_ai_preset_field_input()`: add validation for all 8 new fields
  - `max_tpm`, `max_daily_req`: positive integer
  - `is_emergency`: 0 or 1 (boolean toggle, store as int)
  - `name`: unique check via `db.get_preset(name)`, alphanumeric+underscore
  - `input_cost_per_million`, `output_cost_per_million`: positive float or empty string (= None/NULL)
  - `in_fallback_chain`: 0 or 1 (boolean toggle)
  - `group_label`: any string, no validation needed
- `_discard_all_preset_changes()`: `user_data["preset_edits"].pop(name)` → `_show_ai_preset_view()`
- `_confirm_save_preset()`: show "مطمئنید؟" with two buttons Yes/No
- `_handle_confirm_save_yes()`: call `_save_ai_preset()`
- `_handle_confirm_save_no()`: return to edit keyboard

**Help text integration:**
- In `_edit_ai_preset_field()`: after the prompt line, add a second line with the help text from `_FIELD_HELP[field_name]` (Persian, from Reference section above)

---

## Phase 4 — Full Edit Wizard

**PR:** `feat/full-edit-wizard`
**Rules:** #3 (with B choice: conceptual grouping)
**Depends on:** Phase 3 (keyboard patterns + help texts)

### Field Order (conceptual groups)

| Group | Order | Fields |
|-------|-------|--------|
| **Identity** | 1-4 | `name`, `api_key`, `base_url`, `model` |
| **Limits** | 5-12 | `max_concurrency`, `max_rpm`, `max_tpm`, `daily_batch_size`, `max_daily_req`, `timeout_seconds`, `temperature`, `max_output_tokens` |
| **Fallback** | 13-15 | `priority`, `is_emergency`, `in_fallback_chain` |
| **Cost & Label** | 16-18 | `input_cost_per_million`, `output_cost_per_million`, `group_label` |

### Changes

**`config/keyboards.py`:**
- `ai_preset_edit_keyboard()`: Add button "✏️ ویرایش کامل" (`IBTN_FULL_EDIT_WIZARD` → `admin:ai_preset:full_edit:{name}`)
- Add IBTN constants for wizard navigation (from Reference above)

**`handlers/admin.py`:**
- `_start_full_edit_wizard(update, context, preset_name)`:
  - Initialize `user_data["full_edit"] = {"preset": preset_name, "field_idx": 0, "values": {}}`
  - Set `awaiting = f"ai_preset_full_edit:{preset_name}:0"`
  - Show current field: prompt + help text + current value + keyboard ["▶️ بعدی" / "⏭️ رد کردن" / "❌ انصراف"]
- `_handle_full_edit_input(update, context, preset_name, field_idx_str, text)`:
  - Validate value based on field type (same validators as Phase 3)
  - Store in `user_data["full_edit"]["values"][field_name]`
  - Advance to next field_idx
  - If all 18 done → show summary + "✅ ذخیره همه" / "❌ لغو"
  - If user typed empty → treat as "skip" (don't change this field)
- `_handle_full_edit_next()`: advance wizard to next field
- `_handle_full_edit_skip()`: skip current field (advance without storing)
- `_handle_full_edit_cancel()`: clear `user_data["full_edit"]`, return to edit keyboard
- `_handle_full_edit_save()`: merge wizard values with existing preset via `db.set_preset()`, clear wizard state

---

## Phase 5 — Group & Pagination

**PR:** `feat/preset-group-pagination`
**Rules:** #7 (with A choice), #8
**Depends on:** Phase 1 (group_label column)

### Changes

**`services/db/__init__.py`:**
- `set_preset_api_key_batch(names: list[str], new_key: str)`:
  - Single `BEGIN IMMEDIATE` → `UPDATE ai_presets SET api_key=? WHERE name IN (?,?,?)`
  - Use parameterized IN clause with `"," .join("?" * len(names))`
- `set_preset_group_label_batch(names: list[str], label: str)`:
  - Same pattern, `UPDATE ai_presets SET group_label=? WHERE name IN (...)`
- `get_preset_groups()`: returns `list[dict]` with `{resolved_key, masked_key, label, count, names[]}` — group by resolved api_key (after `resolve_api_key()`), include presets regardless of enabled

**`handlers/admin.py`:**
- `_detect_key_groups()`: Iterate all presets, resolve each api_key, group by resolved value. Return list sorted by count desc.
- `_show_linear_presets(update, context, page=0)`: Paginated list, 5 presets/page, ordered by `is_emergency ASC, priority ASC, name ASC`. Keyboard uses `admin:ai_preset:page:{n}` for navigation.
- `_show_grouped_presets(update, context)`: Show groups from `_detect_key_groups()`. Each group row: `📁 {group_label or masked_key} ({n} preset)` with action buttons.
- `_toggle_preset_view_mode(update, context, mode)`: Store `user_data["preset_view_mode"] = mode`, re-render.
- `_handle_group_batch_key(update, context, group_key_hash)`: awaiting flow for new API key text → call `set_preset_api_key_batch()`.
- `_handle_group_set_label(update, context, group_key_hash)`: awaiting flow for label text → call `set_preset_group_label_batch()`.
- `handle_group_view(update, context, group_key_hash)`: Show all presets in that group with their details.

**`config/keyboards.py`:**
- `ai_presets_list_keyboard()`:
  - Add pagination row: `IBTN_PAGE_PREV` / `IBTN_PAGE_NEXT` (hidden when on first/last page)
  - Add toggle row: `IBTN_VIEW_MODE_LINEAR` / `IBTN_VIEW_MODE_GROUPED`
  - In grouped mode: each group displayed with `IBTN_GROUP_OPEN`, `IBTN_GROUP_BATCH_KEY`, `IBTN_GROUP_SET_LABEL`
  - Store current page and view mode via function parameters

---

## Phase 6 — Chain UX Overhaul

**PR:** `feat/fallback-chain-ux`
**Rules:** #10, #13, #11, #12 (UI portion)
**Depends on:** Phase 1 (in_fallback_chain column + reindex function)

### Changes

**`services/db/__init__.py`:**
- `reindex_preset_priority(name, target_rank, group_is_emergency)` — exact implementation per Reference section above (Python approach: read list, reorder, write back in transaction)

**`services/ai/llm_services.py::_call_ai_limited()`:**
- Line that does `db.get_enabled_presets_ordered()` — change to use a NEW function: `db.get_fallback_chain_presets()`
- Why a new function? Because `get_enabled_presets_ordered()` is used elsewhere (admin display, etc.) and those should still see all enabled presets. The fallback chain filter is:
  ```sql
  SELECT * FROM ai_presets
  WHERE enabled=1 AND in_fallback_chain=1
  ORDER BY is_emergency ASC, priority ASC, name ASC
  ```

**`services/db/__init__.py` — new function:**
- `get_fallback_chain_presets()`: same as `get_enabled_presets_ordered()` but with `AND in_fallback_chain=1`

**`config/keyboards.py::fallback_chain_keyboard()`:**
- COMPACT: ONE row per preset (was 2 rows per preset):
  `{rank}. {short_name} ⬆ ⬇ {🟢/🔴 toggle} {🚨 if applicable} {🎯 rank jump}`
- No separate `admin:noop` label row
- Only render presets where `in_fallback_chain=1`
- Add button "📊 جزئیات مصرف همه" (`IBTN_CONSUMPTION_DETAILS` → `admin:fallback:usage_details`)
- Each row gets "🎯 رتبه دلخواه" (`IBTN_RANK_JUMP` → `admin:fallback:rank:{name}`)

**`handlers/admin.py`:**
- `_show_fallback_chain()`:
  - Top fixed help line: `"ترتیب زنجیره: پریست‌های عادی (is_emergency=0) بر اساس priority (از کم به زیاد)، سپس پریست‌های اضطراری (is_emergency=1). پریست‌های با in_fallback_chain=0 در این زنجیره نمایش داده نمی‌شوند."`
  - Per preset line: `"{rank}. {name} — {🚨 اضطراری / ✅ فعال / 🔴 غیرفعال}"`
  - No per-preset consumption detail (moved to separate view)
  - Called with `db.get_fallback_chain_presets()` (not `get_enabled_presets_ordered()`)
- `_show_fallback_usage_details()`: New view
  - Title: `"📊 مصرف روزانه پریست‌ها"`
  - Table with columns: Name | Requests today | Max daily | Status
  - Data from `db.get_hourly_usage()` for each preset
  - Back button to fallback chain
- `_handle_fallback_rank(update, context, preset_name)`:
  - Set `awaiting = f"ai_fallback_rank:{preset_name}"`
  - Show: "رتبه جدید در گروه {عادی/اضطراری} را وارد کنید (۱ تا {N}):"
  - On input: validate range, call `reindex_preset_priority()`, refresh view
  - Error: "این پریست جزو گروه {عادی/اضطراری} است؛ فقط بین ۱ تا {N} می‌توانید جابه‌جا کنید"

**Update admin `_handle_admin_callback`:**
- Add branches for:
  - `awaiting.startswith("ai_fallback_rank:")` → text input handler
  - `action.startswith("fallback:rank:")` → `_handle_fallback_rank()`
  - `action == "fallback:usage_details"` → `_show_fallback_usage_details()`

---

## Phase 7 — Help & Tracking

**PR:** `feat/preset-help-tracking`
**Rules:** #9, #2 (with A choice)
**Depends on:** Phase 2 (preset_name in llm_requests)

### Changes — Rule #9 (Help Text)

**`handlers/admin.py`:**
- Add `_FIELD_HELP` dict (from Reference section above) at module level
- In `_edit_ai_preset_field()`: add help line: `_FIELD_HELP.get(field_name, "")` below the prompt
- In full-edit wizard (Phase 4): same help per field
- `_show_help_presets()`: overview page
  - Text explaining all field meanings, priority ordering, fallback chain logic, emergency concept, group_label purpose
  - Keyboard: back button
- `_show_help_fallback_chain()`: concise help about chain ordering
  - Text explaining `is_emergency ASC, priority ASC, name ASC`
  - What is_emergency means, what in_fallback_chain does
  - How rank jump works

**`config/keyboards.py`:**
- `ai_settings_keyboard()`: add button "❓ راهنما" (`IBTN_HELP_PRESETS` → `admin:help:presets`)
- `fallback_chain_keyboard()`: add button "❓ راهنما" (`IBTN_HELP_FALLBACK` → `admin:help:fallback_chain`)

**`handlers/admin.py::_handle_admin_callback()`:**
- Add `action == "help:presets"` → `_show_help_presets()`
- Add `action == "help:fallback_chain"` → `_show_help_fallback_chain()`

### Changes — Rule #2 (Preset Tracking)

**`services/ai/ai.py::_log_llm_request()`:**
- Already changed in Phase 2 to pass `preset_name` to `db.add_llm_request()`

**`handlers/admin.py::_show_ai_settings()`:**
- Add one line at bottom (after the active preset info):
  `"📇 آخرین درخواست‌ها:\n           Daily: {preset} | Grammar: {preset} | Word: {preset}"`
- Query per Reference section above (latest successful per request_kind, last 7 days)
- If a kind has no successful request → show `"—"`

---

## Phase 8 — Fallback Integration Tests

**PR:** `test/fallback-integration`
**Rules:** #1

### New file: `tests/test_integration/test_fallback_flow.py`

Using pattern from `test_custom_word_query.py` (mock at module level, construct update/context, call router or handler directly).

**Tests:**
1. `test_grammar_tip_fallback_chain()`:
   - Setup: Seed 2 presets in temp DB, patch `bot._call_ai_limited` to raise `RateLimitError` on first call then succeed on second (use `side_effect`)
   - Action: `send_grammar_tip(update, context)` with onboarded user
   - Assert: grammar tip delivered to user, `preset_hourly_usage` logged for second preset, first preset skipped

2. `test_word_query_fallback_chain()`:
   - Setup: Seed 2 presets, patch `bot._call_ai_limited` same pattern
   - Action: `text_router(update, context)` with custom word text and `awaiting="ask_word"`
   - Assert: word query result delivered, second preset used

3. `test_all_presets_exhausted()`:
   - Setup: One preset that always raises `Exception`
   - Action: `send_grammar_tip(update, context)`
   - Assert: user sees Persian error message, grammar tip reservation refunded (query `db.get_user(user_id)` to verify `grammar_tips_asked_today` unchanged)

4. `test_in_fallback_chain_exclusion()`:
   - Setup: Preset A `in_fallback_chain=1`, Preset B `in_fallback_chain=0`. Patch `_call_ai_limited` to fail on A, succeed on B.
   - Action: `send_grammar_tip(update, context)`
   - Assert: Preset B is NEVER called (it's excluded from chain), `AllPresetsExhausted` propagates
   - Then test direct call: bypass `_call_ai_limited` and call `ai.ask_json` with Preset B directly → works fine (manual use)

---

## Phase 9 — Wiring Tests & Final Validation

**PR:** `chore/wiring-final`

Update `tests/test_wiring.py`:
- Add ALL new callback_data prefixes from "Reference: Complete callback_data List" section to the ALLOWLIST in `_collect_all_callback_prefixes()`
- Add ALL new `admin:` sub-action patterns to `_collect_admin_sub_actions()` check
- Run full validation:
  ```powershell
  python -m unittest discover -s tests -v
  python scripts/compile_all.py
  python -m ruff check --select F821,F811
  python scripts/generate_dashboard.py
  git diff --check
  ```

---

## Per-PR Checklist

For every PR, verify:
- [ ] No new AI calls added (cost impact = 0, stated in PR description)
- [ ] All Persian strings are natural Persian (not machine translation)
- [ ] All dynamic values in MarkdownV2 pass through `escape_mdv2()` from `formatting.py`
- [ ] `callback_data` strings use preset **name** (not numeric index)
- [ ] All SQLite write transactions use `BEGIN IMMEDIATE`
- [ ] No secrets/keys in logs, tests, or commit messages
- [ ] GitHub Issue updated with status + evidence
- [ ] `project_status.json` updated if phase/decision changes
- [ ] Dashboard regenerated

---

## Files Changed Summary (All Phases)

| File | Phases |
|------|--------|
| `services/db/__init__.py` | 1, 2, 5, 6 |
| `services/ai/ai.py` | 2, 7 |
| `services/ai/ai_presets.py` | 2 |
| `services/ai/llm_services.py` | 6 |
| `handlers/admin.py` | 2, 3, 4, 5, 6, 7 |
| `config/keyboards.py` | 3, 4, 5, 6, 7 |
| `tests/test_db_migrations.py` | 1 (new) |
| `tests/test_integration/test_fallback_flow.py` | 8 (new) |
| `tests/test_wiring.py` | 9 |

---

## Prompt for OpenCode — Phase 1: Database Migrations

```markdown
# Phase 1 of 9: Database Migrations — AI Presets Overhaul

## Context
This is the first phase of a 13-rule locked contract for overhauling the AI presets system.
The complete plan is at `.opencode/plans/feat-ai-presets-overhaul.md`.
Read that plan file first for context.

## Goal
Add 5 new columns to the SQLite database schema via the existing migration pattern in `services/db/__init__.py::_init_ai_presets_table()`.

## PR branch name
`feat/db-preset-migrations`

## Files to change
- `services/db/__init__.py` ONLY
- `tests/test_db_migrations.py` (new file)

## Exact changes

### In function `_init_ai_presets_table(conn)` (~line 1630-1660):

Add these 4 columns to `ai_presets` table using the existing try/except ALTER TABLE pattern:

1. `input_cost_per_million REAL`
2. `output_cost_per_million REAL`
3. `group_label TEXT DEFAULT ''`
4. `in_fallback_chain INTEGER DEFAULT 1`

Add this 1 column to `llm_requests` table using the same try/except pattern:

5. `preset_name TEXT`

### Existing migration pattern (copy this style):
The `_init_ai_presets_table` already has:
```python
for col in ("api_key", "max_tpm", "max_daily_req", "priority", "enabled", "is_emergency"):
    try:
        conn.execute(f"ALTER TABLE ai_presets ADD COLUMN {col} ...")
    except (sqlite3.OperativeError, sqlite3.OperationalError):
        pass
```

For `llm_requests`, check if there's already a migration block for that table. If yes, extend it. If not, create a new block right after the ai_presets migrations using the same try/except pattern.

### Important constraints:
- `input_cost_per_million` and `output_cost_per_million` must be NULLABLE (no NOT NULL) — NULL means "use global fallback"
- `group_label` defaults to empty string `''`
- `in_fallback_chain` defaults to `1` (True)
- `preset_name` on `llm_requests` must be NULLABLE (no NOT NULL), no default
- Put the `llm_requests` migration AFTER the ai_presets migration block
- Use EXACTLY the same try/except pattern as existing migrations

## Tests (new file: `tests/test_db_migrations.py`)

Use the same test pattern as other tests:
```python
import os, tempfile, unittest, sqlite3
from services import db

class TestDbMigrations(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        self.tempdir.cleanup()
```

1. `test_fresh_db_has_all_new_columns()`:
   - Call `db.init_db()` to create fresh schema
   - Use `PRAGMA table_info(ai_presets)` to verify all 4 new columns exist with correct types
   - Use `PRAGMA table_info(llm_requests)` to verify `preset_name` column exists

2. `test_migration_from_prior_schema()`:
   - Create a raw SQLite DB with OLD schema (without the 5 new columns)
   - Import `init_db` or call `_init_ai_presets_table` directly to run migration
   - Verify all 5 columns added correctly

3. `test_in_fallback_chain_default_one()`:
   - After `init_db()`, check that seed presets have `in_fallback_chain=1`
   - `SELECT in_fallback_chain FROM ai_presets LIMIT 1` → value should be 1

4. `test_cost_columns_nullable()`:
   - After `init_db()`, `SELECT input_cost_per_million, output_cost_per_million FROM ai_presets LIMIT 1` → both NULL

5. `test_group_label_default_empty()`:
   - After `init_db()`, `SELECT group_label FROM ai_presets LIMIT 1` → `''`

6. `test_llm_requests_preset_name_column()`:
   - After `init_db()`, `PRAGMA table_info(llm_requests)` → find `preset_name` row, confirm `notnull=0`

## Verification
```powershell
python -m unittest tests.test_db_migrations -v
python -m unittest discover -s tests -v
python -m ruff check --select F821,F811
git diff --check
```

## Do NOT touch
- `ai.py`, `ai_presets.py`, `llm_services.py` — leave untouched
- `admin.py`, `keyboards.py` — leave untouched
- `bot.py` — leave untouched
- Any existing test files — only create `tests/test_db_migrations.py`
- The SEED data or preset definitions
```
