---
name: plan-provider-registry
description: Provider-as-data registry (protocol adapters, row routes, convention key refs, dynamic CLI) on the real precard line
created: 2026-09-21
base_commit: e959667
branch: refactor/provider-registry
status: in-progress
---
STATE: phase 4/4 — status: in-progress — focus: kilo-ci-loop on PR #797 (CI pending), merge on owner order

## Locked contract (owner chose each, "proceed" 2026-09-21)

- F1 transport by PROTOCOL (openai_compat/gemini_rest); new provider = row.
- F2 route as row field (registry owns judge-routing routes; TARGETS stays egress-owned).
- F3 key refs by {PROVIDER}_API_KEY_{GROUP} convention + legacy fallbacks.
- F4 CLI choices dynamic from registry (no hardcoded tuples).
- Callback impact NONE. Blast-radius: no structural trigger (new module +
  additive branches; net.py/transport untouched — edits only inside
  provider_transport.py additions, pipeline.py flag/gate/wiring, .env.example names).
- Seams claimed: `AI/LLM Provider` (branch refactor/provider-registry, F1-F4).

## Phases & evidence

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| 1 RED | registry tests (protocols/routes/refs/transports) | `complete` (8 collected, ImportError red) | tests/factory/test_precard_provider_registry.py |
| 2 GREEN | registry + openai_compat adapter + pipeline wiring + .env.example | `complete` (76 focused green) | factory/precard/provider_registry.py, provider_transport.py openai_compat_transport, pipeline.py gate/choices/wiring |
| 3 VALIDATE | pytest -n 14, compile_all, ruff F821/F811, diff-check | `complete` (3537 passed, 0 failed; compile 0; ruff clean; diff clean) | this run |
| 4 REVIEW+PR | hamzaban-reviewer gate → commit → push → PR | in-progress (round2: RED on process + F1-overclaim; fixed: gate narrowed to sense_judge, model guard, normalization, groq legacy var, key_var fallback; full suite 3541 green, 1 known flake solo-green) |

## Notes

- Groq/OpenRouter 5-call probes still need owner GO + exported key vars (GROQ_API_KEY_G1 etc. in the RUNNING shell; repo reads factory/.env + os.environ, never lab files).
- Groq route defaults direct (assumption; probe confirms or corrects the row).
- Unwired R3 row path noted earlier stays deferred (no preset rows inserted).
