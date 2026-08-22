# Hamzaban — Living Project State & Architecture Map

> Single source of truth for current architectural state, active roadmap, domain vocabulary, and next atomic tasks.
> Updated as of **2026-08-22**. Keep under 100 lines. Canonical specs: `AGENTS.md`, `ROADMAP.md`, GitHub Issues. Pull-based study sessions only — no push delivery.

---

## 1. Architectural Guardrails & Principles

- **Separation of Concerns:** strict decoupling between **Learning Core** (`services/session/`, `services/fsrs_core.py` — sessions/cards), **Domain Engine** (`services/streak/` — continuity/XP/intensity, under construction), **Economy Ledger** (coins/items — future), and **Theme/Presentation** (`config/themes.py` — Persian Fire-Temple lore + UI text, future).
- **Single Source of Truth (AGENTS §3):** each domain concept lives in exactly one deep module under `services/` or `config/`; no business logic scattered in `config/` or handlers. Enforced by `tests/test_single_source_of_truth.py` + dead-reference guard (`tests/test_dead_code_guard.py`).
- **Atomic Operations:** hot-path writes use a single `BEGIN IMMEDIATE` transaction (`services/db/schema.py:transaction`); never hold an open transaction across an awaited async call.
- **Restart-Safety:** durable state persists before rendering; in-flight sessions survive restarts via `study_sessions`; idempotent re-grade guards (Bug #401 pattern).
- **Reliability:** AI behind global limiter + timeout; delivery/SRS through shared Telegram retry path; quotas atomic; secrets fail-closed (Fernet).
- **Wiring Integrity:** callback routing centralized in `services/routing.py` (longest-prefix `ROUTES` + `register()`); `tests/test_wiring.py` + `callback-wiring` skill gate every new prefix.

---

## 2. Ubiquitous Domain Vocabulary

| Term | Definition |
|---|---|
| **Continuity (Streak)** | Consecutive days with ≥1 valid **completed** session (`users.streak`, `users.last_active_date`). |
| **Daily Intensity (Flame)** | Runtime-calculated from plan capacity: L1 Base, L2 High-Heat, L3 Perfect Day. Matrix is **computed from `plans.max_sessions`**, never hardcoded per plan (owner decision BF-1). |
| **Shield (Angel/Guardian)** | Passive protection item, consumed on exactly-1-missed-day to preserve continuity; monthly quota per plan (Free 1, Bronze+ 2) — target, storage `users.streak_shields`. |
| **Effort XP** | Anti-gaming flat integer reward (`cards × 1 + 2/session + 5 perfect-day`); **no grade-based score inflation**. |
| **SessionCompleted** | The only authorized event that progresses streak, intensity, and XP. |
| **Theme Dictionary** | Presentation layer mapping domain states → Persian Fire-Temple lore + UI copy (target: `config/themes.py`). |
| **Grade Policy** | Per-activity grade resolution (`services/session/grade_policy.py`: srs_review, first_exposure, ai_quiz, sentence_write). |

---

## 3. Current Live Infrastructure (Baseline Reality)

### Database (`services/db/schema.py` — idempotent `init_db`)
- **Active tables:** `users`, `saved_words`, `settings`, `query_results`, `grammar_tips`, `llm_requests`, `review_events`, `study_sessions`, `session_grade_ledger`, `session_reports`, `ai_presets`, `preset_hourly_usage`, `preset_groups`, `config_tests`, `plans`. (Legacy `daily_cards`/`daily_progress`/`daily_card_sessions` migrated & dropped.)
- **Key `users` columns:** `streak`, `last_active_date`, plan/quota fields (`words_asked_today/date`, `grammar_tips_asked_today/date`, `optional_daily_limit`), card-mode & display toggles, `onboarded`, `bot_blocked`.
- **`plans` columns:** `query_quota`, `max_sessions`, `cards_per_session`, `is_active`, `first_exposure_mode`, `review_mode`. Seeds (`services/db/plans.py`): free 2/3 · bronze 3/3 · silver 3/5 · gold 4/7 · emerald 5/9 (sessions/cards).
- **`review_events`:** per-grade ledger (`grade`, `activity_type`, `grade_source`, `raw_signal`, `response_time_ms`; `response_time` only for `srs_review`).
- **`study_sessions`:** one row per user — the **active** session `state_json` (overwrite/UPSERT), cleared on completion.

### Session Lifecycle (`handlers/study_handler.py`)
1. **Start:** `handle_study_start` → quota check → `consume_session_slot` → `build_session_list` → persist + render first card.
2. **Quota:** daily session count in `settings` key `sessions_used_{user}_{date}` (`services/scheduling.py`); counts sessions **started**, bounds start, in-session footer "نشست X" via `_get_used`.
3. **Grade:** `_handle_srs_review` / `_handle_first_exposure_grade` → `grade_word_review` / `grade_first_exposure` → `record_review_event` → `advance_session`.
4. **Complete:** `advance_session` drains `state.nodes` (+ optional Tier-3 refill) → clears `study_sessions` row → completion message + session summary (Bronze+ via `has_feature("session_summary")`).

### Legacy Call Sites (pruning target)
`touch_streak` (`services/db/users.py:237-255`, exported at `services/db/__init__.py:60`) is currently called from 4 places: `handlers/srs_handler.py:279` & `:374`, `services/word_query.py:255`, `handlers/user.py:406`. **Marked for removal** in favor of the single `SessionCompleted` trigger. Verified safe for `tools/fsrs-replay/sim_runner.py` (computes streak locally, no `services.db` import).

---

## 4. Active Milestone Tracker

- [x] **M0 — System Audit & Contract Lock.** SPEC-STREAK-2026-08-19-V3 finalized. Audits: `docs/audit/Streak/streak_system_audit_2026-08-19.html`, `docs/audit/Streak/streak_engine_technical_audit_2026-08-19.md`. **7 blocking findings (BF-1…BF-7) open** — owner decisions required before M1: plan matrix vs live `plans` (BF-1), shield capacity source (BF-3), Free-XP gating vs #108 (BF-4), session day-attribution (BF-7), refill hook scope (BF-5).
- [ ] **M1 — Core Continuity & Daily Stats (Domain Skeleton).** *Ready to implement.* Schema delta (`daily_study_stats` + `users` columns `total_xp`, `best_streak`, `streak_shields`, `shield_last_reset_month`), `services/streak/` deep module (DTOs + pure math), unit tests (day boundaries, shield depletion, idempotency).
- [ ] **M2 — Atomic Wiring & Hot Path.** *Backlog.* `SessionCompleted` trigger in `advance_session` before `clear_study_session`; single `BEGIN IMMEDIATE` bundling; per-session idempotency token; per-user `asyncio.Lock` (`bot.py:224-228`).
- [ ] **M3 — Theme Registry & UI Formatting.** *Backlog.* `config/themes.py`; `/status` (`handlers/user.py:484`) + end-of-session copy via `services/utils/formatting.py`.
- [ ] **M4 — Streak Shield & Passive Rescue Hook.** *Backlog.* Monthly quota refill; lazy `ensure_streak_state` hook in `/status` & `/start`.
- [ ] **M5 — Economy Ledger & Shop Abstraction.** *Future backlog.* Coins/items; depends on retention events (#84).

---

## 5. Current Active Task (Immediate Next Step)

- **Target:** M1 (Phase 1) — Data Layer & Core Domain.
- **Action:** add `daily_study_stats` table + the 4 `users` columns via the existing idempotent `init_db` ALTER pattern; build the pure math engine in `services/streak/` with the two DTOs (`SessionResult`, `StreakState`); backfill `best_streak = MAX(best_streak, streak)`.
- **Blocked by:** owner decisions BF-1 (plan matrix), BF-3 (shield source), BF-4 (gating) — see M0.

---

## 6. Recent Macro Architecture Changes

1. **FSRS-6 migration:** legacy daily-card tables replaced by FSRS scheduling on `saved_words` (`stability`/`difficulty`/`next_review_at`) + `review_events`; pure engine in `services/fsrs_core.py`.
2. **Deep-module decomposition + routing centralization:** monolith `bot.py`/handlers split into `services/` domain modules and focused handlers; callback registry + guards centralized in `services/routing.py`.
3. **Study-session engine:** `services/session/` (assembly, grade policy, summary) + restart-safe persistence via `study_sessions`, idempotent re-grade recovery, post-session reports (R10).
4. **Plan-driven quotas & admin plan manager:** `plans` table becomes the sole source of per-plan limits; admin wizard (`handlers/admin_plans.py`); plan-identity feature gating (`config/plan_identity.py`).
5. **AI governance & cost tracking:** preset registry with fallback chain + hourly usage, LLM cost accounting, Fernet key encryption (fail-closed) — `services/ai/`, `services/db/{preset_registry,cost_tracking,key_crypto}.py`.