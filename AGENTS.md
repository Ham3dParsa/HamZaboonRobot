# HamZaboon Agent Guidance

This document is the repository-level operating agreement for AI coding
agents, Devin sessions, and human contributors working on HamZaboon. Follow it
alongside the repository README, `ROADMAP.md`, and the user's explicit request.
If those sources conflict, follow the more specific and more recent
instruction.

**SESSION START PROTOCOL**: At the start of every new session or major task,
the agent SHOULD silently verify or explicitly output the **Appendix A** checklist
to refresh context-window constraints before proceeding.

_Last updated: 2026-07-17. See git history of this file for prior versions
and rationale for major protocol changes._

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
| `issues/issues.json` | Canonical structured registry of features, bugs, risks, research, decisions, evidence, status, and roadmap references. | This is the only engineering issue-state file to update during normal implementation work. |
| `project_status.json` | Canonical machine-readable phase, dependency, and decision-lock index. | Update it when phase status, assignments, or locked decisions change. |
| `issues/project_status.html` | Read-only joined dashboard generated from `project_status.json` and `issues/issues.json`. | Never treat embedded data or browser state as canonical. |
| `issues/issues.html` | Compatibility redirect to `issues/project_status.html`. | Do not use it as an editor or status source. |
| `hamzaban-issues.md` | Optional Markdown snapshot/export for human or AI review. | Do not maintain it in normal PRs. Generate it only when a fresh snapshot is explicitly useful. |
| `issues/validate.py` | Validation, JSON import/export, and generated-view synchronization. | Use `check` in normal PR validation; use `sync` after intentional canonical status changes. |
| `issues/status_editor.py` | Reviewable status/issue change application with validation and preview. | Use `preview` before `apply`; never edit generated views directly. |
| `issues/issues.schema.json` | Machine-readable JSON Schema for issue records. | Auto-validate with any JSON Schema-aware editor; update when the programmatic schema in `validate.py` changes. |

`issues/issues.json` is authoritative for issue status and
`project_status.json` is authoritative for phase/decision status. HTML
`localStorage`, embedded fallback data, and Markdown snapshots must never be
treated as canonical state.

### 2.1 Issue update policy

For a meaningful code change:

1. Identify the relevant issue IDs before implementation.
2. Update those records in `issues/issues.json` with:
   - an accurate `status`;
   - `roadmap_refs`;
   - concise evidence pointing to symbols or behavior;
   - `last_reviewed` in `YYYY-MM-DD` format.
3. Update `ROADMAP.md` when the work changes completed scope, remaining work,
   a locked decision, or the next planned step.
4. Run:

   ```bash
   .venv/bin/python issues/validate.py check
   ```

Use `issues/status_editor.py preview changes.json` to review a proposed
structured update, then `issues/status_editor.py apply changes.json --confirm`
to validate and write the canonical JSON plus generated views. The editor
updates only the marked generated section of `ROADMAP.md`; its narrative
sections remain human-maintained. `issues/validate.py sync` remains available
for refreshing views after direct canonical edits.

Use these statuses consistently:

- `open`: not implemented or not yet verified.
- `partial`: some mitigation exists, but material risk remains.
- `resolved`: implementation and focused verification support the conclusion.
- `accepted-risk`: consciously retained and documented.
- `obsolete`: no longer applicable.

Never mark an issue resolved based only on intention, a roadmap statement, or
an unverified code edit.

The canonical schema for issue records is defined in
`issues/issues.schema.json`. Use it for IDE autocompletion and CI validation;
it stays synchronized with the programmatic rules in `issues/validate.py`.

### 2.2 Logic-lock and bilateral-approval rule

The agent **IS FORBIDDEN FROM** inventing missing algorithmic behavior,
silently widening scope, or locking a product/architecture decision to close
an inferred gap. This applies to **ANY behavioral change including bug fixes**.
Before changing learner-facing behavior, persistence semantics, quotas,
scheduling, callbacks, AI contracts, or module boundaries, the agent must
follow the gate protocol in Section 2.4.

After implementation, the agent must report what changed, what was
deliberately not changed, and what remains uncertain. Debugging must target
the demonstrated root cause; opportunistic "extra fixes" or speculative
hardening are out of scope unless explicitly approved. If a safe workaround
exists, document it rather than silently converting it into a permanent
product rule.

