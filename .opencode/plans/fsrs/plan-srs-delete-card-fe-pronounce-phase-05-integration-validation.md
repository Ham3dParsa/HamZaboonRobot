---
name: srs-delete-card-fe-pronounce-phase-05-integration-validation
description: Phase 5 — integration tests, full validation, independent review, PR (Rule 9)
created: 2026-08-19
base_commit: 6305c18
branch: feat/srs-delete-card
status: in-progress
---
STATE: phase — status: DONE (merged via PR #406) — was: integration tests + validation + review + PR

## Blocking edges
- Phases 1–4 complete.

## Scope
- Finalize `tests/test_integration/test_srs_delete_card_flow.py` (Rule 9) if not fully covered in Phase 4.
- Ensure `tests/test_wiring.py` covers the three prefixes (Phase 3) and the reverse-wiring guard passes.

## Validation
- Full suite: `pytest`, `scripts/compile_all.py`, `python -m ruff check --select F821,F811`, `git diff --check`.
- Include `<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>` before commit; explicit staging; Conventional Commits; single logical change.

## Independent review
- Launch read-only `hamzaboon-reviewer` before committing; fix confirmed findings and re-run until none remain.

## PR
- Rebase onto latest `origin/main` (Rule 8 — Persistence seam held by refactor/db-concurrency; proceed-anyway + rebase), push, `gh pr create --fill --base main` linking issue #338. Report repo checks (do not claim CI success from local runs). Owner merges (Squash and merge).

## Post-merge cleanup
- Remove worktree `.worktrees/feat-srs-delete-card`, delete branch (local + remote), release the parallel-work claim (Telegram UI -> SRS Grading, Persistence), close #338 P3-T2, update TICKETS.md / ROADMAP.

## Gates
- Satisfies Rule 9.

## Acceptance criteria
- Full validation passes; reviewer reports no confirmed findings; PR opened; after merge, cleanup complete and claim released.