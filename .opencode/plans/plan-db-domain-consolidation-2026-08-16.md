# DB-Track Domain Consolidation — 2026-08-16

Source report: `docs/audit/Deepening/2026-08-16-db-domain-consolidated.md`.

Three sequential DB-layer refactors, each in its own isolated git worktree + PR.
All three are **MERGED**; the DB track is complete.

| Job | Rule | Module(s) | PR | STATE |
|-----|------|-----------|----|-------|
| J-A1 | R1 — unify atomic writes behind `transaction()` | `services/db/schema.py` (+61 call sites) | #371 | MERGED |
| J-A2 | R5 — centralize plan semantics in `plans.py` | `services/db/plans.py`, `config/` delegates | #372 | MERGED |
| J-A3 | R3 — consolidate display-toggle ownership | `services/db/display_toggles.py` (new), `users.py`/`settings.py` delegates | #377 | MERGED |

## J-A3 detail (R3)

- **Contract (GATE STATUS: LOCKED, all Option A):**
  - A3-1: New `services/db/display_toggles.py` owns `DisplayToggleService`
    (`get_effective`/`set_user_toggle`/`set_forced`/`get_global_defaults`/`set_global_defaults`).
  - A3-2: Precedence forced > user > global > catalog, in exactly one place.
  - A3-3: Settings key imported from `settings.py` (`DISPLAY_TOGGLE_DEFAULTS_KEY`,
    J0.2 registry-backed) — no new settings-key constant.
  - A3-4: Toggles only; no `{card_type}_mode*` keys.
  - A3-5: `services/db/__init__.py` re-exports same public names; zero caller churn.
- **Coordination with J0.2:** J0.2 (`refactor(settings): canonical settings-key
  registry`, PR #3022899) merged before J-A3 and kept `DISPLAY_TOGGLE_DEFAULTS_KEY`
  wired to `SETTINGS_KEYS`. J-A3 consumes it by import (single definition).
- **Independent review (hamzaboon-reviewer):** 5 WARNINGs (F1–F5) + 2 SUGGESTIONs
  (F6/F7) all addressed before commit — F1 interface alignment, F2 seam-guard
  registration, F3 module-change docs (AGENTS.md §3 + SEAMS.md #18), F4
  consolidation-locking test, F5 `DB_PATH` restore in tearDown.
- **Kilo Code Review:** "No Issues Found | Recommendation: Merge". CI green (3.10/3.13).

## Post-merge

- Worktree `.worktrees/refactor-display-toggle-store` removed.
- Parallel claim `refactor/display-toggle-store` (seam "Telegram UI -> User Domain")
  released from `.git/parallel-work-claims.json` (2 claims remain: callback-router, token-counter).
- No remaining jobs in the DB track.
