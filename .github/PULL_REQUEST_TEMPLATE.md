<!--
  PR body template — HamZaboon.

  Fill every applicable section. The Dependency & Wiring Map is REQUIRED for
  any PR that removes/changes a feature, migrates, refactors, changes
  schema/callbacks, or changes module boundaries (AGENTS.md §2.4.2). CI runs
  the reverse-wiring guard (tests/test_wiring.py) and the dead-reference guard
  (tests/test_dead_code_guard.py); a row marked "keep"/"remove" without
  evidence blocks review.
-->

## Summary

<!-- One or two sentences: what this PR does and why. -->

## Behavior change

<!-- User-visible outcome. "None" if this is test/docs-only. -->

## Tests

<!--
  - Focused unit tests: <file names>
  - Integration tests: <file names, per AGENTS.md §6>
  - Migration covered on BOTH fresh DB and upgraded-from-prior-schema DB: yes/no
  - Full validation run: pytest -n 14 (local; CI uses -n 4) / compile_all / ruff F821,F811 / git diff --check
-->

## Dependency & Wiring Map (required if applicable)

| Dependency type | Items affected | Disposition (update / remove / keep) | Evidence |
|---|---|---|---|
| Callback prefixes | | | |
| Router branches | | | |
| Keyboard builders / constants | | | |
| DB tables / columns / functions | | | |
| Handler functions | | | |
| Imports / re-exports | | | |
| Prompts / formatting helpers | | | |
| Tests referencing them | | | |
| Docs (ROADMAP, AGENTS.md §3 map, issues) | | | |

## AI cost impact

<!-- Expected token/cost change, or "none" for test/docs-only changes. -->

## Notes

<!-- Anything the reviewer should pay attention to. -->

Resolves #<!-- issue number -->
