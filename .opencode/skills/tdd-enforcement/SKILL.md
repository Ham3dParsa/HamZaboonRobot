---
name: tdd-enforcement
description: TDD Enforcement — red-green-refactor at pre-agreed seams, driven by implement phase. Adapted from mattpocock/skills (implement, tdd) and AGENTS.md §5 (focused tests + integration tests). Load during implementation phases to enforce test-first discipline.
license: MIT
compatibility: opencode
metadata:
  category: testing
  source: mattpocock/skills (implement, tdd)
author: Ham3dParsa
author_url: https://github.com/Ham3dParsa
---
# TDD Enforcement Skill (AGENTS.md §5 + Pocock implement adaptation)

## Purpose
Enforce Test-Driven Development at pre-agreed seams during implementation. No production code written without a failing test first.

## When to load
- During any implementation phase (after spec-to-tickets breakdown)
- When writing new logic, handlers, DB functions, AI services, formatters
- When modifying existing behavior (callbacks, quotas, scheduling, wiring)

## TDD Cycle (Red → Green → Refactor)

### RED — Write failing test first
- **Unit tests** (`tests/test_*.py`) for new logic/edge cases/DB schema changes
- **Integration tests** (`tests/test_integration/test_*_flow.py`) for behavioral changes (callbacks, handlers, keyboards, DB writes, quotas, AI interaction)
- Test must be written FROM user-facing behavior spec + locked contract, NOT from implementation internals
- Run test to confirm it FAILS (red)

### GREEN — Minimal implementation to pass
- Write only enough code to make the test pass
- No extra features, no speculative hardening
- If implementation reveals ambiguity → HALT, return to Contract Lock Gate (§2.4)

### REFACTOR — Clean up with tests passing
- Apply existing conventions (AGENTS.md §3 module boundaries, catalog rule, formatting)
- Run full validation suite (hamzaban-validation skill)
- No behavior changes during refactor

## Pre-Agreed Seams (where TDD is mandatory)
| Seam | Test Location | Triggers |
|---|---|---|
| DB schema/migrations | `tests/test_db_migrations.py`, `tests/test_migration_guards.py` | Any schema change |
| Callback routing | `tests/test_wiring.py`, `tests/test_integration/` | New/changed callback prefix |
| AI calls/validation | `tests/test_ai_validation.py`, `tests/test_llm_services.py` | AI contract change |
| Quota/plan logic | `tests/test_reliability.py` | Quota/plan enforcement |
| Formatting/escaping | `tests/test_formatting.py`, `tests/test_integration/` | MarkdownV2 output change |
| SRS/delivery | `tests/test_reviews.py`, `tests/test_srs_*`, `tests/test_integration/` | SRS/delivery logic |

## Integration Test Requirements (AGENTS.md §6)
For behavioral changes:
- `tests/test_integration/test_<feature>_flow.py` with `IsolatedAsyncioTestCase`
- DB snapshot isolation (backup → temp copy → restore)
- Mocked Telegram (`AsyncMock` on `Context.bot`)
- AI mocked by default; `AI_TEST_REAL=true` with 1000 token budget
- Assert Telegram output + DB state + keyboard `callback_data` prefixes

## Anti-Patterns (DO NOT)
- Write tests that mirror implementation internals (catches shared wrong assumptions)
- Skip TDD for "simple" changes — all behavioral changes require tests
- Write implementation first, then tests (defeats the purpose)
- Treat passing tests as "done" without validation suite + wiring guards

## Verification Gates
- `tests/test_wiring.py` — reverse-wiring guard (all callback prefixes have router matches)
- `tests/test_dead_code_guard.py` — dead-reference guard (no leftover removed symbols)
- `tests/test_formatting.py` — escaping correctness
- Full §6 validation suite must pass