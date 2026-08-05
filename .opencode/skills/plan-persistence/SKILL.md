---
name: plan-persistence
description: Mandatory plan file persistence for all locked plans — write full plan with per-phase/step progress status to .opencode/plans/plan*.md, update after each step; for complex/thorough tasks with critical module changes, create per-phase plan files to prevent silent gap-filling; completed plans move to docs/archive/. Load when a plan is locked and execution begins, and after each implementation step.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  gate: plan-execution
---
# Plan Persistence Skill

## When to load
- When a plan is locked and execution begins (Contract Lock GATE STATUS = LOCKED)
- After EVERY implementation step/phase completion
- When resuming work after context compaction or in a new chat

## Core Rule

**When a locked plan begins execution, persist the full plan with per-phase/step progress status to `.opencode/plans/plan*.md`, updating it after each step. For complex/thorough tasks with critical module changes, create a per-phase plan file for each phase to prevent silent gap-filling. Resume work from the plan file across context compaction and new chats.**

## Plan File Requirements

### Naming
- Main plan: `.opencode/plans/plan-<short-description>.md` (e.g., `plan-opencode-tooling-setup.md`)
- Per-phase plans (when needed): `.opencode/plans/plan-<main>-phase-<NN>-<topic>.md`

### Frontmatter (required)
```yaml
---
name: <plan-name>
description: <one-line purpose>
created: YYYY-MM-DD
base_commit: <git-sha>
branch: <branch-name>
status: in-progress | complete | archived
---
```

### Phase/Step Status Table (required)
| Phase | Description | Status | Notes |
|-------|-------------|--------|-------|
| 0 | Branch + backups | complete | ... |
| 1 | Agents | in-progress | ... |
| 2 | Skills | planned | ... |

Status values: `planned` / `in-progress` / `blocked` / `complete` / `deferred` (matching `project_status.json` vocabulary)

### Locked Contract References
Each plan file MUST reference the locked contract rules by number/decision so plan and gate stay in sync and traceable.

### Update Log
Append entries after each phase:
```markdown
## Update Log
- YYYY-MM-DD: Phase N complete — <summary>
- YYYY-MM-DD: Phase N+1 next
```

## Per-Phase Sub-Plans (for complex/thorough tasks)
Required when task involves:
- Schema migrations
- Callback routing changes
- Module boundary changes
- Multi-file refactors
- Critical module changes (SRS, MarkdownV2, quotas, delivery)

Each phase gets its own plan file with:
- Detailed step-by-step breakdown
- Specific contract rule references for that phase
- Expected test updates
- Dependency & Wiring Map rows for that phase

**Purpose:** Forces each phase's details to be spelled out up front, preventing the AI from silently self-filling logical gaps. Each phase references back to its locked contract.

## Archive Rule
**When a plan is done and completely evaluated, it moves to `docs/archive/`.**
- Archive preserves: plan file + any per-phase files + final verdict
- Main `.opencode/plans/` keeps only active/in-progress plans
- Archive naming: `docs/archive/plan-<name>-<YYYYMMDD>.md`

## Cross-Session Continuation
To resume in a new chat or after context compaction:
1. Read the plan file (`.opencode/plans/plan-*.md`)
2. Identify current phase (status = `in-progress` or first `planned`)
3. Continue from that phase — do NOT re-plan or re-decide locked rules
4. Update plan file as you progress

## Integration with Contract Lock Gate
- Plan file created **immediately after** Contract Lock GATE STATUS = LOCKED
- Plan file references each locked rule by number
- If new gaps discovered during execution → HALT, return to Contract Lock Gate (§2.4), do NOT silently fill gaps