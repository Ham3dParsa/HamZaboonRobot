# HamZaboon Agent Guidance

This document is the repository-level operating agreement for AI coding
agents, Devin sessions, and human contributors working on HamZaboon. Follow it
alongside the repository README, `ROADMAP.md`, and the user's explicit request.
If those sources conflict, follow the more specific and more recent
instruction.

**SESSION START PROTOCOL**: At the start of every new session or major task,
silently verify or explicitly output the **Appendix A** checklist to refresh
context-window constraints before proceeding.

_Last updated: 2026-08-14._

## 1. Product Context

HamZaboon is a Telegram-based language-learning assistant for Persian-speaking
learners. Its MVP provides:

- AI-generated vocabulary cards and grammar tips.
- Daily learning content with SQLite persistence.
- Manual and scheduled delivery.
- Saved words with simple spaced repetition.
- Language, goal, and level preferences.
- Free, Silver, and Gold plan limits.
- Owner-only administration and per-user plan assignment.

The product prioritizes:

1. Educational usefulness and safe, understandable Telegram UX.
2. Predictable AI and Telegram resource usage.
3. Durable state and restart-safe background work.
4. Correct quotas, dates, and idempotency.
5. Adding languages and learning goals without duplicated registries.

All learner-facing educational content must remain AI-generated through the
existing prompt and validation flow. Do not replace that flow with
hard-coded lesson content unless the user explicitly requests a product
change.

## 2. Source-of-Truth Documents

The repository deliberately separates product planning from engineering
findings:

