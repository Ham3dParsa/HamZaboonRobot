# Reviewer Gate — fixed invocation template

Single source of truth for every `hamzaban-reviewer` call (AGENTS.md §6.3).
Copy this template verbatim. Fill only the bracketed raw inputs.
Do not add, remove, or rephrase fields.

## Request template

```text
Review target: [worktree path + branch + base, e.g. origin/main]
Scope: [files changed, one per line]
Full diff ref: [e.g. git diff origin/main...HEAD, full scope, not incremental]
Locked contract: [paste numbered rules verbatim]
Behavior spec: [paste spec or plan section verbatim]
Focus checks: [wiring / quota / restart safety / hermeticity, as applicable]
```

Banned in the request: verdict words and pre-answers.
Never write: PASS, verified, untouched, already reviewed, benign, else ignore.
Carry only raw inputs. No claim, no conclusion.

## Reviewer output contract

Prove-correct per locked rule. Re-derive every claim from diff plus grep.
One table row per rule. A missing row means the gate is red.

| Rule | Verdict | Evidence (file:line) |
|------|---------|----------------------|
| R.. | hold / confirmed-finding | [path:line + grep or test name] |

Close with exactly one line: `GATE: PASS (0 confirmed findings)` or
`GATE: RED (N confirmed findings)` followed by the finding list.
```

Base directory for this skill: C:\Python_Programming\#T-Bot\HamZaban\.opencode\skills\reviewer-gate
