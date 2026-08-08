---
name: audit-workflow
description: Enforce AGENTS.md §4 Audit and Code-Review Workflow — read source-of-truth docs, trace data/control flow across handlers/AI/DB/scheduling/quotas, classify findings by impact+confidence, record as GitHub Issues, reconcile ROADMAP, run focused+repo checks, and follow context economy. Load when asked to audit, review, or assess the project.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  gate: audit-review
author: Ham3dParsa
author_url: https://github.com/Ham3dParsa
---
# Audit & Code-Review Workflow Skill (AGENTS.md §4)

## When to load
- Asked to audit, review, assess, or verify the project
- When reconciling GitHub Issues with current code evidence
- Before reporting engineering/product status

## Audit Steps
1. Read `AGENTS.md`, `README.md`, `ROADMAP.md`, `docs/vision_and_product_goals.md`, and related GitHub Issues.
2. Inspect all relevant Python modules and tests, not only the file named in the request.
3. Trace data and control flow across:
   - Telegram handlers and callbacks
   - AI calls and response validation
   - SQLite writes, migrations, and transactions
   - scheduled jobs and delivery retries
   - timezone-sensitive day boundaries
   - quotas and plan overrides
4. Compare each existing issue with current code evidence. Do not copy old statuses forward without verification.
5. Look for correctness, security, reliability, cost, concurrency, migration, and UX risks—not only syntax errors.
6. Record findings as GitHub Issues with stable IDs and evidence.
7. Reconcile the product-level consequences in `ROADMAP.md`.
8. Run the focused tests plus the repository-wide checks before reporting.
9. **Context economy:** when investigating a bug or making a targeted change, read the specific function/handler and its direct dependencies first rather than the entire module or repository, unless the reported behavior requires tracing broader data/control flow. Expand scope only as evidence demands it.

## Classification
Classify findings by **impact and confidence**. Separate confirmed bugs from accepted product decisions, intentional guards, speculative concerns, and future enhancements. If a product/safety decision cannot be inferred, ask one focused question; do not silently choose a policy that changes user limits, cost exposure, or stored learning data.

## Output
Record actionable findings as GitHub Issues; update `ROADMAP.md` and `project_status.json` per AGENTS.md §2 and §8, then regenerate the dashboard.