### 2.3 Owner contract-locking protocol

When a requested behavior contains multiple algorithmic or product rules, do
not ask for one blanket approval. Instead, apply the gate protocol in
Section 2.4 with this additional requirement: decompose the behavior into
separately numbered rules, each presented with a recommended option plus
meaningful alternatives in a comparison table. The owner must choose each
rule independently; choosing the recommendation for one rule does not imply
approval of the others.

After implementation, report which locked rules changed, which were
deliberately not changed, and what remains uncertain. Verify each rule with
focused tests or other concrete evidence.

### 2.4 Mandatory Pre-Implementation Contract Lock Gate

**BEFORE ANY CODE CHANGE—exploratory, trivial, bug fix, or major—the agent MUST:**

1. **STOP** and identify all logical gaps, uncertainties, and decision points.
2. **PRESENT** each as a numbered rule with: recommended option + ≥1 alternative + concrete trade-offs in a comparison table.
3. **OBTAIN** explicit owner choice per rule (no blanket approvals).
4. If any logical gap, ambiguous test failure, or architectural uncertainty arises during gate preparation, the agent **MUST halt** and present its findings as a clear, focused inquiry to the project owner. **If an interactive question/decision tool is available in the current environment, use it** (with `multiple: true` for decision options, `custom: true` for open-ended clarification). **If no such tool is available, present the same structured inquiry as plain text in the response and explicitly halt, waiting for the owner's reply before proceeding.** The agent is strictly forbidden from proceeding with code edits until the owner explicitly answers or chooses a decision option.
5. **SUMMARIZE** the locked contract in writing using the template below.
6. **CONFIRM** owner says "proceed" or "locked" before touching code.

**VIOLATION CONSEQUENCE**: If the agent implements without a LOCKED gate, the owner may discard all uncommitted changes, require full rework from the gate, and/or terminate the session. No exceptions.

**GATE KEYWORD**: The agent must include **`<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>`** in its response before any implementation.

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

#### 2.4.1 Fast-track exception for non-behavioral changes

Changes that are strictly non-behavioral MAY skip the full comparison-table
gate. The following qualify:

- Typo or copy fixes in strings or documentation.
- Comment-only edits (no production code change).
- Adding tests that do not change production logic.
- Formatting or whitespace-only diffs.

To use this exception, the agent states in one line under the
`<SYSTEM_GATE>` keyword: what the change is, why it is non-behavioral, and
that it will proceed without a locked contract. This exception does NOT
apply if there is ANY ambiguity about whether the change affects
learner-facing behavior, persistence, quotas, scheduling, or module
boundaries — when in doubt, use the full gate.

## 3. Repository Architecture

Keep responsibilities aligned with the current module boundaries:

- `bot.py`: Telegram handlers, callback routing, jobs, delivery orchestration,
  and user-facing formatting.
- `ai.py`: OpenAI-compatible client construction, provider settings, JSON
  extraction, and AI response validation.
- `db.py`: SQLite schema, migrations, transactions, persistence, quotas,
  daily-card state, delivery queue state, and saved-word state.
- `prompts.py`: system prompts and content-generation instructions.
- `catalog.py`: canonical language, goal, and level metadata.
- `keyboards.py`: Telegram menus and callback identifiers.
- `scheduling.py`: pure session sizing, slot planning, and timezone-aware
  planned timestamps.
- `config.py`: environment and deployment settings only; it must not become a
  second learner-option registry.
- `issues/validate.py`: issue registry validation and optional exports.
- `admin.py` and `user.py` (when introduced): role-specific Telegram handlers
  only; shared domain behavior remains in focused services.
- `formatting.py` (when introduced): learner-facing message formatting and
  escaping behind a stable interface, so a future Telegram parse-mode change
  does not require rewriting handlers or domain logic.

Prefer extending an existing module and convention over introducing a new
abstraction. Keep runtime behavior separate from issue-review tooling.

### Catalog rule

Language, goal, and level identifiers and learner-facing metadata belong in
`catalog.py`. Do not create parallel dictionaries in `config.py`, `prompts.py`,
`bot.py`, or `keyboards.py`. New options must:

