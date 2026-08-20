---
name: session-report-persistence
description: Persist post-session reports for 3 days and reopen via /reports (R10)
created: 2026-08-20
base_commit: 96dc0f6
branch: feat/session-report-persistence
status: complete
---
STATE: complete — merged to main as db6b8ec (#430) on 2026-08-20

# Session Report Persistence (R10)

Locked contract (owner: "proceed", 2026-08-20). Rules R10-A..R10-G:

- **R10-A** Extend existing modules: `session_reports` table in `schema.py`; sibling `services/db/session_reports.py` accessor mirroring `sessions.py`; JSON (de)serialization in `services/session/summary.py` (SessionReport owner); handler in `study_handler.py`.
- **R10-B** Persist the built `SessionReport` as JSON; re-render on reopen with existing formatters.
- **R10-C** Entry: `/reports` command listing recent sessions (≤3 days); tap opens summary + paged details.
- **R10-D** Retain all completed-session reports within 3 days (app-tz session date).
- **R10-E** Lazy purge of expired rows on save and on list; no scheduler.
- **R10-F** Gating change: ALL users get the post-session summary (free users see the motivational message) WITHOUT the detail button; Bronze+/owner get summary + detail. Persisted reports follow the same rule (free reopen summary-only).
- **R10-G** New `reports:` prefix (`reports:list`, `reports:detail:<id>:<page>`, `reports:back`) via `services/routing.py register("reports", _handle_reports_callback)`; not owner-gated.

## Schema (under R10-A/B)
`session_reports`: `id` INTEGER PK AUTOINCREMENT, `user_id` NOT NULL, `session_date` TEXT (app-tz), `created_at` TEXT (UTC), `report_json` TEXT, `is_admin` INTEGER NOT NULL DEFAULT 0. Index on `(user_id, created_at)`.

## Serialization (summary.py)
`serialize_report(report) -> str` / `deserialize_report(json_str) -> SessionReport` with a `version` field for forward-compat.

## Phases
| Phase | Focus | Depends | Status |
|-------|-------|---------|--------|
| 1 | DB table + serialization + accessor (`session_reports.py`) | none | done |
| 2 | `/reports` command + `reports:` callback wiring (bot.py, keyboards.py, study_handler.py, routing.py) | phase 1 | done |
| 3 | Completion-gate change (R10-F) + integration tests + validation | phase 2 | done |

## Notes
- Module change guard: added `services/db/session_reports.py` (new table `session_reports`) — SEAMS.md + AGENTS.md §4 table updated.
- R10-F breaks two pre-existing tests asserting the old free-user minimal completion
  (`test_study_handler.py::test_session_complete_with_remaining_slots_in_context`,
  `test_session_summary_flow.py::test_completion_renders_minimal_for_free`) — updated them to
  reflect the new canonical behavior (free users get the summary, no detail button).
- Full validation green: pytest 1319 passed, compile_all 0, ruff F821/F811 clean, git diff --check clean.

## Blocked Questions
- none