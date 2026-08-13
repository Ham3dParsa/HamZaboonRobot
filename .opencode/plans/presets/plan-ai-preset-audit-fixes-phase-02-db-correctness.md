# Phase 02 — DB correctness (R1, R2, R10, R12, R13, R14)

- **Blocking edges:** R2 (`priority` column) before R14 (create uses priority); R1 ordering before Phase 06 (R17 failover).
- **Scope (files):**
  - `services/db/preset_registry.py` — R1 single order source (`get_fallback_chain_presets` + swap within tier + `set_emergency` flips only target); R2 add `priority` to `set_preset`; R10 `get_active_preset` hard-error + owner alert when none/disabled; R12 guards (rename collision via `previous_name`, emergency-flip-one, no-disable-last, repair `ai_fallback_preset` on delete); R13 atomic quota reserve + prune >24h + count failure only if usage/partial; R14 create defaults disabled+lowest + status/priority prompt + inline test.
  - `services/ai/llm_services.py` — R13 quota atomic + count-token-failures; R10 failover uses priority chain; R13b failure-threshold backoff (`FAILURE_THRESHOLD=3`, `BACKOFF_SECONDS=60`) sidelining then recovery to preferred.
  - `services/ai/ai.py` — R10 no silent `{}`.
  - `handlers/admin_ai.py` — R14 create/duplicate flow + R2 wizard priority; create-flow state machine (priority → status → summary + inline test + enable toggle → full-edit wizard).
  - `handlers/admin.py` — wire new awaiting state `ai_preset_create_priority:<name>` into `_handle_admin_text_input` dispatch (covered by existing `ai_preset_` prefix in `_ADMIN_AWAITING_PREFIXES`).
- **Tests:** `tests/test_preset_registry.py` (order, priority, guards, quota); `tests/test_preset_registry_phase2.py`; `tests/test_fallback_backoff.py`; `tests/test_integration/test_ai_preset_create_flow.py` (create flow, no-active error); `tests/test_wiring.py` (new callbacks auto-collected).
- **Gates:** R1, R2, R10, R12, R13, R14.
- **Wiring rows:** Persistence (order, priority, active, guards, quota) update; AI/LLM Provider (quota atomic, failover, backoff) update; AI Config (create flow) update.
- **Acceptance:** single order source; priority persisted via wizard; no-active → hard error + owner alert (no silent `{}`); rename/emergency/disable-last/fallback-repair guarded; quota atomic + pruned + token-failure counted; create prompts status/priority + test, default disabled/lowest.

## Locked R14 decisions (owner, in-session)

- Priority prompted via inline keyboard: `[top (preferred)]` / `[enter a number]` (manual text input) / `[bottom (least priority)]`.
- Status (enabled/disabled) prompted with a lightweight ping-test button on the status step.
- After name accepted: create summary + inline test + enable toggle, then continue into the full-edit wizard.
- Defaults: new preset created **disabled** and at **lowest priority** unless owner explicitly chooses otherwise at the prompts.
- `set_preset` gained an `enabled` param (default 1) so a new preset can be created disabled at insert time, bypassing the no-disable-last guard (which lives only in `set_preset_enabled`).
- Owner decision (reindex always): for **top / bottom / manual-value**, the fallback-chain priority is reindexed (densified 0,1,2,...) via new `db.insert_preset_at_rank` so the choice yields the intended position and "top" is always genuinely first (no tie-by-name). `insert_preset_at_rank` renumbers only the enabled normal in-fallback group, leaves emergency rows alone, and accepts a disabled target. Manual rank out of range is clamped to the last slot in the handler. Owner decision: `AIRequestTimedOut` (global caller-deadline abort) is NOT counted toward the R13 backoff counter — provider timeouts and 429s are.
- Temperature already satisfies the owner requirement: `temperature` is in `WIZARD_FIELDS` and `set_preset` applies it — no code change needed.
