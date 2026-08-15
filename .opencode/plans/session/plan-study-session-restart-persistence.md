---
name: plan-study-session-restart-persistence
description: Persist the active study session to SQLite so an in-progress session survives a bot restart, resuming same-day on «شروع مطالعه امروز» (Bug 1, owner report 2026-08-15).
created: 2026-08-15
base_commit: 07440f3
branch: fix/session-restart-persistence
status: in-progress
---

STATE: phase 1/1 — status: complete — contract LOCKED 2026-08-15 (Rule 1 Option A: SQLite `study_sessions` table; Rule 2 Option A: resume only if persisted day == today). Seams 1+5 claimed, released after merge. T1+T2 GREEN; full suite 1036 passed; independent reviewer no must-fix; owner decisions applied (clear before completion message, persist before render). Merged PR #364 (0fdec76, 2026-08-15). Issue #363 resolved.

## Contract (GATE: LOCKED — owner chose both A options 2026-08-15)

- **Rule 1 — Persist active session:** new SQLite `study_sessions` table (one row per user). Save session state on build, after resume re-render, and after each advance. Clear on completion/error-pop.
- **Rule 2 — Same-day-only resume:** `handle_study_start` first checks `context.user_data`; if absent, loads from DB. Only restores if the persisted `session_date` equals today's app-day; otherwise the stale row is discarded and a fresh session is built (quota consumed normally).

### Scope boundaries (owner-directed)
- In-memory `user_data` state remains authoritative during a process lifetime; DB is the restart-recovery fallback.
- Telemetry stashes (`prompt_type_*`, `card_shown_at_*`, `revealed_*`) are NOT persisted — after restart they're re-armed by the resume render, and reveal timing becomes `None` (acceptable, out of scope).
- No callback prefixes, keyboards, or routing changes.

### Dependency & Wiring Map
| Dependency type | Items affected | Disposition |
|---|---|---|
| DB tables | new `study_sessions` (fresh CREATE + prior-schema upgrade) | add |
| DB functions | `save_study_session` / `load_study_session` / `clear_study_session` in `services/db/sessions.py` | add |
| Re-exports | `services/db/__init__.py` facade | add |
| Handler functions | `handle_study_start` (load-from-DB fallback + persist), `advance_session` (persist/clear), render-failure pop | update |
| Migration guards | `EXPECTED_TABLES` + `build_prior_schema` upgrade test | update |
| Tests | `tests/test_session_persistence.py` (unit), `tests/test_integration/test_study_session_restart_flow.py` (integration) | add |

## Tickets

### T1 — DB layer: `study_sessions` table + save/load/clear
- **Backend:** `CREATE TABLE IF NOT EXISTS study_sessions` in `init_db` fresh script (schema.py); prior-schema test fixture gains the table so the upgrade path is exercised; `services/db/sessions.py` with JSON round-trip functions using `BEGIN IMMEDIATE`; facade re-exports.
- **Tests:** unit — table exists on fresh + upgraded DB (migration guard), save/load round-trip, load-nonexistent → None, clear removes row, overwrite same user.
- **Acceptance:** persistence functions are pure JSON I/O; no Telegram/handler imports (no circular dependency).

### T2 — Handler: resume-from-DB + persist lifecycle
- **Frontend:** `handle_study_start` — when `context.user_data` has no `current_session`, load from DB; if `session_date == today` restore into user_data and resume; else clear stale row. Persist after new-session build, after resume re-render (updated `study_msg_id`), after each advance; clear on completion and on render-failure pop.
- **Tests:** integration — (a) start session, grade one card, then simulate restart (fresh context) → pressing «شروع مطالعه امروز» resumes the same session (same `session_progress_footer`, remaining card, not a fresh session number); (b) stale-day row → fresh session built; (c) completion clears the DB row.
- **Acceptance:** after restart the same session resumes; quota is NOT double-consumed on resume; session number footer stays consistent.

## Blocked Questions
- None.