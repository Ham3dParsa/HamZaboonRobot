---
name: plan-card-modes
description: Admin-configurable staged/immediate card mode for first-exposure and review cards, with 3-level precedence (user → plan → admin-global → built-in default).
created: 2026-08-15
base_commit: cd35c5a
branch: feat/card-modes-t1-db-core (PR 1/4 = T1)
status: locked
---

STATE: phase 1/1 — status: locked — T1 (DB core) MERGED (#361, `d5a6652`); T2+T3 MERGED (#362, `4d5ecff`), seams 5+6 released; delivery PR 3/4 (T4+T5 admin, seam 8) and PR 4/4 (T6+T7 user, seam 7) pending

## Contract (GATE: LOCKED — owner confirmed 2026-08-15; "adjustment" was process-only: design per the right skills + merge PR #356, both satisfied)

Locked rules (owner choices 2026-08-15):

- **Rule 1 — FE card flow:** first-exposure cards use the 2-stage reveal pattern (front stage via the same randomized prompt engine as due cards + «کارت جدید ✨» badge + reveal → toggle-based full card + FE grade grid). Default `staged`.
- **Rule 2 — Review card mode:** parallel `staged`/`immediate` switch for non-FE cards (`staged` default; `immediate` = full card + grade grid, no reveal).
- **Rule 3 — Renderer:** revealed cards (both types) render via `format_srs_back_stage` with the user's display toggles → example translations follow the user's setting, matching due/query cards.
- **Rule 4 — Precedence:** single resolver `resolve_card_mode(user_id, card_type)` → user override → plan value → admin-global → built-in `staged`. Unknown stored values fall through. Deep module in `services/db/users.py`.
- **Rule 5 — Per-plan:** FE + review modes as two fields in the admin plan wizard (`admin_plans.py`).
- **Rule 6 — Per-user + gating:** user-facing controls for both card types; each card type's control availability (`all` vs `premium`) is an admin setting, default `premium`.
- **Design decisions (owner 2026-08-15):** per-user control gating is admin-configurable per card type separately; per-plan mode added to the plan wizard. Feature ships per `codebase-design` (deep resolver module) and TDD.

## Delivery strategy (owner-approved 2026-08-15)

Per-ticket commits inside **4 reviewable PRs** (each independently mergable):

| PR | Tickets | Seams | Branch | Content |
|---|---|---|---|---|
| 1/4 | T1 | 1 | `feat/card-modes-t1-db-core` | DB schema + canonical registry + accessors + `resolve_card_mode`/`resolve_card_mode_gate` |
| 2/4 | T2+T3 | 5, 6 | `feat/card-modes-t2-t3-render` | FE staged flow + review mode render branches |
| 3/4 | T4+T5 | 8 | `feat/card-modes-t4-t5-admin` | Admin-global modes/gates UI + plan-wizard fields |
| 4/4 | T6+T7 | 7 (coordinated with `feat/per-language-goals`) | `feat/card-modes-t6-t7-user` | Per-user gated controls + final tests/docs |

No module refactors — every change extends existing modules in place. Each PR carries its own tests + wiring updates (T7's integration/docs finish last).

## Data model

- `users.first_exposure_mode TEXT`, `users.review_mode TEXT` (NULL → fall through)
- `plans.first_exposure_mode TEXT`, `plans.review_mode TEXT` (NULL → fall through)
- global settings keys: `first_exposure_mode`, `review_mode` (default `staged`); `first_exposure_mode_gate`, `review_mode_gate` (default `premium`)
- Canonical enums (single registry): `CARD_TYPES = ("first_exposure", "review")`, `CARD_MODES = ("staged", "immediate")`, gate values `("all", "premium")` — live in `services/db/users.py`

## Tickets

### T1 — DB schema + canonical registry + accessors + resolver (deep module core)
- **Backend:** `init_db` migrations (`PRAGMA table_info` + `ALTER TABLE ADD COLUMN`, schema.py:287-311) for the 4 columns on **both** fresh CREATE and upgraded DBs; `CARD_TYPES`/`CARD_MODES`/gate constants; `set_plan_card_mode` targeted UPDATE in `users.py` (deep module; **`upsert_plan`/`_PLAN_COLUMNS` deliberately NOT extended here** — edit preserves modes, new plans get NULL fall-through; wizard integration lands in T5); accessors `set_user_card_mode`, `set_plan_card_mode`, `set_global_card_mode`, `set_card_mode_gate`; **deep resolver** `resolve_card_mode(user_id, card_type, row=None)` and `resolve_card_mode_gate(card_type)` + `card_mode_available(user_id, card_type, row=None)` in `services/db/users.py` (mirrors `get_display_toggles` users.py:38 / `should_show_pronounce` gate pattern).
- **DB interactions:** writes via `BEGIN IMMEDIATE`; all DB work completes before any `await`; unknown stored modes fall through at every level (no crash).
- **Tests:** `tests/test_db_migrations.py` (fresh + upgraded), `tests/test_migration_guards.py`, `tests/test_card_modes.py` resolver precedence/fall-through/validation unit tests, canonical-registry consistency test.
- **Acceptance:** resolver returns `staged`/`immediate` by the full precedence; a corrupt stored value at any level falls through; migrations idempotent on fresh + upgraded DBs; `upsert_plan` edit preserves modes / new plans have NULL modes (reviewer S3).

### T2 — FE staged flow (render + reveal widening + immediate mode)
- **Frontend:** `study_handler._build_card_text_and_keyboard` FE branch consults `resolve_card_mode(user_id, "first_exposure")`:
  - `staged`: `format_srs_front_stage` + `NEW_CARD_BADGE` + `get_srs_front_keyboard` (reveal) + stash `prompt_type_`/`card_shown_at_` + pop `revealed_` (re-arm);
  - `immediate`: `format_srs_back_stage` + `NEW_CARD_BADGE` + `get_first_exposure_keyboard` directly (owner lock 2026-08-15: badge stays visible in immediate mode → `format_srs_back_stage` gained optional `badge` param).
- **Reveal:** `srs_handler._handle_srs_reveal` widened to accept `first_exposure` nodes (active-session node validation kept) → `format_srs_back_stage` + `get_first_exposure_keyboard`.
- **DB:** no new writes; reads `resolve_card_mode`; façade `services/db/__init__.py` re-exports the card-mode symbols (reviewer S6, first consumer T2).
- **Tests:** unit + `tests/test_integration/test_srs_staged_reveal_flow.py` FE staged (front → reveal → FE grades → advance) and FE immediate flows.
- **Acceptance:** new cards reveal in 2 stages by default; example translations shown per user toggle (Rule 3); immediate mode renders full card + grades. ✅ done 2026-08-15 (full suite 1020 passed).

### T3 — Review card mode
- **Frontend:** review branch consults `resolve_card_mode(user_id, "review")`: `staged` = today's behavior; `immediate` = `format_srs_back_stage` + `get_review_keyboard` directly (no front/reveal, no prompt stash).
- **Tests:** unit + integration review immediate flow.
- **Acceptance:** review cards honor the mode; staged path unchanged. ✅ done 2026-08-15 (full suite 1020 passed).

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
- A deactivated plan's stored mode still applies for its users (`get_plan` has no active filter, matching `should_show_pronounce`) — consistent, recorded (reviewer S7).
- `services/db/__init__.py` façade does not re-export the new card-mode symbols yet; add re-exports when the first frontend consumer (T2) lands (reviewer S6).
- Zero AI calls; no token/cost impact.