---
name: query-credit-packs
description: Add financial-model support for non-expiring Query credit packs sold independently from learner plans.
created: 2026-08-10
base_commit: e76c572f63dfb26f661dd52656219dd0ad86147e
branch: feat/financial-model-ui
status: complete
---
STATE: phase 3/3 — status: complete — focus: model, UI, persistence, and validation delivered

## Scope

This plan changes only `tools/financial_model/financial_model_dashboard.html`, an internal brainstorming, planning, and simulation tool. It does not change Telegram behavior, production plans, user entitlements, payment processing, credit migration, or backend/database logic.

## Locked Product Contract

### Rule 1: Product structure

- Decision: Query purchases are separate consumable credit packs, independent from learner plans.
- Option Chosen: A.
- Alternatives Rejected: B (mixes one-time credits with plan identity); C (does not support the requested non-expiring balance).
- Trade-offs: A requires a second product collection but keeps product meaning and financial calculations clear.
- Owner Confirmation: Confirmed.

### Rule 2: Free-plan AI access

- Decision: The free plan has no default Query AI quota.
- Option Chosen: A.
- Alternatives Rejected: B (creates recurring AI cost); C (adds trial accounting and abuse assumptions).
- Trade-offs: A protects cost visibility and monetizes Query directly, at the cost of a higher first-use barrier.
- Owner Confirmation: Confirmed.

### Rule 3: Initial credit packs

- Decision: Provide Query 40 for 9,000 تومان and Query 100 for 19,000 تومان.
- Option Chosen: A.
- Alternatives Rejected: B (insufficient pricing signal); C (too many variables for the first experiment).
- Trade-offs: Two packs provide a simple volume-discount test while keeping the simulation interpretable.
- Owner Confirmation: Confirmed.

### Rule 4: Credit expiration

- Decision: Purchased credits never expire.
- Option Chosen: A.
- Alternatives Rejected: B (less attractive to users); C (more complicated to explain and simulate).
- Trade-offs: Non-expiration improves perceived value but requires a visible estimate of future AI-cost exposure.
- Owner Confirmation: Confirmed.

### Rule 5: Credit consumption

- Decision: One successful user-visible Query answer consumes one credit; failures and timeouts do not consume credits.
- Option Chosen: A.
- Alternatives Rejected: B (technical implementation detail is confusing to users); C (punishes failed requests).
- Trade-offs: A is understandable and stable for financial simulation; it may slightly understate retries unless failure assumptions are modeled separately.
- Owner Confirmation: Confirmed.

### Rule 6: Premium-plan interaction

- Decision: Premium users cannot buy credit packs; credits bought while users were free are assumed to migrate when they become premium.
- Option Chosen: Owner-defined dashboard assumption only.
- Alternatives Rejected: Runtime enforcement, wallet migration, and entitlement implementation are out of scope.
- Trade-offs: The model records the business assumption without pretending to implement bot behavior.
- Owner Confirmation: Confirmed.

### Rule 7: Financial treatment

- Decision: Keep the simulation lightweight. Model realistic configurable purchase and usage rates with controlled noise and reflect the result in revenue and profit.
- Option Chosen: Lightweight stochastic simulation.
- Alternatives Rejected: Formal deferred-revenue accounting; detailed per-user wallet liability ledger.
- Trade-offs: This keeps the dashboard understandable and fast, but results are estimates rather than accounting-grade liability recognition.
- Owner Confirmation: Confirmed.

### Rule 8: Share terminology

- Decision: Plan upgrade mix and credit-pack sales mix are separate metrics.
- Option Chosen: A.
- Alternatives Rejected: B (misleading combined denominator); C (removes useful scenario control).
- Trade-offs: Separate controls improve interpretation but add two sets of assumptions.
- Owner Confirmation: Confirmed.

### Rule 9: Editing ownership and synchronization

- Decision: Each product type has one authoritative editing source; analytical views consume those values and do not duplicate editable inputs.
- Option Chosen: A.
- Alternatives Rejected: B (duplicate editing risks drift); C (combines conceptually different products).
- Trade-offs: A requires reorganizing the UI but prevents inconsistent parameters.
- Owner Confirmation: Confirmed.

## Financial Model Contract

- `plans` remains the source for learner plans.
- `creditPacks` becomes the source for Query credit-pack products.
- Credit-pack purchases are one-time revenue events in the simulation.
- The model exposes configurable free-user purchase rate, pack sales mix, average credit consumption rate, repeat-purchase rate, and noise range.
- Noise must be bounded and reproducible when a seed is provided, so scenario comparisons remain meaningful.
- Pack revenue, Query usage cost, and estimated unused-credit exposure must be visible separately.
- Plan upgrade mix and credit-pack sales mix must never share a denominator.
- Existing saved dashboard data must continue to load with safe defaults for missing `creditPacks` fields.

## Dependency & Wiring Map

| Area | Disposition | Contract impact | Verification |
|------|-------------|-----------------|--------------|
| `plans` data | keep/update | Add only plan fields needed for shared summaries; preserve existing IDs | Existing plan tests/manual regression |
| `creditPacks` data | update/add | New independent pack collection and defaults | Fresh state + import migration checks |
| Plan editor | update | Sole editable source for plan definitions | UI inspection and DOM smoke checks |
| Credit-pack editor | add | Sole editable source for pack definitions | UI smoke checks |
| Pricing/share analysis | update | Read-only synchronized summary | Change-source synchronization check |
| Financial projection | update | Add stochastic pack sales/usage and profit impact | Deterministic seeded scenario tests |
| Charts/KPIs | update | Separate pack revenue and cost display | Chart data assertions |
| JSON export/import | update | Preserve plans and packs independently | Round-trip and partial-import checks |
| LocalStorage migration | update | Default missing packs without overwriting existing plans | Legacy-load test |
| Telegram callbacks | keep | No runtime callback changes | No callback map changes |
| Bot/backend/database | keep | Explicitly out of scope | Grep/scope review |

## Phase Tickets

1. `plan-query-credit-packs-phase-01-model.md` — data model, defaults, migration, and deterministic financial calculations.
2. `plan-query-credit-packs-phase-02-ui.md` — plan/pack editor separation and synchronized analytical views.
3. `plan-query-credit-packs-phase-03-validation.md` — focused verification, export/import checks, and visual regression review.

## Deliberately Not Included

- Telegram bot enforcement.
- Payment gateway integration.
- Premium-user wallet migration implementation.
- Backend persistence or database schema changes.
- Per-user credit ledgers.
- Accounting-grade deferred revenue recognition.
