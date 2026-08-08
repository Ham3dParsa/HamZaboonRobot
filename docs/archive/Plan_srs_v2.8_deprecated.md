# Plan: SRS v2.8 Session-Based Review Engine (Active)

> **Supersedes:** The previous adaptive SRS plan (2026-07-14). The old content is preserved below under "Archived".
>
> **Contract lock date:** 2026-07-20
>
> **Key departure from v1:** Replace push-based per-word reminders with a pull-based session model. Replace the adaptive `daily_reminder_cap` (dead code) with `sessions_used_today`. Introduce `interval_idx = -1` as a pre-graduation state with a 50-card backlog ceiling.

---

## 1. Core Architecture & Tier Economics

### 1.1 — Strict Separation of Limits (Cost Control)

- **Daily AI generation ceilings** for brand-new cards remain locked at **3 / 12 / 30 cards per day** (Free / Silver / Gold).
- **Custom AI query quotas** (`Ask a Word` and `Grammar Tip`) remain unchanged: **3 / 16 / 40 requests per day**.

### 1.2 — Session Sizing & Tier Economics

Each review session is fixed at exactly **5 cards**. Daily session quotas:

| Plan | Sessions/day | Max reviews/day |
|------|-------------|-----------------|
| Free | 1 | 5 |
| Silver | 4 | 20 |
| Gold | 10 | 50 |

**Owner bypass:** If `OWNER_BYPASS_LIMITS` is true and the user is an owner, bypass the 10-session ceiling entirely.

### 1.3 — Cleanup of Legacy Concepts

- The adaptive `daily_reminder_cap` and `reminder_cap_updated_at` columns on `users` are **dead code** — marked for future cleanup.
- The legacy "soft checkpoints every 5 cards" and "Review More" button are discarded. Starting a new session natively handles backlog catch-up.
- `sessions_used_today (INTEGER DEFAULT 0)` and `sessions_used_date (TEXT)` replace the cap columns.

### 1.4 — Deferred Items