- use stable identifiers;
- be represented in the canonical catalog;
- be consumed by menus, prompts, validation, and fallbacks;
- include focused consistency tests;
- preserve compatibility with existing stored IDs and callbacks.

### Reliability rules

Preserve these established contracts when changing runtime code:

- Use `APP_TIMEZONE` for application-day calculations; use UTC timestamps for
  processing metadata where appropriate.
- Keep AI calls behind the global concurrency/request limiter. Blocking
  synchronous provider calls must not run directly on async Telegram handlers.
- Keep an explicit AI timeout.
- Route scheduled delivery, SRS, and broadcasts through the shared Telegram
  retry/concurrency path where applicable.
- Delivery queue retries must remain bounded, back off through `retry_at`, and
  become terminal after the configured attempt budget.
- Quota checks that reserve usage must be atomic.
- Saved-word writes must remain normalized and idempotent.
- Preserve restart safety and avoid duplicate cards, messages, or provider
  requests whenever the existing state model supports it.
- Do not expose API keys, bot tokens, or other secrets in code, logs, tests,
  commits, issue evidence, or PR descriptions.
- SQLite concurrency: all write operations must use context managers with
  immediate/exclusive transactions where write contention is possible, to
  avoid `database is locked` errors during concurrent Telegram callback
  bursts. Do not hold an open database transaction across an awaited async
  call (e.g., an AI request or Telegram API call) — commit or roll back
  before awaiting, and reacquire the transaction after if further writes are
  needed.

### AI Cost Discipline

When adding or modifying AI-calling code paths, the agent must state the
expected token/cost impact (e.g., new call added per user action, expected
frequency, rough token count) as part of the contract lock summary for that
change. Prefer reusing cached or pooled content over issuing a new AI call
when existing project infrastructure (see cost-tracking, pooling, and SRS
planning docs) already covers the case. Flag any change that measurably
increases per-user or per-day AI call volume as requiring explicit owner
approval, even if it would otherwise qualify for the fast-track exception in
Section 2.5.1.

### Localization & Escaping Rules

All learner-facing text must be in correct, natural Persian. Do not mix
machine-translated or placeholder English strings into user-visible messages.

Telegram uses `MarkdownV2` parsing which is brittle when mixing RTL (Persian)
and LTR (English, code, variables, numbers). Special characters
(`_`, `*`, `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`, `|`,
`{`, `}`, `.`, `!`) **must be rigorously escaped** in `bot.py` and
`formatting.py` before interpolation into MarkdownV2 strings. Failure to
escape causes `Bad Request: can't parse entities` API errors and broken
formatting.

- Centralize escaping logic in `formatting.py` behind a stable interface.
- Never concatenate raw user input, AI output, or dynamic values directly into
  MarkdownV2 templates without escaping.
- Test Persian + English mixed strings explicitly in unit tests.

**Escaping contract:** every dynamic value that originates from the AI, the
database, or user input MUST be passed through the centralized escaping
function in `formatting.py` before being interpolated into any MarkdownV2
template string in `bot.py`. Never concatenate a raw dynamic value directly
into a reply string. If a value is already known to be pre-escaped or is a
static, hardcoded literal, that must be stated explicitly in a code comment
at the call site.

## 4. Audit and Code-Review Workflow

When asked to audit or review the project:

1. Read `AGENTS.md`, `README.md`, `ROADMAP.md`, and
   `issues/issues.json`.
2. Inspect all relevant Python modules and tests, not only the file named in
   the request.
3. Trace data and control flow across:
   - Telegram handlers and callbacks;
   - AI calls and response validation;
   - SQLite writes, migrations, and transactions;
   - scheduled jobs and delivery retries;
   - timezone-sensitive day boundaries;
   - quotas and plan overrides.
4. Compare each existing issue with current code evidence. Do not copy old
   statuses forward without verification.
5. Look for correctness, security, reliability, cost, concurrency, migration,
   and UX risks—not only syntax errors.
6. Record findings in `issues/issues.json` with stable IDs and evidence.
7. Reconcile the product-level consequences in `ROADMAP.md`.
8. Run the focused tests plus the repository-wide checks before reporting.
9. **Context economy:** when investigating a bug or making a targeted change,
   read the specific function/handler and its direct dependencies first rather
   than the entire module or repository, unless the reported behavior requires
   tracing broader data/control flow (per item 3 above). Expand scope only as
   evidence demands it.

