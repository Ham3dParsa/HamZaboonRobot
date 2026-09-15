<!--
  PR body template — HamZaboon.
  Fill what applies, delete the rest. Write plain words, no filler, no
  puffery (خلاصه فارسی هم قابل‌قبول است).
  The Dependency & Wiring Map is REQUIRED for any PR that removes/changes a
  feature, migrates, refactors, changes schema/callbacks, or changes module
  boundaries (AGENTS.md §2.4.2).
-->

## Summary

<!-- One or two sentences: what this PR does and why. -->

## Behavior change

<!-- User-visible outcome. "None" if test/docs-only. -->

## Tests

- [ ] Focused unit tests:
- [ ] Integration tests (per AGENTS.md §6):
- [ ] Migration covered on BOTH fresh DB and upgraded-from-prior-schema DB: yes/no/na
- [ ] Full validation: pytest / compile_all / ruff F821,F811 / git diff --check

## AI cost impact

<!-- Expected token/cost change, or "none". -->

<details>
<summary>Dependency & Wiring Map (required if applicable)</summary>

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

</details>

Resolves #<!-- issue number -->
