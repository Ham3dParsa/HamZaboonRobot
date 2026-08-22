# Hamzaban — Living Project State & Architecture Map

> Single source of truth for current architectural state, active roadmap, domain vocabulary, and next atomic tasks.
> Updated as of **2026-08-22**. Keep under 100 lines. Canonical specs: `AGENTS.md`, `ROADMAP.md`, GitHub Issues. Pull-based study sessions only — no push delivery.

---

## 1. Architectural Guardrails & Principles

- **Separation of Concerns:** Learning Core (`services/session/`, `services/fsrs_core.py`), streak domain (`services/streak/` — under construction), Economy (future), Theme/Presentation (`config/themes.py` — future).
- **Single Source of Truth (AGENTS §3):** one deep module per domain concept; enforced by `tests/test_single_source_of_truth.py` + dead-reference guard.
- **Atomic Operations:** hot-path writes via `services/db/schema.py:transaction` (`BEGIN IMMEDIATE`); never hold transaction across await.
- **Restart-Safety:** persist `study_sessions` before render; idempotent re-grade guards (Bug #401); grace reset via job every 30 min.
- **Reliability:** AI behind limiter + timeout; session/SRS via shared Telegram retry; quotas atomic; keys Fernet fail-closed; `MaintenanceGate` exclusive for backup/restore.
- **Wiring Integrity:** `services/routing.py` longest-prefix `ROUTES` + `register()`; `tests/test_wiring.py` gates every prefix.

---

## 2. Ubiquitous Domain Vocabulary

| Term | Definition |
|---|---|
| **Continuity (Streak)** | Consecutive days with ≥1 completed session (`users.streak`, `users.last_active_date`). |
| **Daily Intensity (Flame)** | Computed from `plans.max_sessions`: L1 Base, L2 High-Heat, L3 Perfect Day. |
| **Shield** | Consumed on 1 missed day; monthly quota (Free 1, Bronze+ 2) → `users.streak_shields` (planned). |
| **Effort XP** | Flat `cards×1 + 2/session +5 perfect-day`; no grade inflation (planned). |
| **SessionCompleted** | Sole event advancing streak/intensity/XP. |
| **Grade Policy** | `services/session/grade_policy.py` per activity (srs_review, first_exposure). |

---

## 3. Current Live Infrastructure (Baseline Reality)

### Database (`services/db/schema.py` — idempotent `init_db`)
- **Active tables:** `users`, `saved_words`, `settings`, `query_results`, `grammar_tips`, `llm_requests`, `review_events`, `study_sessions`, `session_grade_ledger`, `session_reports`, `ai_presets`, `preset_hourly_usage`, `preset_groups`, `config_tests`, `plans`. Legacy `daily_cards` dropped.
- **`users`:** `streak`, `last_active_date`, quota fields, `first_exposure_mode`/`review_mode` (staged/immediate), `display_toggles`, `onboarded`, `bot_blocked`. Legacy `preferred_delivery_minute` columns remain but unused.
- **`plans`:** `query_quota`, `max_sessions`, `cards_per_session`, `is_active`, `first_exposure_mode`, `review_mode`. Seeds: free 2/3 · bronze 3/3 · silver 3/5 · gold 4/7 · emerald 5/9.
- **`saved_words`:** `stability`/`difficulty`/`next_review_at`/`last_review_at` (FSRS-6), `normalized_word` (NFC+casefold), `card_data` full payload.
- **`study_sessions`:** one row per user (`state_json` UPSERT), cleared on completion.

### Session Lifecycle (`handlers/study_handler.py`)
1. **Start:** `handle_study_start` → `consume_session_slot` (`services/scheduling.py`) → `build_session_list` (Tier1 due → Tier2 first-exposure → Tier3 stub) → persist → render.
2. **Quota:** `settings:sessions_used_{user}_{date}`; footer `نشست X` / `کارت n از m`.
3. **Grade:** `grade_word_review`/`grade_first_exposure` → `record_review_event` → `advance_session` (edit in place).
4. **Complete:** drain nodes → clear `study_sessions` → summary + 3-day `session_reports` (`/reports`).

### Legacy Call Sites (pruning target)
`touch_streak` in `services/db/users.py` called from `handlers/srs_handler.py`, `services/word_query.py`, `handlers/user.py`. To be replaced by `SessionCompleted`.

---

## 4. Active Milestone Tracker

- [x] **M0 — Audit & Contract Lock.** SPEC-STREAK-2026-08-19-V3 done. 7 BFs open (plan matrix, shield source, gating, day-attribution).
- [ ] **M1 — Core Continuity & Daily Stats.** Schema `daily_study_stats` + `users.total_xp/best_streak/streak_shields`; `services/streak/` DTOs.
- [ ] **M2 — Atomic Wiring.** `SessionCompleted` in `advance_session` before clear; `BEGIN IMMEDIATE` bundling; idempotency token.
- [ ] **M3 — Theme Registry.** `config/themes.py`; `/status` copy.
- [ ] **M4 — Shield & Rescue Hook.** Monthly refill; lazy `ensure_streak_state`.
- [ ] **M5 — Economy Ledger.** Coins/items; depends on retention events.

---

## 5. Current Active Task

- **Target:** M1 — Data Layer & Core Domain.
- **Action:** `daily_study_stats` + 4 `users` columns via `init_db` ALTER; pure math in `services/streak/`; backfill `best_streak`.
- **Blocked by:** BF-1, BF-3, BF-4 owner decisions.

---

## 6. Recent Macro Architecture Changes

1. **FSRS-6:** `saved_words` FSRS columns + `review_events`; `services/fsrs_core.py`; short_term on.
2. **Session engine:** `services/session/` + restart-safe `study_sessions` + R10 reports; staged/immediate card modes (`first_exposure_mode`/`review_mode`).
3. **Deep-module split + routing:** `services/routing.py` central registry; guards.
4. **Plan quotas:** `plans` table sole source; admin wizard; feature gating.
5. **AI governance:** preset fallback chain, hourly usage, cost tracking, Fernet encryption, display toggles.
