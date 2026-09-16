---
name: plan-network-run-ux-phase-01-entry
description: Thin factory/run.py entry with presets and CLI/env config resolution
created: 2026-09-15
base_commit: 926a19b
branch: TBD (feat/network-run-entry)
status: merged
---
STATE: phase 3/6 — status: merged — PR 713 squash 22ee58d (HEAD 96562e1, OpenCode APPROVED zero-blocking, Kilo merge, 7/7 CI pass)

## Scope
- New `factory/run.py`: composes supervisor client + probes + `pipeline.main`. Presets avalai/google/zen. Flags: `--preset --llm-provider --stage-provider --precard-model --judge-model --stage-model --sample --out --progress-dir --limit --sleep-secs --cooldown-secs --max-429-strikes --egress-mode --sup-url --sup-token --sup-port --no-sup-spawn --probe-top-n --cache --dry-run --yes --quiet --json-log --no-color`, each with `FACTORY_*`/`EGRESS_*` env mirror. Precedence CLI>env>preset>default, printed in `--help`. Keys never flags.
- Files: `factory/run.py` (new), `tests/factory/test_factory_run.py` (new), `factory/README.md`.

## Rules: R1 R2 R3 R4.

## Tests
- Hermetic: precedence matrix (flag beats env beats preset beats default), preset expansion table, `--list-models` output, `--dry-run` no-network-no-write, spawn refused when `--no-sup-spawn`.

## Gates
R1 R2 R3 R4. Auto-spawn prints pid+port; health-check first.

## Wiring rows
New module (add); pipeline/supervisor untouched (compose only); docs runbook (update).

## Blocking edges
PR-0 (needs home probe fns + health signal).

## Acceptance
Both example runs (avalai-direct, google-tunnel) work from one command; `--dry-run` green; full suite green.
