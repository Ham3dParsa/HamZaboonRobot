---
name: plan-db-track
description: DB track of architecture-deepening audit — transaction seam (J-A1), plan-semantics (J-A2), display-toggle store (J-A3).
created: 2026-08-16
base_commit: 0b086b5
branch: refactor/transaction-seam (merged #371); refactor/plan-semantics (merged #372); refactor/display-toggle-store (merged #377)
status: completed
---

STATE: phase J-A3/3 — status: DONE — J-A1 (#371), J-A2 (#372), J-A3 (#377) all MERGED; DB track COMPLETE (2026-08-17)

## Locked contract (owner-confirmed)
- **J-A1 (R1) — LOCKED, MERGED:** `transaction()` seam in `services/db/schema.py`; replace 61 raw `BEGIN IMMEDIATE` write-sites across 9 db modules (not schema migration's own). No await in any `with transaction()` block. PR #371 merged (merge commit `0b086b5`).
- **J-A2 (R5) — LOCKED (Option A):** move plan semantics into `services/db/plans.py`: add `plan_spec(name)`, `is_premium(name)`, `effective_plan(name, bypass)`. `config/__init__.py` seven accessors become thin delegates; remove hardcoded free fallback so `DEFAULT_PLANS` in `plans.py` is the single quota source.
- **J-A3 (R3) — MERGED (PR #377, squash `436ffd2`), 2026-08-17:** `DisplayToggleService` store. Implemented as `services/db/display_toggles.py`; `users.py`/`settings.py` remain thin delegates; `__init__.py` re-exports unchanged public names (zero caller churn). Consumed J0.2's `DISPLAY_TOGGLE_DEFAULTS_KEY` by import (single-source, registry-backed). Claim `Telegram UI -> User Domain` (SEAMS.md #7) released post-merge.

## Implementation & evidence (J-A2)
- `services/db/plans.py`: added `plan_spec` (get_plan → DEFAULT_PLANS["free"] fallback, no residual hardcoded quota dict), `is_premium`, `effective_plan` (bypass→"gold"; unknown→"free"). Lazy `from config import PLANS/PREMIUM_PLANS` inside functions to avoid import cycle.
- `config/__init__.py`: `_plan_spec`/`effective_plan` delegate to `plans.plan_spec`/`plans.effective_plan`; removed hardcoded free fallback. Reviewer-flagged dead `config.is_premium` REMOVED (per contract, is_premium lives only in plans.py).
- `tests/test_plan_semantics.py`: 5 tests (DB read, unknown fallback, inactive fallback, is_premium membership, effective_plan). `pytest tests/test_plan_semantics.py tests/test_config.py` → 15 passed.
- Validation: `pytest tests/ -n 14` → **1046 passed, 175 subtests**; `compile_all.py` exit 0; `ruff F821/F811` clean; `generate_dashboard.py` ok; `git diff --check` clean. (One intermittent xdist atexit guard warning observed once; two subsequent full runs clean — not a deterministic regression.)
- Independent reviewer: no confirmed findings after fixes (removed config.is_premium, dropped residual hardcoded fallback, added trailing newline).
- Worktree rebased onto `origin/main` (0b086b5, includes merged J-A1) after J-A1 merge; stash conflict in `plans.py` resolved (kept upstream `transaction()` form).

## Next steps
1. J-A2: MERGED (#372, merge commit `b7a3862`); `Persistence` claim for `refactor/plan-semantics` released; worktree removed. ✓
2. J-A3: MERGED (#377, squash `436ffd2`); `Telegram UI -> User Domain` claim released; worktree removed. ✓ **DB track COMPLETE.**

## Session scope note (2026-08-17 — READ ME)
This plan covers ONLY the 11-job architecture-deepening **roadmap** DB track: J-A1 (R1), J-A2 (R5), J-A3 (R3). All three are merged → this session is DONE.

The source audit `docs/audit/Deepening/2026-08-16-db-domain-consolidated.md` lists a **broader backlog** beyond this 11-job plan: R2, R6, R7, R8, R9, R10, R11, plus BUGS B1–B4 and BOTTLENECKS BN1–BN4 (e.g., the global `RLock` serialization BN1 was NOT removed — only `transaction()` was unified in J-A1; `due_words` write-in-read B3/BN4, unbounded `preset_hourly_usage` B2, sync-DB-on-event-loop B4, composite index BN2, cost/preset listing BN3, `$ENV` resolution B1, `normalize_word` R2, `ai_presets` registry R6, quota helper R7, settings upsert R8, `CardModeService` R9, `__init__.py` facad split R10, key/due/app_today integration R11). These remain OPEN and are **out of scope** of this session; they need their own contract-lock gates and PRs.

## Coordination boundary with Session B (J0.2) — recorded 2026-08-16
- **J0.2 owns** (Track B, pending owner "proceed"): canonical `SETTINGS_KEYS` registry + `settings_key()` accessor + `validate_settings_keys()` (soft-warn) in `config/catalog.py`, mirroring J0.1's `CATALOG_NAMESPACES`. It pulls `display_toggle_defaults` (currently a local literal `DISPLAY_TOGGLE_DEFAULTS_KEY` in `services/db/settings.py`) into `SETTINGS_KEYS`, and centralizes `{card_type}_mode`/`{card_type}_mode_gate` keys.
- **J-A3 consumes (post-merge)** via `settings_key("display_toggle_defaults")` and the `{card_type}_mode*` registry entries. J-A3 must NOT introduce any new settings-key constant string.
- **Surface findings (from code read):** global display-toggle defaults = settings key `display_toggle_defaults` (JSON blob); **per-user toggles are `users` table JSON columns** (`display_toggles`, `display_toggles_forced`), NOT settings keys. Card modes are `users.{card_type}_mode`/`{card_type}_mode_gate` columns. So J-A3's per-user storage stays as user-table columns — no new settings-key constants needed there; only the global-defaults key is shared with J0.2.
- **Frozen-contract path:** Session B offered to pre-share the exact `SETTINGS_KEYS` schema so J-A3's consumption layer can be designed against a frozen contract before J0.2 merges. Session A accepted (option b); will run the J-A3 contract-lock gate (R3) against the frozen schema but will NOT implement/merge until J0.2 lands AND owner re-confirms the PENDING J-A3 gate.

### Frozen SETTINGS_KEYS schema (from Session B, 2026-08-16) — authoritative once J0.2 merges
Lives in `config/catalog.py` beside `CATALOG_NAMESPACES`. Accessors: `settings_key(name) -> dict` (KeyError on unknown, fail-fast like `catalog_namespace`); `validate_settings_keys()` soft-warns. `EPHEMERAL_SETTINGS_PATTERNS = [r"^sessions_used_", r".*_sentinel$"]`.

Keys (stable): `tts_access`, `log_level`, `user_activity_log`, `usd_to_toman_rate`, `ai_primary_preset`, `ai_fallback_preset`, `ai_consecutive_failures`, `ai_fallback_active`, `ai_fallback_since`, `llm_input_cost_usd_per_million`, `llm_output_cost_usd_per_million`, `ai_model`, `display_toggle_defaults` (`{"type":"json","default":DISPLAY_TOGGLE_DEFAULTS,"scope":"global"}`), plus pattern entries `{card_type}_mode` / `{card_type}_mode_gate` (`{"type":"str","default":DEFAULT_CARD_MODE / DEFAULT_CARD_MODE_GATE,"scope":"global","pattern":True}`).

#### Session B answers to J-A3's 4 design questions
1. `display_toggle_defaults` = `{"type":"json","default":DISPLAY_TOGGLE_DEFAULTS,"scope":"global"}`; JSON string in settings under key `"display_toggle_defaults"`.
2. Card-mode keys: per-user override (`users.{card_type}_mode`) + per-plan (`plans.{card_type}_mode`) are columns; the **admin-global default** is a settings key (`users.py` reads `get_setting(f"{card_type}_mode","")`/`..._gate`). J0.2 registers them as pattern entries. **J-A3 touches card-mode settings keys ONLY if it also manages admin-global card modes; otherwise it ignores them.** Either way no new key constants.
3. `settings_key(name)->dict` (KeyError on unknown). For display toggles J-A3 **keeps using existing `get_display_toggle_defaults()` / `set_display_toggle_defaults()`** in `services/db/settings.py` (they do default-merge + `DISPLAY_TOGGLE_FIELDS` validation a generic reader can't safely replicate). J0.2 only registers `display_toggle_defaults` for validation; read/write helpers stay. Generic `read_setting(name)` (typed/JSON-decode) exists for plain scalars — J-A3 doesn't need it for the toggle blob.
4. **Non-goal boundary (agreed):** J-A3 introduces ZERO new settings-key constant strings. Consumes `display_toggle_defaults` via `get_display_toggle_defaults()` (and `settings_key("display_toggle_defaults")` only if it needs the literal key string). **Do NOT reference the local `DISPLAY_TOGGLE_DEFAULTS_KEY` constant in `settings.py`** — J0.2 will replace it with the registry reference. Per-user toggles stay as `users.display_toggles` / `users.display_toggles_forced` JSON columns (unchanged). Seam rule: J0.2 is the only PR editing `config/catalog.py`'s settings surface; J-A3 consumes, never writes new key constants.

#### J-A3 implementation rule (derive now, apply post-J0.2)
- DisplayToggleService (R3) consolidates display-toggle read/write: global defaults via `get_display_toggle_defaults()`/`set_display_toggle_defaults()`; per-user via `users.display_toggles`/`display_toggles_forced` columns (existing `get_display_toggles`/`set_display_toggle`/`set_display_toggle_forced`).
- After J0.2 merges, any literal `"display_toggle_defaults"` reference in J-A3 code must come from `settings_key("display_toggle_defaults")`, never the removed `DISPLAY_TOGGLE_DEFAULTS_KEY`.
- No new constants in `config/catalog.py` settings surface.

### J-A3 GATE STATUS: LOCKED (owner confirmed "all A's locked, per /codebase-design", 2026-08-16)
Validated against deep-module design (codebase-design skill): small interface (`get_effective`, `set_user_toggle`, `set_forced`, `set_global_defaults`) over deep impl (precedence merge + JSON + validation + 32-site consolidation); passes deletion test (complexity would reappear across callers); locality for adding a toggle. Matches report R3 exactly.

| Rule | Decision | Option | Alternatives rejected | GATE |
|---|---|---|---|---|
| A3-1 | New `display_toggles.py` owns service | A | B status-quo, C config-owner | LOCKED |
| A3-2 | Precedence forced>user>global>catalog | A | B different precedence | LOCKED |
| A3-3 | Consume J0.2 helpers, no new constants | A | B bypass helpers | LOCKED |
| A3-4 | Toggles only, no card-mode keys | A | B expand scope | LOCKED |
| A3-5 | Re-export delegates, no 32-site churn | A | B rename all | LOCKED |

Owner Confirmation: "if these are what the reports suggest and are the best options, then all A's can be locked, per /codebase-design."

### CLAIM BLOCKED — parallel-work-guard overlap (HALT, do not acquire)
- J-A3 target seam per plan: **"Telegram UI -> User Domain" = SEAMS.md #7**.
- Current claimants of seam #7: **`feat/per-language-goals`** (active) AND **`fix/word-query-timeout-race`** (STALE — note says merged #358, its #7/#17 claim should have been removed but wasn't).
- Per parallel-work-guard §10.5: overlap = warn + explicit owner decision; never silent proceed. Therefore the `Telegram UI -> User Domain` claim is **NOT acquired** until owner decides.
- Mitigant: Rule A3-5 (re-export delegates, no caller churn) means J-A3 may not actually edit the user-domain handler surface, so the seam claim may be unnecessary. Owner decision required: (a) proceed anyway + coordinate with feat/per-language-goals owner, (b) wait until seam #7 releases, or (c) confirm J-A3 needs no seam claim (re-export-only).
- Also: J-A3 impl is gated on J0.2 merging regardless, so the claim question has time to resolve.

## Blocked Questions
- [2026-08-16] J-A3: owner chose "Leave A3 pending, report". RESOLVED 2026-08-17 — owner re-confirmed "all A's locked" after J0.1 (#370) + J0.2 (#376/#378) merged; implemented and merged as #377.