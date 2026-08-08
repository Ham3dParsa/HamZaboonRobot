# Plan: Fallback Chain Engine + Rate-Limited Batching + Provenance

_Last updated: 2026-07-21_
_Status: Locked, pending implementation_

---

## Objective

Replace the binary (primary/fallback) AI preset system with an ordered fallback chain that respects per-preset rate limits (RPM, TPM, rolling 24h request cap), adapts batch size to rate-limit headroom, and tracks which preset generated each card (provenance) for future quality analysis.

---

## Phase 1 — Schema & Database

### 1.1 New columns on `ai_presets`

```sql
ALTER TABLE ai_presets ADD COLUMN priority INTEGER DEFAULT 0;
ALTER TABLE ai_presets ADD COLUMN enabled INTEGER DEFAULT 1;
ALTER TABLE ai_presets ADD COLUMN is_emergency INTEGER DEFAULT 0;
ALTER TABLE ai_presets ADD COLUMN max_tpm INTEGER DEFAULT 0;
ALTER TABLE ai_presets ADD COLUMN max_daily_req INTEGER DEFAULT 0;
```

### 1.2 New table `preset_hourly_usage`

```sql
CREATE TABLE IF NOT EXISTS preset_hourly_usage (
    preset_name TEXT NOT NULL,
    hour_bucket TEXT NOT NULL,
    request_count INTEGER DEFAULT 0,
    token_count INTEGER DEFAULT 0,
    PRIMARY KEY (preset_name, hour_bucket)
);
```

### 1.3 Provenance on `daily_cards` and `grammar_tips`

```sql
ALTER TABLE daily_cards ADD COLUMN provenance TEXT DEFAULT '';
ALTER TABLE grammar_tips ADD COLUMN provenance TEXT DEFAULT '';
```

### 1.4 Remove dead `pending_ai_settings` system

- Remove CREATE TABLE for `pending_ai_settings`
- Remove `_init_pending_ai_settings_table()`
- Remove `get_pending_ai()`, `set_pending_ai()`, `clear_pending_ai()`, `apply_pending_ai()`, `diff_pending_vs_active()`
- Remove cleanup: `DELETE FROM pending_ai_settings WHERE key LIKE 'ai_preset_%'`
- Remove IBTN_AI_PENDING, IBTN_AI_APPLY, IBTN_AI_ROLLBACK from keyboards.py
- Remove `admin:ai_pending`, `admin:ai_apply`, `admin:ai_rollback` callback handlers
- Remove `_show_ai_pending()`, `_apply_ai_pending()`, `_rollback_ai_pending()` from admin.py
- Remove `ai_pending_keyboard()` function

### 1.5 Update `seed_presets()` with new BUILTIN_PRESETS

```
Google 3.5 Flash:
  base_url = https://generativelanguage.googleapis.com/v1beta/openai/
  model = gemini-3.5-flash
  api_key = $GOOGLE_GEMINI_API_KEY
  daily_batch_size = 6
  max_concurrency = 2
  max_rpm = 5
  max_tpm = 250000
  max_daily_req = 20
  priority = 0
  enabled = 1
  is_emergency = 0

Google Flash Lite:
  model = gemini-flash-lite-latest
  daily_batch_size = 12
  max_rpm = 15
  max_tpm = 250000
  max_daily_req = 500
  priority = 1

Google Gemma 4 31B:
  model = gemma-4-31b-it
  daily_batch_size = 4
  max_rpm = 30
  max_tpm = 16000
  max_daily_req = 14400
  priority = 2

Google Gemma 4 26B:
  model = gemma-4-26b-a4b-it
  daily_batch_size = 3
  max_rpm = 30
  max_tpm = 16000
  max_daily_req = 14400
  priority = 3

GapGPT Gemini Lite:
  base_url = https://api.gapgpt.app/v1
  model = gemini-3.1-flash-lite
  api_key = $GAPGPT_API_KEY
  daily_batch_size = 6
  max_rpm = 30
  max_tpm = 300000
  max_daily_req = 1000
  priority = 0
  is_emergency = 1
```