| File | Responsibility | Normal editing rule |
| --- | --- | --- |
| `ROADMAP.md` | Product direction, phases, locked decisions, acceptance criteria, and remaining work. | Curate it when meaningful implementation or product scope changes. |
| [GitHub Issues](https://github.com/Ham3dParsa/HamZaboonRobot/issues) | Canonical structured issue registry (features, bugs, risks, tech-debt, research, decisions). | Create and update via `gh issue create`/`edit`/`close`. Labels encode category, priority, and phase. |
| `project_status.json` | Canonical machine-readable phase, dependency, and decision-lock index. | Update it when phase status, assignments, or locked decisions change. |
| `issues/project_status.html` | Read-only dashboard generated from `project_status.json`. | Regenerate with `python scripts/generate_dashboard.py`. Never edit directly. |
| `docs/vision_and_product_goals.md` | Product vision, strategic goals, and target audience. | Curate when strategic direction or goals change. |
| `docs/plans/` | Implementation plans grouped by dependency theme. | Archive superseded plans to `docs/archive/`. |
| `docs/audit/` | Read-only audit reports and architecture alignment blueprints. | Keep evidence-cited. |

`project_status.json` is authoritative for phase/decision status. GitHub Issues
are authoritative for individual issue state. HTML `localStorage`, embedded
fallback data, and generated views must never be treated as canonical state.

### 2.1 Issue update policy

For a meaningful code change: identify the relevant issue IDs before
implementation; update the corresponding GitHub Issue with an accurate
`status`, `roadmap_refs`, concise evidence, and `last_reviewed` (`YYYY-MM-DD`);
update `ROADMAP.md` and `project_status.json` as required by §2, then run
`python scripts/generate_dashboard.py`. Statuses: `open`, `partial`,
`resolved` (implementation + focused verification), `accepted-risk`,
`obsolete`. Never mark an issue resolved based only on intention, a roadmap
statement, or an unverified code edit.

### 2.2 Logic-lock and bilateral-approval rule

The agent **IS FORBIDDEN FROM** inventing missing algorithmic behavior,
silently widening scope, or locking a product/architecture decision to close an
inferred gap. This applies to **ANY behavioral change including bug fixes**.
Before changing learner-facing behavior, persistence semantics, quotas,
scheduling, callbacks, AI contracts, or module boundaries, the agent must
follow the gate protocol in §2.4.

After implementation, report what changed, what was deliberately not changed,
and what remains uncertain. Debugging must target the demonstrated root cause;
opportunistic "extra fixes" or speculative hardening are out of scope unless
explicitly approved. If a safe workaround exists, document it rather than
silently converting it into a permanent product rule.

**Bounded cleanup allowance:** A PR MAY delete provably-dead code in the files
it already touches — where "provably dead" means zero references anywhere else,
verified by grep or a test — provided the removal is declared in the contract
lock summary and does not change behavior. Speculative refactors, cleanup of
untouched files, or deletions with any behavioral ambiguity still require
explicit owner approval.

### 2.3 Owner contract-locking protocol

When a requested behavior contains multiple algorithmic or product rules, do not
ask for one blanket approval. Decompose the behavior into separately numbered
rules, each presented with a recommended option plus meaningful alternatives in
a comparison table. The owner must choose each rule independently. After
implementation, report which locked rules changed, which were deliberately not
changed, and what remains uncertain; verify each rule with focused tests or
other concrete evidence.

### 2.4 Mandatory Pre-Implementation Contract Lock Gate

**BEFORE ANY CODE CHANGE—exploratory, trivial, bug fix, or major—the agent MUST
run the contract-lock gate: stop and identify gaps, present each as a numbered
rule with a recommended option + ≥1 alternative in a comparison table, obtain
explicit owner choice per rule, summarize the locked contract with the template
below, and confirm the owner says "proceed" or "locked" before touching code.**

The full protocol — the 8-step sequence, callback-routing impact assessment,
the Dependency & Wiring Map (§2.4.2), and the fast-track exception (§2.4.1) —
lives in the `contract-lock-gate` skill. **Load it before any code change.**

> **Owner experience note:** The owner is not a professional developer. Explain
> each option in plain, non-jargon language; state what it does in practice,
> what it costs, and why the recommended option is preferred.

**VIOLATION CONSEQUENCE**: If the agent implements without a LOCKED gate, the
owner may discard all uncommitted changes, require full rework from the gate,
and/or terminate the session. No exceptions.

**GATE KEYWORD**: The agent must include
**`<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>`** in
its response before any implementation.

#### Contract Lock Template (agent must fill completely)

```
## CONTRACT LOCK TEMPLATE (agent must fill completely)

Rule #: [N]
Decision: [one-line description]
Option Chosen: [A/B/C...]
Alternatives Rejected: [list with one-line reason each]
Trade-offs: [cost/UX/compatibility/regression per alternative]
Owner Confirmation: [quote owner's "proceed" or "locked"]
GATE STATUS: [LOCKED / PENDING]
```

#### 2.4.2 Dependency & Wiring Map

Required when the change removes/changes a feature, migrates, refactors,
changes schema/callbacks, or changes module boundaries. Full template and
verification rule: see `contract-lock-gate` and `callback-wiring` skills.

#### 2.4.1 Fast-track exception

Strictly non-behavioral changes (typos, comments, docs, formatting, test-only)
MAY skip the full comparison-table gate. Under the `<SYSTEM_GATE>` keyword,
state what the change is, why it is non-behavioral, and that it proceeds
without a locked contract. Applies only when there is zero ambiguity about
learner-facing behavior, persistence, quotas, scheduling, or module boundaries.

## 3. Repository Architecture

Keep responsibilities aligned with the current module boundaries:

- `bot.py`: Thin entry point; Telegram handlers, callback routing, jobs, delivery orchestration, and user-facing formatting.
- `services/routing.py`: **Central callback routing registry** (R1). Exports `ROUTES`, `register(prefix, handler, owner_only=False)`, and `dispatch(update, context, data)` with longest-prefix match, owner-gate, and the R8/B1 single-answer guarantee (`_invoke_and_ensure_answered`). Admin (`admin:`/`llm:`) domains are registered here from `handlers/admin.py` at import time; the callback answer is collapsible to exactly one `query.answer` per callback.
- `handlers/`: Telegram handler modules.
  - `handlers/admin.py`: Admin panel **thin dispatcher** — registers the coarse `admin` (owner-gated) and `llm` routes in `services/routing`, delegates `admin:` to `_handle_admin_callback` by prefix to the domain sub-routers below, text-input awaiting dispatch (`_handle_admin_text_input`), and admin-infra handlers (backup/restore, broadcast, phonetic / log-level / user-activity settings).
  - `handlers/admin_stats.py`: Admin **stats** sub-router (`handle_admin_stats`).
  - `handlers/admin_plans.py`: Admin **plans** sub-router (`handle_plan_callback`), plan wizard, plan keyboards.
  - `handlers/admin_cost.py`: Admin **LLM cost / pricing** sub-router (`handle_cost_callback`, `_handle_llm_callback`).
  - `handlers/admin_ai.py`: Admin **AI presets / fallback / custom-test** sub-router (`handle_ai_callback`).
  - `handlers/user.py`: User settings handlers (language, goal, level).
  - `handlers/help_command.py`: User **help** module — `/help` + "راهنما" panel (`send_help_panel`), inline help-section callback dispatch (`handle_help_callback`), content-driven `HELP_SECTIONS` registry.
  - `handlers/srs_handler.py`: SRS review handlers.
- `services/`: Domain services.
  - `services/db/`: SQLite schema, migrations, transactions, persistence, quotas, daily-card state, delivery queue state, saved-word state, plan-spec state. `services/db/__init__.py` is a thin re-export façade + shared helpers; `schema.py` owns schema/migrations, `plans.py` seeds and CRUDs `plans`, `settings.py` owns settings accessors, `cost_tracking.py` owns LLM cost analytics, `preset_registry.py` owns AI preset/fallback/hourly-usage logic.
  - `services/fsrs_core.py`: Pure FSRS-6 engine (w0-w20 constants, DSR formulas, no side effects).
  - `services/word_query.py`: Pure orchestration core for the custom-word query flow — `ask` (validate→reserve→AI→persist), `toggle_save`. Stateless over `services/db/*` + `validation`; no Telegram imports. Handlers (`bot.py` ask-word block, `handlers/srs_handler.py` toggle) stay thin adapters.
  - `services/ai/`: OpenAI-compatible client, provider settings, JSON extraction, AI response validation, system prompts, AI content generation, provider presets.
  - `services/utils/`: `callback_notifications.py` (callback-query seam), `formatting.py` (escaping interface), `helpers.py` (retry, cancel detection), `validation.py` (`validate_word_query(text, language) -> Optional[error_key]`).
  - `services/scheduling.py`: Pure session sizing, slot planning, timezone-aware planned timestamps.
  - `services/tts.py`: Text-to-Speech generation (Edge TTS).
  - `services/session/`: Pure FSRS session engine. `__init__.py` (`build_session_list()`, `generate_tier3_node()`, `SessionNode`); `assembly.py` (3-tier assembler; `generate_tier3_node()` is a stub pending Phase 3b+); `grade_policy.py` (`GradePolicy`, `GRADE_POLICIES`, `resolve_grade()`).
  - `handlers/study_handler.py`: Study-session handler (`handle_study_start()`, `advance_session()`).
- `config/`: `config/__init__.py` (environment/deployment settings; not a second learner-option registry), `config/catalog.py` (canonical language/goal/level metadata), `config/keyboards.py` (menus + callback identifiers).
- `tests/test_integration/`: Handler-level integration tests. `tests/test_integration/helpers.py` shared helpers.
- `.github/workflows/ci.yml`: CI — lint, compile, tests, dashboard generation, whitespace checks on push/PR to `main`.

Prefer extending an existing module and convention over introducing a new
abstraction. Keep runtime behavior separate from issue-review tooling.

### Module change guard

If the module structure changes (add, rename, split, or remove), update the
responsibilities table above AND the scan-target paths in `tests/test_wiring.py`,
and keep `.opencode/skills/parallel-work-guard/SEAMS.md` current.

### Callback Routing Map

The full callback-prefix → handler → entry-function map is maintained in the
`callback-wiring` skill. Load it before adding/changing any callback prefix or
keyboard; it also holds the §2.4.2 Dependency & Wiring Map template and the
wiring/verification guards.

### Catalog rule

Language, goal, and level identifiers and learner-facing metadata belong in
`config/catalog.py`. Do not create parallel dictionaries elsewhere. New options
must: use stable identifiers; be represented in the canonical catalog; be
consumed by menus, prompts, validation, and fallbacks; include focused
consistency tests; preserve compatibility with existing stored IDs and
callbacks.

### Reliability rules

Preserve these established contracts when changing runtime code:

- Use `APP_TIMEZONE` for application-day calculations; UTC timestamps for processing metadata where appropriate.
- Keep AI calls behind the global concurrency/request limiter; never run blocking synchronous provider calls directly on async Telegram handlers.
- Keep an explicit AI timeout.
- Route scheduled delivery, SRS, and broadcasts through the shared Telegram retry/concurrency path.
- Delivery queue retries must remain bounded, back off through `retry_at`, and become terminal after the configured attempt budget.
- Quota checks that reserve usage must be atomic.
- Saved-word writes must remain normalized and idempotent.
- Preserve restart safety; avoid duplicate cards, messages, or provider requests whenever the state model supports it.
- Do not expose API keys, bot tokens, or secrets in code, logs, tests, commits, issue evidence, or PR descriptions.
- **API key storage pattern:** All AI API keys are stored **encrypted at rest**
  using the `cryptography` Fernet cipher, protected by `AI_MASTER_KEY`.
  `services/db/key_crypto.py` owns encryption/decryption/masking
  (`encrypt_for_storage`, `decrypt_secret`, `mask_key`); every write crosses the
  encrypt seam and every resolve crosses the decrypt seam. Behavior is
  **fail-closed**: a missing/invalid master key means nothing is encrypted and
  nothing resolves (empty key), never a plain key in the DB or logs. `AI_MASTER_KEY`
  is required; document new env vars in `.env.example`.
- SQLite concurrency: all writes must use context managers with
  immediate/exclusive transactions where write contention is possible, to avoid
  `database is locked` during concurrent callback bursts. Never hold an open
  transaction across an awaited async call (AI/Telegram); commit or roll back
  first.

### AI Cost Discipline

When adding or modifying AI-calling code paths, state the expected
token/cost impact as part of the contract lock summary. Prefer reusing cached or
pooled content over issuing a new AI call. Flag any change that measurably
increases per-user or per-day AI call volume as requiring explicit owner
approval, even if it would otherwise qualify for the fast-track exception.

### Localization & Escaping Rules

All learner-facing text must be in correct, natural Persian. Do not mix
machine-translated or placeholder English strings into user-visible messages.
Every dynamic value from the AI, the database, or user input **MUST pass through
`services/utils/formatting.py`** before interpolation into any MarkdownV2
template in `bot.py`. The full escaping contract lives in the
`persian-formatting` skill — load it before adding or modifying any
learner-facing message.

## 4. Audit and Code-Review Workflow

When asked to audit or review the project, load the `audit-workflow` skill and
follow it: read the source-of-truth documents (§2), inspect modules and tests,
trace data/control flow across handlers, callbacks, AI calls, SQLite
writes/migrations, delivery/retries, timezone boundaries, and quotas; compare
each issue with current code evidence; classify findings; record as GitHub
Issues; reconcile `ROADMAP.md`; run focused plus repository-wide checks. When
investigating a targeted change, read the specific function and its direct
dependencies first; expand scope only as evidence demands. If a product or
safety decision cannot be inferred, ask one focused question.

## 5. Implementation Workflow

Core discipline (full mechanics in `git-protocol`, `tdd-enforcement`,
`integration-test-proto`, `plan-persistence` skills — load them when their
trigger matches):

0. **Contract lock confirmed per §2.4 (Mandatory Pre-Implementation Contract Lock Gate) before any code change.**
1. Create a fresh feature branch from the latest `origin/main` (`type/short-desc`). **Must** work in an isolated git worktree (via `using-git-worktrees`) instead of the shared main workspace; run the `parallel-work-guard` seam check (§10.5) before locking and before starting work.
2. Write focused tests from the user-facing behavior spec and the locked contract, not from implementation internals. Behavioral changes (handlers, keyboards, DB writes, quotas, AI, callbacks) require `tests/test_integration/` tests and, for callback/router changes, a `tests/test_wiring.py` wiring-integrity test.
3. Stage explicitly (`git add file1.py file2.py` — never `git add .`); commit with Conventional Commits (`type(scope): subject`); push and open PR via `gh pr create --fill --base main`, linking resolved issues.
4. Owner merges via **Squash and merge**; on explicit "merge it", the agent may `gh pr merge --squash` after confirming CI passes. Then clean up the worktree, delete the branch, release the parallel claim, and update issues/ROADMAP per §2 + §8.
5. Do not combine unrelated user-facing features, broad refactors, and issue cleanup in one PR; record out-of-scope issues instead.

### Kilo Code Review PR Loop

Every PR triggers an automated **Kilo Code Review** (comment + a `Kilo Code
Review` check). Follow this loop for every behavioral PR:

1. **Before opening the PR**, rebase the worktree onto the latest `origin/main`
   if it has diverged (`git fetch origin` + rebase), so the PR is clean.
2. Make the **PR body informative**: summary, the locked rules/decisions, what
   changed, review comments addressed (if any), test evidence, and the source
   report/issue. Do not rely on the bare commit message.
3. **Address every Kilo comment** (CRITICAL/WARNING must be fixed or explicitly
   waived with rationale; SUGGESTIONS should be fixed or justified). Push a
   follow-up commit; do not force-push over the review.
4. **Wait for Kilo to re-review, then fetch the comment delta.** Important:
   Kilo does **NOT** always post a brand-new comment after you push fixes —
   sometimes it only updates its prior review/check. Always re-fetch the review
   (and the `Kilo Code Review` check status) to read the delta, rather than
   waiting for a fresh comment to appear.
5. When the Kilo comments are **fixed/addressed via your subsequent commit(s)**
   and the `Kilo Code Review` check passes (and CI is green), **Merge** (squash
   per step 4 above). Do not leave the PR open waiting for a new comment that
   may never come.
6. **Post-merge**: clean up the worktree, delete the branch (remote + local),
   release the parallel-work claim, update plans/ROADMAP/issues per §2 + §8, and
   **rebase onto `origin/main`** before starting the next dependent job.

This loop lives in `writing-for-agents` spirit: it is the canonical, repeatable
PR-review routine; bake it into every AI-track / architecture-deepening job.

### Independent Review Subagent (mandatory for non-trivial changes)

Before committing any change that affects behavior, persistence, quotas,
scheduling, callbacks, AI contracts, module boundaries, or a schema migration,
the implementing agent MUST launch the read-only `hamzaboon-reviewer` subagent
(§10.3) with fresh context. The reviewer assumes the implementation is wrong
until proven correct, checks the diff against the locked contract and behavior
spec, and reports only. The implementing agent fixes confirmed findings and
re-runs until none remain. If the reviewer surfaces a genuine ambiguity or
product decision, resolve it per §2.4. Trivial, non-behavioral changes skip
this step.

| Change scope | Reviewer required? | Default model |
|---|---|---|
| Trivial (1–2 line behavioral swap, doc/string fix) | Skip, or cheap model | Tencent Hy3 (free) via Kilo Gateway |
| Schema / callback / quota / AI / multi-file | Full independent review | Override to a stronger model per run |
| Non-behavioral (typos, comments, docs, formatting) | Skip (fast-track) | N/A |

## 6. Required Validation

Two tiers, chosen by change scope (full mechanics in the `hamzaban-validation`
skill — load it before committing or opening a PR):

- **Full suite** (behavioral: handlers, DB, callbacks, AI, quotas, schemas, production `.py`): `pytest`, `compile_all.py`, `ruff F821/F811`, `generate_dashboard.py`, `git diff --check`.
- **Lightweight path** (non-behavioral: docs, skills, agents, plans, formatting, comments, test-only): `git diff --check` only.

**Locked test worker rule:** local runs MUST use `python -m pytest tests/ -n 14`
(24 logical cores; `-n 14` is the fast-and-stable count). The CI count (`-n 4`)
is only for matching GitHub Actions output exactly. Never use `-n 14` in CI.

**Integration Test Protocol:** behavioral changes MUST add/update handler-level
integration tests in `tests/test_integration/` per the `integration-test-proto`
skill (database snapshot isolation, mocked Telegram, AI mocking budget,
contract-lock requirements for new tests). Load it before writing integration
tests.

**Handling Broken or Outdated Tests:** the agent MUST NOT silently delete,
disable, or ignore a failing test. It MUST NOT revert correct code just to make
a test pass. Determine whether the failure is a bug or an intentional logic
change; if intentional, update/rewrite the test to reflect new canonical
behavior. If uncertain whether it is a regression or an obsolete expectation,
halt and ask the owner per §2.4.

Do not claim CI success from local tests. Report CI based on the repository
checks after the PR is opened.

## 7. Git and Security Discipline

**BEFORE ANY COMMIT, the agent MUST run the pre-commit gate: full/lightweight
validation suite per §6, `git diff --check` and `git diff --staged --check`
clean, no secrets in staged changes, single logical change, Conventional
Commits, explicit staging, correct branch naming. Full checklist and the Error
Recovery Protocol live in `pre-commit-gate` + `git-protocol` skills — load them
before any git/gh operation.**

**Definition of Done** — every commit proves each applicable criterion: new or
changed behavior is covered by a focused test (and an integration test in
`tests/test_integration/` when it touches handler logic, keyboards, callbacks,
DB writes, quotas, or AI); no leftover references to symbols this change meant
to remove (enforced by `tests/test_dead_code_guard.py` and
`tests/test_wiring.py`); schema changes are tested on BOTH a fresh and an
upgraded-from-prior database; issues and `ROADMAP.md` updated per §2; the
Independent Review Subagent (§5) reported no confirmed findings.

> **Phase 2 — F401:** when the codebase is ready for a stricter rule budget, run
> `ruff check --fix --select F401`, review manually, then add `F401` to
> `ruff.toml`'s `select` list. Do not add F401 before that cleanup pass.

**VIOLATION CONSEQUENCE**: If the agent commits without passing the validation gate, the owner may discard the commit, require rework, and/or terminate the session. No exceptions.

**GATE KEYWORD**: The agent must include
**`<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>`** in its
response before any commit.

<!-- TODO: Owner to decide on a convention for preventing concurrent agent edits on the same branch/files. -->

## 8. Documentation Update Protocol

After every meaningful code or product change, load the `documentation-protocol`
skill and follow its "what to update and when" matrix (status/decisions →
`project_status.json` + dashboard; roadmap narrative → `ROADMAP.md`; module
structure → §3 + `tests/test_wiring.py`; tooling → `README.md`; plans →
`docs/plans/` archived to `docs/archive/`; issues; vision doc; AGENTS.md) plus
the canonical-source and staleness-prevention rules.

## 9. Product Scope Guardrails

For product direction, consult the locked plans and theme indexes, GitHub
Issues, and `ROADMAP.md`. This file is not a roadmap.

## 10. OpenCode Skills, Subagents, and Plan Persistence

<!-- [opencode-setup:start] -->

This section is a delimited, revertible block. It defines how skills and
subagents are loaded and how plans must be persisted. Reverting the whole
setup = delete this block (plus the `.gitignore` `[opencode-setup]` block and
the `.opencode/` folders). See `docs/archive/plan-opencode-tooling-setup-2026-08-05.md`.

### 10.1 Skill loading policy

Skills are loaded **lazily and only when relevant** — they are NOT injected into
every session. When a trigger in §10.2 matches, loading the corresponding skill
is MANDATORY and the agent MUST follow its contents exactly. Repo-specific
skills live in `.opencode/skills/`; global skills in `~/.config/opencode/skills/`.

### 10.2 Skills map (mandatory load triggers)

Skills load **lazily on trigger only**. When a trigger matches, loading is
mandatory; otherwise the skill is not loaded. Each row has a single conditional
trigger sentence.

**Skill-registry snapshot note:** `available_skills` is a **session-start
snapshot**. If a skill that exists on disk fails to load (`Skill "<name>" not
found`), request a registry reload or restart the session; do not re-debug the
skill file.

**`gh api` JSON parsing:** PowerShell redirects prepend a UTF-8 BOM, so
`gh api ... | python -c "json.load(sys.stdin)"` raises `JSONDecodeError`. Use
`scripts/ghjson.py` instead (`gh api ... | python scripts/ghjson.py .body`).

| Skill | Load when |
|---|---|
| `contract-lock-gate` | User proposes any code change. |
| `parallel-work-guard` | Working in parallel or creating a branch/worktree. |
| `git-protocol` | Any git or gh command is proposed or run. |
| `hamzaban-validation` | Preparing to commit or before PR creation. |
| `pre-commit-gate` | Immediately before creating a commit. |
| `integration-test-proto` | Behavioral change: callbacks, handlers, DB writes, quotas, or AI. |
| `callback-wiring` | Adding or changing a callback_data prefix or keyboard. |
| `persian-formatting` | Adding or changing learner-facing Persian text. |
| `audit-workflow` | Asked to audit or review the project. |
| `documentation-protocol` | A meaningful code or product change touched docs, status, roadmap, or module structure. |
| `plan-persistence` | A plan is locked and execution begins, or after each implementation step. |
| `grill-to-spec` | Plan needs ambiguity resolution and spec synthesis before execution. |
| `tdd-enforcement` | Writing new logic or modifying existing behavior during implementation. |
| `bug-diagnosis` | Debugging a failure, test failure, or CI failure. |
| `codebase-design` | Designing or refactoring a module's interface. |
| `i18n-accessibility` | Auditing or adding RTL/bidi, `lang`/`dir`, mixed-direction forms, or icon mirroring. |
| `core-web-vitals` | Asked to improve LCP/INP/CLS or page experience. |
| `frontend-ui-engineering` | Building or modifying UI components, pages, or interfaces. |
| `reviewing-interface-quality` | Asked to review, audit, or critique an interface, or as a pre-ship UI gate. |
| `graphify-index` | Structural queries or large refactors needing symbol relationship queries. |
| `spec-to-tickets` | A complex task needs per-phase breakdown before execution. |
| `reviewing-security` | Reviewing code for security before merging/shipping, or when a change touches untrusted input, auth, secrets, SQL, subprocess, paths, or outbound requests. |
| `evolving-apis-and-schemas` | Changing anything other systems/stored data depend on: schema, API, enum, queue format, migration. |
| `investigating-performance` | Something is too slow, uses too much memory/CPU, degrades under load, or times out. |
| `frontend-design` | Building or reshaping visual design direction, typography, or layout choices. |
| `writing-for-agents` | Creating or editing skills, AGENTS.md, CLAUDE.md, or other agent-facing docs. |
| `grilling` | The user wants to stress-test a plan, decision, or idea. |
| `research` | The user wants a topic researched and findings captured as Markdown. |
| `prototype` | The user wants to sanity-check a state model, logic, or UI with a throwaway prototype. |
| `domain-modeling` | Pinning down domain terminology or recording an architectural decision. |
| `resolving-merge-conflicts` | Resolving an in-progress git merge/rebase conflict. |
| `wizard` | Provisioning infrastructure, setting up credentials, or running a one-off migration where only a human can perform steps. |
| `testing-webapps` | Testing local web applications with Playwright. |
| `python-pro` | Building Python 3.11+ apps needing type safety, async, or robust error handling. |
| `test-master` | Writing unit/integration/E2E tests, test strategies, or analyzing coverage. |
| `code-reviewer` | Reviewing a PR or codebase for bugs, security, smells, and architecture. |
| `debugging-wizard` | Parsing error messages, tracing stack traces, or analyzing logs to isolate bugs. |
| `accessibility` | Improving web accessibility or auditing WCAG compliance. |
| `subagent-driven-development` | Executing implementation plans with independent tasks in the current session. |
| `verifying-before-completion` | About to claim work is complete, fixed, or passing, before committing or creating PRs. |
| `receiving-code-review` | Receiving code review feedback and implementing suggestions. |
| `requesting-code-review` | Completing tasks or implementing major features and wanting verification. |
| `executing-plans` | Executing a written implementation plan in the current session. |
| `writing-plans` | Having a spec or requirements for a multi-step task before touching code. |
| `using-git-worktrees` | Starting feature work needing isolation from the current workspace. |
| `git-commit` | Creating a git commit with conventional commit message analysis. |

Global general skills (shared, `~/.config/opencode/skills/`): TDD, systematic
debugging, executing-plans, verifying-before-completion, writing-plans,
requesting/receiving-code-review, reviewing-security, evolving-apis-and-schemas,
subagent-driven-development, using-git-worktrees, git-commit, python-pro,
test-master, code-reviewer, debugging-wizard, accessibility, frontend-design,
testing-webapps, investigating-performance, reviewing-interface-quality. These
are optional conveniences, not HamZaban-specific gates.

MattPocock workflow skills load lazily when their trigger matches and refine
(but do not replace) repo-local gates. Owner-triggered slash commands:
`/grill-me`, `/grill-with-docs`, `/to-spec`, `/to-tickets`, `/triage`,
`/implement`, `/handoff`, `/teach`, `/to-questionnaire`, `/wait-what`,
`/improve-codebase-architecture`. When a MattPocock skill overlaps a repo-local
gate, the repo-local gate remains canonical.

### 10.3 Lean subagents

`.opencode/agents/` defines specialized subagents with tightly scoped tool
permissions. Use them for their domain:

| Subagent | Domain | Key permission |
|---|---|---|
| `hamzaboon-db` | `services/db/*`, `services/fsrs_core.py` | bash → db/reviews/fsrs/migrations tests only |
| `hamzaboon-ai` | `services/ai/*` | bash → ai tests only |
| `hamzaboon-handler` | `handlers/*`, `config/keyboards.py`, `bot.py` | bash → integration/wiring/formatting tests only |
| `hamzaboon-reviewer` | independent review | `edit: deny`; read-only |

The Independent Review Subagent requirement (§5) is satisfied by
`hamzaboon-reviewer`.

### 10.4 Plan persistence rule

When a locked plan begins execution, persist the full plan with per-phase/step
progress to `.opencode/plans/<theme>/plan-*.md`, register it in that theme's
`index.md`, and cross-reference it in `.opencode/plans/TICKETS.md`. Update the
plan STATE line, theme index, and global ticket entry after each step. GitHub
Issues remain canonical for issue state, `project_status.json` for phase/decision
status, plan files for implementation details. Never silently renumber a plan's
internal tickets; record the mapping in `TICKETS.md`. For complex/critical tasks
(schema migrations, callback routing, module boundary changes, multi-file
refactors), create a per-phase plan file (`.opencode/plans/plan-<main>-phase-<NN>-<topic>.md`).
When a plan is done and completely evaluated, move it to `docs/archive/`.

### 10.5 Parallel Work Claims

Before any Contract Lock Gate reaches `GATE STATUS: LOCKED`, the agent MUST run
`parallel-work-guard` to check the shared claims file
(`<git-common-dir>/parallel-work-claims.json`) for seam-level overlaps with
other in-progress branches/worktrees.

1. Conflict unit is the seam registry (`SEAMS.md`), not file diffs.
2. Claims are written to the shared common-Git-directory claims file at `GATE STATUS: LOCKED`.
3. Overlap = warn with the exact resource named + explicit owner decision required (proceed anyway / wait). Never silent block, never silent proceed.
4. Claims are removed on post-merge cleanup (§5); claims older than 14 days are flagged for owner review. Malformed registry data halts claim-guarded work and requests owner repair.
5. Deep-module seam review is folded into the `hamzaboon-reviewer` checklist (§10.3).

Before creating or starting work in a parallel branch or worktree, load
`parallel-work-guard`, resolve the shared claims file, check every affected
canonical seam in `SEAMS.md`, and record a claim after `GATE STATUS: LOCKED`. A
dirty or unrelated worktree MUST NOT be overwritten; propagate shared
documentation changes only through a clean, explicit update or a later
owner-approved synchronization.

<!-- [opencode-setup:end] -->

## Appendix A: Agent Self-Check Checklist

**Before every implementation message** (full detail in §2.4 + `contract-lock-gate`):

- [ ] All logical gaps presented as numbered rules with recommended option + ≥1 alternative in a comparison table
- [ ] Owner chose each rule independently; Contract Lock Template filled completely
- [ ] Owner confirmation quoted ("proceed"/"locked"); `GATE STATUS = LOCKED`
- [ ] `<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>` keyword present
- [ ] No code changes before gate lock
- [ ] Callback impact assessed; wiring integrity test specified if affected
- [ ] §2.2/§2.3 compliance: no invented behavior, no silent scope widening
- [ ] Owner inquiries via `question` tool (`multiple: true` for decisions, `custom: true` for clarifications); options in plain language

**Before every commit** (full detail in §6, §7, `pre-commit-gate` + `git-protocol`):

- [ ] Validation suite passed (§6); `git diff --check` and `git diff --staged --check` clean
- [ ] No secrets in staged changes; single logical commit; explicit `git add` only
- [ ] Branch name follows `type/short-desc`
- [ ] `<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>` keyword present
- [ ] Test failures classified (bug vs. intentional); uncertain cases resolved via `question` per §2.4
- [ ] CI checks passed (`gh pr checks`) or owner accepted failure before merge
