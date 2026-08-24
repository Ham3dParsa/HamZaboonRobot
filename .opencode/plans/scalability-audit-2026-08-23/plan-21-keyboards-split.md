STATE: complete — merged 2026-08-24 #486 702947e (c4b8cca Kilo fix)

Evidence: keyboards split 5 files (constants+common+lang+srs+admin+__init__), tests wiring 24 passed, ruff clean → F811 fix in c4b8cca + missing facade exports DISPLAY_TOGGLE_FA_LABELS/display_toggle_confirm_keyboard/user_display_toggles_keyboard; CI label+test(3.10/3.13)+ram-gate pass, Kilo No Issues (2877h) merged squash 702947e, worktree a-05 removed, claim released

# Plan 21 — god-modules split keyboards first (Session A)

**Ticket:** #21 `god-modules` — `config/keyboards.py:1067` (plus `schema.py:1110`, `bot.py:1211` deferred). Decision: **keyboards first** (owner 2026-08-23).
**Seam:** `config/keyboards.py` — claimed R21-kbd.
**Worktree:** `.worktrees/a-05` branch `refactor/split-keyboards` from d786521
**Depends:** none — A-22/A-24 done, Q/S/P released, only `docs/fast-audit-cleanup2` claim remains (no overlap).

## CONTRACT LOCK TEMPLATE

Rule R1 — Split keyboards first:
Decision: Split `config/keyboards.py:1067` into `config/keyboards/` package per domain
Option Chosen: A — keyboards first (owner: keyboards first)
Alternatives Rejected: B schema first — would touch DB seam still hot; C bot first — more churn
Trade-offs: keyboards is pure UI, no DB/Telegram imports, safest first split, bounded
Owner Confirmation: keyboards first (2026-08-23)
GATE STATUS: LOCKED

Rule R2 — Package layout:
Decision: `config/keyboards/__init__.py` thin facade re-exporting, `config/keyboards/admin.py` (admin panel, AI presets, cost), `config/keyboards/srs.py` (review keyboards), `config/keyboards/lang.py` (lang/goal/level), `config/keyboards/common.py` (main_menu, awaiting)
Option Chosen: A — package + facade (keeps `from config.keyboards import X` working, deletes bodies from old file in same PR per route-delete)
Alternatives Rejected: B single split file — still large; C keep old + new duplicate — violates single-source
Trade-offs: imports unchanged for callers, split tested via wiring guard
Owner Confirmation: keyboards first (implies package layout per skill)
GATE STATUS: LOCKED

GATE STATUS: LOCKED (all rules)

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Keyboard builders | `config/keyboards.py` 1067 lines | split into package, `__init__.py` re-exports |
| Callers | `bot.py`, `handlers/*`, `config/__init__.py` imports | keep import path `config.keyboards` (facade) |
| Tests | `tests/test_wiring.py` scan targets `config/keyboards` | update scan target to package dir |
| SEAMS.md | `config/keyboards.py` seam | update to `config/keyboards/__init__.py` + submodules |

## Execution
1. Create `config/keyboards/` package, move builders per domain
2. Keep `config/keyboards.py` → `config/keyboards/__init__.py` facade (delete bodies)
3. pytest wiring + single_source + ruff + diff-check
4. claim timestamp each commit, push PR, Kilo loop (120s)

## Tickets trace
- TICKETS.md #21 → this plan (keyboards phase); #21 remaining schema+bot phases deferred
