# HamZaboon Agent Guidance

This document is the repository-level operating agreement for AI coding
agents, Devin sessions, and human contributors working on HamZaboon. Follow it
alongside the repository README, `ROADMAP.md`, and the user's explicit request.
If those sources conflict, follow the more specific and more recent
instruction.

**SESSION START PROTOCOL**: At the start of every new session or major task,
the agent SHOULD silently verify or explicitly output the **Appendix A** checklist
to refresh context-window constraints before proceeding.

_Last updated: 2026-07-21. See git history of this file for prior versions
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
| [GitHub Issues](https://github.com/Ham3dParsa/HamZaboonRobot/issues) | Canonical structured issue registry (features, bugs, risks, tech-debt, research, decisions). | Create and update via `gh issue create`/`edit`/`close`. Labels encode category, priority, and phase. |
| `project_status.json` | Canonical machine-readable phase, dependency, and decision-lock index. | Update it when phase status, assignments, or locked decisions change. |
| `issues/project_status.html` | Read-only dashboard generated from `project_status.json`. Links to GitHub Issues for detail. | Regenerate with `python scripts/generate_dashboard.py`. Never edit directly. |
| `issues/issues.html` | Compatibility redirect to `issues/project_status.html`. | Do not use it as an editor or status source. |
| `scripts/generate_dashboard.py` | Lightweight HTML dashboard generator from `project_status.json`. | Use after intentional phase/decision changes. |
| `docs/vision_and_product_goals.md` | Product vision, strategic goals, and target audience. | Curate when strategic direction or goals change. |

`project_status.json` is authoritative for phase/decision status. GitHub Issues
are authoritative for individual issue state. HTML `localStorage`, embedded
fallback data, and generated views must never be treated as canonical state.

### 2.1 Issue update policy

For a meaningful code change:

1. Identify the relevant issue IDs before implementation.
2. Update the corresponding GitHub Issue with:
   - an accurate `status`;
   - `roadmap_refs`;
   - concise evidence pointing to symbols or behavior;
   - `last_reviewed` in `YYYY-MM-DD` format.
3. Update `ROADMAP.md` when the work changes completed scope, remaining work,
   a locked decision, or the next planned step.
4. Update `project_status.json` if phase status, assignments, or decision locks
   changed. Then regenerate the dashboard:

   ```bash
   python scripts/generate_dashboard.py
   ```

Use these statuses consistently:

- `open`: not implemented or not yet verified.
- `partial`: some mitigation exists, but material risk remains.
- `resolved`: implementation and focused verification support the conclusion.
- `accepted-risk`: consciously retained and documented.
- `obsolete`: no longer applicable.

Never mark an issue resolved based only on intention, a roadmap statement, or
an unverified code edit.

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
2. **ASSESS** whether the change affects callback routing (`callback_data` strings, `callback_router` dispatch, sub-router actions) or keyboard construction. If yes, the test plan section of the locked contract MUST specify a wiring integrity test covering the new or affected routes.
3. **PRESENT** each as a numbered rule with: recommended option + ≥1 alternative + concrete trade-offs in a comparison table.
4. **OBTAIN** explicit owner choice per rule (no blanket approvals).
5. If any logical gap, ambiguous test failure, or architectural uncertainty arises during gate preparation, the agent **MUST halt** and present its findings as a clear, focused inquiry to the project owner. **If an interactive question/decision tool is available in the current environment, use it** (with `multiple: true` for decision options, `custom: true` for open-ended clarification). **If no such tool is available, present the same structured inquiry as plain text in the response and explicitly halt, waiting for the owner's reply before proceeding.** The agent is strictly forbidden from proceeding with code edits until the owner explicitly answers or chooses a decision option.
6. **SUMMARIZE** the locked contract in writing using the template below.
7. **CONFIRM** owner says "proceed" or "locked" before touching code.

> **Owner experience note:** The project owner is not a professional developer. When presenting rules, options, and trade-offs during this gate, the agent MUST explain each option in plain, non-jargon language. Define technical terms if they are unavoidable. State clearly what each option does in practice, what it costs (time, complexity, money if applicable), and why the recommended option is preferred. Do not assume familiarity with Python tooling, testing patterns, or deployment concepts.

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

- `bot.py`: Thin entry point; Telegram handlers, callback routing, jobs, delivery orchestration, and user-facing formatting.
- `handlers/`: Telegram handler modules.
  - `handlers/admin.py`: Admin panel handlers.
  - `handlers/user.py`: User settings handlers (language, goal, level).
  - `handlers/srs_handler.py`: SRS review handlers.
- `services/`: Domain services.
  - `services/db/`: SQLite schema, migrations, transactions, persistence, quotas, daily-card state, delivery queue state, and saved-word state.
  - `services/fsrs_core.py`: Pure FSRS-6 engine (w0-w20 constants, DSR formulas, no side effects).
  - `services/ai/`: OpenAI-compatible client, provider settings, JSON extraction, AI response validation, system prompts, AI content generation, and provider presets.
    - `services/ai/ai.py`: Client construction, validation.
    - `services/ai/llm_services.py`: Cached content generation.
    - `services/ai/prompts.py`: System prompts and content-generation instructions.
    - `services/ai/ai_presets.py`: Hardcoded AI provider presets.
  - `services/utils/`: Utility modules.
    - `services/utils/formatting.py`: Learner-facing message formatting and escaping behind a stable interface.
    - `services/utils/helpers.py`: Shared helper functions (retry, cancel detection, etc.).
  - `services/scheduling.py`: Pure session sizing, slot planning, and timezone-aware planned timestamps.
  - `services/tts.py`: Text-to-Speech generation using Edge TTS.
- `config/`: Configuration and metadata.
  - `config/__init__.py`: Environment and deployment settings; it must not become a second learner-option registry.
  - `config/catalog.py`: Canonical language, goal, and level metadata.
  - `config/keyboards.py`: Telegram menus and callback identifiers.
- `tests/test_integration/`: Handler-level integration tests simulating real user flows (see Integration Test Protocol).
  - `tests/test_integration/helpers.py`: Shared helpers for update/context construction and DB snapshot management.
- `.github/workflows/ci.yml`: GitHub Actions CI — runs lint, compile, tests, dashboard generation, and whitespace checks on push/PR to `main`. — runs lint, compile, tests, dashboard generation, and whitespace checks on push/PR to `main`.

Prefer extending an existing module and convention over introducing a new
abstraction. Keep runtime behavior separate from issue-review tooling.

### Module change guard

If the module structure changes (add, rename, split, or remove), the agent
MUST update the responsibilities table above AND the scan-target paths in
`tests/test_wiring.py`.

### Callback Routing Map

This table maps Telegram callback prefixes to their handler modules and entry
functions, so agents can quickly find the right file when tracing a callback
or adding a new one.

| Callback Prefix | Handler File | Key Functions |
|----------------|--------------|---------------|
| `lang:`, `goal:`, `level:` | `handlers/user.py` | `on_lang_selected`, `on_goal_selected`, `on_level_selected`, `on_lang_changed`, `on_goal_changed`, `on_level_changed` |
| `presentation:set:` | `bot.py` | `callback_router` (inline) |
| `daily:prepare:`, `daily:next:` | `bot.py` | `_handle_daily_prepare`, `_send_next_daily_card` |
| `review:prepare:`, `review:menu`, `review:page:`, `review:date:`, `review:next:`, `review:noop` | `bot.py` | `_handle_daily_prepare`, `_show_review_menu`, `_show_review_date`, `_send_card_from_store` |
| `query:prepare:`, `query:add:` | `bot.py` | `_handle_query_prepare`, `_handle_query_add` |
| `tts:pronounce:` | `bot.py` | `_handle_tts_pronounce` |
| `srs:prepare:`, `srs:reveal:`, `srs:` | `handlers/srs_handler.py` | `_handle_srs_prepare`, `_handle_srs_reveal`, `_handle_srs_review` |
| `admin:` | `handlers/admin.py` | `_handle_admin_callback` |
| `llm:` | `handlers/admin.py` | `_handle_llm_callback` |
| `flow:` | `config/keyboards.py` (handled via `_handle_admin_callback`, `_exit_awaiting_flow`) | `_exit_awaiting_flow` |

### Catalog rule

Language, goal, and level identifiers and learner-facing metadata belong in
`config/catalog.py`. Do not create parallel dictionaries in `config/__init__.py`, `services/ai/prompts.py`,
`bot.py`, or `config/keyboards.py`. New options must:

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
- **API key storage pattern:** The `ai_presets` database stores environment
  variable names (e.g., `$HpOF_API_KEY`) instead of actual key values. At
  runtime `resolve_api_key()` in `services/ai/ai_presets.py` reads the real
  value from the environment. This keeps secrets out of the database. When
  adding or editing presets, use `$UPPERCASE_NAME` references — never paste
  a raw key into the database unless the owner explicitly instructs otherwise.
  Document any new env var reference in `.env.example` under the
  "AI PRESET API KEYS" section.
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
Section 2.4.1.

### Localization & Escaping Rules

All learner-facing text must be in correct, natural Persian. Do not mix
machine-translated or placeholder English strings into user-visible messages.

Telegram uses `MarkdownV2` parsing which is brittle when mixing RTL (Persian)
and LTR (English, code, variables, numbers). Special characters
(`_`, `*`, `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`, `|`,
`{`, `}`, `.`, `!`) **must be rigorously escaped** in `bot.py` and
`services/utils/formatting.py` before interpolation into MarkdownV2 strings. Failure to
escape causes `Bad Request: can't parse entities` API errors and broken
formatting.

- Centralize escaping logic in `services/utils/formatting.py` behind a stable interface.
- Never concatenate raw user input, AI output, or dynamic values directly into
  MarkdownV2 templates without escaping.
- Test Persian + English mixed strings explicitly in unit tests.

**Escaping contract:** every dynamic value that originates from the AI, the
database, or user input MUST be passed through the centralized escaping
function in `services/utils/formatting.py` before being interpolated into any MarkdownV2
template string in `bot.py`. Never concatenate a raw dynamic value directly
into a reply string. If a value is already known to be pre-escaped or is a
static, hardcoded literal, that must be stated explicitly in a code comment
at the call site.

## 4. Audit and Code-Review Workflow

When asked to audit or review the project:

1. Read `AGENTS.md`, `README.md`, `ROADMAP.md`, `docs/vision_and_product_goals.md`,
   and related [GitHub Issues](https://github.com/Ham3dParsa/HamZaboonRobot/issues).
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
6. Record findings as GitHub Issues with stable IDs and evidence.
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
3. **Write focused unit tests** in `tests/` for any new logic, edge cases, database schema changes, or callback routing changes introduced by the implementation. For any change that touches `callback_data` strings, `callback_router` dispatch conditions, or sub-router action patterns, a cross-module callback wiring integrity test MUST be added or updated to verify all callback prefixes have matching router and sub-router handlers (see `tests/test_wiring.py`). For behavioral changes (handler logic, keyboard construction, database writes, quota enforcement, or AI interaction), add handler-level integration tests in `tests/test_integration/` following the Integration Test Protocol (Section 6).
4. Stage modified files explicitly: `git add file1.py file2.py` (never `git add .`).
5. Commit with Conventional Commits format: `type(scope): subject` (e.g., `fix(bot): handle collision retry`).
6. Push branch and create PR via `gh pr create --fill --base main`.
   If the PR resolves tracked issues, link them in the body (e.g., "Resolves #N").
   If `gh` is unavailable, provide the GitHub PR creation URL as a fallback.
7. Owner reviews and merges on GitHub using **Squash and merge**.
   If the owner explicitly instructs "merge it" (or equivalent), the agent may
   run `gh pr merge --squash` on the owner's behalf. The agent MUST confirm
   CI passes via `gh pr checks` before merging.
8. After merge, clean up locally:
   `git checkout main && git pull && git branch -d branch-name`
9. Update GitHub Issues and `ROADMAP.md` as required by Section 2.
10. Run the validation commands below.
11. After PR creation, run `gh pr checks` to monitor CI. If checks fail,
    apply the Error Recovery Protocol (Section 7): analyze, fix, push,
    re-check. Report final CI status to the owner before declaring done.

Do not combine unrelated user-facing features, broad refactors, and issue
cleanup in one PR. If a discovered issue is outside the requested scope,
record it rather than silently expanding the implementation.

## 6. Required Validation

Use the repository virtual environment when available:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile $(git ls-files '*.py' | grep -v 'tests/')
.venv/bin/python -m ruff check --select F821,F811
python scripts/generate_dashboard.py
git diff --check
```

Or on Windows PowerShell, use the equivalent:
```powershell
python -m unittest discover -s tests -v
python scripts/compile_all.py
python -m ruff check --select F821,F811
python scripts/generate_dashboard.py
git diff --check
```

For changes to a specific subsystem, add focused tests before relying on the
full suite:

- scheduling or delivery: queue state, retry budget, backoff, restart safety,
  and shared-slot behavior;
- AI: timeout, JSON validation, limiter usage, and async offloading;
- callbacks: authorization, catalog identifier validation, and wiring integrity (all callback_data prefixes from all modules have matching handlers in callback_router and relevant sub-routers);
- quotas and saved words: transaction races, date boundaries, normalization,
  and duplicate insertion;
- SRS or broadcasts: Telegram retry behavior, message-size chunking, and
  partial-failure progress;
- schema changes: fresh-database creation and migration from the prior schema.

Do not claim CI success from local tests. Report CI based on the repository
checks (GitHub Actions, `.github/workflows/ci.yml`) after the PR is opened.

### Integration Test Protocol

When a behavioral change (callback routing, handler logic, keyboard construction,
database writes, quota enforcement, or AI interaction) is made, the agent MUST
add or update handler-level integration tests in `tests/test_integration/` to
verify the change end-to-end. These tests simulate real user actions through
the routing layer and check the full response, not just isolated function
outputs.

**Scope and coverage.** Each integration test follows a user-facing flow:
1. Construct a realistic `Update` (text message or callback query) and `Context`.
2. Call the appropriate router (`text_router`, `callback_router`, or sub-router).
3. Assert on the handler's Telegram output (`reply_text`, `edit_message_text`,
   `answer`) and on any resulting database state change.
4. Assert that the returned keyboard (if any) contains the expected
   `callback_data` prefixes and labels.

**Database isolation.**
- Before the test session runs, the agent backs up the real SQLite database
  (`db.DB_PATH`) to a timestamped snapshot file. The backup is created once per
  session and is never modified.
- Each test class creates a fresh copy of the snapshot in a temp directory and
  sets `db.DB_PATH` to the copy. This ensures every class starts from the same
  realistic data without affecting the production database.
- After the test session, all temp copies and the session snapshot are removed.
  No production data is ever read or written through a production `db.DB_PATH`.

**AI interaction in tests.**
- By default, all AI calls are mocked with controlled, pre-defined responses.
- When `AI_TEST_REAL=true` is set in the environment, real AI calls are made
  using a dedicated test preset (set `_is_test_preset=True` in the preset
  config). The agent MUST enforce a maximum budget of **1000 tokens per test
  session** when real AI is enabled, and MUST skip or abort any test that would
  exceed this budget. Track cumulative token usage via `db.log_llm_request`
  and abort the test session at 1000 tokens.
- Real AI mode is intended for targeted verification of prompt changes or new
  content schemas, not for every test run.

**Telegram interface.** Tests MUST NOT use a real bot token. All Telegram
interactions are mocked via `AsyncMock` on the `Context.bot` object. The
agent verifies the handler's response by inspecting the mock's call arguments
(`reply_text.call_args`, `edit_message_text.call_args`, etc.).

**Test file conventions.** Integration test files live in
`tests/test_integration/` and follow the naming pattern
`test_<feature>_flow.py`. Each file contains one or more
`unittest.IsolatedAsyncioTestCase` classes. Common helpers (update factory,
context factory, DB snapshot management) live in
`tests/test_integration/helpers.py`.

**Contract lock gate for new tests.** Before writing an integration test, the
agent must include the AI cost impact and the database safety plan in the
contract lock summary (Section 2.4). If the test calls real AI, the expected
token count and purpose must be stated.

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
6. While `tests/test_wiring.py` and `tests/test_formatting.py` are recommended locally, any CI failure in these tests triggers the Error Recovery Protocol — fix and re-push immediately. Unlike other tests, `tests/test_wiring.py` performs cross-module introspection and cannot be faked or satisfied by local-only changes.

> **Phase 2 — F401 (unused imports):** When the codebase is ready for a stricter rule
> budget, run `ruff check --fix --select F401` to auto-clean unused imports, review
> the changes manually, then add `F401` to `ruff.toml`'s `select` list and update this
> gate accordingly. Do not add F401 before the cleanup pass is done and reviewed.

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
- **PR creation**: Agent runs `gh pr create --fill --base main` — owner reviews on GitHub UI.
  If the PR resolves tracked issues, link them in the body (e.g., "Resolves #N").
  If `gh` is unavailable, provide the GitHub PR creation URL as a fallback.
- **CI monitoring**: Agent runs `gh pr checks` after PR creation and reports results.
- **Agent-initiated merge**: Only when the owner explicitly instructs "merge it"
  (or equivalent). The agent MUST run `gh pr checks` and confirm all required
  checks pass before `gh pr merge --squash`.
- **Merge method**: **Squash and merge** on GitHub (single commit on `main`).
- **Post-merge**: Clean up locally:
  `git checkout main && git pull && git branch -d branch-name`
- **Local merge fallback only**: With explicit owner instruction:
  `git checkout main && git pull && git merge --ff-only branch-name`.
- **Remote branch deletion**: Owner may delete via GitHub UI after merge.

### GitHub CLI Integration

The agent may use the `gh` CLI for the following operations. Commands outside
this list require explicit prior approval.

**Pull requests:**
- `gh pr create --fill --base main` — create a PR
- `gh pr checks` — monitor CI/CD status
- `gh pr merge --squash` — merge a PR (only on explicit owner instruction)
- `gh pr view` — review PR status and comments

**Issues (read-only):**
- `gh issue list [--label <label>] [--state <state>]` — list issues
- `gh issue view <N>` — read issue details and comments

**Security & bounds:**
- The agent MUST NOT expose the `gh` auth token in logs, commits, or PR descriptions.
- The agent MUST NOT close, reopen, or create GitHub Issues ad hoc
  (these operations are governed by the issue update policy in Section 2).
- The agent MUST NOT merge a PR with failing CI checks.

### Security Rules

- Do not commit `.env`, credentials, tokens, API keys, or generated secrets.
- Do not expose `gh` auth tokens or session credentials in code, logs, tests,
  commits, issue evidence, or PR descriptions.
- Prefer established dependencies and standard-library solutions.
- Treat database migrations as production code: preserve existing data, handle old schemas, test both fresh and upgraded databases.

<!-- TODO: Owner to decide on a convention for preventing concurrent agent edits on the same branch/files (see AGENTS.md #10). -->

## 8. Documentation Update Protocol

Keep the documentation ecosystem coherent by applying these rules after every
meaningful code or product change. Each type of information has exactly one
canonical source; generated views are never edited directly.

### What to update and when

| What changed | Update this | Then |
|---|---|---|
| Phase status, decisions, dependencies, or progress items | `project_status.json` | Run `python scripts/generate_dashboard.py` |
| Product narrative, scope, or roadmap direction | `ROADMAP.md` (narrative sections only) | — |
| Module structure (add/rename/split/remove) | `AGENTS.md` Section 3 table + `tests/test_wiring.py` scan paths | — |
| Tooling, validation commands, or setup | `README.md` | — |
| Bug discovered, feature requested, or risk identified | [GitHub Issue](https://github.com/Ham3dParsa/HamZaboonRobot/issues/new) | Link issue ID in `project_status.json` if phase-relevant |
| New architectural plan written | `docs/plan_<topic>.md` (status line: `> STATUS: active`) | Archive superseded plan to `docs/archive/` |
| Implementation completes a phase or renders a plan obsolete | Move plan doc to `docs/archive/`; update its status line to `implemented` | Update `project_status.json` |
| Vision or strategic goals change | `docs/vision_and_product_goals.md` | — |
| Agent operating agreement changes | `AGENTS.md` | — |

### Staleness prevention

- The CI pipeline verifies that `issues/project_status.html` is in sync with
  `project_status.json` (see `.github/workflows/ci.yml`).
- Every code review or audit must start by checking that the documents listed
  in Section 2 match the actual project state.
- If a stale reference is found (a file or tool that no longer exists), file a
  GitHub Issue and update the referring document immediately.

## 9. Product Scope Guardrails

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
- [ ] Callback routing impact assessed: change affects callback_data / callback_router / keyboard construction? (yes/no); if yes, wiring integrity test specified in contract
- [ ] Section 2.2 (Logic-lock) compliance: no invented behavior, no silent scope widening
- [ ] Section 2.3 (Contract-locking) compliance: decomposition, alternatives, independent choices
- [ ] Step 0 of Section 5 satisfied (contract lock confirmed)
- [ ] Owner inquiries for logical gaps/uncertainties made via `question` tool (multiple: true for decisions, custom: true for clarifications)
- [ ] Options and trade-offs explained in plain language per §2.4 owner experience note (no jargon, define terms, state practical impact)

Before every commit, the agent MUST verify:

- [ ] Full validation suite passed (Section 6)
- [ ] `git diff --check` and `git diff --staged --check` clean
- [ ] No secrets in staged changes
- [ ] Single logical commit (Conventional Commits format)
- [ ] Explicit `git add file1.py file2.py` only
- [ ] Branch name follows `type/short-desc` convention
- [ ] `<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>` keyword present in response
- [ ] Test failures classified (bug vs. intentional change); uncertain cases resolved via `question` tool with `custom: true` per fallback protocol in Section 2.4
- [ ] CI checks passed (`gh pr checks`) or owner accepted failure before merge

(End of file)