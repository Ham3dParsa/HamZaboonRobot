---
name: workflow-optimization
description: Cut recurring context/token cost from skill injection and reviewer subagent while preserving all safety rails.
created: 2026-08-11
base_commit: 6797cd4
branch: docs/workflow-optimization
status: in-progress
---

STATE: phase 1/3 — status: in-progress — focus: conditional injection + tiered reviewer

## Bottleneck Evidence

Issue #308: 2-line intent change in `handlers/srs_handler.py` (success grade →
toast). The change itself was trivial, but the session consumed large context from:
1. Bulk-loading 8+ full SKILL.md files "just in case".
2. A separate `hamzaboon-reviewer` subagent re-reading the whole diff in a
   fresh context for a 1-2 line swap.
3. Re-debugging the parallel-work-claims PowerShell lock twice.

## Gate Decision Tree

```
User proposes change
  ├─ Fast-track eligible? (typos/docs/tests/formatting) → yes → skip full gate
  └─ No → STOP + identify gaps
        ├─ Working in parallel? → yes → load parallel-work-guard
        ├─ New module / refactor / interface design? → yes → load codebase-design (+ grill-to-spec if rules not locked)
        ├─ Behavioral (handler/DB/quota/callback/AI)? → yes → load integration-test-proto + tdd-enforcement
        └─ After LOCK → load plan-persistence
              Before commit → load hamzaban-validation + pre-commit-gate + git-protocol
```

## Tiered Reviewer Rule

| Change scope | Reviewer | Default model |
|---|---|---|
| Trivial (1–2 line behavioral swap, doc/string fix) | Skip OR cheap subagent | Tencent Hy3 (free) via Kilo Gateway |
| Schema / callback / quota / AI / multi-file | Full independent review | Override to strong model per run |
| Non-behavioral (fast-track) | Skip | N/A |

## Claims-Script Design

Reusable `scripts/claim_seam.ps1` replaces inline PowerShell in
`parallel-work-guard/SKILL.md`. Subcommands: `acquire`, `release`, `check`,
`prune`. Uses `[System.IO.FileStream]` exclusive lock + `Move-Item` atomic
write. Path normalization via `[System.IO.DirectoryInfo].FullName`. Never
`[IO.File]::Replace` on mixed-slash paths.

## Acceptance Criteria

- [ ] `contract-lock-gate/SKILL.md` documents triage questions and conditional
      injection; no skill is loaded speculatively.
- [ ] `hamzaboon-reviewer.md` has `model:` set to cheap model; `AGENTS.md` §5
      states the tiering rule.
- [ ] `scripts/claim_seam.ps1` exists and is referenced by
      `parallel-work-guard/SKILL.md`.
- [ ] `AGENTS.md` §10.2 has exact one-line triggers per skill, no pre-load
      implication.
- [ ] This plan file exists and is linked from `.opencode/plans/workflow/index.md`.
- [ ] Validation passes: `python -m pytest tests/ -n 14`, `compile_all.py`,
      `ruff --select F821,F811`, `generate_dashboard.py`, `git diff --check`.
