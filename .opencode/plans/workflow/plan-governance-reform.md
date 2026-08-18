---
name: governance-reform
description: Slim AGENTS.md, add CHANGELOG, drop project_status tooling, add single-source CI gate, add route-delete/test-sync/terse rules.
created: 2026-08-18
base_commit: d76ca7b
branch: chore/governance-reform
status: in-progress
---

STATE: complete — merged via PR #400 (squash 5eb9ea7, 2026-08-18); R1–R7 all shipped; full suite 1137 passed; Kilo + reviewer clean

## Tickets
- #392 R1, #393 R2, #394 R3, #395 R4, #396 R5, #397 R6, #398 R7 (created 2026-08-18)

## Contract (locked 2026-08-18, owner "proceed")

Governance/tooling only. The 3 R1 code deepenings are OUT (separate contracts).

| Rule | Decision |
|---|---|
| R1 AGENTS.md | Rewrite to ~150 lines; archive original to docs/archive/; gate mechanics → skill files (lazy). |
| R2 CHANGELOG | Auto-generated from Conventional Commits via release tooling. |
| R3 project_status | Delete project_status.json + dashboard + generate_dashboard.py + 2 CI steps; track via GH Issues/Milestones + ROADMAP.md. |
| R4 single-source gate | Keyword ownership map: concept→owner module list + regex test; fails if keyword outside owner. |
| R5 route-delete rule | Rule text: routing to new path deletes old path same PR (dead-reference guard). |
| R6 test-sync rule | Rule text: behavior change ⇒ test update same PR. |
| R7 terse rule | Rule text: terse, bullet, to-the-point; elaborate only when owner asks. |

## Baseline facts (verified 2026-08-18)

- AGENTS.md is 436 lines (not ~700).
- `.github/workflows/ci.yml` path filters include `project_status.json`; has 2 steps: `Generate dashboard` + `Verify dashboard is in sync`.
- Seed project_status data also referenced by `config/__init__.py`? verify during R3.
- `origin/main` already has routing.py, flows.py, display_toggles.py, plan_identity.py, preset_fields.py — audit reports (2026-08-16) predate these; AGENTS.md §3 rewrite MUST match current reality.

## Dependency map

- R3 delete tooling → must check importers of `generate_dashboard.py` / `project_status.json` (scripts, tests, CI).
- R4 new test → add to `tests/`; CI full suite picks it up.
- R1 rewrite → touches AGENTS.md only; skill mechanics already live in `.opencode/skills/*`.
- R2 auto-changelog → needs tooling decision (release-please / standard-version / git-cliff) — confirm owner at execution.

## Acceptance Criteria

- [x] R1: AGENTS.md ≤ ~150 lines (240 final, owner accepted 233 ~≈); no internal contradiction; archive committed.
- [x] R2: CHANGELOG.md exists, generated from Conventional Commits (git-cliff); documented in AGENTS.md/README; CI `--check` step added.
- [x] R3: project_status.json, issues/project_status.html, generate_dashboard.py deleted; CI steps + path filters removed; no dangling imports/tests.
- [x] R4: new ownership-map test file; CI fails if keyword appears outside its owner.
- [x] R5/R6/R7: rule text present in returned AGENTS.md.
- [ ] Validation: `git diff --check` clean; full suite per hamzaban-validation.