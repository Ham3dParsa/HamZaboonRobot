---
name: plan-dim2-metrics-halflocked
description: Half-locked metric specs for dimension 2 (cheap algorithmic monitoring, #467)
created: 2026-09-07
base_commit: ab8163d
branch: docs/dim1-lock
status: in-progress
---
STATE: dim 2/7 — status: HALF-LOCKED (audit-required) — focus: live-variable audit, then Contract Lock Gate

## Contract Gateway Status: Half-Locked / Audit-Required

No code is written under this document. Implementation is conditional on a live-variable audit plus explicit Contract Lock Gate confirmation.

### Metric matrix (zero DB / processing cost monitoring)

- **MTR-01 Learning Velocity (avg reviews to stabilize):** reviews seen per word until stable (`S >= 21` and `D < 4`); proves FSRS efficacy. Read path: two proposed `users` columns (`stabilized_cards_count`, `total_reviews_to_stabilize`). Storage: 2 numeric fields (needs migration). Processing: O(1) division. Refresh: card threshold-crossing moment in `advance_session`; no history backfill (from activation only). Consumers: profile stats panel (`/status`). AUDIT GAP: can it be lazy/approximate at profile-open with zero schema change instead of new columns?
- **MTR-02 Tomorrow Due Load:** tomorrow workload estimate for return/completion nudges. Read path: existing `due_words_for_user` (`services/db/words.py`), window now..now+24h. Storage: zero. Processing: single indexed `next_review_at` query on `saved_words`. Refresh: stats-panel call or last nightly session end. Consumers: nightly summary, status card. AUDIT GAP: does `_schedule` (words.py) stamp exact hours or day-round? "Calendar tomorrow" vs "rolling 24h" must align on APP_TIMEZONE.
- **MTR-03 Session Recall Rate:** finished-session success % on grade weights 1-4 (`RECALL_WEIGHTS`). Read path: grades array in live `SessionState.graded_word_ids`. Storage: zero new tables (text field or existing `session_reports` column). Processing: weighted mean of max 9 items (O(1)). Refresh: session end inside `build_report`. Consumers: summary quote, M10 variant pick. AUDIT GAP: verify `session_reports` structure so no second query hits `review_events`.
- **MTR-04 Daily Heat Slot:** today quota-use state per 2026-09-17 band 2: cold before first session; fire 1 for sessions 1..ceil(N/2)-1; fire 2 for ceil(N/2)..N-1; fire 3 on completing session N (N=1 completes straight to fire 3). Read path: `sessions_used_{user}_{date}` in `settings` divided by quota from `plans`. Storage: zero (quota row reuse). Processing: one division + comparison. Refresh: session start (`consume_session_slot`) and end. Consumers: card footers, summary header, M04/M08 triggers. BF-1 RESOLVED 2026-09-17 band 15: the ceil(N/2) formula guarantees a fire-1 step for every quota except N=1.

### Technical pre-lock checks
1. MTR-01 users columns: does the owner accept the 2-column migration, or drop/lazy the metric to keep the DB untouched?
2. MTR-02 tomorrow boundary: end of next calendar day (23:59 Iran) or rolling 24h window?
3. MTR-04 free-quota fit: RESOLVED 2026-09-17 (band 15, ceil(N/2) + N=1 exception).

## Evidence
- Owner + Gemini 7-dimension structure (2026-09-07); dim 2 text verbatim.
- dims 1,5,6 LOCKED; dims 3,4,7 PENDING.

## Blocked Questions
- The 3 pre-lock checks above (need live-variable audit first).
