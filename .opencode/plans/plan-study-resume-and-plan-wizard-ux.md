# Plan — Study Resume Recovery + Plan-Wizard UX

- Status: in-progress
- Branch: `feat/study-resume-and-plan-wizard-ux` (new, from latest main)
- Depends on: PR #258 (plan-spec feature) being unrelated — this is a new change
- Traces to locked Contract Lock rules R1–R5 below.

## Locked contract

Trigger: owner reported during manual testing that resuming a study session whose
original card message was deleted/lost only shows "جلسه‌ی قبلی ادامه داده می‌شه."
and no new card is sent (disaster UX). Also reported plan-wizard UX gaps (no back
button; redundant next/skip; confusing quota labels/groups). Product decision
(gate §2.4) — each rule chosen independently by owner.

| Rule | Decision | Option chosen |
|---|---|---|
| R1 | Study resume: old/inactive card message gets replaced; new card message is sent; pressing old card shows "inactive" popup then deletes that old message | Custom (owner) — deactivate old + send new + `study:inactive` popup then delete |
| R2 | Add back button to plan wizard | A (add back) |
| R3 | Make "رد کردن" = leave unchanged & advance; remove the redundant "بعدی" button | A |
| R4 | Fix wizard groups + clarify سهمیه سؤال روزانه label | A (fix groups + clarify) |
| R5 | Card "گزارش" button | B (defer — file GitHub issue) |

**CONTRACT LOCK TEMPLATE**
- Rule 1: Study resume — deactivate prior card message and send a fresh card;
  stale card's buttons are swapped to a single inactive button whose callback
  (`study:inactive`) shows the popup then deletes the stale message. Alternatives
  rejected: (A) edit-then-fallback — didn't match owner's inactivate design;
  (B) always-send-new — duplicates cards. Trade-offs: R1 inactivates via
  `edit_message_reply_markup` swap, catching `BadRequest` when the stale message is
  already deleted; no duplicate cards when stale message persists because its
  button is replaced.
- Rule 2/3: add `admin:plans:full_edit_back:{name}`; remove
  `admin:plans:full_edit_next`; "skip" leaves current DB value.
- Rule 4: group map in `PLAN_WIZARD_GROUP_HEADERS` corrected; `price` no longer
  under "❒"; add clarifying label under سهمه سؤال روزانه.
- Rule 5: defer, issue `feat(plans): add گزارش button to study cards`.
- Owner confirmation: answered gate question tool (R1–R5); R1 follow-up chose
  "Popup then delete old message".
- GATE STATUS: LOCKED

## Dependency & Wiring Map (AGENTS.md §2.4.2)

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | `study:inactive` (new); `admin:plans:full_edit_back` (new); `admin:plans:full_edit_next` (remove) | update |
| Router branch (callback_router) | bot.py add `study:inactive`; remove nothing for plans (plans sub-router) | update |
| Sub-router (admin.py `_handle_admin_callback`) | add `plans:full_edit_back:`; changemount `full_edit_next` handler | update |
| Keyboard builders | `plan_wizard_keyboard` (remove next, add back); new inactive card builder | keyboards.py update |
| Buttons constants | add inactive labels; `IBTN_FULL_EDIT_BACK` | keyboards.py |
| DB | none | keep |
| Handler funcs | `_handle_plan_wizard_back` (new); `_handle_plan_wizard_next` (now skip-only, clears pending field value); tweak `handle_study_start` resume | update |
| Imports | none removed | keep |
| Tests | `tests/test_wiring.py`, `tests/test_keyboards.py`, `tests/test_study_handler.py` resume expectations | update |
| Docs | ROADMAP (UX note), callback-wiring skill map, AGENTS.md none | update ROADMAP + skill map |
| GitHub issue | # existing plan feature; new R5 issue | file new |

## Phase / Step table

| Phase | Step | Status | Evidence |
|---|---|---|---|
| A study | add `study:inactive` route + `_handle_study_inactive` | complete | test_study_handler inactive tests |
| B study | resume: swap old card to inactive; send new card; wrap errors | complete | resume + deleted-old-card tests |
| C wizard | add back button + remove next + skip semantics | complete | wiring + integration |
| D wizard | label/group fix + per-field hints + pending-value display | complete | integration render test |
| E | wiring/dead-ref/format tests | complete | test_wiring + keyboards |
| F | file R5 issue (#259) | complete | gh issue #259 |
| G | Independent Review + validation + commit + PR | complete | review + suite (399) + PR #260 CI green |

## Update Log

- 2026-08-06: Contract locked (R1–R5). Branch `feat/study-resume-and-plan-wizard-ux` created on top of `feat/db-driven-plan-spec` (PR #258) since the wizard edits depend on the un-merged #258 code.
- 2026-08-06: Phase A–F complete. R1 study-resume inactivates old card + sends fresh card; `study:inactive` handler pops then deletes. R2 back button + R3 skip semantics (skip clears pending per owner) on `admin_plan_full_edit`. R4 labels/groups + F3 (header on all 3 quota fields) + F5 (DB + pending value display) + R3 (display header on price). R5 deferred as issue #259.
- 2026-08-06: Independent Review pass 1 (no critical bugs) applied: F1 assert inactive keyboard; F2 drop is_last; F4 view label; F8 back-at-first + skip tests. Pass 2 (no critical bugs) applied: R1 render test, R6 BadRequest-resume test, R3 price header (owner), R4 skip-clears-typed (owner). Added html.escape (F2 from pass 2), de-hardened test (F3). Full suite 399 green. #258 plan file Phase F marked complete (bookkeeping).
- 2026-08-06: Committed `ef95738` (10 files), pushed, opened PR #260 against `main` (documented stack dependency on #257/#258; merge order #258 then #260). All 3 CI checks green (label, test 3.10, test 3.13). ROADMAP Done section updated with study-wizard UX note; callback-wiring skill map updated.

## Verification
- Full validation suite (§6) green; wiring integrity + dead-reference guards pass.
- Focused tests: resume recovery (stale message deleted → new card sent, old no
  longer clickable), wizard back returns to previous field preserving other values.
- Do NOT claim CI from local; re-check against GitHub Actions.