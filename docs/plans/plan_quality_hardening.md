# Engineering Quality & Safety Hardening Plan

> STATUS: active

**Purpose:** Make HamZaboon's AI-assisted change process verification-centric so that (1) leftover/dead code cannot survive migrations, (2) tests can never damage the production database, and (3) runtime bugs surface in a scripted staging step instead of after users see them.

**Context:** Owner is a non-professional Python coder; quality must come from automation and enforced process, not human review. Product is a paid startup service; silent/sneaky errors are business-critical. Users are promised good uptime and a low-error (ideally error-free) experience.

**Companion docs:** `AGENTS.md` (operating agreement), `docs/plans/plan_fsrs_migration_v2.md` (next major migration that must benefit from this system), `ROADMAP.md`, GitHub Issues #171, #233, #234.

---

## 1. Why the current process still leaks bugs

| # | Failure mode | Evidence | Fix direction |
|---|---|---|---|
| 1 | **Verification-fidelity gap** — tests mock Telegram/AI and use fresh temp DBs, so the real runtime (timing, concurrency, real network, real DB state) is never exercised until the bot is turned on | Bugs discovered only after boot; user reports | Staging smoke test (WP3) |
| 2 | **Same author writes code and tests** — tests encode the same wrong assumptions as the code; green tests + broken bot | Recurring post-boot defects | Test-independence rule + adversarial review (WP4) |
| 3 | **Cleanup planned but not enforced** — migration plans put cleanup in a final manual-grep Phase 2; nothing fails if old code remains | `advance_word_review`, `interval_idx`, `INTERVALS_DAYS`, `IBTN_REMEMBERED` still present in production code | Dead-reference guard test (WP2) |
| 4 | **No real-system check before cutover** — no staging, no runbook | Defects found only when bot runs | Smoke test + runbook (WP3) |
| 5 | **Test DB isolation is fragile** — a single test that forgets to redirect its DB path writes to production | Issue #234: full suite wiped production AI presets | Choke-point guard (WP1) |
| 6 | **State leaks between tests** — global state can mask or sneak bugs | Not yet instrumented | State-isolation CI checks (WP6) |

**Core principle adopted:** A plan is a *text promise*; the only real promise is an automated check that runs in CI and physically blocks the merge. Convert every "verifiable acceptance" criterion into a test.

---

## 2. The safety spine (non-negotiable, built first)

Goal: make DB damage *structurally impossible*, not merely unlikely.

1. **Choke-point guard.** All DB access funnels through `get_conn()` (`services/db/schema.py:59`). When env `HAMZABAN_TEST_MODE=1` is set, connecting to the production DB path raises `RuntimeError` with a clear message. Covers every future write path automatically.
2. **Test mode forced on.** `tests/__init__.py` sets `HAMZABAN_TEST_MODE=1` at collection; CI sets it too.
3. **CI hash check.** CI records the production DB checksum before the suite and fails if it changed after.
4. **Meta-test.** A test deliberately attempts a production-path write in test mode and asserts it is blocked.
5. **Prerequisite fix.** Merge commit `6ad58ad` (`services/db/schema.py` reads live `db.DB_PATH`), currently stranded on the unmerged `fix/ai-preset-manager-clone` branch. Must land as its own PR first.

---

## 3. Work packages

### WP0 — Land the pending DB-isolation root-cause fix

> **Status: DONE** — landed on `main` via PR #235 (`06c7fbb`, squash-merged 2026-07-31). Verified on `main`: `services/db/schema.py::get_conn()` reads the live `services.db.DB_PATH`; `tests/test_db_isolation.py` present; `tests/test_fallback_flow.py` sets the schema path too.

- **Problem:** On `main`, `schema.get_conn()` uses an import-time copy of `config.DB_PATH`, so `db.DB_PATH` overrides don't isolate schema writes.
- **Approach:** Open a PR from `fix/ai-preset-manager-clone` (or cherry-pick `6ad58ad`) so schema reads the live path.
- **Files:** `services/db/schema.py`, `tests/test_fallback_flow.py` (already hardened).
- **Acceptance:** A test that sets only `db.DB_PATH` (not `db_schema.DB_PATH`) operates on the temp DB; `services/db/schema.py` no longer imports an at-import `DB_PATH` copy.
- **Dep/priority:** None / **P0**.