All Google presets share the same `base_url` and `$GOOGLE_GEMINI_API_KEY` env var.

### 1.6 New DB functions

```python
def get_enabled_presets_ordered() -> list[dict]:
    """SELECT * FROM ai_presets WHERE enabled=1 ORDER BY is_emergency ASC, priority ASC, name ASC"""

def get_hourly_usage(preset_name: str, hours_back: int = 24) -> tuple[int, int]:
    """SELECT SUM(request_count), SUM(token_count) FROM preset_hourly_usage
       WHERE preset_name=? AND hour_bucket >= ?"""

def increment_hourly_usage(preset_name: str, hour_bucket: str, req_count=1, token_count=0):
    """INSERT OR UPDATE preset_hourly_usage ..."""

def set_preset_priority(name: str, priority: int):
def set_preset_enabled(name: str, enabled: bool):
def set_preset_emergency(name: str, is_emergency: bool):
```

---

## Phase 2 — AI Layer

### 2.1 `ai.py` — thread preset parameter through all functions

Add optional `preset: dict | None = None` parameter to:
- `_client(preset=None)`
- `_model(preset=None)`
- `_request_json(..., preset=None)`
- `ask_json(..., preset=None)`
- `ask_card(..., preset=None)`
- `ask_batch(..., preset=None)`
- `repair_card(..., preset=None)`

When `preset` is provided, `_client()` and `_model()` use it directly. When `None`, fall back to `db.get_active_preset()` (current behavior).

### 2.2 Define `RateLimitError` exception

```python
class RateLimitError(Exception):
    """Raised when an AI provider returns HTTP 429 (rate limited)."""
```

Detect in `_request_json()`: catch `openai.RateLimitError` or check `status_code == 429` on the raw response, then raise `RateLimitError`.

### 2.3 `llm_services.py` — rewrite `_call_ai_limited`

New architecture:

```python
def _call_ai_limited(function, *args, **kwargs):
    """Execute function with automatic fallback across the preset chain.

    For each preset in the chain (ordered by priority):
      1. Skip if rate-limited (RPM/TPM/daily)
      2. Acquire concurrency slot
      3. Wait for RPM slot
      4. Execute the function with this preset
      5. On RateLimitError: skip to next preset
      6. On other error: increment failures; skip if threshold reached
      7. On success: record usage, return result
    """
    chain = db.get_enabled_presets_ordered()
    if not chain:
        raise AllPresetsExhausted("No enabled presets available")

    for preset in chain:
        if _is_preset_rate_limited(preset):
            continue

        limiter = _get_limiter(preset)
        limiter["slots"].acquire()
        try:
            _wait_for_rpm(preset, limiter)
            result = function(*args, preset=preset, **kwargs)
            _record_success(preset)
            _log_preset_usage(preset, result)
            return result
        except RateLimitError:
            continue
        except Exception as exc:
            _record_failure(preset)
            if limiter["consecutive_failures"] >= 2:
                continue
            raise
        finally:
            limiter["slots"].release()

    raise AllPresetsExhausted(...)
```

### 2.4 Rate limit checking helpers

```python
def _is_preset_rate_limited(preset: dict) -> bool:
    if _is_rpm_exhausted(preset):
        return True
    if _is_tpm_exhausted(preset):
        return True
    if _is_daily_exhausted(preset):
        return True
    return False

def _is_daily_exhausted(preset: dict) -> bool:
    max_daily = preset.get("max_daily_req", 0)
    if max_daily <= 0:
        return False  # unlimited
    req_count, _ = db.get_hourly_usage(preset["name"], hours_back=24)
    return req_count >= max_daily

def _log_preset_usage(preset: dict, result):
    # Extract token count from result (from telemetry or prompt/completion)
    # Call db.increment_hourly_usage(...)
    # Update in-memory TPM/RPM trackers
```

