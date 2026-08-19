---
name: plan-db-remaining
description: Serial DB-domain continuation pipeline — 13 tickets (A2-1..A2-13) covering the remaining items from 2026-08-16-db-domain-consolidated.md after J-A1/A2/A3.
created: 2026-08-17
base_commit: f6cd2b3 (origin/main, post #385)
status: planned (serial pipeline; A2-1 NOT yet opened)
---

# DB Track Continuation — Serial Pipeline (13 tickets)

STATE: SERIAL PIPELINE — 13 tickets, **ONE active worktree at a time**. Every
phase (A2-1..A2-12) claims the **Persistence seam (#1)** during its active
window; **A2-13 additionally claims Custom-word query orchestration (#17)**.
Phases MUST NOT run concurrently — all edit `services/db/*` and many overlap on
`schema.py` / `words.py` / `users.py`.

> **Owner correction (2026-08-17):** "These are a SERIAL pipeline, not parallel
> sessions... Run them as ONE serial DB pipeline: one active worktree at a time →
> claim Persistence → implement → merge → release → next." Order preserved:
> A2-1 → A2-2 → (A2-3,A2-4) → (A2-5,6,7) → (A2-8,9) → (A2-10,11,12,13).

## Evidence base
`hamzaboon-db` subagent verified against `origin/main` @ `c6bd1de`: of 14
remaining items, **1 ADDRESSED** (BUG-B2, by another session), **3 PARTIAL**
(R6, R7, BN3), **10 NOT ADDRESSED**. This pipeline covers the **13 open/partial**
items. BUG-B2 is excluded (done).

## Order (locked)
```
A2-1 → A2-2 → (A2-3, A2-4) → (A2-5, A2-6, A2-7) → (A2-8, A2-9) → (A2-10, A2-11, A2-12, A2-13)
```

## Tickets

### A2-1 (PHASE 1, HIGH-RISK) — BN1: remove global RLock, add WAL + busy_timeout + **maintenance mode**
- **Seam:** Persistence (#1) + Telegram UI -> Admin (#8)
- **Files:** `services/db/schema.py` (`_DB_LOCK`, `get_conn`); `services/db/__init__.py` (export/import); `handlers/admin.py` + `config/keyboards.py` (maintenance toggle button); user-facing message via `services/utils/formatting.py`.
- **GATE STATUS: LOCKED** 2026-08-18 (owner chose per rule).

**Locked contract:**
- **A2-1-1 (A):** WAL + `busy_timeout`, keep `BEGIN IMMEDIATE` per write.
- **A2-1-2 (A):** `busy_timeout` = 5000 ms.
- **A2-1-3 (A):** `PRAGMA journal_mode=WAL` on every connection open; no migration (DB treated as throwaway/test).
- **A2-1-4 (A):** only remove `_DB_LOCK` wrapper in `get_conn`; `transaction()` untouched. (`database_lock()` kept — still used by `import_db_bytes`.)
- **A2-1-5 (A):** mandatory `hamzaboon-reviewer` + fresh & non-WAL existing DB tests + concurrent-writer 0-lock test.
- **A2-1-6 (A):** **maintenance-mode gate** = shared/exclusive lock. Normal reads/writes hold a **shared** lock (concurrent); entering maintenance / restore takes an **exclusive** lock (blocks normal ops; restore waits for active connections). Preserves restore-safety that the old global lock provided.
- **A2-1-7 (A):** **admin panel button** to enter/exit maintenance; **friendly default Persian message** with **optional edit** in the flow; **auto-exit** when restore/backup finishes.
- **Design decisions (owner, 2026-08-18):** Admin panel button ✓; Friendly Persian message ✓; Auto-exit on restore finish ✓; default message + optional edit ✓.
- **Callback impact:** new admin callback prefix for the maintenance toggle → **wiring integrity test** in `tests/test_wiring.py` required. Learner-facing message must pass through `services/utils/formatting.py`.
- **Acceptance:** WAL on; `get_conn` no longer serializes normal traffic; 0 `database is locked` under concurrent writers; restore/export wait for active connections (shared/exclusive); maintenance blocks normal user ops with friendly Persian message and auto-exits after restore; fresh + non-WAL existing DB tests.
- **Risk:** touches ALL DB traffic + admin panel. **Mandatory `hamzaboon-reviewer` independent review + dual DB migration tests + wiring test before PR.**
- **STATUS: IMPLEMENTED (2026-08-19)** — WAL+busy_timeout in `get_conn` (A2-1-1/2/3), shared/exclusive `_MaintenanceGate` + `maintenance()` around export/import (A2-1-4/6), admin maintenance toggle + editable Persian message + auto-exit on restore (A2-1-7), wiring test green, fresh+non-WAL tests in `tests/test_db_wal_concurrency.py`. PR pending independent review.

### A2-2 — BUG-B3 / BN4: `due_words_for_user` read-only
- **Seam:** Persistence (#1)
- **Files:** `services/db/words.py:212-233`; callers `services/session/assembly.py:46`, `handlers/user.py:475`.
- **Deps:** after A2-1 (both concurrency).
- **Acceptance:** `due_words_for_user` does 0 writes; grace-deadline maintenance moved to a separate fn; callers unchanged.

### A2-3 — R2: single `normalize_word` (NFC)
- **Seam:** Persistence (#1)
- **Files:** `schema.py:70`, `words.py:17`, `__init__.py:172-182`.
- **Acceptance:** one canonical NFC fn; other 2 delegate; dedupe test NFC vs non-NFC unicode.

### A2-4 — BUG-B1: `$ENV` resolved in runtime resolver too
- **Seam:** Persistence (#1)
- **Files:** `schema.py:684-686` (migration) + `key_crypto.py:86-109` (`decrypt_secret`/`resolve_api_key`).
- **Acceptance:** `$ENV` resolved identically migration + runtime; test for unset-env key on both paths.

### A2-5 — R6 (finish partial): `build_preset_upsert` single registry
- **Seam:** Persistence (#1)
- **Files:** `schema.py:30-59` (`_AI_PRESETS_COLUMNS`) + `preset_registry.py:119, 293-299`.
- **Acceptance:** `set_preset` + `clone_preset` consume shared registry; single column source.

### A2-6 — R7 (finish partial): single parametric quota helper
- **Seam:** Persistence (#1)
- **Files:** `schema.py:103-119` + `users.py:282-370` (6 near-identical fns).
- **Acceptance:** one `_daily_counter(conn, user, date_col, count_col, limit)`; 6 callers delegate.

### A2-7 — R8: route settings upserts through `set_setting`
- **Seam:** Persistence (#1)
- **Files:** `preset_registry.py:316-402` (13 manual upserts) → `settings.set_setting` / `set_bool_setting`.
- **Acceptance:** 0 manual `INSERT/UPDATE settings` in `preset_registry`.

### A2-8 — R9: `CardModeService`
- **Seam:** Persistence (#1)
- **Files:** `users.py:15-19,93-178` + `plans` cols + settings seed (`schema.py:441-444`) + `catalog.py`.
- **Deps:** relies on J0.1/J0.2 catalog/settings registry (done).
- **Acceptance:** single owner for card-mode resolution; registry in `catalog.py`.

### A2-9 — R10: split `__init__.py` facade
- **Seam:** Persistence (#1)
- **Files:** `__init__.py:168-297,304-349` → `query_results.py` / `grammar_tips.py`.
- **Acceptance:** `__init__.py` re-export only; real CRUD in dedicated modules.

### A2-10 — R11: single `app_today()` + consolidate key-resolver
- **Seam:** Persistence (#1)
- **Files:** `schema.py:62-63`, `config/__init__.py:139-141`, `ai/ai_presets.py:18-31`.
- **Acceptance:** one `app_today()`; `$ENV` resolution centralized in `key_crypto`.

### A2-11 — BN2: composite SRS index on `saved_words`
- **Seam:** Persistence (#1)
- **Files:** `schema.py:430` (add `saved_words_due_idx ON saved_words(user_id, first_exposure_done, review_status, retry_at)`).
- **Acceptance:** `EXPLAIN QUERY PLAN` shows SEARCH via new index for due-words filter.

### A2-12 — BN3 (finish partial): `get_presets` no `SELECT *` api_key
- **Seam:** Persistence (#1)
- **Files:** `preset_registry.py:12-15`.
- **Acceptance:** `api_key` excluded / non-secret cols only; pagination if needed.

### A2-13 — BUG-B4: offload sync DB in `word_query.ask` to `asyncio.to_thread`
- **Seam:** Persistence (#1) **AND** Custom-word query orchestration (#17)
- **Files:** `services/word_query.py:187,211,249,256,262`.
- **COORDINATION (owner correction #2):** explicitly claim **#17**; verify no overlapping branch is editing `word_query.py`; **serialize against** `fix/word-query-timeout-race` + `word-query-card-consistency` worktrees (they currently do NOT claim #17 → **FLAG those worktrees to claim #17**).
- **Acceptance:** `ask` never blocks the event loop; non-blocking integration test.

## Standing rules (every ticket)
- Own **contract-lock gate** before any code (AGENTS.md §2.4).
- Update this plan STATUS column + `TICKETS.md` after each step.
- Rebase worktree onto `origin/main` after each merged PR.
- One active worktree; claim Persistence (#1) on start, **release on merge**.
- Behavioral changes: `hamzaboon-reviewer` independent review + `tests/test_integration/` before PR.
- Schema/migration changes: tests on BOTH fresh and upgraded-from-prior DB.

## Excluded
- **BUG-B2** (`preset_hourly_usage` prune) — ADDRESSED in `origin/main`
  (`preset_registry.py:439-450` + `services/ai/llm_services.py:109-118`). Not in pipeline.
