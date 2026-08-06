---
name: db-driven-plan-spec
description: Admin-editable DB-driven plan specs (5 plans, query quota, sessions, cards) replacing hardcoded plan config
created: 2026-08-05
base_commit: 553084d
branch: feat/db-driven-plan-spec
status: in-progress
---

# Plan: DB-Driven Admin-Editable Plan Spec

## Locked Contract Rules (all GATE STATUS = LOCKED)

| Rule | Decision |
|---|---|
| R1 | New DB `plans` table (id, name PK, display_name, price, query_quota, max_sessions, cards_per_session, is_active, sort_order); extensible columns later |
| R2 | Exactly 5 plans: free/bronze/silver/gold/emerald; drop platinum; gold stays owner-bypass code name |
| R3 | Per-session card count and daily session budget come fully from DB (`cards_per_session`, `max_sessions`) |
| R4 | Daily word-query quota comes from DB `query_quota` (2/4/7/12/20); env vars removed |
| R5 | Admin UI reuses full_edit wizard pattern (`ai_preset:full_edit:*` style) |
| R6 | Price stored + admin display only; no billing/payment logic |
| R7 | Plan lifecycle: edit + deactivate (is_active=0), no hard delete |
| R8 | Drop FREE_/SILVER_/GOLD_DAILY_CARD_LIMIT and *_DAILY_WORD_QUERY_LIMIT env vars; DB seed is sole source |

## New plan specs (per day, Tehran 00:00-23:59)

| plan | display | sessions/day | cards/session | query quota |
|---|---|---|---|---|
| free | رایگان | 2 | 3 | 2 |
| bronze | برنزی | 3 | 3 | 4 |
| silver | نقره‌ای | 3 | 5 | 7 |
| gold | طلایی | 4 | 7 | 12 |
| emerald | زمردی | 5 | 9 | 20 |

## Phase/Step Status

| Phase | Description | Status |
|---|---|---|
| 0 | Branch + plan persistence | complete |
| A | plans table + db/plans.py + seeds + migration tests | planned |
| B | config DB-backed plan readers, remove env limits | planned |
| C | scheduling max_sessions + session sizing from DB | complete |
| D | admin plan-manager wizard callbacks + keyboards | complete |
| E | wiring/integration/config/scheduling tests + docs | complete |
| F | Independent Review + full validation + commit + PR | in-progress |

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes (new) | `admin:plan_list`, `admin:plan_manage`, `plans:*` (list/edit/next/skip/cancel/save/set_active) | update |
| Router branches | bot.py callback_router + handlers/admin.py sub-router + awaiting handler | update |
| Keyboard builders | config/keyboards.py plan-manager menus | update |
| DB tables/columns/functions | NEW `plans` table; NEW services/db/plans.py; re-export in db/__init__.py; seed in init_db() | add |
| Config constants | PLANS, PREMIUM_PLANS, _user_plan_label, effective_plan | update |
| Quota functions | daily_card_count_for_plan, daily_word_query_limit_for_plan, effective_daily_allowance | update |
| Scheduling | services/scheduling.py PLAN_SESSION_CONFIG -> DB max_sessions | update |
| Session sizing | assembly.py max_nodes + study_handler.py:151 -> DB cards_per_session | update |
| DB validation | services/db/users.py:255 set_plan validates against DB plan names | update |
| TTS/premium gates | bot.py, user.py, study_handler.py PREMIUM_PLANS (code set {silver,gold,emerald}) | update |
| Tests | test_config.py, test_scheduling.py, test_db_migrations.py, test_wiring.py, integration | update |
| Docs | ROADMAP.md, issues, project_status.json + dashboard, AGENTS.md §3 | update |

## Update Log

- 2026-08-05: Contract locked (Rules 1-8). Branch `feat/db-driven-plan-spec` created from origin/main @553084d. Plan persisted.
- 2026-08-05: Phase A-D implemented. DB plans table + db/plans.py + seeds (tests passing). config DB-backed plan readers, env limits removed. scheduling/session sizing from DB. Admin plan-manager wizard (`admin:plans:*` callbacks, keyboards, awaiting `admin_plan_full_edit:*`). `admin_set_plan` validates against DB `valid_plan_name`. Phase E (wiring/integration tests + docs) in progress.
- 2026-08-05: Phase E complete. Wiring guard passes (8 tests). New integration suite `tests/test_integration/test_plan_manager_flow.py` (8 tests). Docs: ROADMAP env quotas -> DB plans; session sizing decisions; .env.example plan-limits removed; AGENTS.md §3 plans.py; callback-wiring map. GitHub Issue #257 created (feat(plans) DB-driven plan specs). project_status.json phase-5 updated + dashboard regenerated. Phase F (independent review + validation + commit + PR) in progress.
- 2026-08-06: Phase F independent review. Fixed reviewer findings: F1 (critical) plan-wizard text-input awaiting parse at handlers/admin.py was dead (`parts[2].rsplit(":",1)` on bare index) — now `split(":",3)` => parts[1]=name, parts[2]=idx; added regression test `test_plan_wizard_text_input_dispatches_through_awaiting`. F2 (medium) two stale tests/test_study_handler.py assumed free=1 session/day — updated to free=2. F3 (low) `plan_full_edit` state leak on flow:back/cancel — bot.py now pops it. Owner approved fix to the identically-broken pre-existing `ai_preset_full_edit:` text-input branch (also parts[2].rsplit bug) — fixed same way. Non-tracking note: `effective_daily_allowance` (config:182) imported but never called (pre-existing dead code, out of scope). Full suite 389 tests pass; ruff F821/F811 clean on tracked code (untracked tools/Fsrs_simulation archive files have Python 3.12-only syntax errors, not in CI).