Classify findings by impact and confidence. Separate confirmed bugs from
accepted product decisions, intentional guards, speculative concerns, and
future enhancements. If a product or safety decision cannot be inferred,
ask one focused question; do not silently choose a policy that changes user
limits, cost exposure, or stored learning data.

## 5. Implementation Workflow

For a non-trivial task:

0. **Contract lock confirmed per Section 2.4 (Mandatory Pre-Implementation Contract Lock Gate).**
1. Implement on current branch (or stash changes); run full validation (Section 6).
2. **Create a fresh feature branch from the latest `origin/main`** using convention: `type/short-desc` (e.g., `feat/custom-words`, `fix/collision-retry`).
3. **Write focused unit tests** in `tests/` for any new logic, edge cases, or database schema changes introduced by the implementation.
4. Stage modified files explicitly: `git add file1.py file2.py` (never `git add .`).
5. Commit with Conventional Commits format: `type(scope): subject` (e.g., `fix(bot): handle collision retry`).
6. Push branch and create PR via `gh pr create --fill --base main`.
7. Owner reviews and merges on GitHub using **Squash and merge**.
8. Delete branch after merge (GitHub "Delete branch" button or `git branch -d`).
9. Update `issues/issues.json` and `ROADMAP.md` as required by Section 2.
10. Run the validation commands below.
11. Check CI and address review feedback before declaring the work complete.

Do not combine unrelated user-facing features, broad refactors, and issue
cleanup in one PR. If a discovered issue is outside the requested scope,
record it rather than silently expanding the implementation.

## 6. Required Validation

Use the repository virtual environment when available:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile \
  config.py catalog.py scheduling.py db.py prompts.py ai.py keyboards.py \
  bot.py issues/validate.py issues/status_editor.py
.venv/bin/python issues/validate.py check
git diff --check
```

For changes to a specific subsystem, add focused tests before relying on the
full suite:

- scheduling or delivery: queue state, retry budget, backoff, restart safety,
  and shared-slot behavior;
- AI: timeout, JSON validation, limiter usage, and async offloading;
- callbacks: authorization and catalog identifier validation;
- quotas and saved words: transaction races, date boundaries, normalization,
  and duplicate insertion;
- SRS or broadcasts: Telegram retry behavior, message-size chunking, and
  partial-failure progress;
- schema changes: fresh-database creation and migration from the prior schema.

Do not claim CI success from local tests. Report CI based on the repository
checks after the PR is opened.

### Handling Broken or Outdated Tests

If a test fails because the underlying product logic was intentionally changed or deprecated:

a) The agent **MUST NOT** silently delete, disable, or ignore the test.
b) The agent **MUST NOT** revert correct code modifications just to make an outdated test pass.
c) The agent **MUST** determine if the failure is due to a bug or an intentional logic change. If intentional, the agent must update or rewrite the unit test to reflect the new canonical behavior, ensuring test coverage remains intact.
d) If the agent is uncertain whether a test failure represents a regression or an obsolete expectation, it **MUST halt and ask the project owner** per the fallback protocol in Section 2.4.

## 7. Git and Security Discipline

### Mandatory Pre-Commit Validation Gate

**BEFORE ANY COMMIT, the agent MUST:**

1. Run the full validation suite (Section 6).
2. Run `git diff --check` and `git diff --staged --check` — no whitespace errors.
3. Verify no secrets, credentials, tokens, API keys, or generated secrets in staged changes.
4. Confirm single logical change per commit (Section 5 Steps 3–4).
5. Verify branch naming convention: `type/short-desc` with type in `feat|fix|docs|refactor|test|chore`.

**VIOLATION CONSEQUENCE**: If the agent commits without passing the validation gate, the owner may discard the commit, require rework from a clean state, and/or terminate the session. No exceptions.

**GATE KEYWORD**: The agent must include **`<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>`** in its response before any commit.

### Error Recovery Protocol

If validation fails (tests, `git diff --check`, or other checks), the agent MUST NOT immediately ask for human help. Instead:

1. **Analyze** the stack trace or diff output to identify the root cause.
2. **Attempt a fix** targeting the specific failure.
3. **Retry** the full validation suite (Section 6).
4. Only after **2 consecutive failed attempts** should the agent:
   - Reset state (e.g., `git reset HEAD~1` or discard staged changes).
   - Report the exact error and context.
   - Halt for human input.

This protocol prioritizes autonomous recovery over escalation.

### Commit Rules

- **Single logical commit per PR** — one coherent change (feature, fix, docs, refactor, test, chore).
- **Conventional Commits format**: `type(scope): subject`
  - Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`
  - Scope: module or subsystem (e.g., `bot`, `db`, `ai`, `catalog`, `scheduling`)
  - Subject: imperative, lowercase, no trailing period
  - Example: `fix(bot): handle collision retry on network error`
