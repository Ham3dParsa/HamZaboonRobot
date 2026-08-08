---
name: plan-i18n-multilingual-expansion
description: Multi-lingual expansion foundation — i18n extraction, schema neutrality, native_lang onboarding, catalog/plans localization, locale-aware rendering.
created: 2026-08-06
base_commit: 130941a
branch: (pending) feat/i18n-foundation
status: in-progress
---

# Plan: Multi-Language Expansion (i18n/l10n)

**Status:** Contract LOCKED; execution DEFERRED by owner. This file exists so the
locked scope survives context compaction / a later session without re-deciding or
gap-filling. See `docs/archive/` for the prior assessment artifacts.

## Locked Contract (rules traceability)

| Rule | Decision | GATE STATUS |
| :--- | :--- | :--- |
| 1 | Extract all hardcoded Farsi UI/keyboard strings to new `services/i18n/` module (`text(locale,key)`), resolve at render time, `fa` default preserves UX. AI cost: none. | LOCKED |
| 2 | Remove `fa_` prefix from prompt variables and DB keys (`fa_meaning`->`meaning`, `fa_explanation`->`explanation`); migrate existing stored JSON TEXT in place via idempotent SQL `replace()`. AI cost: none. | LOCKED |
| 3 | Ask Native/UI Language FIRST in onboarding, before Target Language; add `users.native_lang` (default `fa`) + `daily_card_sessions.native_lang`; `native:` callback route. AI cost: none. | LOCKED |
| 4 | Catalog & plans localization at render time: stable codes in DB (`konkur`, `gold`, `plan_gold`); labels via per-locale maps resolved by locale with `fa` fallback. AI cost: none. | LOCKED |

Canonical GitHub Issues (opened 2026-08-06):
- #261 — Rule 2 (schema decouple) — `i18n,tech-debt,phase-1,priority-high`
- #262 — Issue 4 open (locale-aware rendering) — `i18n,tech-debt,phase-3,priority-medium`
- #263 — Rule 4 (catalog localization) — `i18n,feature,phase-2,priority-medium`
- #264 — Rule 3 (users.native_lang onboarding) — `i18n,feature,phase-2,priority-high`
- Also created `i18n` label; repo label taxonomy is `phase-N` + `priority-{high,medium,low}`.

## Phase/Step Status

| Phase | Description | Status | Notes |
|-------|-------------|--------|-------|
| 0 | Canonical registry (open issues + labels) | complete | #261-#264 opened; `i18n` label created |
| 1 | Rule 1 — i18n extraction to `services/i18n/` | planned | no behavior change |
| 2 | Rule 2 — schema neutrality + SQL migration | planned | depends on nothing; req. fresh + upgrade DB tests |
| 3 | Rule 3 — native_lang onboarding + prompt threading | planned | depends on Phases 1-2 |
| 4 | Rule 4 — catalog & plans localization at render | planned | can proceed with Phase 3; keep plans.display_name as fa-locale override |
| 5 | Locale-aware rendering (Issue #262) | planned | digit table + RTL/LTR + cancel-input |
| 6 | Full validation + review + docs + dashboard | planned | blocks commit |

## Locked owner decisions recorded
- Onboarding native/lang first (Rule 3, locked).
- Migration via in-place SQL rename (Rule 2, locked).
- `plans.display_name` semantics under Rule 4 (execution-time detail): keep the
  admin-editable field but treat it as the **fa-locale override** (rendered verbatim
  for `fa`, i18n key `plan_{name}` for other locales). No visible change today.

## Scope (touched modules — current map)
- `config/catalog.py`, `config/keyboards.py`, `config/__init__.py`, `bot.py`
- `services/ai/prompts.py`, `services/ai/ai.py`
- `services/db/schema.py`, `services/db/users.py`, `services/db/plans.py`
- `services/utils/formatting.py`, `services/utils/helpers.py`
- `handlers/user.py`, `handlers/admin.py`, `handlers/study_handler.py`, `handlers/srs_handler.py`
- `export_cards.py` (Rule 2 read site), `tests/*` (fixtures + new tests)

## Known coupling hotspots (verified)
- `services/ai/ai.py`: `_COMPACT_CARD_FIELDS` maps `m/x -> fa_meaning/fa_explanation`;
  `validate_card`, `card_repair_fields`, `validate_card_patch` hardcode `fa_*`.
- `services/ai/prompts.py`: `_card_schema` + repairable prompt instruct Farsi; guidance
  written in Farsi («برای فارسیزبانان»).
- `services/utils/formatting.py`: `format_card`, `_saved_word_card` read `fa_*`;
  `to_persian_digits()` locale-blind; SRS strings hardcoded Farsi.
- `services/utils/helpers.py`: `_CANCEL_INPUTS` hardcodes Farsi cancel words.
- `services/db/plans.py`: `DEFAULT_PLANS.display_name` single-language seed.
- Stored JSON columns: `daily_cards.card_data`, `saved_words.card_data`,
  `query_results.result_json`, `grammar_tips.tip_json` (Rule 2 SQL replace targets).

## Per-Phase Plans
Created at each phase start during execution (per plan-persistence skill) to avoid
staleness during deferral: `plan-i18n-phases-phase-0N-<topic>.md`.

## Update Log
- 2026-08-06: Step 0 complete — opened Issue #261-#264, created `i18n` label.
  Plan persisted for deferred execution; no code changes per owner.
- 2026-08-06: Next on execution — Phase 1 (i18n extraction), after branch
  `feat/i18n-foundation` + Step 6 validation gate + `hamzaboon-reviewer`.