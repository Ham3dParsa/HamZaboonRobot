# Plan: SRS v3 — Pull-Based Hybrid Smart Session Engine

> **STATUS: Active — Replaces v2.8 (archived at `docs/archive/Plan_srs_v2.8_deprecated.md`)**
>
> **Contract lock date:** 2026-07-26
>
> **Key departure from v2.8:** Abandon push-based delivery entirely. A single golden button initiates on-demand Smart Sessions. Scheduled flashcard pushing is replaced by lightweight AI-nudge engagement messages.

---

## 1. Core Philosophy

### 1.1 — Pull-Based, Always

The learner **pulls** content when ready. No flashcards are ever pushed via cron jobs. The system provides a single entry point:

> **📚 شروع مطالعه امروز (Start Today's Study)**

This button replaces all of:
- `BTN_TODAY_CARD` (فلش‌کارت امروز)
- `BTN_SRS_REVIEW` (شروع مرور SRS)
- `daily_job` / `srs_job` / `srs_retry_job` scheduled pushes

**Zero backlog anxiety.** The learner is never behind. Whatever they haven't studied today simply waits for tomorrow's session cap.

### 1.2 — Dynamic Session Size (Per Plan, User-Customizable)

- Session size is **dynamic per plan**: Free = 5, Silver = 6, Gold = 7.
- A session is generated on-demand when the user presses the study button.
- The session fills its slots via the 3-Tier Priority Queue (Section 3), capped by the plan's session size.
- The session is presented as a linear sequence; the user advances at their own pace.
- A session is "completed" when all cards have been viewed (regardless of review outcome).
- Premium users can customize their session cap in settings (future UI).
- Partial sessions do NOT consume a quota slot — only fully started sessions count.

### 1.3 — No More Push Loops

All scheduled cron jobs that push flashcards (`srs_job`, `srs_retry_job`, `daily_job`, `delivery_dispatch_job`, `_dispatch_queue`) are **removed**. The only remaining scheduled job is a single daily AI nudge (see Section 4).

---

## 2. Quota & Session Sizing

### 2.1 — Per-Plan Caps

| Plan   | Session size | Max AI cards/day | Manual word queries/day |
|--------|-------------|------------------|-------------------------|
| Free   | 4 (default) | 3                | 3                       |
| Silver | 6 (customizable) | 7           | 6                       |
| Gold   | 7 (customizable) | 15           | 12                      |

**Owner bypass:** If `OWNER_BYPASS_LIMITS` is true and the user is the owner, session cap is lifted entirely.

Session size is determined by `get_user_session_size(plan)` in `config/__init__.py`. Premium users may override their session size via a future settings UI. The engine reads `get_user_session_size()` dynamically on every session start.

### 2.2 — Lazy Session Quota Reset

- `sessions_used_today (INTEGER DEFAULT 0)` and `sessions_used_date (TEXT)` on the `users` table (future schema addition).
- On first session request of the day, compare `sessions_used_date` against today's date. If stale, reset `sessions_used_today = 0`.
- One session quota slot is consumed when the session is initialized (cards assembled and first card sent).

### 2.3 — Manual Word Query Quota

`daily_word_query_limit_for_plan()` returns the values above. The existing reservation/commitment pattern in `db.reserve_word_query()` / `db.release_word_query()` is preserved.

---

## 3. The 3-Tier Priority Queue

Every session fills up to `session_size` slots. Slot filling follows strict priority:

### Tier 1 — Overdue SRS Cards
```
SELECT id FROM saved_words
WHERE user_id = ? AND target_lang = ?
  AND interval_idx >= 0 AND next_review <= ?
ORDER BY (julianday(?) - julianday(next_review)) DESC
LIMIT ?;  -- session_size
```
All due SRS cards for the user's current `target_lang`. If `session_size` or more are due, the session is 100% review; no AI generation occurs.

### Tier 2 — User-Queried Saved Words (Pre-Graduation Pool)
```
SELECT id FROM saved_words
WHERE user_id = ?
  AND interval_idx = -1
  AND review_status='idle'
ORDER BY added_at ASC
LIMIT ?;  -- remaining slots after Tier 1
```
Pre-graduation words (`interval_idx = -1`) that the user previously saved via `query:add:` or daily-card save but has never reviewed.

### Tier 3 — New AI Generation

Generate brand-new cards via `_call_ai_limited(ai.ask_batch, daily_batch_system_prompt(...), gen_count)`.
Capped by `daily_card_count_for_plan(plan) - count_daily_cards(user_id, today)`. Generated cards are persisted to both `saved_words` (interval_idx=-1) and `daily_cards`.

### 3.1 — Slot-Filling Logic (Pseudocode)
```
session_size = get_user_session_size(plan)
remaining = session_size
tier1 = fetch_due(user_id, target_lang, limit=remaining)
remaining -= len(tier1)
tier2 = fetch_pregraduation(user_id, target_lang, limit=remaining)
remaining -= len(tier2)

if remaining > 0:
    cap = daily_card_count_for_plan(plan)
    used = count_daily_cards(user_id, today)
    ai_budget = max(0, cap - used)
    gen_count = min(remaining, ai_budget)
    if gen_count > 0:
        prompt = daily_batch_system_prompt(lang, goal, level, gen_count)
        cards = _call_ai_limited(ai.ask_batch, prompt, gen_count, ...)
        save to saved_words + daily_cards
        tier3 = wrap in SessionNode

cards = tier1 + tier2 + tier3  # up to session_size
```

### 3.2 — Overdue Demotion
Cards >60 days overdue are automatically reset to `interval_idx = 0` during the slot-filling query (applied as a `WHERE` filter or pre-query update). This prevents permanent backlog rot.

---

## 4. Smart Engagement (AI Nudges)

### 4.1 — What Gets Scheduled

A single daily cron job replaces all current push jobs:

```python
app.job_queue.run_daily(
    smart_nudge_job,
    time=datetime.time(hour=9, minute=0, tzinfo=_app_timezone),
)
```

This job sends at most **one message per user per day**. The message is a lightweight AI-generated motivational nudge, NOT a flashcard.

### 4.2 — Nudge Content

The nudge is generated via a single AI call that receives:
- User's streak length
- Number of due SRS cards
- Number of ungraduated saved words
- User's plan tier
- Whether they've studied today (session quota used)

The AI produces 1–2 short Persian lines, e.g.:
- "🔥 ۵ روز پشت‌هم! امروز ۳ تا واژه برای مرور داری."
- "📚 امروز هنوز شروع نکردی. یک جلسه ۵ تا کارتی آماده‌ست."

### 4.3 — Cost Budget

At most 1 AI call per user per day. Expected tokens: ~50 input + ~100 output. For 500 users, this is ~75k tokens/day (~$0.15 at GPT-4o-mini rates). Well within the cost envelope.

### 4.4 — Nudge Keyboard

The nudge message carries a single inline button:

> 📚 شروع مطالعه امروز

Which triggers the same session-initiation callback as the main menu button.

### 4.5 — Banished Jobs

The following are **removed entirely**:
- `srs_job` — per-word push of due SRS cards
- `srs_retry_job` — retry loop for failed SRS pushes
- `daily_job` — daily queue planning and dispatch
- `delivery_dispatch_job` — 60-second dispatch loop
- `startup_catch_up_job` — catch-up on restart
- `_plan_daily_queue()` — pre-computing session schedules
- `_dispatch_queue()` — pushing cards to users
- `_ensure_scheduled_session_cards()` — generating cards for push slots

---

## 5. Future-Proofing Extensibility Hooks

### 5.1 — Multi-Language Support: `(user_id, target_lang)` Scope

All session queue queries and state queries MUST include `target_lang` in the WHERE clause. This enables users learning multiple languages to have independent session quotas, SRS pools, and review schedules per language.

- `saved_words` already has a `lang` column — all Tier 1 and Tier 2 queries filter by it.
- `users.target_lang` is the user's active language.
- A future UI could let users switch `target_lang` without resetting their per-language SRS state.

### 5.2 — Polymorphic Activities

The session engine abstracts card content behind an `activity_type` field:

```python
@dataclass
class SessionNode:
    activity_type: str       # "flashcard" | "quiz" | "sentence_builder" | ...
    source_tier: int         # 1 | 2 | 3
    card_data: dict          # activity-specific payload
    activity_meta: dict      # e.g., {"question": "...", "options": [...]}
```

The scheduling engine (Tier 1/2/3 queue, quota, session initialization) is completely agnostic to `activity_type`. A future activity type:

- Defines its own keyboard and renderer in a `services/activities/<type>.py` module.
- Registers via a simple `ACTIVITY_REGISTRY` dict mapping `activity_type` → `(render_fn, keyboard_fn)`.
- Is selected during Tier 3 generation based on user goal, level, or A/B test assignment.

This means adding `quiz` or `sentence_builder` requires zero changes to:
- Session scheduling
- Quota enforcement
- Queue priority logic
- DB schema (aside from storing `activity_type` in the session node)

### 5.3 — Schema Changes

```sql
ALTER TABLE users ADD COLUMN sessions_used_today INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN sessions_used_date TEXT;

CREATE TABLE IF NOT EXISTS smart_study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    target_lang TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    slot_count INTEGER NOT NULL DEFAULT 5,
    activity_types TEXT NOT NULL DEFAULT '["flashcard"]',
    session_meta TEXT  -- JSON blob for extensibility
);

CREATE TABLE IF NOT EXISTS session_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES smart_study_sessions(id),
    sequence_index INTEGER NOT NULL,
    activity_type TEXT NOT NULL DEFAULT 'flashcard',
    source_tier INTEGER NOT NULL,
    source_id INTEGER,  -- saved_word.id for Tiers 1-2, NULL for Tier 3
    card_data TEXT NOT NULL,  -- JSON
    activity_meta TEXT
);
```

### 5.4 — Activity Registry (Future)

```python
# services/activities/__init__.py
ACTIVITY_REGISTRY: dict[str, ActivityHandler] = {}

def register_activity(activity_type: str, handler: ActivityHandler):
    ACTIVITY_REGISTRY[activity_type] = handler

# Each activity module calls register_activity() at import time
```

---

## 6. Implementation Roadmap

### Phase 1 — Purge & Scaffold (complete)

Purge v2.8 push-based SRS (delivery_queue, scheduler, push jobs). Replace with single golden button. Scaffold the v3 engine skeleton.

### Phase 2 — Core Engine (complete)

Implement `generate_v3_session()` with 3-Tier Priority Queue. Dynamic session size per plan. Hybrid text/callback entry point.

### Phase 3 — Interactive Session Flow (complete)

Wire inline keyboard (Remembered/Again/Next). Implement real Tier 3 AI generation. Wire callback handlers for session actions.

### Phase 4 — Smart Nudge (planned)

Daily scheduled nudge with lightweight AI-generated motivational message. Single "Start study" button on nudge.

### Phase 5 — Extensibility (planned)

Add `activity_type` column, multi-language query scoping, cleanup dead v2.8 code.

---

## 7. Data Migration

- All `saved_words` data is preserved. The `interval_idx` values remain valid.
- No user-facing data loss. The existing `saved_words` table feeds Tier 1 and Tier 2 of the new queue.
- `delivery_queue` table can be dropped (no more scheduled pushes).
- `daily_card_sessions` table can be dropped (no more pre-planned daily sessions).

---

## 8. Cost & Performance Impact

| Aspect | v2.8 Baseline | v3 Projection |
|--------|--------------|---------------|
| Scheduled AI calls | Per user per session (push) + per nudge | Per user per session (pull) + 1 nudge/day |
| Telegram pushes | Sessions pushed regardless of readiness | Zero pushes; all pull-based |
| DB writes per session | Multiple `delivery_queue` rows + card writes | One `smart_study_sessions` row + 5 `session_nodes` rows |
| DB load | Continuous dispatch polling every 60s | Near-zero between user actions |

---

## 9. Contract-Locked Rules

### Rule 1 — Single Golden Button
- **Decision:** Replace `BTN_TODAY_CARD`, `BTN_SRS_REVIEW`, `BTN_GRAMMAR` with a single `📚 شروع مطالعه امروز` button.
- **Alternatives rejected:** Keep separate buttons (confuses users); Keep SRS button as secondary (unnecessary complexity).
- **Trade-offs:** Users lose the ability to "just get a grammar tip" in one tap — grammar becomes a session activity type in a future phase.
- **GATE STATUS: LOCKED**

### Rule 2 — Dynamic Session Size (Per Plan)
- **Decision:** Session size is dynamic per plan: Free = 5, Silver = 6, Gold = 7. Premium users can customize. The engine reads `get_user_session_size(plan)` on every session start.
- **Alternatives rejected:** Fixed 5-card sessions (no premium differentiation); variable per-session (unpredictable).
- **Trade-offs:** Free users always get 5; premium users get more with future customization UI. AI generation fills remaining slots regardless of plan.
- **GATE STATUS: LOCKED**

### Rule 3 — No Push Flashcards
- **Decision:** Zero scheduled flashcard pushes. Only the AI nudge is scheduled.
- **Alternatives rejected:** Keep `daily_job` for Free users (dual-path complexity); Keep `srs_job` for failed-retry safety (retry is unnecessary in pull model).
- **Trade-offs:** Users who never open the bot will not get flashcards at all. The nudge is the only re-engagement mechanism.
- **GATE STATUS: LOCKED**

### Rule 4 — AI Nudge is Lightweight and Separate
- **Decision:** The nudge is generated by a single AI call per user per day. It NEVER contains flashcard content.
- **Alternatives rejected:** Nudge with a sample card (blurs line between nudge and push); No nudge (zero re-engagement).
- **Trade-offs:** Added AI cost of ~$0.15/day for 500 users. Acceptable for the engagement benefit.
- **GATE STATUS: LOCKED**

### Rule 5 — `(user_id, target_lang)` Scope on All Queries
- **Decision:** Every queue and state query scoped by both `user_id` and `target_lang`.
- **Alternatives rejected:** Single-language scope (blocks multi-language future); Application-level filtering (DB should enforce).
- **Trade-offs:** Slightly more complex queries now, zero migration cost later.
- **GATE STATUS: LOCKED**

### Rule 6 — Polymorphic Activity Nodes
- **Decision:** Session nodes carry an `activity_type` field. The engine is agnostic to it.
- **Alternatives rejected:** Monolithic card format (requires schema migration for every new activity type); Separate tables per activity (join complexity).
- **Trade-offs:** Slightly more complex session rendering; vastly simpler extensibility.
- **GATE STATUS: LOCKED**

---

## 10. Deferred Items

The following are explicitly **not** part of v3:
- **Grammar Tips as an activity type** — will be added post-v3 as an `activity_type = "grammar_tip"` handler.
- **Content Pool** — deferred until Phase 4 content quality work.
- **Retention points / Gamification** — no `retention_events` table yet.
- **Multi-language UI switcher** — the query scoping is in place, but the UI to switch `target_lang` is future work.
- **Sentence builder / Quiz activity types** — deferred until the registry pattern is exercised by a real second type.
