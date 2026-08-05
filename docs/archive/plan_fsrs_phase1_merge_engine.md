# Plan — Phase 1: Merge the Session Engine onto `main`

**Status:** `> STATUS: implemented` (merged 2026-08-02 via PR #240; B1 completion fix merged 2026-08-03 via PR #243)
**Owner gate:** LOCKED — owner approved proceed; executed and closed
**References:**
- `docs/plans/plan_fsrs_session_cleanup.md` — comprehensive plan (this was its Phase 1)
- Local branch `feat/fsrs-migration` — source of the engine (tip `025f968`)
- `docs/plans/plan_fsrs_migration_v2.md` — engine design (Phases 0–1g complete; 1a/1c partial per FSRS wiring stubs)

---

## Goal

Bring the working, tested session engine from `feat/fsrs-migration` onto `main` as a clean,
reviewed, conflict-resolved merge — without disturbing the owner's unrelated in-progress
`tools/financial_model/financial_model_dashboard.html` change.

## Non-Goals (explicitly out of Phase 1)

- NO removal of stale daily/review/old-SRS flows (Phase 2).
- NO saved-word scheduling reset (Phase 3).
- NO changes to learner-facing behavior beyond what the engine already implements on the branch.
- NO rewriting or "improving" the engine's internals during the merge — land it as-is unless a
  conflict forces a decision, and any such forced change is reported to the owner.

## Facts verified on 2026-08-02

- Current branch: `main`; `handlers/study_handler.py` = 33-line stub.
- `feat/fsrs-migration` tip `025f968`; shared ancestor with `main` = `ba0f6816`.
- Branch carries the engine: `services/session/` (`__init__.py`, `assembly.py`, `grade_policy.py`),
  265-line `study_handler.py`, rewritten `scheduling.py` (96 lines), 4-grade keyboards + `srs:fe:`,
  rewritten `record_review_event`, and tests `test_study_handler.py`, `test_session_engine.py`,
  `test_srs_callback_routing.py`, `test_reviews.py`.
- The "deletions" in `git diff main feat/fsrs-migration` for financial-dashboard files
  (`tools/financial_model/financial_model_dashboard.html`, `docs/plan_financial_dashboard_baseline.md`,
  `tests/__init__.py`, `tests/test_ai_preset_manager.py`, `tests/test_db_guard.py`,
  `tests/test_integration/test_ai_timeout_flow.py`) are NOT in the merge-base and NOT on the branch —
  they were added to `main` after the split. A three-way merge preserves them.
- Genuine branch deletions: `services/srs_engine.py` (intentional; replaced by `services/session/`),
  plus the v2-plan checkbox marks and some test/requirements/doc diffs — all reviewed during merge.

## Procedure

### Step 0 — Pre-flight
1. `git status --porcelain` — confirm only the known tracked modifications.
2. Record for rollback: current `main` HEAD sha.

### Step 1 — Stash the unrelated change
- `git stash push -- tools/financial_model/financial_model_dashboard.html`
- Verify `git status` is clean of tracked changes.

### Step 2 — Update `main`
- `git checkout main` (already there) and `git pull` (or `git fetch origin main` then confirm
  `main` matches `origin/main`). If origin/main moved, note it — merge base may shift.

### Step 3 — Create merge branch
- `git checkout -b merge/fsrs-engine`
- Branch name follows `type/short-desc` convention.

### Step 4 — Merge
- `git merge feat/fsrs-migration`
- If it merges cleanly with no conflicts, still perform the review passes below.
- Expected conflict areas: `bot.py`, `config/keyboards.py`,
  `handlers/srs_handler.py`, `handlers/user.py`, `services/db/schema.py`, `services/db/words.py`,
  `services/db/reviews.py`, `services/db/__init__.py`, `services/ai/llm_services.py`,
  `services/utils/formatting.py`, `services/scheduling.py`, `tests/test_keyboards.py`,
  `tests/test_reliability.py`, `tests/test_srs_staged_reveal.py`, `project_status.json`,
  `issues/project_status.html`.

### Step 5 — Conflict resolution policy
Resolve each conflict by taking the ENGINE version when it is the designated implementation (see
`plan_fsrs_migration_v2.md`) and the `main` version when the change is an unrelated `main` feature.
**Rule:** if any conflict is ambiguous about behavior, persistence, quotas, scheduling, callbacks, or
AI contracts, STOP and ask the owner (Section 2.4 of AGENTS.md). Never silently pick a side on a
behavioral conflict.

### Step 6 — Verification
- `python -m unittest discover -s tests` (must be green; the branch's new tests
  `test_study_handler.py`, `test_session_engine.py`, `test_srs_callback_routing.py`, `test_reviews.py`
  must pass after merge).
- `python scripts/compile_all.py`
- `python -m ruff check --select F821,F811`
- `python scripts/generate_dashboard.py`
- `git diff --check`
- Confirm `study:start` + `srs:fe:` are wired in the merged `bot.py` callback_router and present in
  the wiring allowlist logic.

### Step 7 — Independent review
- Launch a fresh-context reviewer subagent against the merge diff (per AGENTS.md §5). It must check:
  spec-vs-contract gaps, leftover old symbols, restart safety, callback wiring, test independence,
  scope violations. It reports only; it does not edit.
- Fix any confirmed findings; re-run reviewer until none remain.

### Step 8 — Commit + PR
- Stage explicitly (`git add <files>`), single logical commit (`merge(engine): bring FSRS session
  engine from feat/fsrs-migration`).
- Push branch, `gh pr create --base main --fill`.
- `gh pr checks` — monitor CI; apply Error Recovery Protocol on failure.
- Report final CI status to the owner.

### Step 9 — Owner merge + restore stash
- Owner reviews on GitHub; on "merge it", `gh pr checks` confirm green, then `gh checkout main`,
  `git pull`.
- Post-merge: confirm the dashboard file is intact.

## Locked contract summary (Phase 1)

- Rule 1 (merge): A = merge `feat/fsrs-migration` onto `main`; rejected = rebuild fresh.
- Rule 2 (scope): A = land engine as-is; rejected = refactor/improve during merge.
- Rule 3 (conflicts): A = engine version when designated, main version when unrelated, STOP+ask on
  ambiguity; rejected = silent unilateral choice.
- Rule 4 (stash): A = stash/restore the dashboard file, never commit it; rejected = include it.
- Owner Confirmation: LOCKED — owner approved "proceed" and merged the resulting PR.
- GATE STATUS: LOCKED — completed.

## Rollback

- Record `main` HEAD before merge (Step 0.2). If the merge is bad: revert the squash commit with a
  corrective commit (no force-push).

## Outcome

- Merged onto `main` via PR #240 (session engine shell). B01 session-completion crash fixed via
  PR #243. Phase 1 = Phase 0–1g from `plan_fsrs_migration_v2.md` (1a/1c partial: FSRS DB wiring and
  Tier-3 AI generation are stubs deferred to Phase 3b).