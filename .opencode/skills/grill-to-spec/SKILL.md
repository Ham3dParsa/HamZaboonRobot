---
name: grill-to-spec
description: Grill-to-Spec discipline — before any implementation, grill the plan to resolve ambiguities and build domain model (CONTEXT.md / ADRs), then synthesize a locked spec (Contract Lock Template) with explicit owner choices per rule. Adapted from mattpocock/skills (grill-with-docs, to-spec) but scoped to AGENTS.md §2.4 gate. Load when plan is being finalized before execution.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  source: mattpocock/skills (grill-with-docs, to-spec)
---
# Grill-to-Spec Skill (AGENTS.md §2.4 Adaptation)

## Purpose
Bridge the gap between a rough idea and a locked, implementable spec. Enforces the AGENTS.md §2.4 Mandatory Pre-Implementation Contract Lock Gate using a structured "grill" process.

## When to load
- Contract Lock Gate requires decomposition into numbered rules
- Multiple algorithmic/product rules need independent owner choices
- Ambiguities exist that could lead to silent gap-filling

## Process (adapted from Pocock: grill-with-docs → to-spec)

### 1. GRILL (grill-with-docs equivalent)
- Interview the owner relentlessly about the plan until decision branches resolve
- Build/sharpen domain terminology inline (updates `CONTEXT.md` / ADRs if they exist)
- Identify all logical gaps, uncertainties, decision points
- Assess callback routing impact (§2.4 step 2)

### 2. DECOMPOSE INTO NUMBERED RULES
Each gap becomes a numbered rule with:
- Recommended option + rationale
- ≥1 meaningful alternative
- Comparison table: cost/UX/compatibility/regression
- Plain-language explanation (owner is not a pro developer)

### 3. LOCK SPEC (to-spec equivalent)
- Fill Contract Lock Template completely per rule
- Dependency & Wiring Map if required (§2.4.2)
- Owner confirms "proceed" or "locked" per rule
- GATE STATUS = LOCKED

### 4. PERSIST (plan-persistence skill)
- Write full plan with per-phase status to `.opencode/plans/plan-*.md`
- Reference each locked rule by number

## Key Differences from Upstream
- **No GitHub issue tracker dependency** — specs lock in Contract Lock Template, not GH issues
- **Integrated with AGENTS.md §2.4** — gate protocol is the authority
- **Plan-persistence mandatory** — every locked spec gets a plan file
- **No "ready-for-agent" label** — owner confirmation is the trigger

## Output
Locked Contract Lock Template + Dependency & Wiring Map (if needed) + Plan file with per-phase status.