---
name: rt-bn1-broadcast-semaphore
description: Broadcast concurrency (gather + bounded semaphore) + re-entry guard + seam migration (RT-BN1)
created: 2026-08-20
base_commit: a4835d8
branch: refactor/broadcast-semaphore
status: in-progress
---

STATE: phase 1/1 — status: in-progress — focus: write integration tests (red), then implement

## Contract Lock (RT-BN1) — owner said "proceed" 2026-08-20

- R1: `asyncio.gather` + broadcast-local `asyncio.Semaphore(BROADCAST_MAX_CONCURRENCY)`; each send through `_send_with_retry` (global 4-slot cap preserved).
- R2: `BROADCAST_MAX_CONCURRENCY` env setting, default 20, in `config/__init__.py` + `.env.example`.
- R3: per-user try/except, log failures, count successes (behavioral parity).
- R4: module-level `_BROADCAST_RUNNING` flag set before first await (race-free), reset in `finally`; second broadcast refused with polite Persian message; awaiting consumed.
- R5: final report via `services.send_pretty.say(update, context, ..., raw=RawFormat.PLAIN)` (replaces `update.message.reply_text`). Remove this site from #418 list.
- R6: deterministic integration tests on CI + wall-time benchmark script (local only, not CI-gated).

## Gaps / Deliberately Not Done
- `db.all_active_users()` sync-on-event-loop is BN2/BN3 → Session A G1, out of scope.
- Other #418 bypass sites in admin.py remain (11 → now 10 after this PR).

## Implementation
- Files: `handlers/admin.py` (`_handle_admin_broadcast` rewrite, import `say`/`RawFormat`), `config/__init__.py`, `.env.example`.
- Tests: `tests/test_integration/test_admin_broadcast_concurrency.py`.
- Benchmark: `scripts/bench_broadcast.py` (local, manual).

## Evidence
- Tests: `tests/test_integration/test_admin_broadcast_concurrency.py` (3 tests) — 3 passed.
- Regression: `test_early_awaiting_reset.py` (13 passed), `test_send_pretty_route_flow.py`, `test_admin_awaiting.py`, `test_wiring.py`, `test_single_source_of_truth.py`, `test_dead_code_guard.py` (107 passed + 4 subtests).
- Test-sync: `_make_text_update` in `test_early_awaiting_reset.py` gained `update.callback_query = None` (R5 final-reply now routes through `say`; real text updates have callback_query None).
- Benchmark (`scripts/bench_broadcast.py`, local only): N=1000, 5ms latency → 6.02s sequential vs 0.98s concurrent = **6.16× speedup**, cap=20.
- Files: `handlers/admin.py`, `config/__init__.py`, `.env.example`, `scripts/bench_broadcast.py`, `tests/test_integration/test_admin_broadcast_concurrency.py`.