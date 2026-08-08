---
name: plan-reconcile-pool-plans-audits
description: Reconcile the pooling plan and 2026-08-06 audits with current code reality and the Claude-conversation decision context, so the pool-builder contract lock can proceed cleanly.
created: 2026-08-08
base_commit: 972e7243459873662d8caad3eb6d6a5cce251994
branch: main
status: in-progress
---

# Plan: Reconcile Pooling Plan & Audits with Current Reality

## Context

The earlier reorganization grouped plans by dependency theme
(`docs/plans/fsrs|content|costs/`). Before the pool-builder tool's
contract-lock rules can be locked, three documents carry **outdated
assumptions** vs. current code and vs. the Claude-conversation decisions:

1. `docs/plans/content/plan_pooling.md` — assumes `daily_cards` as pool
   intake; lacks `entry_source` (landed in #266); uses schema-column segment
   keys instead of `tier3_context`.
2. `docs/audit/pool_semantic_cache_audit_2026-08-06.md` — status is
   "Under Revision"; several verdicts are PENDING owner decision.
3. `docs/audit/architecture_alignment_2026-08-06.md` — status "Under
   Revision"; R0–R3/A1–A4/B2/B5 are PENDING; the B6 `entry_source` half is
   already LANDED and must be marked resolved.

This plan only **edits documentation** (non-behavioral, fast-track §2.4.1).
It does not implement any pool/feedback/model-tag/admin-group code. It
produces a consistent, decision-ready baseline so the next session can run
the pool-builder Contract Lock Gate cleanly.

## Locked Contract References

No new behavioral contract rules are locked by this plan (docs-only). It
consumes prior locked/landed decisions:

- B6 `entry_source` — landed (#266), rule #1/#3 LOCKED, #2 deferred.
- `decision-pool-deferred` — locked deferral with re-entry trigger.
- Claude-conversation Rules 1–12 — **PENDING**, documented here as decision
  inputs to be resolved by the owner in the next contract-lock session.

## Phase/Step Status Table

| Phase | Description | Status | Notes |
|-------|-------------|--------|-------|
| 0 | Baseline + branch | complete | Committed reorg `85c1076`; base `972e724` |
| 1 | Reconcile `plan_pooling.md` | planned | Re-anchor intake, segment keys, entry_source, normalization |
| 2 | Reconcile `pool_semantic_cache_audit_2026-08-06.md` | planned | Mark resolved items, record current code evidence |
| 3 | Reconcile `architecture_alignment_2026-08-06.md` | planned | Mark B6 landed; update statuses of R/A/B rules |
| 4 | Record Claude decision context | planned | Append Rules 1–12 PENDING table (decision inputs) |
| 5 | Cross-link + validate + commit | planned | Fix refs, READMEs, regenerate dashboard, full validation |

## Phase Details

### Phase 1 — `docs/plans/content/plan_pooling.md`

Edit (non-behavioral content correction) to reflect:

- **Intake re-anchor:** replace `source_kind: daily_card` eligibility path
  with `saved_words.first_exposure_done` Tier-2 acceptance (Phase 2b drops
  `daily_cards`). Note `daily_cards` is a drained source awaiting DROP.
- **Segment key:** state that `(target_lang, goal, level)` is derived from
  `tier3_context` at runtime (no `goal`/`level` columns on `saved_words`).
- **entry_source:** note the landed `entry_source` origin tag (`manual`/
  `auto`) on `saved_words` (#266) and that `'auto'` has no write path until
  Tier-3 lands — consistent with pool writes.
- **Normalization:** reaffirm `casefold` as the single canonical standard
  (matches `_normalize_word`, resolves the `lower(trim)` divergence).
- **Sequencing trigger:** keep the DAU≥50 + segment-density trigger but note
  current live scale (users=15, saved_words=531) — trigger still unmet.
- **Do NOT** change the locked schema, identity key, quota, or selection rules.

### Phase 2 — `docs/audit/pool_semantic_cache_audit_2026-08-06.md`

- Update status line to reflect this reconciliation date.
- Mark findings resolved/confirmed vs. still-open with current code evidence
  (re-verify `entry_source`, `saved_words` columns, `content_pool` absent).
- Keep evidence-cited `file:line` style; do not invent decisions.

### Phase 3 — `docs/audit/architecture_alignment_2026-08-06.md`

- Mark **B6 `entry_source`** as LOCKED/landed (schema.py, words.py,
  srs_handler.py, tests) — no longer PENDING.
- Update R0–R3, A1–A4, B2, B5 statuses only where code evidence now supports
  a change; leave true open questions (embedding rollout, admin-group
  ROADMAP move, pool pilot budget) as PENDING owner decisions.

### Phase 4 — Record Claude decision context

Append a non-normative section to the pooling plan (or a referenced note)
capturing Claude-conversation **Rules 1–12** as PENDING decision inputs
(word source, resumable CLI, preset reuse, budget cap, dedup, feedback flag
formula, auto-hide action, admin-group scope). These are **decision inputs,
not locked rules** — resolved by the owner in the next contract-lock session.

### Phase 5 — Cross-link + validate + commit

- Ensure all `docs/plans/` and `docs/audit/` references use full theme paths.
- Recheck `docs/plans/README.md` and `docs/audit/README.md` status text.
- Regenerate dashboard (`python scripts/generate_dashboard.py`) if
  `project_status.json` changes (unlikely).
- Run full local validation: `python -m pytest tests/ -n 14`,
  `compile_all.py`, `ruff --select F821,F811`, `git diff --check`.
- Commit as a single docs commit on `main`.

## Update Log

- 2026-08-08: Plan created (base `972e724`, reorg already committed).
- 2026-08-08: Phases 1–4 complete — reconciled `plan_pooling.md` (additive
  Reconciliation + Claude decision context), refreshed `pool_semantic_cache_audit`
  (new §6), marked B6 `entry_source` landed in `architecture_alignment`.
  Phase 5 (cross-link/validate/commit) next.
