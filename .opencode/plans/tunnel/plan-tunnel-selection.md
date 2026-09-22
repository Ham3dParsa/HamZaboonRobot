---
name: plan-tunnel-selection
description: Ticket breakdown for the locked provider-aware tunnel-selection build
created: 2026-09-22
base_commit: e4f7468
branch: feat/linker-judge-webui
status: complete
---

STATE: phase 6/6 — status: complete (2026-09-22, no commit) — all tickets T1–T8 implemented across phases 01–06 (each phase file holds its own evidence STATE); build closed by T8, no commits per owner order

# Tunnel-selection build — ticket plan (docs only, no code)

Source: `C:\Users\HamedParsa\AppData\Local\Temp\opencode\tunnel-selection-design.html`
(5-step owner cycle, deep-module discipline, §3 `TunnelSelector`, §8 migration order, §9 rejections).
Anchors: work branch `feat/linker-judge-webui` (`factory/linking/google_clean.py`,
`factory/linking/probe_providers.py`, WebUI server), egress supervisor + lease policy
(`tools/egress/supervisor.py`, `factory/precard/provider_lease_policy.py`).

## Locked rules R1–R7 (owner-locked, amendment applied everywhere)

- **R1** — One permanent module: `factory/net/tunnel_selection.py`, class `TunnelSelector`. One fix point forever.
- **R2** — 3-method interface only: `select(provider)`, `prove(provider, exits)`, `remember(provider, exit_id, latency_ms)` with the §3 contracts (`NoTunnelExit`, `unknown`-vs-`blocked`, best-effort `remember`). Callers and tests cross this seam, never internals.
- **R3** — Exactly two adapters: `SubscriptionSource` (subscription refresh) and `ProviderProbe` (per-provider probe shape). Ping, dedup, latency ranking, cache writers stay **internal**; no carrier/lease/distributed-cache adapter.
- **R4** — Paid-first ordering everywhere (refresh + ping + prove) **and PROVIDER-AWARE cache** (amendment, overrides any global-cache text): each provider keeps its own whitelist — a Google-clean exit list is separate from a Groq-clean list; never one global cache. Cache rows carry id + timing only, no links/keys.
- **R5** — `batch=5`, `keep=5` as injectable defaults, never hardcoded. `prove` runs batches of max 5 in priority order with early stop at `keep` clean; `remember` never-overwrites-with-empty.
- **R6** — Migration order, behavior-safe: probes → linker → precard → pilot → web last. Old caller path deleted in the **same PR** it migrates (no parallel paths). Registry untouched (no forced migration — `registry_fn` injection, default stays on `TARGETS`). Forbidden zone untouched (screening functions, evidence strings, ranking internals, `linker.py` core, `TARGETS`/key semantics, `leases.jsonl` audit, `xray`/carrier). Batch and concurrency semantics untouched (locked debt, out of scope).
- **R7** — Rejections stand: no supervisor god-module, no per-caller copies, file cache (no SQLite/service), keyless Google probe (`models:list`, never billed), supervisor self-start only at run entry (`factory/run.py`), lock covers decisions only — ping/network outside the lock.

## Ticket list with priorities

| Ticket | Phase file | Priority | Serial / parallel | Locked rules |
|--------|-----------|----------|-------------------|--------------|
| T1 module skeleton + 3-method seam | phase-01 | P0 (blocks all) | Serial root | R1, R2, R7 |
| T2 provider-aware store + paid-first subscription adapter | phase-01 | P0 | Parallel with T3 after T1 | R3, R4 |
| T3 prove batch-5/keep-5 loop + two-adapter proof | phase-01 | P0 | Parallel with T2 after T1 | R3, R5, R4-cache-read |
| T4 probes migration (`probe_providers`/`probe_keys`, `--probe` flags) | phase-02 | P1 | Serial gate (first + lowest-risk caller) | R6, R2, R3 |
| T5 linker migration (`google_clean` → adapters) | phase-03 | P1 | Serial (after T4) | R6, R3, R4 |
| T6 precard migration (pipeline/judge/topic + `run.py`) | phase-04 | P2 | Serial (after T5, busiest path) | R6, R2 |
| T7 pilot migration (`card_pilot.py` + optional `blind50`) | phase-05 | P2 | Serial (after T6) | R6, R2 |
| T8 web-last migration (linker WebUI + precard viewer) | phase-06 | P3 | Serial (after T7, closes build) | R6, R7 |

Domain language: module (`factory/net/tunnel_selection.py`), interface (`select`/`prove`/`remember`), seam (the 3-method boundary every caller and test crosses), adapter (`SubscriptionSource`, `ProviderProbe`). Provider-aware cache is restated in every ticket it touches (T2, T3, T5, T6).

## Wave plan (max 2–3 workers, dependency justification)

- **Wave 0 — T1 alone (1 worker, serial).** Locks the interface seam file all others import. No parallel work can start without the seam signatures.
- **Wave 1 — T2 ∥ T3 (2 workers, parallel).** Both consume only the locked T1 signatures; T2 owns the provider-aware store + subscription adapter, T3 owns the prove loop + probe adapter — disjoint internals, no shared files except the T1 seam (read-only). Fits the 2–3 worker budget.
- **Wave 2 — T4 alone (serial).** Locked R6 gate: probes are the lowest-risk caller and prove the module live; old probe path stays until green, then is deleted in the same PR.
- **Wave 3 — T5 alone (serial).** Converts the worktree `google_clean` helpers into official adapters; touches the same seam as T4 did, so parallel migration would collide on adapter ownership and violate R6 order.
- **Wave 4 — T6 alone (serial).** Busiest path (`ensure_supervisor`, `call_leg` become callers only); serial because a precard regression blocks pilot/web validation.
- **Wave 5 — T7 alone (serial).** Pilot `urllib` direct calls route through the interface; serial because it depends on precard's stabilized adapter behavior.
- **Wave 6 — T8 alone (serial).** Display layer last; serial because it depends on all four prior callers being on the seam, and per R7 no domain logic may leak into the server.

Why not more parallelism: every migration ticket (T4–T8) mutates the same module seam plus its own caller, and R6 mandates a strict caller order with same-PR old-path deletion — two workers migrating two callers at once would race on the seam and break the behavior-safe rollback story. Batch/concurrency semantics are locked out of scope, so no worker can "speed up" another by touching them.

## Test-first discipline (all tickets)

Red-green-refactor: failing hermetic test first (`tests/factory/test_tunnel_selection_*.py`, fake sub source + fake probes + tmp store, injected `clock`), then minimal implementation. Live tests are gated (explicit env flag + provider + batch cap, free probes only) and never run in CI default. No test may touch `xray`, real ports, lock internals, or screening/evidence internals.

## Out of scope (locked debt, never in a ticket)

Registry migration, batch/concurrency rework, SQLite/service cache, carrier/protocol adapters, screening/evidence/ranking internals, `TARGETS`/key semantics, audit format, any AI-call volume change.

## Parked ambiguities (not decided — owner calls at implementation lock)

1. Exact per-provider cache file layout (one JSON with provider keys vs. one file per provider) — tickets require provider-aware behavior, not layout.
2. Paid-source labeling mechanism (source tag on server rows without leaking subscription values) — tickets require the tag, not its encoding.
3. `ping_budget` / `LEASE_PING_MAX_ROWS` numeric values — tickets treat them as injected caps, values set at contract lock.
