# Spec — Arbiter Line (linking execution capability + R2 console rebuild)

Owner-stated historical flow (verified against code where noted):
screened senses → candidate shortlist → mechanical rules (some approved
on the spot; mechanical mostly REJECTS) → local-model arbiter (prompt
template) → post-arbiter gates → leftovers to supervised queue. Screening
was added later as a pre-link Kaikki garbage filter.

## Stage → code anchor → TUI → WUI → gap

| # | Stage | Code anchor | TUI (CLI) | WUI (console) | Gap |
|---|---|---|---|---|---|
| 0 | Screening | `factory/precard/prune.py`, `/api/screening/*` | manual scripts | ✅ run + history + handoff | none |
| 1 | Shortlist | `factory/linking/linker.py` shortlist | `linking.cli link --words/--out` | via `/api/runs` flow=linking | UI shows no shortlist panel (R2 tab 0) |
| 2 | Mechanical rules | `linker.py:393 arbitrate_link` (TO RENAME) | same `link` run | same | name collision (DDD) |
| 3 | Arbiter run (LLM) | `linking/arbitration.py` port + `arbitration_prompt.py` | ❌ NO command | ❌ NO endpoint, tab 2 hollow | **core gap: needs runner + CLI + endpoint** |
| 4 | Gates | `ArbitrationVerdict` auto-linked/routed (`arbitration.py:52-60`) | n/a (in-runner) | n/a | assemble in runner (P1) |
| 5 | Supervised review | `labels.py`, batches store, human queue | via files | ✅ batches/import/review/history | rename done (R5); A2 integration pending (R2) |
| 6 | TSV + gallery | `linking/cli.py` export, `viewer.build_linker_gallery` | ✅ | ✅ build+view (PR 832) | none |

Probing (`probe_providers.py:273`) is the only current AI consumer (manual).
Past gallery verdicts came from manual/probe runs, never a pipeline.

## Locked naming decisions (DDD, owner 2026-09-28)

- D1: `arbiter` = LLM-based only; `judge` banned on linking line (precard-owned).
- D2: `arbitrate_link` (mechanical) renamed → `resolve_link` (rule resolution).
- D3: A2 = design language (standard); R2 = rebuild work package (depends on arbiter capability).
- D4: Owner runs real models; builders test with stubs/mocks only (no live keys/calls in tests).

## Non-goals

Model execution BY the builder; precard-line changes; Telegram surface changes.
