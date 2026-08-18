# Active Plan Tickets

| Ticket | Plan | Issue | Branch | Status |
|---|---|---|---|---|
| CB-NOTIFY-01 | `callbacks/plan-callback-notifications.md` | #310 | `refactor/callback-notifications` | in-progress |
| HELP-01 | `help-command/plan-help-command.md` | — | `feat/help-command` | complete |
| GRADE-FEEDBACK-01 (PR 312) | `ux/plan-grade-feedback-toast.md` | #308 | `feat/grade-feedback-toast` | complete |
| T05 (owner T05 / local T02) | `fsrs/plan-fsrs-session-completion-phase-02-timestamp-schema.md` | #309 | `feat/fsrs-timestamp-schema` | complete (PR #318 merged); archived to `docs/archive/plans/fsrs-2026-08-14/` |
| T06 (owner T06 / local T03) | `fsrs/plan-fsrs-session-completion-phase-03-grade-transitions.md` | #309 | `feat/phase-3b-fsrs-scheduling` | complete (PR #336 merged); archived |
| T07 (phase 4) | `fsrs/plan-fsrs-session-completion-phase-04-due-priority.md` | #309 | `feat/phase-3b-fsrs-scheduling` | complete (PR #336 merged); archived |
| T08 (phase 5) | `fsrs/plan-fsrs-session-completion-phase-05-handler-integration.md` | #309 | `feat/phase-3b-fsrs-scheduling` | complete (PR #336 merged); archived |
| T09 (release/docs) | `fsrs/plan-fsrs-session-completion-phase-06-release.md` | #309 | multiple-see-main-plan | complete — docs reconciled, dashboard regenerated, plans archived; live smoke test owner-informally handled (5 sessions worked) |
| AI-PRESET-FIX (phase 1 of 7) | `presets/plan-ai-preset-audit-fixes.md` | #330 | `fix/ai-preset-audit-findings` | complete (PR #333 merged) |
| AI-PRESET-FIX (phase 2 of 7) | `presets/plan-ai-preset-audit-fixes.md` | #330 | `fix/ai-preset-audit-findings` | complete (PR #333 merged, R1/R2/R10/R12/R13/R14) |
| AI-PRESET-FIX (phase 3 of 7) | `presets/plan-ai-preset-audit-fixes-phase-03-handlers-ux.md` | #330 | `feat/ai-preset-handlers-ux` | complete (PR #334/#335 merged, R3/R4/R5/R7) |
| AI-PRESET-FIX (phase 4 of 7) | `presets/plan-ai-preset-audit-fixes-phase-04-builtin-removal.md` | #330 | `feat/ai-preset-phase4-builtin-removal` | complete (PR #337 merged) |
| AI-PRESET-FIX (phase 5 of 7) | `presets/plan-ai-preset-audit-fixes-phase-05-secure-keys.md` | #330 | `feat/ai-preset-secure-keys` | complete (PR #339 merged); archived to docs/archive/ |
| SRS-STAGED-REVEAL (spec) | `session/plan-srs-staged-reveal-spec.md` | #338 | `feat/srs-staged-reveal` | Phases 1-2 complete (PR #353, #355 merged 2026-08-15); Phase 3 pending per `fsrs/plan-srs-staged-reveal-phase-03-telemetry-delete-toggle-ui.md` |
| SRS-STAGED-REVEAL (phase 2) | `fsrs/plan-srs-staged-reveal-phase-02-session-staging.md` | #338 | `feat/srs-staged-reveal` | complete — PR #355 merged 2026-08-15 (P2-T1..T4, Kilo review clean) |
| SRS-STAGED-REVEAL (phase 3) | `fsrs/plan-srs-staged-reveal-phase-03-telemetry-delete-toggle-ui.md` | #338 | `feat/srs-staged-reveal` | planned — tickets P3-T1..T5 drafted (2026-08-15); blocking edge = Phase 2 merged (done); owner decisions locked 2026-08-15 (premium toggles, presentation removal, delete scope); open questions pending owner |
| WORD-QUERY-CONSISTENCY (phase 1) | `ux/plan-word-query-card-consistency.md` | #340 | done | R1-R6 shipped (#341) |
| WORD-QUERY-DUP-RETENTION (phase 2) | `ux/plan-word-query-card-consistency-phase-02-retrieve-new-retention.md` | #344 | in-progress | R7-R8 implemented, tests green, pending review/PR |
| ADMIN-AI-LABELS-BACK | `presets/plan-admin-ai-labels-and-back.md` | #342, #343 | `fix/admin-ai-labels-and-back` | complete (PR #352 merged as 2b1315f); archived to docs/archive/ |
| AI-MASTER-KEY-ROTATION (deferred) | `security/plan-ai-master-key-rotation.md` | #354 | pending (deferred) | R1/R2/R4 locked 2026-08-15; blocked on feat/srs-staged-reveal Seam 1 |
| CARD-MODES (FE + review staged/immediate) | `session/plan-card-modes.md` | #338 (ext.) | `feat/card-modes-t2-t3-render` → `-t4-t5-admin` → `-t6-t7-user` | locked 2026-08-15 — T1 MERGED (#361, `d5a6652`); T2+T3 MERGED (#362, `4d5ecff`); delivery = 4 PRs; PR 3/4 (T4+T5) and PR 4/4 (T6+T7) pending |
| STUDY-SESSION-RESTART (Bug 1) | `session/plan-study-session-restart-persistence.md` | #363 | `fix/session-restart-persistence` | complete (PR #364 merged 0fdec76); seam 1+5 released |
| R3-SEND-PRETTY (T1–T5) | `callbacks/plan-send-pretty-span-tree-r3.md` | — | `refactor/send-pretty` | COMPLETE (PR #385 merged f6cd2b3); T6/T7 deferred to follow-up PRs |
| T8-ADMIN-AI (T8-PRE..T8-last) | `callbacks/plan-send-pretty-followups-t8-admin-ai.md` | — | `refactor/admin-ai-spans` | locked 2026-08-17 (R1–R5); T8-PRE pending — add backend= to say()/send() |
| A2-1 (BN1) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-concurrency` (planned) | planned (gate pending; PR #372 merged) |
| A2-2 (BUG-B3/BN4) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-concurrency` (planned) | planned |
| A2-3 (R2) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-normalize` (planned) | planned |
| A2-4 (BUG-B1) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-normalize` (planned) | planned |
| A2-5 (R6) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-presets` (planned) | planned |
| A2-6 (R7) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-presets` (planned) | planned |
| A2-7 (R8) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-presets` (planned) | planned |
| A2-8 (R9) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-cardmode` (planned) | planned |
| A2-9 (R10) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-cardmode` (planned) | planned |
| A2-10 (R11) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-integration` (planned) | planned |
| A2-11 (BN2) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-integration` (planned) | planned |
| A2-12 (BN3) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-integration` (planned) | planned |
| A2-13 (BUG-B4) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-integration` (planned) | planned (seam #17 + serialize vs word-query worktrees) |
| J-B6 (R5/F5) | `architecture-deepening/plan-2026-08-17-jb6-plan-identity.md` | — | `refactor/plan-identity` | PR open (code complete, full suite green) |
| GOV-R1 | `workflow/plan-governance-reform.md` | #392 | `chore/governance-reform` | done (impl) — 233-line AGENTS.md + archive; pending review |
| GOV-R2 | `workflow/plan-governance-reform.md` | #393 | `chore/governance-reform` | done (impl) — git-cliff + config + script + CI check; pending review |
| GOV-R3 | `workflow/plan-governance-reform.md` | #394 | `chore/governance-reform` | done (impl) — tooling+CI+refs removed, test_issue_tooling.py deleted; pending review |
| GOV-R4 | `workflow/plan-governance-reform.md` | #395 | `chore/governance-reform` | done (impl) — test_single_source_of_truth.py (16 tests green); pending review |
| GOV-R5 | `workflow/plan-governance-reform.md` | #396 | `chore/governance-reform` | done (impl) — route-delete text in AGENTS.md §6 |
| GOV-R6 | `workflow/plan-governance-reform.md` | #397 | `chore/governance-reform` | done (impl) — test-sync text in AGENTS.md §6 |
| GOV-R7 | `workflow/plan-governance-reform.md` | #398 | `chore/governance-reform` | done (impl) — terse rule text in AGENTS.md |