The following are explicitly **not** part of this plan:
- **Content Pool** (Issue #80) — deferred until AI output format is locked by Phase 4 content quality work (#122, #123, #119).
- **Retention Points / Gamification** (Issues #84, #108) — no `retention_events` table yet; deferred until session engine is stable.
- **Travel-goal pacing biasing** — stretch goal, no frequency/practicality signal exists yet.

---

## 2. Contract-Locked Rules

### Rule 1 — Legacy Data Migration
- **Decision:** All existing `saved_words` reset to `interval_idx = -1`, `next_review = NULL`.
- **Reason:** Clean slate. All cards enter the pre-graduation pool regardless of prior interval progress.
- **Migration SQL:** `UPDATE saved_words SET interval_idx = -1, next_review = NULL`
- **GATE STATUS: LOCKED**

### Rule 2 — srs_job Coexistence
- **Decision:** Hard cutover. Once v2.8 sessions are deployed, the per-word push loop in `srs_job` is disabled entirely.
- **Reason:** Removes the dual-path confusion and the inner-raise bug path (#99).
- **GATE STATUS: LOCKED**

### Rule 3 — Streak Policy
- **Decision:** Streak advances only when all 5 cards in a session are reviewed (per-session completion).
- **Reason:** Incentivizes full sessions over partial engagement.
- **Implementation:** `touch_streak()` called once when `current_index` reaches the end of `card_ids`.
- **GATE STATUS: LOCKED**

### Rule 4 — Source A Button (Daily Card → SRS Hook)
- **Decision:** New dedicated inline button `👁 ثبت در مرور` on every daily card keyboard, visible to all plans.
- **Reason:** Clear, explicit action. Not conflated with pronunciation or translation.
- **On tap:** Check 50-card backlog ceiling → call `add_saved_word()` with `interval_idx = -1`.
- **GATE STATUS: LOCKED**

### Rule 5 — Session Quota Reset
- **Decision:** Lazy reset — compare `sessions_used_date` against `_today().isoformat()` on first session request of the day. If different, reset `sessions_used_today = 0`.
- **Reason:** No separate cron job needed; matches existing quota patterns.
- **GATE STATUS: LOCKED**

### Rule 6 — Backlog Ceiling
- **Decision:** Hard ceiling of 50 ungraduated cards (`interval_idx = -1`). Dynamic check at insertion time: `SELECT COUNT(*) FROM saved_words WHERE user_id = ? AND interval_idx = -1`. If ≥ 50, reject with alert: `"صف مرور شما پر است — ابتدا مواردی که دارید را مرور کنید."`
- **GATE STATUS: LOCKED**

---

## 3. New Schema

### 3.1 — `users` table additions

```sql
ALTER TABLE users ADD COLUMN sessions_used_today INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN sessions_used_date TEXT;
```

### 3.2 — `review_sessions` table

```sql
CREATE TABLE IF NOT EXISTS review_sessions (
    user_id INTEGER PRIMARY KEY,      -- Exactly one active session per user
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,      -- Target for Telegram in-place editing
    card_ids TEXT NOT NULL,           -- Comma-separated: "14,52,89,101,7"
    current_index INTEGER DEFAULT 0,  -- Pointer to active card
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 — `interval_idx` state machine

| Value | Meaning | Next step |
|-------|---------|-----------|
| `-1` | Pre-graduation (saved but never reviewed) | First interaction graduates to `0` |
| `0` | First review scheduled (today + 1 day) | `advance_word_review` → `1` |
| `1` | Survived 1-day interval (today + 3 days) | `advance_word_review` → `2` |
| `2` | Survived 3-day interval (today + 7 days) | `advance_word_review` → `3` |
| `3` | Survived 7-day interval (today + 16 days) | `advance_word_review` → `4` |
| `4` | Survived 16-day interval (today + 30 days) | Final checkpoint |

### 3.4 — `graduate_word()` new function

```python
def graduate_word(word_id: int) -> bool:
    """Move a word from interval_idx=-1 to 0, set next_review=today+1."""
    # Called on first user interaction inside a session
```

---

## 4. Session-Builder Query (Capped at 5 Cards)

```sql
-- Priority 1: Due reviews (idx >= 0, overdue first)
SELECT id FROM saved_words
WHERE user_id = ? AND interval_idx >= 0 AND next_review <= ?
ORDER BY (julianday(?) - julianday(next_review)) DESC
LIMIT 5;

-- Priority 2: Fill remaining slots from pre-graduation pool
SELECT id FROM saved_words
WHERE user_id = ? AND interval_idx = -1
ORDER BY added_at ASC
LIMIT ?;  -- remaining slots after Priority 1

-- Priority 3: Staleness protection — cards >60 days overdue demoted to idx=0
-- Applied during session-builder, not as a separate job
```

---

## 5. Deferral Split

Replace the single `defer_word_review()` with two separate operations:

### Action 1: Postpone (`بعداً مرور می‌کنم`)
- User is busy, content unseen.
- **Preserve** `interval_idx`.
- Set `next_review = today + 1`.
- Set `review_status = 'idle'`.

### Action 2: Again (`دوباره مرور`)
- User saw the card but failed to recall it.
- **Reset** `interval_idx = 0`.
- Set `next_review = today + 1`.
- Set `review_status = 'idle'`.

---

## 6. Admission Gate (How Words Enter SRS)

### Source A — Daily Card Interaction

- Daily cards do **not** auto-enter SRS on generation.
- A card enters `saved_words` with `interval_idx = -1` **only** if the user explicitly taps the `👁 ثبت در مرور` button during daily delivery.
- Uses existing idempotent `INSERT OR IGNORE` path keyed on `(user_id, lang, normalized_word)`.
- Subject to 50-card backlog ceiling check.

### Source B — Custom Word Query (`Ask a Word`)

- When user triggers `query:add:{token}`, write to `saved_words` with `interval_idx = -1`.
- Already uses `add_saved_word()` — change default from `0` to `-1`.

### Cutover rule

- Apply a timestamp-based cutover. Do not backfill legacy cards retroactively.

---

## 7. Implementation Roadmap

### Phase 1 — Immediate Hotfixes (ship now)

| # | Change | File | Status |
|---|--------|------|--------|
| 1 | Remove inner `raise` in `srs_job` — log + continue instead | `bot.py:1249-1251` | Pending |
| 2 | Add `ORDER BY (julianday('now') - julianday(next_review)) DESC` to `due_words_for_user()` | `services/db/__init__.py:1335` | Pending |

### Phase 2 — Backend Infrastructure & Quota Layer

| # | Change | Details |
|---|--------|---------|
| 3 | DB migration: add `sessions_used_today`, `sessions_used_date` to `users` | `services/db/__init__.py:init_db()` |
| 4 | DB migration: create `review_sessions` table | New `CREATE TABLE` |
| 5 | DB migration: reset all `interval_idx` to `-1`, `next_review` to `NULL` | `UPDATE saved_words SET interval_idx=-1, next_review=NULL` |
| 6 | Implement `graduate_word()` | New function in db layer |
| 7 | Implement lazy session quota reset | Compare date on session request |
| 8 | Update `_handle_query_add` to write `interval_idx = -1` | `srs_handler.py` |
| 9 | Add Source A button `👁 ثبت در مرور` to daily card keyboard | `keyboards.py:daily_card_keyboard()` |
| 10 | Implement 50-card backlog ceiling check | In `add_saved_word()` or handler |
| 11 | Split deferral: `postpone_word()` + `fail_word_review()` | Replace `defer_word_review()` |
| 12 | Disable old per-word push loop in `srs_job` | Remove inner card-sending code |

### Phase 3 — Telegram Session UI (In-Place Edits)

| # | Change | Details |
|---|--------|---------|
| 13 | Entry prompt: `"📚 زمان مرور! یک جلسه جدید آماده است. شروع کنیم؟"` | New handler or button |
| 14 | Empty queue guard: `"آفرین! همه کلمات را مرور کرده‌اید. 🎉"` | Check query returns > 0 |
| 15 | Session initialization: consume 1 quota slot, create `review_sessions` row | New handler |
| 16 | In-place card navigation via `srs_next` / `srs_prev` callbacks | `_edit_with_retry` |
| 17 | Progress indicator: `"کارت ۳ از ۵"` in message body | Render from `current_index` |
| 18 | `🔍 ترجمه` button on revealed cards using `example_translations` field | Keyboard addition |
| 19 | `🗑️ حذف` button (Issue #138) on session cards | Keyboard addition |
| 20 | Per-session streak completion check | `touch_streak()` at end of `card_ids` |

---

## 8. Database Hygiene

- `daily_reminder_cap` and `reminder_cap_updated_at` on `users` — **dead code**. Written during migration but never read at runtime.
- Cleanup is deferred to avoid changing schema alongside session migration. Mark for removal in a future sprint.

---

---

## Archived: Pre-v2.8 Adaptive SRS Plan (2026-07-14)

> The content below is the previous plan, **superseded** by the v2.8 Session Engine above. It is preserved for historical reference and audit traceability.

### Original Goal

Replace the current fixed, plan-agnostic SRS reminder behavior with a
per-user adaptive reminder system that responds to actual engagement, and
introduce a points/progress system that measures genuine retention and
learning signal rather than raw activity volume. This is the single highest
priority item on the roadmap right now: it directly affects retention and
perceived product quality, ahead of any cost-optimization or pooling work.

> **Implementation status (2026-07-14):** This document was a locked future
> plan, not the behavior currently running. The live
> baseline still used fixed intervals, sent every due non-pending word, had
> no SRS cap, and had no pending grace-window, claim, or retention-event
> implementation. Issues 42-46 and 59-60 tracked the resulting SRS gaps.

### Original Why This Was The Priority

Every other improvement discussed so far (content pooling, cost dashboards,
plan pricing) optimizes the business or engineering side of the product.
None of it matters if the core learning loop — new card today, reminder
tomorrow, retention next month — does not actually work better than a
generic flashcard app. The product's differentiation has to come from
demonstrably better retention outcomes, not from having "more" of any
single feature (more cards, more badges, more streaks) that competitors
already offer at the same or greater scale.

Gamification stays, but as a secondary layer that reflects real learning
signal, not a substitute for it. A user should never be able to raise their
score by generating volume (asking for more cards, more grammar tips)
without that volume translating into retained vocabulary.

### Original Baseline (What Existed)

- `saved_words` stores `interval_idx`, `next_review`, `review_status`
  (`idle` / `pending`), `review_requested_at`, and the full validated
  `card_data` payload — no new API call is needed to render a reminder.
- Review intervals are fixed and global: `INTERVALS_DAYS = [1, 3, 7, 16, 30]`
  in `services/db/__init__.py`. The index only advances on explicit user action
  (`advance_word_review`) — Telegram delivery success alone does not advance it.
- `users.goal` and `users.level` are already stored per user and already
  drive content generation — the same fields are the natural input for
  reminder pacing.
- There was currently no daily cap, no priority ordering beyond due-date
  order, and no points/progress table of any kind.
- `srs_job` caught errors around the whole per-user due-word loop, so one
  failed word could prevent later due words for that user from being attempted
  in the same run.

### Original Adaptive Pacing Design (Replaced)

The old plan specified:
- **Completion rate** (7-day rolling) as the control signal
- **Dynamic daily cap** adjusted by step function (70%/40% thresholds)
- **Overdue-priority ordering** (`today - next_review_date`)
- **Goal-informed pacing shape** (conversation vs exam)

All of the above are **replaced** by the v2.8 session model, which uses
fixed 5-card sessions with tier-based daily quotas instead of a dynamic
per-user cap.

### Original Scoring Design (Deferred)

The old plan specified **retention points** awarded at interval milestones
(1, 3, 6, 10 points for intervals 1-4, plus 10-point mastery bonus at
interval 4). This is **deferred** — no `retention_events` table will be
built until the session engine is stable in production.

### Original Data Model (Partially Replaced)

```sql
-- These columns are now DEAD CODE (never read at runtime):
ALTER TABLE users ADD COLUMN daily_reminder_cap INTEGER;
ALTER TABLE users ADD COLUMN reminder_cap_updated_at TEXT;

-- This table is DEFERRED:
CREATE TABLE IF NOT EXISTS retention_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    saved_word_id INTEGER NOT NULL,
    interval_idx_reached INTEGER NOT NULL,
    points_awarded INTEGER NOT NULL,
    occurred_at TEXT NOT NULL
);
```

### Original Audit Resolutions (Status)

1. **Pending-reminder grace window (48h)** — still valid, implemented in `due_words_for_user()`
2. **Cap adjustment idempotency** — made obsolete by removal of adaptive cap
3. **Goal-change mid-cycle** — still valid, applies to session pacing in future
4. **Scoring abuse** — deferred with retention_events
5. **Backward compatibility** — superseded by full reset to `-1`
6. **Reminder delivery idempotency** — handled by claim/release mechanism
7. **Per-word failure isolation** — hotfixed in Phase 1a (remove inner raise)
8. **Deferral semantics** — resolved by v2.8 split (postpone vs again)

### Original Implementation Slices (Superseded)

1. ~~Add `daily_reminder_cap`/`reminder_cap_updated_at` columns and `retention_events` table~~ → Done (columns exist but dead; table deferred)
2. ~~Implement overdue-priority ordering~~ → Subsumed by v2.8 session-builder query
3. ~~Completion-rate calculation and daily cap step function~~ → Replaced by session quotas
4. ~~Goal-informed pacing shape~~ → Deferred; session model is goal-agnostic in v1
5. ~~Retention-event logging and progress view~~ → Deferred
6. ~~Travel-goal pacing~~ → Deferred

### Original Definition of Done (Replaced)

The old definition of done is replaced by the v2.8 acceptance criteria:

- Users can start a review session on demand and see exactly 5 cards
- Session quota enforces plan tier limits (1/4/10 per day)
- Pre-graduation pool is capped at 50 cards; overflow is blocked with alert
- First card interaction graduates `-1 → 0` and enters the SM-2 ladder
- Streak advances only on full session completion
- No push-based review messages are sent (srs_job per-word loop disabled)
- All legacy saved_words migrated to `interval_idx = -1`
