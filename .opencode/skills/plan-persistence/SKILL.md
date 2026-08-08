---
name: plan-persistence
description: Mandatory plan file persistence for locked plans. Use when a plan is locked, after each implementation step, or when resuming work.
compatibility: opencode
metadata:
  category: workflow
  gate: plan-execution
author: Ham3dParsa
author_url: https://github.com/Ham3dParsa
---
# Plan Persistence Skill

## When to load
- When a plan is locked and execution begins (Contract Lock GATE STATUS = LOCKED).
- After EVERY implementation step/phase completion.
- When resuming work after context compaction or in a new chat.

## Core Rule

**Persist locked plans to `.opencode/plans/<theme>/plan-*.md` with a top-level `STATE` line, theme subfolders, per-theme `index.md`, evidence-gated completion, and blocked-question logs. Update after each step. Resume work from the plan file across context compaction and new chats.**

## Structure & Naming

Plans live in dependency-based theme subfolders with a discovery index:
- Theme folder: `.opencode/plans/<theme>/` (`fsrs/`, `content/`, `callbacks/`, `costs/`)
- Theme index: `.opencode/plans/<theme>/index.md` (theme scope, plans, phases, and dependency edges)
- Main plan: `.opencode/plans/<theme>/plan-<short-description>.md`
- Per-phase sub-plans: `.opencode/plans/<theme>/plan-<main>-phase-<NN>-<topic>.md`

### Theme Index Template (`index.md`)
```markdown
---
name: <theme>
scope: <one-line purpose>
---
## Plans & Dependency Edges
| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-<main>.md` | 1..N | `<theme>/plan-X-phase-NN` | `in-progress` |
```

### Frontmatter & Top STATE Block
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
```markdown
STATE: phase <N>/<M> — status: <in-progress|blocked|complete> — focus: <short action>
```
*A resuming agent reads this first to orient in milliseconds without scanning logs.*

### Evidence-Gated Status Rule
A phase or step status MUST NOT be marked `complete` based on intent. The Notes column MUST cite real artifacts:
- Test names (`pytest tests/test_wiring.py -k test_foo`)
- Commit hashes (`git rev: ...`)
- File paths modified (`services/db/schema.py`)

### Blocked Question Log
When a phase is `blocked`, append or update:
```markdown
## Blocked Questions
- [YYYY-MM-DD] Phase <N>: Exact question posed to owner. Decision: <choice>.
```
*Prevents re-asking the owner or re-deriving answers across restarts.*

### Archive Rule & Final Verdict
When a plan is done and evaluated, it moves to `docs/archive/plan-<name>-<YYYYMMDD>.md` with a **Final Verdict** block:
```markdown
## Final Verdict
- Done: <shipped items>
- Deliberately Not Done: <untouched scope>
- Deferred: <future work>
- Uncertain: <remaining edge risks>
```

## Cross-Session Continuation
1. Check per-theme `index.md` to locate active plans.
2. Read the top `STATE` line of the plan file.
3. Resume from current phase — do NOT re-plan or re-decide locked rules.
