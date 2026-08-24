# Active Plan Tickets
> **Note:** This file tracks only **active / incomplete** plans (pending, in-progress, or open worktree). Completed plans are archived via `git log` and `docs/archive/` — they are no longer listed here to keep the board readable.

| Ticket | Plan | Issue | Branch | Status |
|---|---|---|---|---|
| AI-MASTER-KEY-ROTATION (deferred) | `security/plan-ai-master-key-rotation.md` | #354 | pending (deferred) | R1/R2/R4 locked 2026-08-15; Seam 1 now free (srs-staged-reveal merged) — ready to start |
| CARD-MODES (FE + review staged/immediate) | `session/plan-card-modes.md` | #338 (ext.) | `feat/card-modes-t2-t3-render` → `-t4-t5-admin` → `-t6-t7-user` | locked 2026-08-15 — T1 MERGED (#361, `d5a6652`); T2+T3 MERGED (#362, `4d5ecff`); delivery = 4 PRs; PR 3/4 (T4+T5) and PR 4/4 (T6+T7) pending; **re-validated vs `d76ca7b` (2026-08-18): target new owners `services/routing.py` (R1), `services/db/plans.py` (R5); card-mode keys canonical in `SETTINGS_KEYS`; gate is complementary two-layer (admin setting → `has_feature(plan,"card_modes")`); 1 hygiene item (card-types single-source, still OPEN — `SETTINGS_CARD_TYPES` remains in `config/catalog.py`)** |
| A2-1 (BN1) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-concurrency` | complete (PR #415 merged; #372 was a separate R5 plan-semantics item) |
| A2-2 (BUG-B3/BN4) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-concurrency` | complete (PR #425 merged) |
| A2-3 (R2) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-normalize` | complete (PR #434 merged) |
| A2-4 (BUG-B1) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-normalize` | planned |
| A2-5 (R6) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-presets` | planned |
| A2-6 (R7) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-presets` | planned |
| A2-7 (R8) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-presets` | planned |
| A2-8 (R9) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-cardmode` | planned |
| A2-9 (R10) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-cardmode` | planned |
| A2-10 (R11) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-integration` | planned |
| A2-11 (BN2) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-integration` | planned |
| A2-12 (BN3) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-integration` | planned |
| A2-13 (BUG-B4) | `architecture-deepening/plan-2026-08-17-db-remaining.md` | — | `refactor/db-integration` | planned (seam #17 + serialize vs word-query worktrees) |
| J-B6 (R5/F5) | `architecture-deepening/plan-2026-08-17-jb6-plan-identity.md` | — | `refactor/plan-identity` | complete (PR #387 merged) |
| ARCH-DEEPENING (canonical remaining-work tracker) | `architecture-deepening/plan-2026-08-19-remaining-work.md` | — | A/B/C tracks | in-progress — counts tracked live in remaining-work plan (#437) |
