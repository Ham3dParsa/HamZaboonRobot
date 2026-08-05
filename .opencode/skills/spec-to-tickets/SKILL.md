---
name: spec-to-tickets
description: Spec-to-Tickets breakdown — decompose a locked spec/plan into tracer-bullet tickets (per-phase sub-plans), each declaring blocking edges and acceptance criteria. Adapted from mattpocock/skills (to-tickets) but scoped to plan-persistence per-phase sub-plans. Load when a locked spec needs phase-level breakdown for complex/thorough tasks.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  source: mattpocock/skills (to-tickets)
---
# Spec-to-Tickets Skill (plan-persistence per-phase adaptation)

## Purpose
Break a locked spec into granular, ordered tickets (phases) that can be executed independently with clear dependencies. Implements the AGENTS.md §2.4 + plan-persistence requirement for per-phase plans on complex tasks.

## When to load
- Plan involves schema migrations, callback routing changes, module boundary changes, multi-file refactors, or critical module changes (SRS, MarkdownV2, quotas, delivery)
- Phase-level detail needed to prevent silent gap-filling
- Task is "complex/thorough with nuances and critical changes"

## Process (adapted from Pocock: to-tickets)

### Input
- Locked Contract Lock Template (all rules LOCKED)
- Main plan file (`.opencode/plans/plan-*.md`)

### Output per phase
Create `.opencode/plans/plan-<main>-phase-<NN>-<topic>.md` with:
- Detailed step-by-step breakdown for that phase
- Specific contract rule references for that phase
- Expected test updates / validation steps
- Dependency & Wiring Map rows for that phase
- Blocking edges (which phases must complete first)
- Acceptance criteria (how to verify phase complete)

### Ticket structure
Each phase ticket declares:
1. **Blocking edges** — what must be done first (explicit dependencies)
2. **Scope** — exactly what files/modules change
3. **Tests** — which tests must be added/updated
4. **Gates** — which contract rules this phase satisfies
5. **Wiring rows** — Dependency & Wiring Map entries for this phase

## Key Differences from Upstream
- **Output = per-phase plan files** (not GitHub issues or local text file)
- **Integrated with plan-persistence** — main plan references sub-plans
- **Enforces AGENTS.md §2.4.2** — each phase produces verifiable wiring map rows
- **Traceability** — every ticket traces back to a locked rule number

## Integration with Other Skills
- `grill-to-spec` produces the locked spec this consumes
- `plan-persistence` manages the main + sub-plan files
- `contract-lock-gate` validates each phase against its locked rules
- `tdd-enforcement` drives implementation within each phase