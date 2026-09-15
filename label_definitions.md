# HamZaban PR Label Standard

## Audit Context

- Repo: `Ham3dParsa/HamZaboonRobot` — Telegram language-learning bot for Persian speakers
- 200 PRs (475-697), **zero labels currently applied**
- Project uses AGENTS.md architecture: `bot.py`, `handlers/`, `services/`, `config/`, `factory/`, `tools/`, `tests/`, `docs/`
- `.github/labeler.yml` defines path-based auto-labeling but it is non-functional
- Existing labels on the repo are extensive but unused on any PR

## Label Dimensions

Each PR should receive **exactly one Type label** and **zero or more Domain labels** (plus optional special labels).

### Dimension 1: Type (REQUIRED, exactly one)

| Label | Description | Color reference |
|---|---|---|
| `type-feature` | New user-facing feature or capability | #a2eeef |
| `type-bugfix` | Bug fix correcting incorrect behavior | #d73a4a |
| `type-refactor` | Code restructuring without behavior change | #8110BA |
| `type-docs` | Documentation-only change | #0075ca |
| `type-chore` | Maintenance: deps, config, CI, build | #7057ff |
| `type-test` | Test additions or modifications | #5319e7 |
| `type-perf` | Performance optimization | #fbca04 |
| `type-design` | Architecture/design decision or pattern | #006b75 |

### Dimension 2: Domain (OPTIONAL, one or more)

| Label | Paths |
|---|---|
| `domain-bot` | `bot.py`, `config/keyboards.py` |
| `domain-handlers` | `handlers/` (non-bot routing) |
| `domain-ai` | `services/ai/**/*` |
| `domain-db` | `services/db/**/*` |
| `domain-session` | `services/session/**/*` |
| `domain-config` | `config/` (non-keyboard) |
| `domain-factory` | `factory/**/*`, `services/ai/preset_fields.py` |
| `domain-tools` | `tools/**/*`, `scripts/**/*` (non-CI) |
| `domain-tests` | `tests/**/*` |
| `domain-docs` | `docs/**/*`, `**/*.md` |
| `domain-deploy` | `supervisor.conf`, `start.sh`, `chabok-pre-start.sh`, deploy configs |
| `domain-ci` | `.github/**/*`, `requirements.txt` |
| `domain-utils` | `services/utils/**/*` |
| `domain-scheduling` | `services/scheduling.py` |
| `domain-tts` | `services/tts.py`, `tts_cache/` |
| `domain-quota` | `services/quota_service.py`, `services/grade_service.py` |
| `domain-activity` | `services/activity_log.py` |
| `domain-theme` | `config/themes.py`, `config/catalog.py` (theme catalog) |
| `domain-gamification` | Gamification features (streak, points, levels, quizzes, leaderboards) — manual application until dedicated module exists |

### Dimension 3: Special (OPTIONAL, zero or more)

| Label | When to apply |
|---|---|
| `i18n` | Changes affecting Persian language, RTL, localization |
| `UI/UX` | Changes to Telegram keyboard layouts, message formatting, user experience |
| `risk` | High-risk change: DB schema migration, security-sensitive, concurrency-critical |
| `blocked` | PR blocked by an external dependency or decision |
| `needs-verification` | PR needs focused verification/regression test before merge |
| `tech-debt` | Technical debt reduction with no user-facing change |
| `research` | Research spike or investigation PR |
| `decision` | ADR or decision record |
| `partial` | Partial implementation, requires follow-up |
| `accepted-risk` | Known risk accepted by owner |
| `obsolete` | Superseded or deprecated code/feature |

### Dimension 4: Priority (OPTIONAL, zero or one)

| Label | When to apply |
|---|---|
| `priority-high` | Critical path, blocks other work, or urgent user impact |
| `priority-medium` | Important but not blocking |
| `priority-low` | Nice-to-have or backlog |

## Rules

1. **Exactly one Type label per PR.** This is the primary classification.
2. **Zero or more Domain labels.** Use all domains the PR touches.
3. **Special labels only when clearly applicable.** Do not guess.
4. **Priority only when clearly stated in PR title/body.** Do not infer urgency.
5. **Do not use `phase-*` labels** (out of scope per owner instruction).
6. **Do not use standard GitHub labels** (`bug`, `documentation`, `enhancement`, etc.) — use the `type-*` equivalents instead to avoid confusion with the auto-labeler.
7. **If a PR spans multiple domains, list all** — this is the whole point of the taxonomy.
8. **For `type-chore` PRs**, always add `domain-ci` or `domain-tools` as appropriate.

## Inheritance from existing labels

| Existing label | Maps to | Notes |
|---|---|---|
| `bug` | `type-bugfix` | |
| `feature` | `type-feature` | |
| `documentation` | `type-docs` | |
| `bugfix` | `type-bugfix` | |
| `tech-debt` | `type-refactor` + `tech-debt` | |
| `research` | `type-design` + `research` | |
| `decision` | `type-design` + `decision` | |
| `i18n` | `type-feature` + `i18n` | If it's a feature, also tag i18n |
| `UI/UX` | Domain + `UI/UX` | |
| `risk` | Domain + `risk` | |
| `blocked` | `blocked` | Standalone |
| `priority-*` | `priority-*` | Unchanged |
| `phase-*` | **SKIPPED** | Owner instructed to ignore |
| `partial` | `partial` | Standalone |
| `accepted-risk` | `accepted-risk` | Standalone |
| `obsolete` | `type-chore` + `obsolete` | |
| `unsafe-lazy-init-pattern` | `type-bugfix` + `risk` | |
| `AI Presets` | `domain-ai` + `type-feature` | |
| `Ask A Word (Query)` | `domain-ai` + `type-feature` | |
| `fixture` | `domain-tests` + `type-test` | |
| `needs-verification` | `type-bugfix` or `type-refactor` + `needs-verification` | |
| `good first issue` | Keep as-is | Standard GitHub label |
| `help wanted` | Keep as-is | Standard GitHub label |
| `duplicate` | Keep as-is | Standard GitHub label |
| `invalid` | Keep as-is | Standard GitHub label |
| `question` | Keep as-is | Standard GitHub label |
| `wontfix` | Keep as-is | Standard GitHub label |

## Review Methodology

Each wave of 20 PRs is reviewed by a sub-agent that:
1. Reads the PR title, body, and changed files (via `gh pr view`)
2. Applies the label taxonomy above
3. Outputs a structured recommendation per PR
4. Notes any ambiguities or edge cases
