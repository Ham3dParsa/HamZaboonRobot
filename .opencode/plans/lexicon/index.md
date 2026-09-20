---
name: lexicon
scope: factory precard/pilot lines, datasets, CEFR/topic/sense quality
---
## Plans & Dependency Edges
| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-precard-v141-fanout.md` | implementation (done, committed) | — | `complete` (proof run + diff delivered) |
| `plan-precard-identity-141.md` | 0/4, awaiting owner (D1 + version) | `plan-precard-v141-fanout.md` | `in-progress` |
| `plan-precard-quality-141.md` | 0/6, awaiting owner (D-brand/D-semcor/order) | `plan-precard-identity-141.md` | `in-progress` |
| `plan-network-home.md` | locked R1..R8, P0→P1→P2 after 697 | `plan-precard-identity-141.md` | `locked` |
| `plan-network-run-ux.md` | 3/6 in-progress, R1..R11 (waves 1a+1b+2 merged: PR 710+711+713; PR-B table next) | `plan-network-home.md` | `in-progress` |
| `plan-async-cloud-judge.md` | 1/4 RED tests in progress, R1..R6 (branch feat/async-cloud-judge) | — | `in-progress` |
