---
name: plan-card-modes
description: Admin-configurable staged/immediate card mode for first-exposure and review cards, with 3-level precedence (user → plan → admin-global → built-in default).
created: 2026-08-15
base_commit: cd35c5a
branch: TBD (feat/card-modes-fe-review)
status: planned
---

STATE: phase 1/1 — status: planned — focus: contract final confirmation pending, then T1 DB core → T2-T3 flows → T4-T6 UI → T7 tests/docs

## Contract (GATE: PENDING owner final confirmation — owner selected "Adjust the contract", 2026-08-15; no concrete changes supplied yet)

Locked so far (owner choices 2026-08-15):

- **Rule 1 — FE card flow:** first-exposure cards use the 2-stage reveal pattern (front stage via the same randomized prompt engine as due cards + «کارت جدید ✨» badge + reveal → toggle-based full card + FE grade grid). Default `staged`.
- **Rule 2 — Review card mode:** parallel `staged`/`immediate` switch for non-FE cards (`staged` default; `immediate` = full card + grade grid, no reveal).
- **Rule 3 — Renderer:** revealed cards (both types) render via `format_srs_back_stage` with the user's display toggles → example translations follow the user's setting, matching due/query cards.
- **Rule 4 — Precedence:** single resolver `resolve_card_mode(user_id, card_type)` → user override → plan value → admin-global → built-in `staged`. Unknown stored values fall through. Deep module in `services/db/users.py`.
- **Rule 5 — Per-plan:** FE + review modes as two fields in the admin plan wizard (`admin_plans.py`).
- **Rule 6 — Per-user + gating:** user-facing controls for both card types; each card type's control availability (`all` vs `premium`) is an admin setting, default `premium`.
- **Design decisions (owner 2026-08-15):** per-user control gating is admin-configurable per card type separately; per-plan mode added to the plan wizard. Feature ships per `codebase-design` (deep resolver module) and TDD.

## Data model

- `users.first_exposure_mode TEXT`, `users.review_mode TEXT` (NULL → fall through)
- `plans.first_exposure_mode TEXT`, `plans.review_mode TEXT` (NULL → fall through)
- global settings keys: `first_exposure_mode`, `review_mode` (default `staged`); `first_exposure_mode_gate`, `review_mode_gate` (default `premium`)
- Canonical enums (single registry): `CARD_TYPES = ("first_exposure", "review")`, `CARD_MODES = ("staged", "immediate")`, gate values `("all", "premium")` — live in `services/db/users.py`

## Tickets

### T1 — DB schema + canonical registry + accessors + resolver (deep module core)
- **Backend:** `init_db` migrations (`PRAGMA table_info` + `ALTER TABLE ADD COLUMN`, schema.py:287-311) for the 4 columns on **both** fresh CREATE and upgraded DBs; `CARD_TYPES`/`CARD_MODES`/gate constants; `upsert_plan` + `_PLAN_COLUMNS` extended (plans.py); accessors `set_user_card_mode`, `set_plan_card_mode`, global via `set_setting`; **deep resolver** `resolve_card_mode(user_id, card_type, row=None)` and `resolve_card_mode_gate(card_type)` in `services/db/users.py` (mirrors `get_display_toggles` users.py:38).
- **DB interactions:** writes via `BEGIN IMMEDIATE`; all DB work completes before any `await`; unknown stored modes fall through (no crash).
- **Tests:** `tests/test_db_migrations.py` (fresh + upgraded), `tests/test_migration_guards.py`, resolver precedence/fall-through/validation unit tests, canonical-registry consistency test (mirrors `test_config.py` toggle-fields test).
- **Acceptance:** resolver returns `staged`/`immediate` by the full precedence; a corrupt stored value falls through; migrations idempotent on fresh + upgraded DBs.

