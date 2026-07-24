# Plan: LLM Cost Metrics and Admin Dashboard

> **STATUS:** active

## Goal

Add a robust admin-facing cost analytics layer that turns raw LLM usage logs into:

- per-request cost
- per-user cost
- per-plan cost
- daily / weekly / monthly rollups
- monthly projection
- filtered drill-down views

The implementation should stay lightweight, accurate enough for operations, and easy to extend later.

## What already exists

The current codebase already records some request metadata in `ai.py`:

- request kind
- model
- latency
- provider token counts

The next step is to persist that telemetry in a dedicated structure that can support:

- real cost calculation from token counts
- grouping by user, plan, date, request kind, and model
- admin dashboard summaries without recomputing everything from raw logs each time

## Core product decisions to lock

### 1) What counts as a billable LLM event?

Include:

- daily batch generation
- custom word query
- grammar tip generation
- any future AI request that hits the provider

Exclude:

- pure Telegram actions
- local cache hits
- validation-only paths that never call the model

### 2) What data should be stored per request?

Store one durable record per AI call with at least:

- timestamp
- user_id
- plan at request time
- request_kind
- model
- prompt_tokens
- completion_tokens
- total_tokens
- estimated cost
- provider latency
- success / failure outcome
- error class or failure reason when relevant

Keep the raw prompt and raw response out of analytics tables unless absolutely needed for debugging, because the dashboard only needs metrics, not content.

### 3) How should cost be calculated?

Use provider-specific token pricing in a single source of truth, with prices expressed as:

- input cost per 1M tokens
- output cost per 1M tokens

Per-request cost formula:

`(prompt_tokens / 1_000_000) * input_price + (completion_tokens / 1_000_000) * output_price`

If the provider returns only total tokens, keep the schema flexible enough to store both the detailed split and the fallback total.

### 4) How should rollups work?

Precompute or aggregate the following dimensions:

- date
- week
- month
- user_id
- plan
- request_kind
- model

Rollups should answer:

- total requests
- total prompt tokens
- total completion tokens
- total tokens
- total estimated cost
- average cost per request
- average latency
- error rate

### 5) What should the admin panel show?

Add a dedicated “LLM Cost Metrics” section in the admin area with:

#### Overview cards
- today’s spend
- this week’s spend
- this month’s spend
- projected month-end spend
- total requests
- failure rate

#### Trend views
- daily spend trend
- daily token trend
- request count trend
- split by request kind

#### Drill-down tables
- by user
- by plan
- by request kind
- by model
- by date range

#### Filters
- date range
- user
- plan
- request kind
- model
- success/failure

## Suggested implementation shape

### Data layer

Add a new persistent metrics table, likely something like:

- `llm_requests`

Optional supporting tables if needed:

- `llm_request_rollups_daily`
- `llm_request_rollups_weekly`
- `llm_request_rollups_monthly`

The design should allow future recomputation from raw request rows.

### Write path

At every provider call:

1. record request start time
2. call the model
3. read usage and outcome
4. compute estimated cost
5. persist the metrics row

If the provider fails before usage is available, still persist the request with:

- failure flag
- error category
- zero or null token counts as appropriate

### Read path

Admin UI should read from aggregates when possible and fall back to raw rows for fine-grained detail.

## Accuracy and robustness rules

- Never double-count retries unless they are truly separate provider requests.
- Never charge cache hits or skipped validations.
- Keep all rollups deterministic and recomputable.
- Use the stored plan at request time, not the user’s current plan, for historical reports.
- Preserve timezone consistency for day/week/month boundaries.
- Make sure “monthly projection” is clearly labeled as an estimate.

## Nice-to-have later

- CSV export
- per-model cost comparison
- threshold alerts when spend spikes
- cost by feature area
- cost by active vs. inactive users

## Locked decisions

The following choices are now fixed:

- **Pricing source:** hybrid — `.env` defaults plus admin overrides.
- **Stored values:** raw USD plus a USD→toman exchange rate for dual display.
- **Failure handling:** separate `billed failure` and `zero-cost failure` metrics.
- **Projection:** show both linear extrapolation and rolling average.
- **Date filters:** support presets for today, 7d, 30d, and month-to-date.

No open product questions remain for the first implementation slice.

## Proposed first implementation slice

1. Add durable LLM request logging.
2. Add pricing config and cost calculation.
3. Add daily aggregation and a summary query layer.
4. Add a minimal admin dashboard view with filters.
5. Expand to weekly/monthly rollups and projections.

## Definition of done

The feature is done when an admin can:

- see spend by day, week, and month
- filter by user, plan, model, and request kind
- inspect individual requests
- compare estimated cost across users and plans
- trust that retries, failures, and cache hits are not double-counted
