# Plan: Financial Dashboard — Dynamic Plans + Selective Export/Import + Dynamic CAC

> STATUS: COMPLETE — all locked rules including R5 implemented, merged, reviewed.
> Scope: `tools/financial_model/financial_model_dashboard.html` only. Not related to the bot.
> Contract Lock: All 10 rules LOCKED by owner 2026-08-05. R5 rules LOCKED 2026-08-05 (all option A).
> Progress: Steps 1–12 complete. PR #251 MERGED (8a99ab5). R5 Option B implemented + reviewed PASS; PR #253 MERGED (b04a2e7). Feature fully done.

## Locked Rules (summary)

1. Plans data model: single `plans: [{id,name,nameEn,price,callsPerDay,initialCount,sharePct,notes}]` array replaces flat keys.
2. Free plan always present, fully editable in Marketing tab (price default 0, share always 0).
3. Upgrade distribution: share-based proportional (`monthlyUpgrades * sharePct/totalPaidShare`).
4. Settings tab: new section-card "Plan Pricing & Share" — price + share% sliders per paid plan (free read-only there).
5. Share% auto-balance proportional (sum stays 100%).
6. Export/Import: 5 sections in `EXPORT_SECTIONS` — `simulation` (incl. growth keys), `financial`, `aiModel`, `plans`, `marketing`. (Note: contract said 6 sections; Growth keys were merged into the `simulation` group, so the implemented count is 5.)
7. Plan notes: internal admin only, never user-facing.
8. CAC model C: keep `cacPerNewUser` field + live blended CAC display.
9. CAC default = 0.
10. `computeSeries` iterates `plans` array (single source of truth).

## Steps

### 1. DEFAULTS migration — DONE
- Flat plan keys removed (bronzeShare/silverShare/goldShare, free0…emerald0, bronzePrice…emeraldPrice, freeCallsPerDay…emeraldCallsPerDay, old `notes` object).
- `plans` array added with 5 defaults (free 0/3/1500, bronze 49000/4/150/40%, silver 199000/7/250/35%, gold 359000/12/100/15%, emerald 499000/20/50/10%).
- `cacPerNewUser: 0`.

### 2. sanitizeLoaded migration — DONE
- `bk` (number fallback) + `bks` (string fallback) helpers.
- Missing `plans` → built from old flat keys (preserves prices, counts, shares, notes); old flat keys deleted.
- Existing `plans` → schema normalized per plan; free `sharePct` forced 0; empty → DEFAULTS fallback.

### 3. EXPORT_SECTIONS constant — DONE
- 5 groups (simulation, financial, aiModel, plans, marketing) with Persian+English labels and `keys` lists.

### 4. computeSeries refactor — DONE
- `freePlan = plans.find(id==='free') || plans[0]`; `paidPlans` filter; `totalPaidShare` guard (|| 1).
- `counts` object keyed by plan id; conversion mode distributes upgrades by share; manual mode uses `initialCount`.
- Blended CAC: `cacManual > 0 ? cacManual : (adBudget>0 && paidNewSignups>0 ? adBudget/paidNewSignups : 0)`.

### 5. perTierContribution + other hardcoded tier refs → plans array — DONE
- `perTierContribution`/`paidUsersM1`/`contributionPerPaidUser` use plans + `m1.counts`.
- `costFreeUser` etc. replaced by `planCostPerUser`/`planCostTotalM1` (computed maps).
- Pie chart + dashboard table iterate plans; `COLORS[p.id] || PLAN_COLORS[i]` fallback.
- `getTrialCACPerNewUser` picks top paid plan by `callsPerDay` instead of `goldCallsPerDay`.
- `effectiveCACPerNewUser` added; drives `cacPaybackMonths`, `healthScore`, `weakIndicator`.

### 6. Settings UI: Plan Pricing & Share section-card — DONE
- New section-card with price slider (0–3,000,000) + share slider per paid plan; free read-only.
- "Plans & user counts" section iterates plans (conversion mode shows share-sum indicator).
- Auto-balance via `@input="autoBalanceShare(idx, $event.target.value)"`.

