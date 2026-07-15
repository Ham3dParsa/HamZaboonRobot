# Daily-card batching and scheduled-job reliability audit

## Scope
Reviewed two reliability areas:

- manual vs scheduled daily-card batching
- scheduled job reliability for daily delivery, delivery dispatch, and SRS

## Daily-card batching

### Manual flow
- `send_daily_card_now()` calls `_send_next_daily_card()`.
- `_send_next_daily_card()` loads `daily_cards` for the day and only generates more when the current index exceeds stored cards.
- The gap is still the same one-card path: `_ensure_next_daily_card()` calls `_generate_daily_batch(..., 1, used_words)`.
- Result: manual requests do not share a pre-generated reservoir and still burn one LLM call at a time when the user keeps pressing the button.

### Scheduled flow
- `daily_job()` plans sessions with `_plan_daily_queue()`.
- `_plan_daily_queue()` uses `plan_sessions()` to split the day’s allowance into multiple delivery sessions.
- `enqueue_delivery_sessions()` stores those sessions in `delivery_queue`.
- `_dispatch_queue()` claims due rows, generates session cards with `_ensure_scheduled_session_cards()`, and sends them one by one.
- Result: scheduled delivery already batches generation at the session level and is more token-efficient than the manual path.

## Scheduled-job reliability

### What exists
- `main()` registers `daily_job`, `delivery_dispatch_job`, and `srs_job` on `app.job_queue`.
- `delivery_dispatch_job()` keeps sending queued delivery rows that are already in the DB.
- `srs_job()` sends due-word reminders and advances reviews after successful sends.

### What is missing
- There is no startup catch-up or replay step.
- If the bot is offline when `daily_job` should have run, today’s delivery queue is not planned until a later manual run.
- If `srs_job` is missed, the reminder does not replay later.
- `daily_job()` is also the place that requeues stale deliveries, so missing that tick delays recovery as well.

## Findings

1. **Manual daily-card batching is still the only real token-efficiency gap.**
   - Scheduled delivery is already batched.
   - Manual button presses still generate one card at a time.

2. **Scheduled jobs are restart-sensitive.**
   - They work while the bot is alive.
   - They do not self-heal after downtime because there is no replay/backfill on startup.

3. **The original “no SRS job exists” concern is outdated.**
   - The reminder job is present now.
   - The remaining issue is missed execution, not missing implementation.

## Recommendation

- Keep manual batching as a separate follow-up: prime a 2–6 card reservoir on the first manual request and consume it on later clicks.
- Add startup catch-up for scheduled jobs so missed `daily_job` and `srs_job` runs can be replayed after downtime.
- Keep manual and scheduled state separate so the auto queue does not leak into the manual reservoir.

## Related roadmap / issue notes

- `ROADMAP.md` should mention the restart/catch-up gap as a reliability follow-up.
- `issues/issues.json` should keep issue `29` open for manual reservoir batching and add a separate issue for scheduled-job replay after downtime.
- Issue `2` can now be treated as resolved because the SRS job exists; the remaining problem is the missed-run behavior above.
