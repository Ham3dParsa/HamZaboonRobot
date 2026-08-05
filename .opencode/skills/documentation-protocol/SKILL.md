---
name: documentation-protocol
description: Enforce AGENTS.md §8 Documentation Update Protocol — keep the documentation ecosystem coherent with one canonical source per information type, never edit generated views directly, regenerate the dashboard after phase/decision changes, archive superseded plans. Load after any meaningful code or product change that touches status, roadmap, plans, or tooling docs.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  gate: documentation-change
---
# Documentation Update Protocol Skill (AGENTS.md §8)

## When to load
- After a meaningful code or product change
- When phase status, decisions, dependencies, roadmap, plans, tooling, or module structure change

## Which document to update

| What changed | Update this | Then |
|---|---|---|
| Phase status, decisions, dependencies, or progress items | `project_status.json` | Run `python scripts/generate_dashboard.py` |
| Product narrative, scope, or roadmap direction | `ROADMAP.md` (narrative sections only) | — |
| Module structure (add/rename/split/remove) | `AGENTS.md` §3 table + `tests/test_wiring.py` scan paths | — |
| Tooling, validation commands, or setup | `README.md` | — |
| Bug discovered, feature requested, or risk identified | GitHub Issue | Link issue ID in `project_status.json` if phase-relevant |
| New architectural plan written | `docs/plan_<topic>.md` (status line: `> STATUS: active`) | Archive superseded plan to `docs/archive/` |
| Implementation completes a phase or renders a plan obsolete | Move plan doc to `docs/archive/`; update its status line to `implemented` | Update `project_status.json` |
| Vision or strategic goals change | `docs/vision_and_product_goals.md` | — |
| Agent operating agreement changes | `AGENTS.md` | — |

## Canonical source rule
Each type of information has exactly one canonical source. Generated views are never edited directly:
- `issues/project_status.html` is regenerated from `project_status.json` only.
- `project_status.json` is authoritative for phase/decision status; GitHub Issues are authoritative for individual issue state.

## Staleness prevention
- The CI pipeline verifies `issues/project_status.html` is in sync with `project_status.json`.
- Every code review or audit must start by checking that the §2 documents match the actual project state.
- If a stale reference (a file/tool that no longer exists) is found, file a GitHub Issue and update the referring document immediately.