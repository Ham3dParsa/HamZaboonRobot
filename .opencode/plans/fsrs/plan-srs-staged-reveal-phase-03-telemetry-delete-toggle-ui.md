---
name: srs-staged-reveal-phase-03-telemetry-delete-toggle-ui
description: Execution plan for #338 Phase 3 — review telemetry (R8/R12), delete-with-confirm (R6), per-user toggle UI (R7/R9), admin toggle UI (R10)
created: 2026-08-15
base_commit: pending (after Phase 2)
branch: feat/srs-staged-reveal
status: planned
---

STATE: phase 3/3 — status: PLANNED — tickets drafted (spec-to-tickets, 2026-08-15); blocking edge = Phase 2 merged (PR #355, `7cba7a6`, DONE); owner decisions LOCKED (2026-08-15) on toggle gating, presentation removal, delete scope; open questions all resolved — awaiting Phase 3 contract-lock gate

## Locked owner decisions (2026-08-15)

1. **Toggle gating:** display toggles are **premium-only** for now — the per-user toggle UI is gated like the `presentation` setting it replaces (non-premium users get default rendering, no toggle UI). The R10 resolution + admin-global defaults still apply to all users; only the user-facing toggle editing is premium-gated.
2. **Presentation removal:** the old brief/detailed `presentation` setting is **fully removed** — `settings:presentation` route, `presentation:set:` callback (bot.py), `set_presentation_preference`, `presentation_settings_keyboard`, and its premium-gate text all removed and replaced by the toggle UI. Legacy `presentation_preference` column stays (unread) per spec §8; removed symbols added to `tests/test_dead_code_guard.py` BANNED_SYMBOLS.
3. **Delete scope:** the `🗑 حذف کارت` button is available on **both** review front-stage cards AND first-exposure (new) cards.

## Blocking edges

1. Phase 2 merged (front/back staging + `srs:reveal:` + prompt_type/shown_at stash) — PR #355 (`7cba7a6`).
2. Phase 1 display-toggle storage/resolution already on `main` (`get_display_toggles`, `set_display_toggle`, `set_display_toggle_forced`, `set_display_toggle_defaults`).
3. Work in an isolated worktree from `origin/main`; run `parallel-work-guard` before locking.

## Scope (files/modules)

- `handlers/srs_handler.py` — telemetry in `_handle_srs_review`; delete handlers.
- `handlers/user.py` — per-user display-toggle settings UI (routed via `services/routing.py` + `handlers/flows.py`).
- `handlers/admin.py` — admin-global defaults + per-user forced override UI (routed via `services/routing.py`; render via `send_pretty`).
- `config/keyboards.py` — delete-confirm keyboard; front keyboard gains the delete row.
- `services/routing.py` (R1) — register `srs:delete:` / `srs:delete:yes:` / `srs:delete:no:` + new `settings:toggles:*` / admin toggle prefixes; `bot.py callback_router` is replaced by this registry.
- `services/db/words.py` — `delete_saved_word(word_id, user_id)` (R6 physical delete).
- `services/db/display_toggles.py` (`DisplayToggleService`) — owns display-toggle state + precedence (R3); use its accessors (replaces the old `db.set_display_toggle` in users.py/settings.py).
- `config/plan_identity.py` `has_feature(plan, feature)` — premium/tier gating for the toggle UI (see open decision on the feature key).

## Reconciliation vs landed refactors (base `d76ca7b`, 2026-08-18)

- **Callbacks via `services/routing.py`** (R1) — P3-T2/T3/T4 register prefixes there; admin `admin:` delegates to sub-routers, user `settings:*` to `handlers/user.py` / `handlers/flows.py`. `bot.py callback_router` no longer the registration point.
- **Display toggles owned by `services/db/display_toggles.py`** (`DisplayToggleService`) — P3-T3/T4 use its accessors, not `db.set_display_toggle` in users.py/settings.py.
- **Awaiting flows via `handlers/flows.py`** (R2 central registry `register_flow()`) — delete-confirm / toggle-edit text inputs register there.
- **Premium gating via `has_feature`** — `_FEATURE_MIN_RANK` has `presentation:2` but NO `display_toggles` key. Since display toggles **replace** the `presentation` setting (Phase-3 decision 2), reuse `has_feature(plan, "presentation")` for the toggle-UI gate (rank 2). Optional clarity rename to `display_toggles` is non-blocking hygiene.
- **Admin UI via `send_pretty`** — #388 migrated admin screens to the `send_pretty` span module; P3-T4 follows.

## Tickets

### P3-T1 — Review telemetry (R8/R12)
- **Blocking:** Phase 2 (prompt_type + shown_at stash; revealed marker).
- **Scope:** `_handle_srs_review` — `raw_signal = json.dumps({"button_value": grade, "prompt_type": <stashed or None>, "revealed": <stashed bool>})`; `response_time_ms` = front-stage-shown (stashed `card_shown_at_*`) → grade (existing). Pop stash on grade. first_exposure unchanged (`response_time_ms=None`; raw_signal stays `button_value`).
- **Tests:** assert `review_events.raw_signal` contains `prompt_type` + `revealed` for review and not for first-exposure; `response_time_ms` populated from prompt-shown.
- **Gates:** R8, R12.
- **Wiring:** none new.

### P3-T2 — Delete-with-confirm (R6)
- **Blocking:** Phase 2 (front keyboard exists; `srs:reveal:` flow).
- **Scope:** `config/keyboards.py` — `get_srs_delete_confirm_keyboard(user_id, word_id)` (`بله حذف شود` → `srs:delete:yes:`, `انصراف` → `srs:delete:no:`); add `🗑 حذف کارت از جعبه مرور` row to **both** `get_srs_front_keyboard` (review) and `get_first_exposure_keyboard` (new cards — owner decision 2026-08-15). `services/db/words.py::delete_saved_word(word_id, user_id)` — physical `DELETE FROM saved_words WHERE id=? AND user_id=?` (normalized, idempotent). `bot.py` routes `srs:delete:` / `srs:delete:yes:` / `srs:delete:no:`. Handlers in `srs_handler.py`: `_handle_srs_delete` (ownership guard → confirm message + confirm keyboard); `_handle_srs_delete_yes` (delete row → toast → pop node/`advance_session`); `_handle_srs_delete_no` (re-render the front stage on the same message).
- **Tests:** `tests/test_wiring.py` (3 new prefixes); `tests/test_srs_staged_reveal.py` — confirm shown, yes deletes row + advances, no restores front stage, double-tap idempotent; delete reachable from review AND first-exposure cards; integration flow.
- **Gates:** R6.
- **Wiring rows:** `srs:delete:` / `srs:delete:yes:` / `srs:delete:no:` → registered in `services/routing.py` (R1) → handlers in `srs_handler.py`; keyboard rows in `config/keyboards.py`.

### P3-T3 — Per-user toggle editing UI (R7/R9, premium-gated)
- **Blocking:** none (toggle accessors on `main`).
- **Scope:** `handlers/user.py` + `bot.py` settings routing — replace the `settings:presentation` flow with a **premium-gated** display-toggle submenu (one button per field); non-premium users see no toggle UI (or the previous premium-gate message). Toggle via `db.set_display_toggle`; turning OFF a high-value field (explanation, synonyms, antonyms, examples) shows the R9 warning popup (`خاموش کردن نمایش این مورد کیفیت و غنای تجربه آموزشی را کاهش میدهد. باز هم خاموشش میکنید؟ بله / انصراف`) before applying; low-value fields (phonetic, grammar_tip, example_translations) toggle directly. **Remove fully:** `settings:presentation` route, `presentation:set:` callback, `set_presentation_preference`, `presentation_settings_keyboard`, premium-gate text (owner decision 2026-08-15).
- **Tests:** user-settings integration tests; wiring for new settings prefixes; `tests/test_dead_code_guard.py` BANNED_SYMBOLS += removed presentation symbols; premium-gate test (free plan cannot open toggles; silver/gold can).
- **Gates:** R7, R9.
- **Wiring rows:** new `settings:toggles:*` (or `settings:display:*`) prefixes → user handlers.

### P3-T4 — Admin-global defaults + forced override (R10)
- **Blocking:** none.
- **Scope:** `handlers/admin.py` — display-toggle section: admin-global defaults for all fields (`set_display_toggle_defaults`), plus optional per-user forced override (`set_display_toggle_forced`) with a confirm + warn step. Extends the Phase-1 phonetic section to a full-field panel.
- **Tests:** admin integration tests; wiring for new `admin:` prefixes; `tests/test_wiring.py`.
- **Gates:** R10.
- **Wiring rows:** new `admin:` toggle prefixes → admin sub-router.

### P3-T5 — Integration + validation + review + PR
- **Blocking:** P3-T1..T4.
- **Scope:** end-to-end `tests/test_integration` flows (delete, toggles, admin), full §6 suite, independent review, Kilo loop, PR against `main`.
- **Gates:** §6 full validation, independent review, Kilo clean, PR merged.

## Acceptance criteria

- `review_events.raw_signal` carries `prompt_type` + `revealed`; `response_time_ms` reflects prompt→grade.
- Delete-with-confirm physically removes the row, idempotent, advances the session.
- Per-user toggles editable with R9 warning on high-value off; admin-global defaults + forced override work per R10 precedence.
- All §6 checks green; independent review + Kilo clean; PR merged.

## Open questions

All previously-open questions resolved by the owner (2026-08-15): toggle gating = premium-only; presentation setting fully removed; delete button on both review + first-exposure cards.