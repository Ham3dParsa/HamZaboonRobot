---
name: plan-session-summary-report
description: Show a session summary report after a study session ends (learner + admin variants, paged detail)
created: 2026-08-19
base_commit: 7f16597
branch: feat/session-summary
status: in-progress
---

STATE: phase 3/3 — status: completed — focus: all 3 phases implemented + tests GREEN (pending commit/PR)

# Session Summary Report

Locked contract (all 7 rules chosen by owner 2026-08-19; seams checked clean under
parallel-work-guard; claim acquired on `feat/session-summary`).

## Locked Rules

- **R1 — Presentation:** replace the completion message («جلسه مطالعه تموم شد! 🎉») with the
  report. Default = compact summary. A «جزئیات» button opens the paged word list in the same
  message; pages paginate via callback; back to summary.
- **R2 — Prior review dates:** show **one** prior date per word from `saved_words.last_review_at`.
- **R3 — Stability/grade source (seam-safe):** no `srs_handler` edit. Assemble at session end from
  `saved_words.stability` (after), a before-stability snapshot captured in `study_handler` when a
  node is first rendered, and grade/activity from `review_events`. Avoids SRS Grading seam.
- **R4 — Tier gating:** new `session_summary` feature, min_rank=1 (bronze+). Free keeps minimal
  message. Owner (`is_owner`) gets the admin variant.
- **R5 — Learner list:** header with split counts (learned = first-exposure graded, reviewed =
  srs_review graded) + paged word list; each line shows word + stability-after + new/review badge;
  summary line states average stability change.
- **R6 — Admin variant:** appends per word precise FSRS: stability before→after, interval days,
  next-review date, difficulty, grade.
- **R7 — Lifetime:** report computed at completion; page data ephemeral in per-user memory (not
  persisted). Session row cleared as today → shown once; stale «جزئیات»/page button after restart
  fails gracefully with a «پیام منقضی» notice.

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| New module | `services/session/summary.py` | add (pure builder) |
| Callback prefixes | `session:summary:` (detail/pagination) | add |
| Router branches | `services/routing.py` register | add |
| Keyboard builders | `config/keyboards.py` summary keyboards | add |
| Session state | `SessionState.before_stability` + serialization in `study_handler.py` | update |
| Completion path | `advance_session` in `study_handler.py` | update |
| Feature gate | `config/plan_identity.py` `session_summary` min_rank=1 | add |
| Tests | `test_wiring.py` (new callback), integration tests | add/update |
| Docs | AGENTS.md §3 module map, SEAMS.md (module guard) | update |

## Blocked Questions

(none)
