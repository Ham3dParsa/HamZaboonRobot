---
name: plan-precard-v141-fanout
description: PreCard pipeline v14.1 blocker resolution + P1 fan-out (R1-R6)
created: 2026-09-14
base_commit: b335a0f
branch: fix/precard-v141-fanout
status: in-progress
---
STATE: phase 4/4 — status: in-progress — focus: independent review + code-review, then commit

## Locked rules (owner chose all Recommended, 2026-09-14)
- R1 true fan-out: 1 lemma -> N precard rows, own pre_card_id/topic/CEFR/IPA/examples
- R2 fail-closed: structured drop for every token, zero failed-no-entry
- R3 example fallback chain: sense -> lemma -> pool -> synthetic-flag, never empty A1-B1
- R4 inflection-review reason: strict concise English, max 12 words
- R5 topic guardrails: prompt tie-breaker + deterministic post-guard (abstract + gender)
- R6 diff reporter: side-by-side N precards per lemma

## Phases
| Phase | Scope | Evidence | Status |
|---|---|---|---|
| 1 | Failing tests R1-R6 (new tests/test_precard_v141.py) | pytest tests/test_precard_v141.py (14/14) | complete |
| 2 | Implement R1-R6 in factory/pipeline/{precard_pipeline,card_pilot}.py | files + tests green | complete |
| 3 | Full validation (pytest, compile_all, ruff, diff-check) | command outputs | complete (2 integration flakes pass solo; ruff/compile/diff clean) |
| 4 | Independent review + code-review, fix, commit | reviewer verdict + sha | in-progress |

## Notes
- Factory-only change; no callback/router/keyboard/DB-schema touch (no wiring test needed).
- Extend existing modules only (no new module).
- Claims registry: no factory seam in SEAMS.md; no claim acquired.
- Review 2026-09-14 (hamzaban-reviewer): 0 confirmed findings.
- Deliberately not done: wiring render_lemma_fanout into render_gallery
  (gallery consumes rec+card pairs, not precard rows — follow-up ticket).
