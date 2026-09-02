---
name: plan-27-polish
description: Polish follow-up for per-user-lock — split buckets, per-action limits, conftest logging
created: 2026-09-02
base_commit: 316e04f
branch: fix/per-user-lock-polish
status: in-progress
---

STATE: phase 0/3 — status: in-progress — focus: polish per-user-lock follow-up

# Plan 27 Polish — deferred SUGGESTIONs

**Source:** PR #525 Kilo SUGGESTIONs deferred per triage (owner: "do them").
**Seams:** `scheduling/quota` (`services/scheduling.py`), `tests/conftest.py`.

## CONTRACT LOCK TEMPLATE

Rule #1 — Split srs_grade bucket:
Decision: Separate review vs first-exposure buckets
Option Chosen: A — split into srs_grade_review / srs_grade_first (5/10s each) — preserves 5 fast grades in mixed sessions
Alternatives Rejected: B keep single bucket — throttles 6th card in mixed sessions; C raise limit to 8 — higher burn
Trade-offs: A = 1 extra dict key, no migration; B = simple but UX hit; C = more burn
Owner Confirmation: delegated "do them" 2026-09-02
GATE STATUS: LOCKED

Rule #2 — Per-action configurable limits (hook):
Decision: Allow per-action limit override via settings (future), keep 5/10s default now
Option Chosen: A — add _RATE_LIMITS dict per action (all 5 now), read from settings if present, else default
Alternatives Rejected: B single limit for all — less flexible
Trade-offs: A = small dict, no migration, future-proof
Owner Confirmation: delegated
GATE STATUS: LOCKED

Rule #3 — Conftest logging:
Decision: Log swallowed fixture errors
Option Chosen: A — wrap _clear with try/except logger.debug(exc_info=True) instead of pass
Alternatives Rejected: B keep silent pass — hides broken fixture
Trade-offs: A = 1 line, visible in pytest -v
Owner Confirmation: delegated
GATE STATUS: LOCKED

GATE STATUS: LOCKED
<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| scheduling | try_acquire_per_user_slot, is_rate_limited, _RATE_LIMITS | update |
| handlers | srs_handler uses srs_grade_review/first | update |
| tests | conftest _per_user_rate_cleared | update |

## Phases

| Phase | Topic | Status |
|-------|-------|--------|
| 01 | Split buckets + per-action limits in scheduling | pending |
| 02 | Handler split (srs_handler) | pending |
| 03 | Conftest logging + tests | pending |
