---
name: plan-network-run-ux
description: One-command factory runs (entry, config, cache, resume, telemetry, logging) over P0 net home
created: 2026-09-15
base_commit: 926a19b
branch: docs/network-run-spec
status: in-progress
---
STATE: phase 2/6 — status: in-progress — focus: wave1 done (PR 710 + 711 merged); wave2 PR-A entry next

## Locked rules
- R1 thin entry `factory/run.py`; R2 presets avalai/google/zen; R3 `CLI>env>file>default` + `--list-models`; R4 auto-spawn supervisor with pid print + `--no-sup-spawn`.
- R5 `LEG_FALLBACKS` single owner `net.py`; R6 step-down only on ROTATE, auto-switch free legs only, paid stop+resume.
- R7 clean-server cache with TTL + real-ping gate + write-back, never-clobber; R8 direct-first AvalAI leaseless.
- R9 positive `--resume` + plan print + 4 refusals, flush on every stop.
- R10 phased telemetry (terminal enrichment + run_id now, attempt rows flagged); R11 split streams + colors + ETA + `--quiet/--json-log`.
- Keys never in CLI. No callback/keyboard/schema change. No new AI calls. Hermetic tests per PR + full suite before merge.

## Waves (parallel verdict: only PR-0 and PR-E are file-disjoint)
| Wave | PR | Phase file | Blocked on |
|---|---|---|---|
| 1a | PR-0 P1 whitelist | `plan-network-run-ux-phase-00-p1.md` | none |
| 1b | PR-E telemetry/logging | `plan-network-run-ux-phase-05-telemetry.md` | none (parallel with 00) |
| 2 | PR-A entry+config | `plan-network-run-ux-phase-01-entry.md` | PR-0 |
| 3 | PR-B table | `plan-network-run-ux-phase-02-table.md` | PR-A |
| 4 | PR-C cache+direct | `plan-network-run-ux-phase-03-cache.md` | PR-0, PR-A |
| 5 | PR-D resume | `plan-network-run-ux-phase-04-resume.md` | PR-B, PR-C |

## Subagent grouping
- Wave 1: two subagents in parallel (seams disjoint, verified by file list).
- Waves 2-5: one subagent each, serial. Each PR: implement + full suite + reviewer gate + push; merge only on explicit owner order.
