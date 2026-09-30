# Phase 08 — Arbiter cost guards (owner-locked option A)

Gates: OC must-fix (rate caps/pacing/concurrency) + AI cost discipline.
Blocking: P3 (extends launch/worker/routes without changing shapes).

## Rules (owner wording, implemented verbatim)

1. Fail-fast at the door: hourly/daily remaining by scope checked in
   `launch()` BEFORE any thread/model call; refusal carries counts
   (`VALIDATION-quota-exhausted … remaining hour=N day=M`).
2. Single-flight: one active arbiter run per console
   (`ConflictError` → HTTP 409); matches the batch/approve locks.
3. Per-run ceiling: `ARBITER_RUN_MAX = 100`, clamped with
   `requested` kept on the job for honesty.

## Usage stats (precision rule)

Append-only `arbiter_usage.jsonl`: one line per judged sense with
`{ts, provider, model, endpoint, key_var NAME only, preset, run_id}`.
Scope buckets: model→model, address→endpoint (fallback provider),
account→key-var-name (fallback provider). Windows: trailing minute /
hour + UTC calendar day (metadata convention, like `created_at`).
`0` cap = unlimited everywhere. Minute pacing sleeps abort-aware in
the worker (max one minute per stall).

## Tests

`test_arbiter_cost_guards.py` (scope keys, window math, unlimited,
quota counts, single-flight conflict, ceiling clamp). No wall-time
sleep tests (pacing verified through summarize math).

## Acceptance

Route 409 on concurrent create; 400 with counts on exhausted quota;
usage file grows one line per sense with names only (verified by
reading it, never by parsing secrets — there are none).
