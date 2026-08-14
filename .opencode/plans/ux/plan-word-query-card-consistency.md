---
name: word-query-card-consistency
description: Locked spec — unify word-query card output with session cards (default spoiler translations, remove Translations button), move quota to closing message, and add duplicate-word retrieve-vs-new with 30-day retention.
created: 2026-08-14
base_commit: pending (R7/R8 deferred)
branch: pending
status: locked-spec
---

STATE: phase 2/2 — status: IN PROGRESS — phase 1 (R1-R6) shipped (#341); phase 2 (R7-R8) implementing on feat/word-query-dup-retention (#344). See phase-02 sub-plan.

# Spec — Word-Query Output Pipeline & Final Message Structure

> **Status:** LOCKED (owner decisions via grill, 2026-08-14). Split into two
> phases by the Persistence-seam gate. Tracking issue: see §7.

## 0. Contract Lock Summary (GATE STATUS: LOCKED)

| Rule | Decision | Option | Green? |
|---|---|---|---|
| R1 | Word-query card renders translations **on by default as MarkdownV2 spoilers** (`translations_prepared=True`); English examples shown exactly as now | A | ✅ |
| R2 | **Remove** the `Translations` reveal button (`IBTN_TRANSLATIONS` → `query:prepare:`) | A | ✅ |
| R3 | **Full removal** of dead prepare path: `_handle_query_prepare` (handlers/user.py:519), `query:prepare:` routing (bot.py:451,534-535), `word_query.prepare` + `PrepareResult` (services/word_query.py), `_message_has_prepared_translations` (helpers.py:134) if it becomes unused, and related tests. **Verify TTS `show_pronounce` is set at ask-time** (bot.py:370) so TTS keeps working | A | ✅ |
| R4 | Keep **Add-to-review** and **Pronounce** buttons as-is | A | ✅ |
| R5 | Keep `brief`/`detailed` `presentation` knob for now; replaced later by display-toggle spec (#338 R7) | A | ✅ |
| R6 | **Quota moves to the closing message** (usage + remaining) replacing «به منوی اصلی برگشتی 🙂» + main-menu markup. Card footer = add-to-review instruction only (drop usage line from card) | A | ✅ |
| R7a | Prior card = same normalized word + user + **same lang**, within retention window | A | 🔴 Persistence |
| R7b | 2-button choice after typing: «درخواست جدید (مصرف سهمیه)» / «بازیابی کارت قبلی»; no prior → normal ask | A | 🔴 (callbacks `query:dup:*`, no seam) |
| R7c | Retrieve is **free** (no quota, no AI call) — re-render stored `result_json` | A | 🔴 Persistence |
| R8a | Retention window = **30 days** (reuse `expires_at` as marker; change default TTL 24h→30d in `create_query_result`) | 30 days | 🔴 Persistence |
| R8b | **Purge all** `query_results` rows older than 30 days (saved or not); `saved_words` is the permanent store; wire a real scheduled cleanup job | A | 🔴 Persistence |

## 1. Rationale

- **Consistency:** session back-stage cards already render `📝 مثال‌ها + ترجمه` as
  `||spoiler||` via `format_card(translations_prepared=True)`. Word-query currently
  hides them behind a button — an unnecessary extra tap. Unify both surfaces.
- **Quota placement:** the usage/remaining summary belongs in the closing message
  (post-delivery), not inside the card.
- **Duplicate retrieve:** a repeated word should not force a fresh (quota-consuming,
  AI-costing) card when a good card already exists for that user+lang.
- **Retention:** query_results is a transient per-user search cache; saved words live
  permanently in `saved_words`. The future **content pool** is a separate canonical
  cross-user store that will **supersede** R7 for frequent words — R7 is its per-user
  precursor and must not conflict with it (pool = its own table).

## 2. Phase 1 (green) — R1–R6

1. `bot.py` ask-word block: pass `translations_prepared=True` to `format_card`
   (line 381); remove `show_translations=True`/`query_kb_...` show_translations usage.
2. `config/keyboards.py` `query_result_keyboard`: remove `IBTN_TRANSLATIONS` + the
   `query:prepare:{token}` button + the `show_translations` param; keep Add-to-review
   and Pronounce.
3. Remove dead prepare path (R3) + update tests.
4. `bot.py` closing message: replace «به منوی اصلی برگشتی 🙂» with a message showing
   `word_query_usage_text(row)` (usage + remaining) + `main_menu` markup. Remove usage
   line from the card footer (keep add-to-review instruction).
5. Keep `presentation=_user_presentation(row)` (R5).

## 3. Phase 2 (deferred on Persistence seam) — R7–R8

1. `services/db/__init__.py`: change `create_query_result` default
   `ttl_seconds` 24h→30d; add `find_unexpired_query(user_id, word, lang)`; wire
   `cleanup_expired_query_results` into a scheduled job (reuse retry job cadence or a
   new repeating job).
2. `services/word_query.py`: add duplicate-lookup orchestration (check prior card →
   return choice or reuse result).
3. `config/keyboards.py`: add duplicate-choice keyboard (`query:dup:new` /
   `query:dup:reuse`); `bot.py` callback_router: remove `query:prepare:`, add
   `query:dup:new` + `query:dup:reuse`.
4. Retrieve path: re-render stored `result_json` with `translations_prepared=True`,
   send closing usage message; no quota, no AI.

## 4. Dependency & Wiring Map

| Surface | Current | Disposition | Gate |
|---|---|---|---|
| `bot.py` ask-word block | `format_card` w/o translations_prepared; `show_translations=True`; closing «برگشتی» | **update** (R1,R6) | ✅ |
| `bot.py` callback_router | routes `query:add:`, `query:prepare:` | **update** (R2,R7b): remove prepare, add dup | ✅ + 🔴 |
| `bot.py` jobs | retry job 1800s | **update** (R8b): wire cleanup | 🔴 |
| `config/keyboards.py` | `query_result_keyboard` (IBTN_TRANSLATIONS, show_translations) | **update** (R2,R4,R7b) | ✅ + 🔴 |
| `handlers/user.py` | `_handle_query_prepare` | **remove** (R3) | ✅ |
| `services/word_query.py` | `prepare`, `PrepareResult` | **remove** (R3) + add dup orchestration (R7) | ✅ + 🔴 |
| `services/db/__init__.py` | ttl 24h; `cleanup_expired_query_results` defined-but-dead; no by-word lookup | **update** (R7a,R8) | 🔴 Persistence |
| `services/utils/helpers.py` | `_message_has_prepared_translations` | **remove** if unused after R3 | ✅ |
| `services/utils/formatting.py` | `format_card` (spoiler support), `word_query_usage_text` | **keep** (reuse) | ✅ |
| tests | test_custom_word_query.py, test_word_query.py, test_integration/test_word_query_prepare_toggle_flow.py, test_custom_word_quota_flow.py, test_word_query_ask_flow.py, test_wiring.py | **update/remove** (R3,R6,R7,R8) | both |

**Verification guards:** `tests/test_wiring.py` (query:prepare removed, query:dup added),
`tests/test_dead_code_guard.py` (removed symbols), `tests/test_formatting.py`.

## 5. Parallel-Work / Seam Note

- **Green now:** formatting, keyboards, bot routing, handlers/user, word_query,
  helpers — none are claimed seams.
- **Deferred (Persistence seam = `services/db/__init__.py` + `schema.py`, claimed by
  `feat/ai-preset-secure-keys`):** R7 (by-word lookup) + R8 (TTL + purge). Owner chose
  **split**: implement R1-R6 now, R7-R8 later. Re-check claims before starting phase 2.

## 6. Future Pool Alignment

Content pool is a separate canonical cross-user store (~1000 frequent words per
lang-level, AI-quality-gated). A user's good search card is a valid *candidate
source* but must be curated/validated before becoming canonical. When the pool lands,
the ask flow should serve pooled cards before AI for any user — superseding R7 for
frequent words. Keep `query_results` per-user and out of the pool's way (pool = its
own table).

## 7. Tracking

- **GitHub Issue:** [#340](https://github.com/Ham3dParsa/HamZaboonRobot/issues/340) tracks this spec (recorded in TICKETS.md).
- **Plan register:** `.opencode/plans/TICKETS.md`.
- **Blocked Questions:** none outstanding.

## 8. Deferred

- Phase 2 (R7-R8) until the AI-preset branch releases the Persistence seam.
- Display-toggle refactor of `brief`/`detailed` (R5) → display-toggle spec #338.