### T2 — FE staged flow (render + reveal widening + immediate mode)
- **Frontend:** `study_handler._build_card_text_and_keyboard` FE branch consults `resolve_card_mode(user_id, "first_exposure")`:
  - `staged`: `format_srs_front_stage` + `NEW_CARD_BADGE` + `get_srs_front_keyboard` (reveal) + stash `prompt_type_`/`card_shown_at_`;
  - `immediate`: `format_srs_back_stage` + `get_first_exposure_keyboard` directly.
- **Reveal:** `srs_handler._handle_srs_reveal` widened to accept `first_exposure` nodes (active-session node validation kept) → `format_srs_back_stage` + `get_first_exposure_keyboard`.
- **DB:** no new writes; reads `resolve_card_mode`.
- **Tests:** unit + `tests/test_integration/test_*_flow.py` FE staged (front → reveal → grades) and FE immediate flows.
- **Acceptance:** new cards reveal in 2 stages by default; example translations shown per user toggle (Rule 3); immediate mode renders full card + grades.

### T3 — Review card mode
- **Frontend:** review branch consults `resolve_card_mode(user_id, "review")`: `staged` = today's behavior; `immediate` = `format_srs_back_stage` + `get_review_keyboard` directly (no front/reveal, no prompt stash).
- **Tests:** unit + integration review immediate flow.
- **Acceptance:** review cards honor the mode; staged path unchanged.

### T4 — Admin-global UI (modes + gates)
- **Frontend:** two rows + two gates in `admin.py` `_show_settings` (mirror `phonetics:` pattern admin.py:202-223); callbacks `admin:fe_mode:set:*`, `admin:review_mode:set:*`, `admin:fe_gate:*`, `admin:review_gate:*`; keyboards in `config/keyboards.py`.
- **DB:** global `set_setting` writes.
- **Tests:** handler tests + `tests/test_wiring.py` for the 4 prefixes.
- **Acceptance:** admin flips default mode and gate; takes effect for users who have no override.

### T5 — Plan-wizard fields
- **Frontend:** add `first_exposure_mode`, `review_mode` to `PLAN_WIZARD_FIELDS`/LABELS/GROUP_HEADERS + `_validate_plan_wizard_value` accepting `staged`/`immediate` (admin_plans.py).
- **DB:** `upsert_plan` extended; plan CRUD tests updated.
- **Tests:** wizard field unit tests + integration.
- **Acceptance:** plan wizard edits persist per-plan modes.

### T6 — Per-user controls (gated)
- **Frontend:** two settings-menu entries in `handlers/user.py`; gate check via `resolve_card_mode_gate(card_type)` instead of hardcoded premium (user.py:257); callbacks `settings:fe_mode:set:*`, `settings:review_mode:set:*`.
- **DB:** `set_user_card_mode` writes.
- **Tests:** handler tests (gate=all vs gate=premium) + wiring.
- **Acceptance:** control availability follows the admin gate per card type.

### T7 — Wiring guards, integration tests, docs
- **Tests:** `tests/test_wiring.py` all new prefixes; full `tests/test_integration/` FE/review flows incl. admin→user session effect; `tests/test_dead_code_guard.py` no removals.
- **Docs:** update `TICKETS.md`, `session/index.md`, plan STATE after each step; `ROADMAP.md`/`project_status.json`/dashboard per §2/§8 when shipped.
- **Acceptance:** full §6 validation green; issue evidence recorded.

## Blocked Questions
- [2026-08-15] Contract final confirmation: owner selected "Adjust the contract" then requested the design/tickets first. Decision: pending owner's concrete changes. Do NOT begin implementation until `GATE STATUS: LOCKED`.
- [2026-08-15] Seam note: seam 6 (`handlers/srs_handler.py`) was held by PR #356 (`fix/srs-front-hint-leak`) — **MERGED 2026-08-15 (`233534d`), claim released; seam 6 now free.** No longer blocking.

## Known edges
- Admin flipping a mode mid-session: a stale reveal button still renders the back stage safely (no crash, no orphan card) — documented, acceptable.
- Zero AI calls; no token/cost impact.