- **Explicit staging only**: `git add file1.py file2.py` — never `git add .` or `git add -A`.
- **No commit amending** — add corrective commit if needed.
- **No destructive Git commands**: `reset --hard`, `clean -fd`, force-push protected branches.
- **Never skip hooks** unless owner explicitly requests.

### Branch & PR Rules

- **Branch naming**: `type/short-desc` (e.g., `feat/custom-words`, `fix/collision-retry`, `docs/git-workflow`).
- **Branch creation**: After validation passes (Section 5 Step 2), not before implementation.
- **PR creation**: Agent runs `gh pr create --fill --base main` — owner merges on GitHub UI.
- **Merge method**: **Squash and merge** on GitHub (single commit on `main`).
- **Post-merge**: Delete branch (GitHub button or `git branch -d branch-name`).
- **Local merge fallback only** with explicit owner instruction: `git checkout main && git pull && git merge --ff-only branch-name`.

### Security Rules

- Do not commit `.env`, credentials, tokens, API keys, or generated secrets.
- Prefer established dependencies and standard-library solutions.
- Treat database migrations as production code: preserve existing data, handle old schemas, test both fresh and upgraded databases.

<!-- TODO: Owner to decide on a convention for preventing concurrent agent edits on the same branch/files (see AGENTS.md #10). -->

## 8. Product Scope Guardrails

The current next user-facing direction is custom-word query improvement:
visible quota, idempotent "Add to review", and removal of the separate manual
save action from the primary flow. Reliability and data correctness take
priority over additional premium features.

Do not introduce payment automation, groups, leaderboards, AI images, broad
analytics, or advanced placement testing unless the user explicitly moves
them into scope through `ROADMAP.md`.

## Appendix A: Agent Self-Check Checklist

**Context Refresh Protocol**: At the start of every new session or major task, the agent SHOULD silently verify or explicitly output this checklist to refresh context-window constraints before proceeding.

Before every implementation message, the agent MUST verify:

- [ ] All logical gaps identified and presented as numbered rules
- [ ] Each rule has: recommended option + ≥1 alternative in comparison table
- [ ] Owner has explicitly chosen each rule independently
- [ ] Contract lock template filled completely
- [ ] Owner confirmation quoted ("proceed" or "locked")
- [ ] GATE STATUS = LOCKED
- [ ] `<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>` keyword present in response
- [ ] No code changes proposed or implemented before gate lock
- [ ] Section 2.2 (Logic-lock) compliance: no invented behavior, no silent scope widening
- [ ] Section 2.3 (Contract-locking) compliance: decomposition, alternatives, independent choices
- [ ] Step 0 of Section 5 satisfied (contract lock confirmed)
- [ ] Owner inquiries for logical gaps/uncertainties made via `question` tool (multiple: true for decisions, custom: true for clarifications)

Before every commit, the agent MUST verify:

- [ ] Full validation suite passed (Section 6)
- [ ] `git diff --check` and `git diff --staged --check` clean
- [ ] No secrets in staged changes
- [ ] Single logical commit (Conventional Commits format)
- [ ] Explicit `git add file1.py file2.py` only
- [ ] Branch name follows `type/short-desc` convention
- [ ] `<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>` keyword present in response
- [ ] Test failures classified (bug vs. intentional change); uncertain cases resolved via `question` tool with `custom: true` per fallback protocol in Section 2.4

(End of file)