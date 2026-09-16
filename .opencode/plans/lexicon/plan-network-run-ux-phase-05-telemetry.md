---
name: plan-network-run-ux-phase-05-telemetry
description: Phased telemetry enrichment plus split-stream colored logging with ETA
created: 2026-09-15
base_commit: 926a19b
branch: TBD (feat/network-telemetry)
status: locked
---
STATE: phase 1/6 — status: complete — focus: merged 2bcfc4e (PR 711); reviewer 0 findings; 2850 passed

## Scope
- `run_id` (start-ts + pid) into provider_map, run.log header, every record. Terminal records carry real `latency_s` (perf_counter), real `key_idx` (ring.idx), provider, `model_actual` vs `model_requested`; Google None-usage flagged `cost unknown`, never zero. Attempt rows behind flag (default off). `transport.py` re-export shim kept, duplicate bodies deleted (route-delete). Streams: stdout human (bars/boxes/CACHE/RESUME, colorized, `\r` padded), stderr warnings/errors, files machine (`run.log` compact lines, `dropped.log` multilingual, `--json-log` JSONL). Bar v2: done/todo, ok/fail, ETA (rolling mean, `?` until 3 batches), HIT/MISS counters. Red aborts. NO_COLOR honored.
- Files: `factory/core/telemetry.py`, `factory/precard/transport.py`, `factory/precard/pipeline.py`, `factory/precard/judge.py`, `factory/precard/topics.py`, `tools/egress/run_with_lease.py` (server+provider in line), supervisor `leases.jsonl` append.

## Rules: R10 R11.

## Tests
- Hermetic: run_id joins all four sinks; latency/key/model_actual assertions; cost-unknown flag; unknown-usage never sums as zero; `--quiet`/`--json-log` outputs.

## Gates
R10 R11. Attempt-row volume unchanged by default.

## Wiring rows
telemetry owner single (update); transport dup bodies (remove); egress lines (update).

## Blocking edges
None. Parallel-safe with phase-00 (disjoint files: no supervisor probe logic touched, only leases.jsonl append; coordinate in review).

## Acceptance
Remap-name lie gone (actual vs requested asserted); backoff/telemetry joined by run_id; full suite green.