### 7. Marketing UI: Plan Management full CRUD — DONE
- `addPlan` / `removePlan` (confirm; free-deletion promotes plans[0] to free) + auto-rebalance to 100%.
- Editable name, nameEn, price, callsPerDay, share slider, notes textarea, delete button.
- Marketing summary chips: blended CAC row (`effectiveCACPerNewUser`) added.

### 8. Export/Import modals — DONE
- Inline Vue `template` modals (exportSelecting/importSelecting) INSIDE `#app` root (relocated after first placement was outside root).
- `selectedSections` checkboxes, `doExport` (downloads filtered object), `doImport` (merges only selected sections then `{...DEFAULTS, ...sanitizeLoaded(merged)}`).
- `exportJSON` retained as alias of `openExportModal` for old button compatibility.

### 9. Blended CAC — DONE
- Default 0; live blended display in Financial section + Marketing tab.

### 10. Validation — DONE
- [x] node --check on block 8 (OK, 65916 chars).
- [x] Tag balance (template/div/table/span all balanced; `hr` void false-positive).
- [x] Node functional test harness: 48 assertions on extracted sanitizeLoaded/computeSeries/getTrialCACPerNewUser/autoBalanceShare — ALL PASSED (migration + notes, share distribution, blended vs manual CAC, free-fallback, auto-balance, trial-plan selection, free-deletion guard).
- [x] git diff --check (clean).
- [x] Reviewer subagent (hamzaboon-reviewer): APPROVED after 3 fix cycles.
  - BUG-1: `autoBalanceShare` full-array-index bug → fixed by passing `p.id`.
  - GAP-1: stale `growthRateBase` export key → removed.
  - BUG-2 (owner: block free deletion): delete button hidden for free plan + `removePlan` early-return guard + `sanitizeLoaded` free-promotion.
  - BUG-3 (owner: migrate old flat keys on import): `doImport` copies flat keys + deletes `merged.plans` so the migration branch runs; try/catch added.
  - Optional (owner: all 3): pie `backgroundColor` refresh in `updateCharts`; doImport try/catch; `trialPlanName` computed replaces hardcoded «پلن طلایی» in 3 help texts.
  - BUG-A: trial-plan reduce seed `{callsPerDay:12}` acted as comparison baseline → seeded `{callsPerDay:0}`; `trialCallsPerDay` falls back to 12 only when no paid plans.
  - BUG-B: `DEFAULTS.plans` aliasing via shallow spread → `freshDefaults()` deep-clones plans for init/reset; line-1183 empty-array fallback also deep-clones.
  - Final review: APPROVE. Only pre-existing out-of-scope note: `marketingTechniques` array aliasing (unchanged from HEAD), flagged for owner as possible follow-up.

### 11. Independent Review Subagent (hamzaboon-reviewer, working model) — DONE, FAIL verdict
- Verdict: FAIL — feature mostly correct; both prior findings genuinely fixed; 1 confirmed bug + 1 boundary bug + 4 product gaps requiring owner decisions.
- BUG-1 (claimed fixed): VERIFIED — both slider call sites pass `p.id`, `autoBalanceShare` matches by id.
- GAP-1 (claimed fixed): VERIFIED — no `growthRateBase` symbol anywhere.
- BUG-2 (confirmed): `{ ...DEFAULTS }` shallow copies at `inp.value = { ...DEFAULTS }` (load ~line 1205, reset ~line 1242) share nested `plans` array with DEFAULTS; slider edits / addPlan mutate DEFAULTS.plans in place → reset() cannot restore pristine defaults and polluted "defaults" can be auto-saved. **Owner decision: FIX — deep-copy plans on load/reset.**
- BUG-3 (boundary): `autoBalanceShare` skips redistribution when `otherSum === 0` → dragging a plan leaves sum < 100. **Owner decision: when all other paid shares are 0, set changed plan to 100%.**
- Gap A (free plan deletable): **ADDRESSED in a parallel session (checked 2026-08-05)** — delete button `v-if="p.id !== 'free'"`, `removePlan` refuses free, `sanitizeLoaded` guarantees free with sharePct 0. No further action from this plan.
- Gap C: `removePlan` rebalances by equal split, not proportional. **Owner decision: scale remaining shares proportionally.**
- Gap D: trial CAC uses top paid plan with hidden floor `|| 12`. **Owner decision (custom): trial campaigns must let the user pick from actual defined plans per technique and get correct per-plan values** — i.e., add a per-technique plan selector in the technique modal and use that plan's callsPerDay (no 12 floor) in `getTrialCACPerNewUser`.
- Gap E: user-facing copy still says "پلن طلایی" (lines ~1058, 1074, 1110) while math uses top plan. **Owner decision: dynamic plan name text.** UI labels already use `{{ trialPlanName }}`; hardcoded technique descriptions still stale.

