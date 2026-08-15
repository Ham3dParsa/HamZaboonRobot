---
name: srs-staged-reveal-phase-02-session-staging
description: Execution plan for #338 Phase 2 — session-flow staging: review front-stage render, reveal callback, back-stage render, first-exposure badge, keyboards + wiring
created: 2026-08-15
base_commit: dce5bc8
branch: feat/srs-staged-reveal
status: complete
---

STATE: phase 2/3 — status: COMPLETE — PR #355 merged 2026-08-15 (`7cba7a6`); P2-T1..T4 shipped with TDD tests + integration flow; Kilo review clean ("Merge"); claim released, worktree removed. Next: Phase 3 (telemetry/delete/toggle UI) per phase-03 plan — 2026-08-15

## Blocking edges

1. Phase 1 merged (PR #353) — prompt engine (`format_srs_front_stage`/`format_srs_back_stage`/`select_srs_prompt_type`/`format_review_badge`/`NEW_CARD_BADGE`) + display-toggle storage/resolution (`get_display_toggles`, `set_display_toggle*`, defaults) available on `main`.
2. No parallel claim on seams 1, 3, 4, 5, 6, 8 (Phase-1 claim released; `feat/per-language-goals` holds seam 7 — disjoint).
3. Work in an isolated worktree from `origin/main`; run `parallel-work-guard` before locking.

## Scope (files/modules)

- `handlers/study_handler.py` — `_build_card_text_and_keyboard`: `srs_review` → front stage; `first_exposure` → full card + `کارت جدید ✨` badge.
- `handlers/srs_handler.py` — new `_handle_srs_reveal`.
- `config/keyboards.py` — new `get_srs_front_keyboard` (Row1 `👁 نمایش پاسخ`); review back keyboard reuses `get_review_keyboard`.
- `bot.py` `callback_router` — new `srs:reveal:` route before `srs:` catch-all.
- `services/utils/formatting.py` — days-since-last-review helper for `format_review_badge` (small, only if not already present).

## Tickets

### P2-T1 — Review front-stage render
- **Blocking:** Phase 1 merged.
- **Scope:** `_build_card_text_and_keyboard` for `node.activity_type == "srs_review"`: pick `prompt_type = select_srs_prompt_type(card_data, toggles)` (system RNG), render `format_srs_front_stage(card_data, prompt_type, toggles=db.get_display_toggles(user_id), phonetic_lines=..., badge=format_review_badge(days_since_last_review), footer=progress)`. Stash `context.user_data[f"prompt_type_{word_id}"]` and `card_shown_at_{word_id}` (epoch) for P3 telemetry. `first_exposure` → `format_card` + `NEW_CARD_BADGE` badge + footer (R5).
- **Tests:** `tests/test_study_handler.py` — front-stage text: hidden (no fa_meaning/examples), badge/footer/sub-instruction present; toggles respected (e.g. synonyms off ⇒ no synonym prompt in the message); FE shows `کارت جدید ✨`. Days-since-last-review helper unit test.
- **Gates:** R1, R2, R3, R4, R5, R11.
- **Wiring:** none new.
- **Open items:** none.

### P2-T2 — Reveal callback + back-stage render
- **Blocking:** P2-T1 (prompt stash), P2-T3 (keyboard).
- **Scope:** `bot.py`: `elif data.startswith("srs:reveal:"):` (parts length 4) → `_handle_srs_reveal(update, context, parts[2], parts[3])`. `_handle_srs_reveal` in `srs_handler.py`: ownership guard (uid == effective user), re-fetch card via `_saved_word_card`, render `format_srs_back_stage(card_data, toggles=db.get_display_toggles(user_id), phonetic_lines=..., footer=progress)` (progress + sub-instruction on back stage per R4), `edit_message_text` + swap to `get_review_keyboard` (4-grade + pronounce). Mark reveal (e.g. `context.user_data[f"revealed_{word_id}"] = True`) for P3 telemetry. Guard repeated reveal (idempotent: ignore if already revealed).
- **Tests:** `tests/test_wiring.py` (ALLOWLIST += `srs:reveal:`); handler test — reveal edits text to back stage + swaps keyboard; repeated reveal safe; wrong-user rejected.
- **Gates:** R4, R7 (back stage respects toggles).
- **Wiring rows:** `srs:reveal:{uid}:{wid}` → `_handle_srs_reveal` (bot.py callback_router).

### P2-T3 — Front review keyboard + FE badge wiring
- **Blocking:** none (independent of P2-T1 except FE badge text).
- **Scope:** `config/keyboards.py` — `get_srs_front_keyboard(user_id, word_id)` → `[[👁 نمایش پاسخ → srs:reveal:{uid}:{wid}]]` (delete row deferred to P3-T2 to keep wiring green). Wire `NEW_CARD_BADGE` + progress footer into the `first_exposure` branch of `_build_card_text_and_keyboard` (R5).
- **Tests:** `tests/test_keyboards.py` — front keyboard has exactly the reveal callback; FE message contains `کارت جدید ✨` + footer.
- **Gates:** R4, R5.
- **Wiring rows:** `srs:reveal:` consumed by front keyboard (paired with P2-T2).

### P2-T4 — Wiring + integration tests + validation + PR
- **Blocking:** P2-T1..T3.
- **Scope:** `tests/test_wiring.py` integrity (reveal route); new `tests/test_integration/test_srs_staged_reveal_flow.py` — review node: message = front stage → tap `srs:reveal:` → back stage + grades → grade → `advance_session` to next node; first-exposure node: full card + badge → grade → advance; resume-session still renders the front stage. Update stale assertions in `tests/test_srs_staged_reveal.py` / `tests/test_study_handler.py` that assumed full-card render for review nodes.
- **Gates:** §6 full validation, independent review, Kilo loop, PR against `main`.

## Acceptance criteria

- Review nodes render a staged front stage (never the full card); first-exposure nodes render the full card with `کارت جدید ✨`.
- `srs:reveal:` swaps message to the back stage and grade keyboard; wiring test green.
- All §6 checks green; independent review + Kilo clean; PR merged.

## Open questions (resolve at contract-lock before Phase 3)

None for Phase 2. (Delete button + confirm flow = Phase 3-T2.)