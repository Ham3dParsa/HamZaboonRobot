---
name: opencode-tooling-setup
description: Add lean subagents, project skills, global skills, graphify indexing, and AGENTS.md workflow rules
created: 2026-08-05
base_commit: 3c7f251
branch: feat/opencode-skills-setup
status: in-progress
---

# Plan: OpenCode Tooling Setup (Lean Subagents + Skills + Graphify)

## Overview
Implement the full OpenCode tooling setup as per locked contract: 4 lean subagents, 7 project skills (incl. plan-persistence), curated global skills, Pocock/EC-C adapted skills, Graphify indexing, and AGENTS.md workflow updates. All changes are `.opencode/` config + AGENTS.md + .gitignore + project_status.json — no production code.

## Phases & Progress Status

| Phase | Description | Status | Notes |
|-------|-------------|--------|-------|
| 0 | Branch + backups + write this plan file | complete | Branch `feat/opencode-skills-setup` from `main` @ `3c7f251`; no global skills dir existed |
| 1 | `.opencode/agents/` — 4 lean subagents | complete | hamzaboon-db, hamzaboon-ai, hamzaboon-handler, hamzaboon-reviewer |
| 2 | `.opencode/skills/` — 7 project skills | complete | contract-lock-gate, hamzaban-validation, pre-commit-gate, integration-test-proto, callback-wiring, persian-formatting, plan-persistence |
| 3 | Global general skills → `~/.config/opencode/skills/` | complete | Curated: osmontero (11), vekzz (1), farmage (4); backup taken first |
| 4 | Pocock/EC-C adapted skills (repo-local, scoped) | complete | grill-to-spec, spec-to-tickets, tdd-enforcement, bug-diagnosis (4 skills) |
| 5 | Graphify install + build + `.gitignore` block | complete | `uv tool install graphifyy` (uv 0.12.1 installed); `graphify . --code-only` → 2490 nodes; graphify-index skill added; `.gitignore` block added |
| 6 | AGENTS.md §11 + `project_status.json` + dashboard | complete | §10 skills/subagent/plan-persistence block added (no §11 existed; kept sequential); decision-opencode-tooling-setup entry; dashboard regenerated |
| 7 | Validation suite + commit | in-progress | Full suite passes (379 tests); compile OK; diff --check clean. Pre-existing ruff F821 errors only in untracked tools/ archives (not in change set). Decision entry removed from project_status.json per owner (dev tooling not a product decision). |

## Locked Contract References
- **Rule 1 (Knowledge Graph):** Graphify indexing (Option A chosen)
- **Rule 2 (Lean Agents):** 4 specialized subagents with strict permissions (Option A)
- **Rule 3 (Workflow Skills):** 6 project skills + global split (Option A)
- **Rule 4 (AGENTS.md Skills Map):** Delimited §11 block (Option A)
- **Rule 5 (Plan Persistence):** Mandatory plan file with per-phase status, updated after each step; completed plans move to `docs/archive/` (new rule)

## Revert Strategy
Each phase is independent and reversible:
- Phases 1-2, 4: `git rm -r` the created folders
- Phase 3: restore global backup from `.opencode-backup-global/`
- Phase 5: `uv tool uninstall graphifyy` + `git checkout .gitignore`
- Phase 6: `git checkout AGENTS.md .gitignore project_status.json`
- Full revert: `git checkout main && git reset --hard origin/main && uv tool uninstall graphifyy && Remove-Item ~/.config/opencode\skills`

## Update Log
- 2026-08-05: Plan created; Phase 0 complete
- 2026-08-05: Phase 1 complete — 4 lean subagents created
- 2026-08-05: Phase 2 complete — 7 project skills created
- 2026-08-05: Phase 3 complete — 16 global skills installed
- 2026-08-05: Phase 4 complete — 4 Pocock/EC-C adapted skills created
- 2026-08-05: Phase 5 complete — uv + graphifyy installed, graph built (2490 nodes), graphify-index skill + .gitignore block added
- 2026-08-05: Phase 6 complete — AGENTS.md §10 block added; decision entry added then removed per owner (dev tooling not a product decision); dashboard regenerated
- 2026-08-05: Phase 7 — validation passing (379 tests OK, compile OK, diff --check clean); commit pending