### 2.5 In-memory TPM tracker

Alongside the existing RPM deque, add a TPM deque tracking tokens per minute:

```python
limiter["token_times"] = deque()  # (timestamp, token_count)
limiter["token_lock"] = threading.Lock()
```

---

## Phase 3 — Bot Layer

### 3.1 Wire `daily_batch_size` from preset into generation

In `_generate_daily_batch()`, `_ensure_next_daily_card()`, `_ensure_scheduled_session_cards()`:

```python
# BEFORE (hardcoded):
min(6, remaining)

# AFTER (from active preset):
preset = db.get_active_preset()
batch_size = preset.get("daily_batch_size", 6)
min(batch_size, remaining)
```

### 3.2 RPM-adaptive batching

```python
def _adaptive_batch_size(desired: int, preset: dict) -> int:
    remaining = _estimate_remaining_rpm_slots(preset)
    if remaining <= 2:
        return min(desired * 2, 30)  # double batch, cap at 30
    return desired
```

Apply in `_generate_daily_batch()` before calling `_ask_batch_limited()`.

### 3.3 Provenance storage

When storing generated cards, add provenance:

```python
# In _generate_daily_batch, after successful AI call:
preset_name = active_preset.get("name", "unknown")

# Pass to store function:
db.store_daily_cards(user_id, card_date, cards, provenance=preset_name)
```

Update `store_daily_cards()` and `store_grammar_tip()` to accept and persist `provenance`.

---

## Phase 4 — Admin UI

### 4.1 Keyboard changes

**Remove** from `ai_settings_keyboard()`:
- `IBTN_AI_PENDING`
- `IBTN_AI_APPLY`
- `IBTN_AI_ROLLBACK`

**Add**:
- `IBTN_FALLBACK_CHAIN` → `admin:fallback_chain`

**New keyboard functions**:
- `fallback_chain_keyboard(chain: list[dict])` — one row per preset with move up/down/toggle/emergency buttons
- `ab_test_preset_picker(presets: list[dict])` — multi-select preset picker with confirm

### 4.2 New handler: `_show_fallback_chain()`

```
🔄 مدیریت زنجیره فال‌بک

📊 Google 3.5 Flash: ۳ req امروز (از ۲۰)
  [⬆] [⬇] [🔴 غیرفعال]
📊 Google Flash Lite: ۰ req امروز (از ۵۰۰)
  [⬆] [⬇] [🔴 غیرفعال]
...

🚨 اضطراری: GapGPT Gemini Lite
  [🔴 غیرفعال]

[🧪 A/B Test] [↩️ بازگشت]
```

### 4.3 Actions

| Callback | Handler |
|---|---|
| `admin:fallback_chain` | `_show_fallback_chain()` |
| `admin:fallback:move_up:{name}` | Priority -= 1 |
| `admin:fallback:move_down:{name}` | Priority += 1 |
| `admin:fallback:toggle:{name}` | Toggle enabled |
| `admin:fallback:set_emergency:{name}` | Set is_emergency=1 for this, 0 for others |
| `admin:fallback:ab_test` | Start A/B test flow |

### 4.4 A/B Test flow

1. `admin:fallback:ab_test` → show `ab_test_preset_picker` (multi-select with ✓)
2. User selects presets → prompt for word/input text
3. User enters text → prompt for language
4. User selects language → execute prompt against each selected preset
5. Each result sent as a separate message with preset name header
6. Results logged to `config_tests` table

### 4.5 Remove dead `ai_fallback:status` button

The `Status: ...` button in `ai_fallback_keyboard()` had no handler — remove it entirely.

---

## Phase 5 — Cleanup & Validation

### 5.1 Dead code per file

