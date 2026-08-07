# Audit Reports

Read-only audit reports and architecture alignment blueprints. These analyze
the plans in `docs/plans/` (grouped by theme) and record evidence-cited
findings. Never treat them as canonical state — `project_status.json` and
GitHub Issues are authoritative.

| File | Scope | Status |
| --- | --- | --- |
| `audit_content_pool_feedback_2026-08.md` | Pooling, card feedback, model-tag, admin group — first audit | Outdated — superseded by the 2026-08-06 audits (still referenced as Claude-decision evidence in `plan_pooling.md`) |
| `pool_semantic_cache_audit_2026-08-06.md` | Pool vs FSRS compatibility, embedding feasibility, callback wiring, Tier-3 interconnection | Reconciled 2026-08-08 — resolved rows (entry_source, casefold, segment key) marked; open decisions listed in §6 |
| `architecture_alignment_2026-08-06.md` | System architecture alignment & technical blueprint; contract-lock table (R0–R3, A1–A4, B2, B5) and owner amendments (entry-source rule) | Reconciled 2026-08-08 — B6 `entry_source` Rules #1/#3 LOCKED & landed; remaining PENDING |
