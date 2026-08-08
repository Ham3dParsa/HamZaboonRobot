---
name: contract-lock-gate
description: Enforce AGENTS.md §2.4 Mandatory Pre-Implementation Contract Lock Gate — identify logical gaps, present numbered rules with options+tradeoffs, obtain explicit owner choice per rule, fill Contract Lock Template, confirm owner says "proceed" or "locked" before any code change. Load when user requests implementation or when proposing a code change.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  gate: pre-implementation
author: Ham3dParsa
author_url: https://github.com/Ham3dParsa
---
# Contract Lock Gate Skill

## When to load
- User says "implement", "build", "add feature", "fix bug", or proposes ANY code change
- Before writing ANY production code or test code
- When a task contains multiple algorithmic/product rules needing independent decisions

## Gate Protocol (AGENTS.md §2.4)

### STOP and identify
1. All logical gaps, uncertainties, decision points in the proposed change
2. Assess callback routing impact: does it affect `callback_data` strings, `callback_router` dispatch, sub-router actions, or keyboard construction? If yes, the test plan section of the locked contract MUST specify a wiring integrity test.

### PRESENT each as a numbered rule
For each gap/uncertainty/decision:
- Recommended option (with rationale)
- ≥1 meaningful alternative
- Concrete trade-offs in a comparison table (cost/UX/compatibility/regression)
- Explain in plain language — no jargon, define terms, state practical impact

### OBTAIN explicit owner choice per rule
- No blanket approvals
- Use `question` tool: `multiple: true` for decision options, `custom: true` for clarifications
- If any gap/ambiguity arises during preparation → HALT and present focused inquiry

### FILL Contract Lock Template completely
```markdown
## CONTRACT LOCK TEMPLATE (agent must fill completely)

Rule #: [N]
Decision: [one-line description]
Option Chosen: [A/B/C...]
Alternatives Rejected: [list with one-line reason each]
Trade-offs: [cost/UX/compatibility/regression per alternative]
Owner Confirmation: [quote owner's "proceed" or "locked"]
GATE STATUS: [LOCKED / PENDING]
```

### Dependency & Wiring Map (required when change removes/changes feature, migrates, refactors, changes schema/callbacks, or changes module boundaries)
```markdown
| Dependency type | Items affected | Disposition (update / remove / keep) |
|---|---|---|
| Callback prefixes | ... | ... |
| Router branches (callback_router / sub-routers) | ... | ... |
| Keyboard builders / constants | ... | ... |
| DB tables / columns / functions | ... | ... |
| Handler functions | ... | ... |
| Imports / re-exports | ... | ... |
| Prompts / formatting helpers | ... | ... |
| Tests referencing them | ... | ... |
| Docs (ROADMAP, AGENTS.md §3 map, issues) | ... | ...
```

### CONFIRM owner says "proceed" or "locked" before touching code

### GATE KEYWORD
Agent MUST include `<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>` in response before any implementation.

## Fast-track exception (AGENTS.md §2.4.1)
Only for strictly non-behavioral changes:
- Typo/copy fixes in strings or docs
- Comment-only edits (no production code change)
- Adding tests that don't change production logic
- Formatting/whitespace-only diffs

To use: state under `<SYSTEM_GATE>` what the change is, why non-behavioral, and that it proceeds without locked contract. Does NOT apply if ANY ambiguity about learner-facing behavior, persistence, quotas, scheduling, or module boundaries.

## Owner Experience Note (AGENTS.md §2.4)
Owner is not a professional developer. Explain options in plain language:
- What each option does in practice
- What it costs (time, complexity, money if applicable)
- Why recommended option is preferred
- Define technical terms if unavoidable