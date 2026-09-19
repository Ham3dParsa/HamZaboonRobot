---
name: plan-run-leg-e
description: T-RUN-E single rotation helper run_leg.py over net policy, no semantic change
created: 2026-09-19
base_commit: 3c567f4
branch: feat/run-leg-e
status: in-progress
---
STATE: phase 4/5 — status: in-progress — focus: reviewer gate, then commit
(State 2026-09-19: phases 1-3 complete. Focused: run_leg/loops/net/
telemetry 126 passed; topics/judge/registry/enrich/factory_run 110
passed. Full: 3266 passed, 1 flaky load-sim-5k — passes solo, unrelated.
compile_all + ruff F821/F811 + diff-check clean. graphify updated.
Reviewer round 1: GATE RED, 1 confirmed finding (R8 falsy-provider
walk divergence). Fixed: plan() passes raw provider to switch_plan;
test pins empty walk + mixed-case. Reviewer round 2: all hold, R24
graph-coverage finding. Fixed: graphify updated post-fix,
built_at_commit == HEAD, run_leg 21 nodes indexed. Blast radius:
plan() degree 16 — callers exactly 4 legs + 6 tests, calls only net
policy fns; cooldown_continues same 4 legs. Full suite re-run pending.)

## Locked contract (owner freed blockers 2026-09-19; lowest-risk pick PR-E)

- Scope: new `factory/precard/run_leg.py` (thin helper over existing net
  policy) + call-site thinning in `factory/precard/judge.py`
  (inflection_review, sense_judge) + `factory/precard/topics.py`
  (topic_label, topic_vectors); read-only use of `factory/precard/net.py`
  (`leg_chain`/`switch_plan`/`call_leg`). Legs keep prompt + validate.
- Non-goals: no policy/model/prompt/cost change; prompts byte-identical
  (`tests/factory/data/precard_prompts_v1.snapshot.json` unchanged);
  no pipeline.py/run.py touch (neighbor PR-C lane); no viewer touch.
- Acceptance: hermetic rotation/cooldown/telemetry test without network;
  full suite green; reviewer gate 0 confirmed findings.
- Module guard fallout: update AGENTS.md §4 table +
  tests/test_wiring.py scan targets + SEAMS.md + `graphify update .`.

## Phases (evidence-gated)

| # | Step | Evidence |
|---|---|---|
| 1 | Read 4 loops + call_leg fully | notes below |
| 2 | Hermetic red test `tests/factory/test_precard_run_leg.py` | pytest red run |
| 3 | `run_leg.py` green + thin 4 call sites | pytest green, diff |
| 4 | Full suite + compile + ruff + diff-check + reviewer gate | logs, reviewer verdict |
| 5 | Commit + push + PR + kilo loop to OC APPROVED | PR URL, checks |

## Reading notes (phase 1)

- Walk skeleton identical in all legs: switch_plan-filtered providers →
  base_models or leg_chain → ring/target/key_var → MAX_ATTEMPTS with
  RETRY_PREFIX → call_leg → exception taxonomy → validate → settle.
- Side effects differ per leg (telemetry fn names, auth handling,
  terminal fallback semantics) → seam: helper owns walk + call +
  classification, legs own ALL side effects via per-event handling.
- inflection (judge.py:440-679): sys-prompt transport adapter,
  R8 precheck, review tele fns, per-item review-fallback on unsettled.
- sense_judge (judge.py:743-869+): bare AuthError raise, _tele_record,
  _attempts hook, returns out on valid.
- topic_label / topic_vectors (topics.py): record_call, best-model
  tracking. REMAINDER TO READ before seam freeze.
