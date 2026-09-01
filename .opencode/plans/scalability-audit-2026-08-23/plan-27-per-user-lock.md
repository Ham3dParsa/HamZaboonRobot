---
name: plan-27-per-user-lock
description: A-remaining #27 per-user-lock spam guard for costly flows
created: 2026-09-01
base_commit: 9e5184a66aba58e720297886a305c9936dc90ca0
branch: fix/per-user-lock
status: in-progress
---

STATE: phase 0/3 — status: in-progress — focus: lock + TDD for per-user-lock

# Plan 27 — per-user-lock spam guard (scalability-audit A-remaining)

**Ticket:** A-remaining #27 — `per-user-lock` from `decisions-20260823.json` (keep). Note: «به شدت مهم ... گارد اسپم بهینه و کارآمد که مزاحم رفتار عادی نشود» برای بخش‌های حساس/هزینه‌بر.
**Seams:** `scheduling/quota` (`services/scheduling.py`), `Telegram UI -> Study` (`handlers/study_handler.py`), `Telegram UI -> SRS` (`handlers/srs_handler.py`), `custom-word query` (`services/word_query.py` + `bot.py`), `Telegram UI -> User` (`handlers/user.py` for grammar-tip).
**Worktree:** `.worktrees/fix-per-user-lock` branch `fix/per-user-lock` from `origin/main` 9e5184a

## CONTRACT LOCK TEMPLATE

Rule #1 — Target ticket identity:
Decision: Next is per-user-lock spam guard
Option Chosen: A — per-user-lock (owner-delegated: "اگر بر اساس مهارت دقیق است قفل کن")
Alternatives Rejected: B offline-dos/broadcast-alloc/telegram-slot — valid but lower leverage; C card-types-dup/preset-3list — registry polish, defer
Trade-offs: A blocks quota/AI burn with minimal schema change; B needs semaphore tuning; C low impact
Owner Confirmation: delegated proceed 2026-09-01 ("شروع کن" + "اگر بر اساس مهارت دقیق هستند قفل کن")
GATE STATUS: LOCKED

Rule #2 — Scope:
Decision: Single-finding PR (only per-user-lock)
Option Chosen: A — single finding
Alternatives Rejected: B batch 2 — higher collision risk, harder Kilo review
Trade-offs: A = small PR, clean review; B = faster throughput but seam overlap
Owner Confirmation: delegated
GATE STATUS: LOCKED

Rule #3 — Guard algorithm:
Decision: Sliding-window in services/scheduling.py — memory-only fixed 5/10s (no persistence)
Option Chosen: A — sliding-window lightweight memory-only
Alternatives Rejected: B token-bucket table — needs migration, overkill; C semaphore only — not anti-spam
Trade-offs: A = no migration, per-user 5 req/10s, resets on restart (documented, bounded); B = precise but schema churn; C = simple but ineffective
Owner Confirmation: delegated — amended post-reviewer 2026-09-01 to memory-only per hamzaban-reviewer gap
GATE STATUS: LOCKED

Rule #4 — Block behavior:
Decision: answerCallbackQuery with Persian notice, no quota/AI consumption
Option Chosen: A — friendly Persian throttle message
Alternatives Rejected: B silent drop — confuses user
Trade-offs: A = clear UX, zero cost; B = silent failure
Owner Confirmation: delegated
GATE STATUS: LOCKED

GATE STATUS: LOCKED
<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | `study:*`, `srs:*`, `query:*`, `grammar:*` throttled before quota reserve | update (guard check) |
| Router branches | `handlers/study_handler.py:handle_study_start`, `handlers/srs_handler.py:_handle_srs_review`, `bot.py:_process_ask_word` | update |
| Keyboard builders | none (no new buttons) | keep |
| DB tables/columns | none (memory-only, no new table/key) | keep |
| Handler functions | `services/scheduling.py:try_acquire_per_user_slot` atomic (new) + `check_per_user_rate` legacy | add |
| Imports | `services/scheduling.py` imported by handlers | update |
| Tests | `tests/test_integration/test_per_user_lock.py`, `tests/test_wiring.py` | add/update |

## Phases

| Phase | Topic | Blocking edges | Status |
|-------|-------|---------------|--------|
| 01 | Core guard in scheduling (sliding window) | — | pending |
| 02 | Handler integration (study/srs/query) | 01 | pending |
| 03 | Tests + wiring + docs | 01,02 | pending |
