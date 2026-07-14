# Plan: Adaptive SRS Core and Real-Progress Scoring

## Goal

Replace the current fixed, plan-agnostic SRS reminder behavior with a
per-user adaptive reminder system that responds to actual engagement, and
introduce a points/progress system that measures genuine retention and
learning signal rather than raw activity volume. This is the single highest
priority item on the roadmap right now: it directly affects retention and
perceived product quality, ahead of any cost-optimization or pooling work.

This is the locked implementation plan for the next SRS direction. It
supersedes the current static SRS behavior described under "Locked
Operational Configuration Decisions"; `ROADMAP.md` contains the concise
product-level summary and `issues/issues.json` contains the audit records.

> **Implementation status (2026-07-14):** This document is a locked future
> plan, not the behavior currently running in `bot.py` and `db.py`. The live
> baseline still uses fixed intervals, sends every due non-pending word, has
> no SRS cap, and has no pending grace-window, claim, or retention-event
> implementation. Issues 42-46 and 59-60 track the resulting SRS gaps.

## Why this is the priority

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

## What already exists (baseline to build on)

- `saved_words` stores `interval_idx`, `next_review`, `review_status`
  (`idle` / `pending`), `review_requested_at`, and the full validated
  `card_data` payload — no new API call is needed to render a reminder.
- Review intervals are fixed and global: `INTERVALS_DAYS = [1, 3, 7, 16, 30]`
  in `db.py`. The index only advances on explicit user action
  (`advance_word_review`) or resets on `defer_word_review` — Telegram
  delivery success alone does not advance it. This is the right foundation:
  interval progression is already gated on real user confirmation, not on
  send success.
- `SRS_REMINDER_TIME` controls only the time of day reminders are sent, not
  volume or pacing.
- `users.goal` and `users.level` are already stored per user and already
  drive content generation (`target_lang`, `goal`, `level` are read
  together everywhere cards are generated) — the same fields are the
  natural input for reminder pacing, no new user-facing setting is required
  to start.
- There is currently no daily cap, no priority ordering beyond due-date
  order, and no points/progress table of any kind.
- `srs_job` catches errors around the whole per-user due-word loop, so one
  failed word can prevent later due words for that user from being attempted
  in the same run.
- Reminder delivery is not atomic with the transition to `pending`: Telegram
  acceptance can be followed by a process crash before SQLite persistence,
  allowing a duplicate on restart. A compare-and-set claim and explicit
  recovery policy are required before completion metrics are trusted.

## Part 1 — Adaptive reminder pacing

### Core principle

Daily reminder volume is not a fixed number per plan. It is a function of
the individual user's own recent completion behavior, bounded by a
goal-informed pacing profile. Two users on the same plan with different
engagement patterns should receive different reminder loads.

### 1.1 — Completion rate as the control signal

Track, per user, a rolling completion rate over the last 7 days:

```
completion_rate = (reminders answered) / (reminders sent)
```

"Answered" means the user pressed either the "remembered" or "review again
tomorrow" control — i.e. `advance_word_review` or `defer_word_review` was
called. A reminder that sits in `pending` past the locked 48-hour grace
window without a response counts as unanswered, not as still-pending
forever, so the rate reflects real behavior rather than a permanently
inflated denominator from stale pending rows.

This is a simple moving computation over existing `saved_words` rows
(`review_status`, `review_requested_at`) — no new tracking table is
strictly required for the rate itself, only for the daily cap decision
below.

### 1.2 — Dynamic daily cap

Maintain a per-user `daily_reminder_cap`, adjusted (not recalculated from
scratch) each day based on the completion rate:

- completion rate ≥ 70%: cap increases by a small fixed step, up to a hard
  ceiling.
- completion rate 40–70%: cap holds steady.
- completion rate < 40%: cap decreases by a small fixed step, down to a
  hard floor.

The locked initial caps and outer ceilings are the existing plan allowances:
Free 3, Silver 12, and Gold 30. The cap adjustment step is 1 reminder, the
floor is 1, and the completion thresholds are 70% for increasing, below 40%
for decreasing, and 40–70% for holding. Existing users with a null cap are
seeded from their current plan allowance, with the normal Free fallback for
unknown plans. The adjustment runs at most once per application day, even
when startup catch-up replays scheduled work.

This is intentionally a simple additive/subtractive step function, not a
PID controller or ML model — it is easy to reason about, easy to explain to
a user if asked, and easy to tune from real data once you have it.

### 1.3 — Overdue-priority ordering

When due reminders exceed the daily cap, select which ones to send using
staleness, not queue order:

```
priority_score = today - next_review_date
```

Highest `priority_score` (most overdue relative to its own scheduled date)
is sent first. This directly targets the forgetting-curve risk: a word 10
days overdue is more urgently at risk than one due today. This requires no
new schema — it is a `WHERE next_review <= today ORDER BY (today -
next_review) DESC LIMIT daily_reminder_cap` style query against the
existing `saved_words` table.

### 1.4 — Goal-informed pacing shape

`users.goal` already exists and is already read for content generation.
Use the same field to shape *pacing*, not just cap size:

- **Conversation-oriented goals**: spread the daily cap across multiple
  short delivery windows in the day (reuses the existing
  `active_window_start/end` and session-slot machinery from the scheduler,
  rather than introducing a second scheduling system).
- **Exam-oriented goals**: consolidate into fewer, larger review sessions
  per day, since exam preparation benefits from structured block review
  more than ambient spaced touches.
- **Travel/short-term goals**: bias the priority ordering toward
  practical/high-frequency vocabulary already tagged by the content
  generation prompt, rather than strict overdue-first ordering — flag this
  as a stretch goal, not part of the first implementation slice, since it
  requires the card payload to carry a frequency/practicality signal that
  does not exist yet.

Only the first two (conversation vs. exam pacing shape) are in scope for
the first implementation slice. Travel-goal biasing is explicitly deferred.
A goal change applies from the next daily planning cycle; already-queued
reminders keep their existing pacing shape.

## Part 2 — Real-progress scoring (points system)

### Core principle

Points must be earned from evidence of retention, not from activity volume.
A user who requests fewer cards but retains more of them should be able to
outscore a user who requests the maximum daily allowance but forgets most
of it. This is the single rule every scoring decision below must satisfy.

### 2.1 — What counts as a scoring event

Award points for:

- A word successfully reviewed at each interval milestone
  (`advance_word_review` succeeding at `interval_idx` 1, 2, 3, 4 — i.e.
  surviving the 3-day, 7-day, 16-day, and 30-day checkpoints). Later
  milestones award more points than earlier ones, since surviving a 30-day
  gap is stronger evidence of retention than surviving a 1-day gap.
- The locked milestone ladder is 1, 3, 6, and 10 points for interval
  indexes 1, 2, 3, and 4. Reaching interval 4 also awards a one-time
  10-point mastery bonus.
- A grammar tip's associated concept re-appearing correctly in a later
  quiz interaction, once the quiz feature exists — flagged as a
  post-quiz-launch addition, not part of this slice.

Do **not** award points for:

- Requesting a new card or grammar tip (generation is not learning).
- Sending or receiving a reminder (delivery is not learning).
- Streak days alone, in isolation from retention — see 2.2.

### 2.2 — Streak stays, but decoupled from raw points

Keep the existing `streak` field and its daily-touch semantics — it is a
proven, low-cost engagement mechanic and users already understand it. But
do not let streak length directly inflate the points/progress score. Treat
streak as its own displayed metric ("12-day streak") alongside, not folded
into, the retention-based score ("83% retention this month" or similar). A
user should be able to see both without one being a disguised multiplier
of the other.

### 2.3 — What the user sees

Surface a small number of meaningful, retention-grounded indicators instead
of a single opaque "score":

- **Words retained** — count of words that have survived their most recent
  interval checkpoint (i.e. currently sitting at `interval_idx` ≥ 1 with
  no recent `defer`).
- **Retention rate** — the completion-rate signal from Part 1.1, reframed
  user-facing as "how much of what you've reviewed actually stuck".
- **Streak** — kept as-is, displayed separately.