### 12. Pending implementation — DONE
- Fixes applied on 2026-08-05 (working tree, then committed on `fix/financial-dashboard-dynamic-plans`): BUG-2 `freshDefaults()` deep copy; BUG-3 `autoBalanceShare` 100% edge; Gap C `removePlan` proportional rebalance; Gap D per-technique trial plan picker (`techForm.trialPlanId`, `resolveTrialPlan`, `techniqueTrialName`, round-trip, B2 normalization); Gap E dynamic plan-name copy.
- Re-review (fresh context): PASS-WITH-NITS — B1/B2 fixed correctly, no new bugs, all rules hold; nit = two statements on one line (fixed), no automated test coverage (documented, JS harness in temp), `marketingTechniques` aliasing on first run (out of locked scope).
- Validation: node --check PASS, harness 21/21 PASS, 384 unit tests OK, compile_all PASS, ruff F821/F811 PASS (tracked files), generate_dashboard PASS, git diff --check clean.
- Committed cf88d74 (499+/174- single file), pushed, PR #251 created with write-tool body (verified clean, no BOM/BEL).
- Note: working tree also carries unrelated FSRS Phase 3a changes (bot.py, schema.py, words.py, tests, plan_quality_hardening.md) — excluded from this commit, left on branch `feat/phase-3a-daily-cards-migration`.
- Open item: R5 (CAC autocomplete = manual) still awaits owner decision before feature "fully done".

### 13. R5 (CAC display) — Option B LOCKED by owner 2026-08-05 (all four rules option A)
- Rule 1: Display-only. `effectiveCACPerNewUser` (line 1774) remains the calculation driver, unchanged. New `autoCACPerNewUser` computed always computes `adBudget / paidSignups` (0 when not computable).
- Rule 2: Show both values in BOTH places — financial section card (line 254–258) and marketing chip (line 432).
- Rule 3: When manual CAC = 0, render "دستی: —" alongside the estimate.
- Rule 4: No diff warning/highlight.
- No change to `computeSeries` internal CAC (1612–1614) or any P&L math.
- Steps: add computed → expose in return (line 1980) → update card → update chip → extend harness → node --check → git diff --check → commit + PR.
- Implementation DONE 2026-08-05: `autoCACPerNewUser` computed added (~1790-1796, independent of manual field); exposed in return (~1996); financial card now shows CAC ترکیبی / CAC دستی / CAC تخمینی از بودجهٔ تبلیغات (258-265); marketing chip adds estimate row (441); helper text reworded (266) to "این اعداد را برای بازبینی کنار هم مقایسه کنید" after reviewer nit. `effectiveCACPerNewUser` + `computeSeries` CAC untouched (manual-priority).
- Harness extended with R5 group (9 checks) — 30/30 PASS. node --check PASS. git diff --check clean. Full suite: 384 tests OK, compile_all PASS, ruff F821/F811 PASS (tracked), dashboard regen PASS.
- Reviewer re-review: PASS (nit fixed, no confirmed findings).
- PR #253 `fix/financial-dashboard-cac-dual-display` (f0321ca) MERGED by owner on GitHub 2026-08-05 → `b04a2e7`. Local branch deleted. Feature fully complete.

## Not in scope
- Bot code, DB, handlers, callbacks.
- Explicit upgrade matrix.
- Reorder drag handles.
