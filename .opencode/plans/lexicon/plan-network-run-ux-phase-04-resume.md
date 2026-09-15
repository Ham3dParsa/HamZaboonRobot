---
name: plan-network-run-ux-phase-04-resume
description: Positive --resume UX with plan print, refusals, flush-on-every-stop
created: 2026-09-15
base_commit: 926a19b
branch: TBD (feat/network-resume-ux)
status: locked
---
STATE: phase 0/6 — status: locked — focus: implement after PR-B and PR-C

## Scope
- `--resume` prints RESUME PLAN (per-stage done/todo from progress) then runs; 4 refusals: resume+no-resume, rekey keys missing from sample, corrupt progress (name file, suggest --no-resume, never auto-discard), `--only` with empty upstream. Every leg caller flushes then stops on RateLimited/ProviderCooldown/AuthError (extend S4 pattern). Chain may change between runs; provider_map keeps per-item actual model.
- Files: `factory/run.py`, `factory/precard/pipeline.py`, `factory/precard/judge.py`, `factory/precard/topics.py`, `tests/factory/test_factory_run.py`.

## Rules: R9.

## Tests
- Hermetic: plan print counts; each refusal errors by name; kill-mid-run (inject 429 at item k) then resume with different chain → items <k skipped, k retried on new model, zero re-billing of done items.

## Gates
R9. Resume key stays `(item_key + stage markers)`, never failed-only or cache-only.

## Wiring rows
Run flags (update); leg flush sites (update).

## Blocking edges
PR-B (chain), PR-C (cache lines in plan).

## Acceptance
Resume test green; corrupt-progress test green; full suite green.