### WP1 — Bulletproof test-DB guard (safety spine)

- **Approach:** Add `HAMZABAN_TEST_MODE` guard inside `get_conn()`; bootstrap in `tests/__init__.py`; CI hash job; meta-test proving the guard.
- **Files:** `services/db/schema.py`, `tests/__init__.py`, `.github/workflows/ci.yml`, `tests/test_db_guard.py` (new).
- **Acceptance:** With test mode on, no path reaches production writes; the guard's own test passes; CI fails if production DB checksum changes during a run.
- **Dep/priority:** WP0 / **P0**.

### WP2 — Verification guardrails

- **2.1 Dead-reference guard.** `tests/test_dead_code_guard.py` (new) scans production code (`bot.py`, `handlers/`, `services/`, `config/`) and fails if any symbol in a `BANNED_SYMBOLS` registry still exists (as a definition, reference, import, or attribute access). Registry lives in the test file with a `why` comment per symbol; `PRESERVED_SYMBOLS` lists intentionally-retained symbols the guard skips. When a plan deletes a symbol (e.g., the FSRS migration's `advance_word_review`), it adds it here — so the migration's Phase 2 cleanup becomes enforced. Placeholder entries prove the mechanism until the FSRS merge lands and adds the real deleted names.
- **2.2 Definition of Done (DoD).** A mandatory checklist in `AGENTS.md` (§7 pre-commit gate) + a PR body template (`.github/PULL_REQUEST_TEMPLATE.md`): new tests present, no banned symbols, migration tested on fresh + upgraded DB, integration test added, docs/issues updated, staging smoke passed.
- **2.3 Migration-completeness test template.** `tests/test_migration_guards.py` (new): reusable assertions (expected tables/columns present, banned columns absent) on BOTH a fresh DB and an upgraded-from-old-schema DB. Reused by the FSRS migration.
- **2.4 Reverse wiring + Dependency & Wiring Map.** `tests/test_wiring.py` extended: router call targets resolve, and all project-internal `from X import Y` resolve (including re-exports/submodules). `AGENTS.md` §2.4 gains a mandatory **Dependency & Wiring Map** (§2.4.2) — the gate refuses to lock a refactor/migration/feature-removal contract without it, and each disposition is verified after implementation.
- **Files:** `tests/test_dead_code_guard.py`, `tests/test_wiring.py`, `tests/test_migration_guards.py`, `AGENTS.md`, `.github/PULL_REQUEST_TEMPLATE.md`.
- **Acceptance:** a simulated "forgot to delete old function" change fails CI; a feature-removal plan omitting the Dependency & Wiring Map is rejected at the gate; the migration template is reused for the FSRS migration.
- **Dep/priority:** WP1 / **P1** (must exist before FSRS migration).

### WP3 — Staging smoke test + release runbook

- **Approach:** `scripts/smoke_test.py` walks the main user flows for real (onboarding, ask-word, grammar tip, daily card, SRS, admin) against a **copy** of the production DB and a **dev bot token**, with a hard AI-token budget. Safety guards: refuses to run if DB path is production or token is the production token (env `HAMZABAN_SMOKE_MODE=1`). `docs/release_runbook.md` is a step-by-step pre-cutover checklist (backup → smoke → verify logs/quotas/jobs → rollback plan).
- **Files:** `scripts/smoke_test.py` (new), `docs/release_runbook.md` (new), `.env.example`.
- **Acceptance:** Running the smoke script against production path exits nonzero with a clear refusal; it completes against a staging copy and exercises quota + persistence paths.
- **Dep/priority:** WP1 / **P1** (before FSRS cutover).

### WP4 — AGENTS.md process amendments

- **4.1 Bounded cleanup.** Amend §2.2: a PR may delete dead code in files it touches, declared in the contract — so cleanup happens with the change, not in a forgotten Phase 2.
- **4.2 Adversarial review + test independence.** Amend §5: after implementing, agent runs an explicit "what did the plan miss?" hunt (integration points, leftover refs, state leaks, restart safety, quota edges); tests must be written from the user-behavior spec, not the code.
- **4.3 DoD in the gate.** Add the WP2.2 checklist to the pre-commit gate (§7).
- **Files:** `AGENTS.md`.
- **Dep/priority:** WP1 / **P1** (quick).

### WP5 — Debt sweep + worktree hygiene

- **Approach:** Structured inventory of dead code, stale `tools/` simulators, untracked ad-hoc files (`check_db.py`, `export_cards.py`, `button_usage.jsonl`, temp docs, `tools/Fsrs_simulation_v5/…`, `tts_cache/`, etc.) → GitHub Issues with labels; decide per-file fate (track / archive / delete); populate `BANNED_SYMBOLS` from findings.
- **Files:** repo-wide (read-only analysis), then targeted cleanups.
- **Acceptance:** Every piece of untracked/dead material has an Issue or is resolved; worktree is clean.
- **Dep/priority:** Parallel; feeds WP2 / **P2** (before FSRS migration to know the baseline).

### WP6 — Sneaky-state checks

- **Approach:** CI runs the suite twice in one process and once with random test order; occasional `vulture` dead-code scan as a CI job (opt-in threshold).
- **Files:** `.github/workflows/ci.yml`.
- **Dep/priority:** WP1 / **P2** (ongoing).

---

## 4. Execution order

1. **WP0 + WP1** — small; makes DB damage impossible.
2. **WP4** — quick process fix.
3. **WP2** — dead-reference guard + DoD (required before FSRS migration).
4. **WP5** — baseline inventory.
5. **WP3** — smoke + runbook (required before FSRS cutover).
6. **WP6** — ongoing.

Each WP is a single logical commit/PR following `AGENTS.md` workflow (contract lock → validate → branch `type/short-desc` → PR → squash merge).

---

## 5. Decisions log

| # | Decision | Choice | Date | Status |
|---|---|---|---|---|
| 1 | Quality strategy | Verification-centric: automated checks over plans/human review | 2026-07-31 | Approved |
| 2 | DB safety mechanism | Choke-point guard in `get_conn()` + test-mode flag + CI hash + meta-test | 2026-07-31 | Approved (WP1) |
| 3 | Dead-code enforcement | `BANNED_SYMBOLS` registry + CI guard test | 2026-07-31 | Proposed (WP2) |
| 4 | Cleanup timing | Bounded cleanup with each PR (amend AGENTS.md §2.2) | 2026-07-31 | Approved (WP4) |
| 5 | Real-system check | Staging copy-DB smoke test + release runbook before cutovers | 2026-07-31 | Proposed (WP3) |
| 6 | Independent review | Mandatory reviewer subagent (fresh context, report-only) for non-trivial changes | 2026-08-01 | Approved (WP4) |
| 7 | Guard scan scope | Production only (`bot.py`, `handlers/`, `services/`, `config/`) | 2026-08-02 | Approved (WP2) |
| 8 | Preservation mechanism | Archive + `PRESERVED` list with why-comments | 2026-08-02 | Approved (WP2) |
| 9 | Reverse wiring test | Router targets + imports both resolve | 2026-08-02 | Approved (WP2) |
| 10 | Dependency & Wiring Map | Hard gate requirement (§2.4.2) | 2026-08-02 | Approved (WP2) |

---

## 6. Progress tracker

| WP | Scope | PR | CI | Merged |
|---|---|---|---|---|
| WP0 | Land `6ad58ad` DB-isolation fix | #235 | pass | ✅ |
| WP1 | Bulletproof test-DB guard | #237 | pass | ✅ |
| WP2 | Dead-ref guard, DoD, migration tests | — | — | ☐ |
| WP3 | Smoke test + runbook | — | — | ☐ |
| WP4 | AGENTS.md amendments | #238 | pass | ✅ |
| WP5 | Debt sweep + hygiene | — | — | ☐ |
| WP6 | State-isolation + vulture | — | — | ☐ |
