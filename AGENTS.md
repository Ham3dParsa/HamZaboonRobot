# HamZaboon Agent Guidance

This document is the repository-level operating agreement for AI coding
agents, Devin sessions, and human contributors working on HamZaboon. Follow it
alongside the repository README, `ROADMAP.md`, and the user's explicit request.
If those sources conflict, follow the more specific and more recent
instruction.

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

`issues/issues.json` is authoritative for issue status and
`project_status.json` is authoritative for phase/decision status. HTML
`localStorage`, embedded fallback data, and Markdown snapshots must never be
treated as canonical state.

### Issue update policy

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

Classify findings by impact and confidence. Separate confirmed bugs from
accepted product decisions, intentional guards, speculative concerns, and
future enhancements. If a product or safety decision cannot be inferred,
ask one focused question; do not silently choose a policy that changes user
limits, cost exposure, or stored learning data.

## 5. Implementation Workflow

For a non-trivial task:

1. Create a fresh feature branch from the latest `origin/main`.
2. Read the relevant source, tests, roadmap section, and issue records before
   editing.
3. Make the smallest coherent implementation.
4. Add or update focused tests for changed behavior. Never weaken or rewrite
   tests solely to make them pass.
5. Update `issues/issues.json` and `ROADMAP.md` as required by Section 2.
6. Run the validation commands below.
7. Review the diff against `origin/main`, including generated/unintended
   files and secrets.
8. Fetch the repository PR template, commit functional changes, push the
   branch, and open one focused PR.
9. Check CI and address review feedback before declaring the work complete.

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

## 7. Git and Security Discipline

- Keep edits focused and reviewable.
- Do not commit `.env`, credentials, tokens, API keys, or generated secrets.
- Do not use destructive Git commands such as `reset --hard`, `clean -fd`,
  or force-push protected branches.
- Never skip hooks unless the user explicitly requests it.
- Stage intended files explicitly; do not use `git add .`.
- Do not amend commits; add a corrective commit when needed.
- Do not modify security policies or dependency protections to bypass a
  failing check.
- Prefer established dependencies and standard-library solutions.
- Treat database migrations as production code: preserve existing data,
  handle old schemas, and test both fresh and upgraded databases.

## 8. Product Scope Guardrails

The current next user-facing direction is custom-word query improvement:
visible quota, idempotent “Add to review”, and removal of the separate manual
save action from the primary flow. Reliability and data correctness take
priority over additional premium features.

Do not introduce payment automation, groups, leaderboards, AI images, broad
analytics, or advanced placement testing unless the user explicitly moves
them into scope through `ROADMAP.md`.
