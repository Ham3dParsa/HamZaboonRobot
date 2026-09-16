---
name: plan-network-run-ux-phase-03-cache
description: Clean-server cache first with TTL/ping/write-back plus AvalAI direct-first
created: 2026-09-15
base_commit: 926a19b
branch: TBD (feat/network-clean-cache)
status: locked
---
STATE: phase 5/6 — status: locked — focus: implement after PR-0 and PR-A

## Scope
- `clean_cache.json` beside pool: `{server_id, provider, last_ok_ts, latency_ms}`; `lease_for` tries fresh (TTL, default 24h, `--clean-ttl`/`EGRESS_CLEAN_TTL`) + cooled-out rows first with one real-ping gate; full probe only on miss; write-back successes; empty probe clobbers neither pool nor cache. `--direct-probe`/`AVALAI_DIRECT_FIRST=1`: leaseless AvalAI path, failure falls back to lease with telemetry. `CACHE HIT/MISS` console lines.
- Files: `factory/precard/net.py`, `factory/run.py` (`--cache --clean-ttl`), `tools/egress/supervisor.py` (minimal hook), `tests/factory/test_precard_net.py`.

## Rules: R7 R8.

## Tests
- Hermetic: cache-hit skips full scan; stale entry re-pinged; empty probe never clobbers; direct-ok takes zero lease; direct-fail takes lease + telemetry.

## Gates
R7 R8. Google free legs use top 1-2 cached servers (no 50-server rescan).

## Wiring rows
net internal cache seam (add); run flags (update); supervisor hook (update).

## Blocking edges
PR-0 (probe fns), PR-A (entry flags).

## Acceptance
Second consecutive run probes ~zero servers on cache hit; AvalAI run takes no lease when direct reachable; full suite green.
