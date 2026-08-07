# WP2 — Verification Guardrails: Dead-Reference Guard, Reverse Wiring, Migration Template, Dependency Map Gate

> STATUS: active
> Parent: `docs/plans/content/plan_quality_hardening.md` (WP2)

**Purpose:** Prevent dead code from surviving any future plan or implementation, and force an agent to enumerate every dependent feature before writing a refactor/migration/feature-removal plan — then verify all wiring after implementation. Catches the failure mode where a plan deletes a function/handler/symbol but leaves a caller, callback branch, keyboard, or import behind, and nothing fails CI until the bot breaks at runtime.

**Companion docs:** `AGENTS.md` (§2.4 contract-lock gate, §3 callback routing map), `docs/plans/content/plan_quality_hardening.md`, `docs/plans/fsrs/plan_fsrs_migration_v2.md` (first consumer: FSRS merge adds its deleted names to `BANNED_SYMBOLS`).

---

## Locked decisions

| # | Decision | Choice | Date |
|---|---|---|---|
| D1 | Guard scan scope | Production only (`bot.py`, `handlers/`, `services/`, `config/`) — `tools/`, `tests/`, `docs/` never flagged | 2026-08-02 |
| D2 | Preservation mechanism | Archive + `PRESERVED` list (kept code → `docs/archive/`/`tools/`, or allowlist with `why` comments) | 2026-08-02 |
| D3 | Guard test symbols | Placeholders now; real FSRS-deleted names added when the FSRS branch merges | 2026-08-02 |
| D4 | Reverse wiring test | Router targets + imports both resolve | 2026-08-02 |
| D5 | Dependency & Wiring Map | Hard gate requirement — gate refuses to lock without it | 2026-08-02 |

---

## 1. Dead-reference guard (`tests/test_dead_code_guard.py`)

- `BANNED_SYMBOLS: dict[str, str]` — symbol → `why` comment. A symbol is listed here only when a locked plan decided to delete it (e.g., `advance_word_review`, `INTERVALS_DAYS`, `IBTN_REMEMBERED` after the FSRS migration).
- `PRESERVED: dict[str, str]` — intentionally retained symbols → `why` comment. The guard skips these.
- Scan scope: production directories `bot.py`, `handlers/`, `services/`, `config/`. Uses AST to find symbol definitions, references, imports, and attribute accesses.
- Fails CI if any banned symbol appears anywhere in production code.
- Initial population: placeholder names to prove the mechanism; the real FSRS-deleted names are added by the FSRS merge PR (which already deletes them), so the guard proves they can never return.
- `PRESERVED` starts with at least one real retained symbol to prove the skip path works.

**Acceptance:** re-introducing a banned symbol fails CI; a PRESERVED symbol does not.

## 2. Reverse wiring test (extend `tests/test_wiring.py`)

Existing `test_wiring.py` checks the forward direction: every `InlineKeyboardButton` `callback_data` prefix has a matching `callback_router` branch. WP2 adds the reverse:

- Every `await _handler(...)` target called inside `callback_router` resolves to an existing, importable function.
- Every `from handlers.X import Y` / `from services... import Z` / `from config... import Y` name in production code resolves to an existing attribute in the target module.

**Acceptance:** simulating "delete a handler but leave its router call" fails CI; deleting an import while leaving the usage fails CI.

## 3. Migration-completeness template (`tests/test_migration_guards.py`)

Reusable helper asserting schema completeness:
- New columns/functions exist.
- Old (banned/removed) columns/functions are absent.
- Verified on BOTH a fresh database and an upgraded-from-prior-schema database.

Documented for reuse by the FSRS merge (`migrate_saved_words_to_fsrs`, new FSRS columns, dropped `interval_idx`).

## 4. Dependency & Wiring Map gate (amend `AGENTS.md` §2.4)

For any contract that removes/changes a feature, migrates, refactors, changes schema/callbacks, or changes module boundaries, the contract-lock template MUST include a completed Dependency & Wiring Map table:

| Dependency type | Items affected | Disposition (update / remove / keep) |
|---|---|---|
| Callback prefixes | … | … |
| Router branches | … | … |
| Keyboard builders / constants | … | … |
| DB tables / columns / functions | … | … |
| Handler functions | … | … |
| Imports / re-exports | … | … |
| Prompts / formatting helpers | … | … |
| Tests referencing them | … | … |
| Docs (ROADMAP, AGENTS.md §3 map, issues) | … | … |

Filled BEFORE the owner locks the contract; each disposition is VERIFIED after implementation (grep + reverse-wiring test). The gate refuses to lock without the completed map.

## 5. PR body template (`.github/PULL_REQUEST_TEMPLATE.md`)

Mirrors the Dependency & Wiring Map as a merge-blocking checklist, so reviewers/CI see the map per PR.

---

## Execution order

1. `tests/test_dead_code_guard.py` (new)
2. `tests/test_wiring.py` (extend — reverse direction)
3. `tests/test_migration_guards.py` (new)
4. `AGENTS.md` §2.4 amendment + §3 map check
5. `.github/PULL_REQUEST_TEMPLATE.md` (new)
6. Full validation, reviewer subagent, branch `test/wire-and-dead-ref-guard-wp2`, commit, PR, CI.

## Acceptance criteria

- A simulated "forgot to delete old function" change fails CI (guard + reverse wiring).
- A feature-removal plan omitting the Dependency & Wiring Map is rejected at the gate.
- Migration template is reusable by the FSRS merge (tested on fresh + upgraded DB).

## Coordination

WP2 does NOT touch the FSRS merge; it supplies the guardrail the merge (and all future work) runs against. The FSRS merge PR adds its real deleted names to `BANNED_SYMBOLS` and reuses the migration template.

## Progress tracker

| Deliverable | Status |
|---|---|
| WP2 plan doc | ✅ |
| Dead-reference guard | ✅ |
| Reverse wiring test | ✅ |
| Migration template | ✅ |
| AGENTS.md §2.4 gate | ✅ |
| PR template | ✅ |
| Validation + reviewer + PR | 🔄 (PR pending) |