| File | Remove |
|---|---|
| `services/db/__init__.py` | `get_pending_ai`, `set_pending_ai`, `clear_pending_ai`, `apply_pending_ai`, `diff_pending_vs_active`, `_init_pending_ai_settings_table`, `pending_ai_settings` table schema + init |
| `handlers/admin.py` | `_show_ai_pending`, `_apply_ai_pending`, `_rollback_ai_pending`, import of `ai_pending_keyboard` |
| `config/keyboards.py` | `ai_pending_keyboard()`, `IBTN_AI_PENDING`, `IBTN_AI_APPLY`, `IBTN_AI_ROLLBACK` |
| `bot.py` | Remove `admin:ai_pending`, `admin:ai_apply`, `admin:ai_rollback` from callback router (line ~178-183) |

### 5.2 Remove hardcoded `"gapgpt"` defaults

Replace all `"gapgpt"` literal defaults in `get_active_preset_name()`, `get_active_preset()`, and fallback settings with chain-based resolution.

### 5.3 Test updates

- `test_wiring.py` — verify new fallback chain callbacks are routed
- New tests for `preset_hourly_usage` CRUD
- New tests for `_is_preset_rate_limited()` logic
- New tests for fallback chain iteration
- New tests for provenance storage

---

## Files Changed (full list)

| # | File | Change type |
|---|---|---|
| 1 | `services/db/__init__.py` | Schema, new functions, dead code removal |
| 2 | `services/ai/ai_presets.py` | BUILTIN_PRESETS replacement |
| 3 | `services/ai/ai.py` | Preset parameter threading + RateLimitError |
| 4 | `services/ai/llm_services.py` | Fallback chain engine + TPM tracking |
| 5 | `bot.py` | Batch size wire-up + provenance + cleanup |
| 6 | `handlers/admin.py` | Fallback chain UI + A/B test + dead code removal |
| 7 | `config/keyboards.py` | New keyboards + dead code removal |
| 8 | `config/__init__.py` | Optional: new constants |
| 9 | `tests/test_wiring.py` | New callback prefix verification |
| 10 | `tests/` (new) | Rate limit + chain + provenance tests |

---

## Prompt for new session

Copy the following block to start a new implementation session:

---

```
You have the complete plan in docs/archive/PLAN_fallback_chain_and_batching.md.

Implement the plan phase by phase:

Phase 1: Schema & Database
- Add columns to ai_presets (priority, enabled, is_emergency, max_tpm, max_daily_req)
- Create preset_hourly_usage table
- Add provenance column to daily_cards and grammar_tips
- Remove all pending_ai_settings dead code (table, functions, handlers, keyboards, callbacks)
- Update BUILTIN_PRESETS in ai_presets.py with the 5 new presets
- Add new DB functions: get_enabled_presets_ordered, get_hourly_usage, increment_hourly_usage, set_preset_priority/enabled/emergency

Phase 2: AI Layer
- Thread optional preset parameter through ai.py functions (_client, _model, _request_json, ask_json, ask_card, ask_batch, repair_card)
- Define RateLimitError exception
- Rewrite llm_services.py _call_ai_limited with fallback chain, rate limit checking, usage logging
- Add in-memory TPM tracker alongside existing RPM tracker

Phase 3: Bot Layer
- Wire daily_batch_size from preset into _generate_daily_batch and callers
- Add RPM-adaptive batching function
- Store provenance on generated cards and grammar tips

Phase 4: Admin UI
- Replace ai_settings_keyboard (remove pending/apply/rollback, add fallback chain)
- Implement _show_fallback_chain with move up/down/toggle/emergency controls
- Implement A/B test flow with multi-select preset picker
- Remove dead ai_fallback:status button
- Create new keyboard functions (fallback_chain_keyboard, ab_test_preset_picker)

Phase 5: Cleanup & Validation
- Remove all hardcoded "gapgpt" defaults
- Run full validation: python -m unittest discover -s tests -v && python scripts/compile_all.py && python -m ruff check --select F821,F811 && python scripts/generate_dashboard.py && git diff --check

Follow the AGENTS.md workflow: contract lock before changes, explicit staging, conventional commit.
```
