# Plan: J-B6 — Canonical plan-identity leaf (R5/F5)

STATE: DONE — code complete, full suite 1137 passed (all 7 previously-failing
tests updated to the locked free-pronounce behavior), validation green, PR
opened for review.

## Context

`docs/audit/Deepening/2026-08-16-ai-config-consolidated.md` finding **R5/F5**
called out a duplicated plan-name/premium registry: `config.PLANS`,
`config.PREMIUM_PLANS`, and per-module `in PREMIUM_PLANS` gates were scattered
across `config/`, `services/db/plans.py`, `services/db/users.py`, `bot.py`,
and `handlers/user.py`. Each feature gate reached for the raw premium set
independently, so adding a tier or a feature required touching many files.

## Locked contract (owner, 2026-08-17)

| Rule | Decision | Choice |
|---|---|---|
| 1. Mechanism | `rank` per plan + `_FEATURE_MIN_RANK` map (feature unlocks when `plan.rank >= feature.min_rank`); feature inherited automatically by higher tiers | A |
| 2. Feature-gate values | `pronounce` free to all (min_rank 0); `card_modes` + `presentation` at silver+ (min_rank 2); `sentence_audio` NOT defined (no gate yet) | B |
| 3. `premium_plans()` / `free_plans()` / `plans_from()` | deferred — no caller | A |
| 4. Consistency test | identity registry must match DB seed; rank contiguity; monotonic inheritance | A |

`pronounce`-free is a **deliberate product decision**: `hamzaban.db` has no
`tts_access` row (resolves to default `"premium"`), and the DB is throwaway MVP
test data, so there is no real paid-usage behavior to preserve.

## Implementation (TDD)

- `config/plan_identity.py` (new leaf, stdlib-only, no app imports): `_PLANS`
  `{label, premium, rank}` + `_FEATURE_MIN_RANK`; helpers `valid_plans()`,
  `is_premium()`, `plan_label()`, `has_feature(plan, feature)`.
- `config/__init__.py`: deleted `PLANS` / `PREMIUM_PLANS`; `plan_display_name`
  falls back to `plan_label`; `presentation_for_user` uses `has_feature(..., "presentation")`.
- `services/db/plans.py`: deleted `is_premium`; `effective_plan` uses `valid_plans()`.
- `services/db/users.py`: `should_show_pronounce` → `has_feature(plan, "pronounce")`
  (free); `card_mode_available` → `has_feature(plan, "card_modes")`.
- `bot.py` (removed `PREMIUM_PLANS` + unused `presentation_for_user` imports;
  added `has_feature`): presentation gate (line ~649) → `has_feature(..., "presentation")`;
  pronounce gate (line ~847) → `has_feature(_user_plan(row), "pronounce")`.
- `handlers/user.py`: removed unused `PLANS` + `PREMIUM_PLANS`; presentation
  gate → `has_feature(..., "presentation")`.
- Dead-code guard: banned `PLANS` and `PREMIUM_PLANS` (`is_premium` not banned —
  the leaf legitimately owns that name).

## Tests

- `tests/test_plan_identity.py` (new): valid-set==DB-seed, label==DB display
  name, rank contiguity, premium membership, pronounce-free, card_modes/
  presentation==premium, fail-closed unknown plan/feature, monotonic inheritance.
- `tests/test_config.py`: dropped `PLANS`/`PREMIUM_PLANS`; kept label/presentation
  assertions via the config API.
- `tests/test_plan_semantics.py`: `is_premium` imported from the leaf.
- Updated 3 pronounce-gate tests + 4 SRS/study grid tests to the locked
  free-pronounce behavior (grade grid now ends with `tts:pronounce:s:{user_id}:{word_id}`).

## Validation

`pytest tests/ -n 14` → 1137 passed; `compile_all.py` ok; `ruff F821/F811` ok;
`generate_dashboard.py` ok; `git diff --check` clean.

## Out of scope (deliberately not changed)

- `config.presentation_for_user` stays a config-level helper (delegates to the leaf).
- `effective_plan` bypass→`gold` semantics unchanged.
- No schema change, no cache, no `premium_plans()`/`free_plans()`/`plans_from()`.