Avoid introducing a leaderboard or cross-user ranking — that is explicitly
out of scope per the existing roadmap ("Groups, leaderboards, or social
ranking"), and nothing in this plan requires revisiting that boundary.

## Data model additions

Two additions, both additive and following the existing `init_db()`
migration pattern:

```sql
-- Extends the existing users table; no new table needed for pacing state.
ALTER TABLE users ADD COLUMN daily_reminder_cap INTEGER;
ALTER TABLE users ADD COLUMN reminder_cap_updated_at TEXT;

-- New table for retention scoring events, kept separate from saved_words
-- so historical scoring is preserved even if a word is later reset/removed.
CREATE TABLE IF NOT EXISTS retention_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    saved_word_id INTEGER NOT NULL,
    interval_idx_reached INTEGER NOT NULL,
    points_awarded INTEGER NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS retention_events_user_idx
    ON retention_events(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS retention_events_word_interval_idx
    ON retention_events(saved_word_id, interval_idx_reached);
```

No changes to `saved_words`, `daily_cards`, or `grammar_tips` schemas are
required — the pacing cap lives on `users`, and scoring events are an
append-only log keyed against the existing `saved_words.id`.

## Locked audit resolutions before implementation

1. **Pending-reminder grace window**: current code leaves `pending` rows
   excluded indefinitely. The implementation must use the locked 48-hour
   grace window and count expired unanswered reminders in the denominator
   without advancing the interval.

2. **Cap adjustment idempotency**: startup catch-up can replay `srs_job`.
   `reminder_cap_updated_at` must therefore guard the adjustment in the same
   application-day transaction so a replay cannot double-step the cap.

3. **Goal-change mid-cycle**: `users.goal` can change at any time, but the
   locked rule is that existing queued reminders retain their shape and the
   new goal applies at the next daily planning cycle.

4. **Scoring abuse**: current pending-state guards reject repeated responses,
   but the new event write must be in the same transaction as interval
   advancement and protected by the unique word/interval index. The mastery
   bonus uses the same one-time event guard.

5. **Backward compatibility**: users created before this change receive a
   cap seed from their current plan allowance (3/12/30, with Free fallback).
   This prevents a migration-day drop to zero while keeping the new behavior
   bounded and explainable.

6. **Reminder delivery idempotency**: a reminder must have a durable claim and
   attempt identity. The state machine must prevent concurrent claims, preserve
   enough progress to recover after restart, and explicitly bound the
   unavoidable Telegram-send/SQLite-commit duplicate window.

7. **Per-word failure isolation**: one failed due-word preparation or send
   must not abort the remaining due words for the same user. Retry state must
   be bounded and must not consume a cap slot as a successful reminder unless
   the configured delivery success boundary is reached.

8. **Deferral semantics**: the implementation must resolve the existing
   mismatch between the plan's “reset on defer” wording and
   `defer_word_review()` currently preserving `interval_idx`. The chosen reset
   rule must be locked before changing interval behavior.

## Suggested implementation slices

1. Add `daily_reminder_cap`/`reminder_cap_updated_at` columns and
   `retention_events` table. No behavior change yet.
2. Implement overdue-priority ordering (1.3) inside the existing SRS
   delivery job — this alone improves reminder quality with no new state
   and is safe to ship first.
3. Implement the completion-rate calculation and daily cap step function
   (1.1, 1.2), gated behind a config flag so it can be tested against real
   usage before affecting all users.
4. Implement goal-informed pacing shape for conversation vs. exam goals
   (1.4, first two only).
5. Implement retention-event logging and the user-facing progress view
   (Part 2), decoupled from and shipped after the pacing work, since
   scoring depends on the same `advance_word_review` checkpoints but is
   not required for pacing to function.
6. Revisit travel-goal pacing and quiz-linked scoring once the quiz
   feature is scoped.

## Baseline scheduled-delivery risks adjacent to SRS

The daily-card queue is separate from the future adaptive SRS cap, but its
restart behavior affects the same learner-facing reliability contract:

- A processing queue row can remain stranded when a worker restarts before
  the 15-minute stale threshold; recovery currently runs from `daily_job`,
  not from the repeating dispatcher.
- The current slot planner reads a preferred delivery time but passes the
  evenly distributed window ideal to the load-aware chooser, so preference is
  not actually used as a soft target.
- Startup catch-up operates on today's date only. Older pending/failed dates
  need an explicit replay-or-expire policy; silently leaving them in the
  queue is not restart-complete.
- A crash after Telegram accepts a card but before `sent_count` is persisted
  can resend part of a session. Exact-once external delivery is impossible,
  so the design must make the duplicate window explicit and observable.

These are tracked as issues 61-63 and must be covered by focused crash,
lease/recovery, scheduling-preference, and past-date replay tests before
phase-6 delivery reliability is considered complete.

## Definition of done

- Two users with identical plans but different completion behavior receive
  measurably different daily reminder volumes within one to two weeks of
  real usage.
- No user's daily reminders exceed the deployment-configured ceiling or
  drop below the floor, regardless of completion rate.
- A user's displayed progress (words retained, retention rate) cannot be
  increased by requesting more cards or grammar tips alone — only by
  successfully clearing existing review checkpoints.
- Streak and retention rate are both visible and clearly distinct in the
  bot's status/profile view.
- All five audits above have an explicit resolution documented in
  `issues/issues.json`, following the same evidence-and-resolution format
  used for existing entries.
