# Implementation Plans

Plans are grouped by dependency theme so related and dependent work lives
together. Each subfolder keeps its own plans; cross-theme references use full
`docs/plans/<theme>/<file>.md` paths. Superseded plans move to
`docs/archive/`.

| Theme | Folder | Plans | Dependency note |
| --- | --- | --- | --- |
| FSRS migration & session engine | `docs/plans/fsrs/` | `plan_fsrs_migration.md`, `plan_fsrs_migration_v2.md`, `plan_daily_cards_migration.md`, `plan_fsrs_session_cleanup.md` | `plan_fsrs_migration_v2` supersedes `plan_fsrs_migration`; daily-card migration (Phase 3a) and session cleanup (Phase 2) both build on v2 ordering. |
| Content pooling, extraction, quality | `docs/plans/content/` | `plan_bot_extraction.md`, `plan_pooling.md`, `plan_quality_hardening.md`, `plan_wp2_verification_guardrails.md` | Pooling builds on bot-extraction (#180); WP2 guardrails build on quality hardening. |
| Costs & financial baseline | `docs/plans/costs/` | `plan_llm_costs_metrics.md`, `plan_financial_dashboard_baseline.md` | Complementary cost/telemetry topics. |

Audit reports live in `docs/audit/`; they analyze these plans and must cite
them by full path.
