# HamZaboon Agent Guidance

This document is the repository-level operating agreement for AI coding
agents, Devin sessions, and human contributors working on HamZaboon. Follow it
alongside the repository README, `ROADMAP.md`, and the user's explicit request.
If those sources conflict, follow the more specific and more recent
instruction.

**SESSION START PROTOCOL**: At the start of every new session or major task,
the agent SHOULD silently verify or explicitly output the **Appendix A** checklist
to refresh context-window constraints before proceeding.

_Last updated: 2026-08-05. See git history of this file for prior versions
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
| `docs/plans/` | Implementation plans grouped by dependency theme: `fsrs/` (FSRS migration chain), `content/` (pooling, extraction, quality hardening), `costs/` (LLM cost metrics, financial baseline). | Plan files reference related plans via `docs/plans/<theme>/` paths; archive superseded plans to `docs/archive/`. |
| `docs/audit/` | Read-only audit reports and architecture alignment blueprints. | Keep evidence-cited; reference the `docs/plans/` files they analyze via full paths. |

`project_status.json` is authoritative for phase/decision status. GitHub Issues
are authoritative for individual issue state. HTML `localStorage`, embedded
fallback data, and generated views must never be treated as canonical state.

### 2.1 Issue update policy

For a meaningful code change:

1. Identify the relevant issue IDs before implementation.
2. Update the corresponding GitHub Issue with an accurate `status`,
   `roadmap_refs`, concise evidence, and `last_reviewed` (`YYYY-MM-DD`).
3. Update `ROADMAP.md` when the work changes completed scope, remaining work,
   a locked decision, or the next planned step.
4. Update `project_status.json` if phase status, assignments, or decision locks
   changed, then run `python scripts/generate_dashboard.py`.

Statuses: `open`, `partial` (some mitigation, risk remains), `resolved`
(implementation + focused verification), `accepted-risk`, `obsolete`. Never
mark an issue resolved based only on intention, a roadmap statement, or an
unverified code edit.

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

**Bounded cleanup allowance:** A PR MAY delete provably-dead code in the
files it already touches — where "provably dead" means zero references
anywhere else, verified by grep or a test — provided the removal is declared
in the contract lock summary and does not change behavior. Speculative
refactors, cleanup of untouched files, or deletions with any behavioral
ambiguity still require explicit owner approval.

### 2.3 Owner contract-locking protocol

When a requested behavior contains multiple algorithmic or product rules, do
not ask for one blanket approval. Decompose the behavior into separately
numbered rules, each presented with a recommended option plus meaningful
alternatives in a comparison table. The owner must choose each rule
independently; choosing the recommendation for one rule does not imply
approval of the others. After implementation, report which locked rules
changed, which were deliberately not changed, and what remains uncertain;
verify each rule with focused tests or other concrete evidence.

### 2.4 Mandatory Pre-Implementation Contract Lock Gate

**BEFORE ANY CODE CHANGE—exploratory, trivial, bug fix, or major—the agent MUST:**

1. **STOP** and identify all logical gaps, uncertainties, and decision points.
2. **ASSESS** whether the change affects callback routing (`callback_data`
   strings, `callback_router` dispatch, sub-router actions) or keyboard
   construction. If yes, the test plan section of the locked contract MUST
   specify a wiring integrity test covering the new or affected routes.
3. **PRESENT** each as a numbered rule with: recommended option + ≥1
   alternative + concrete trade-offs in a comparison table.
4. **OBTAIN** explicit owner choice per rule (no blanket approvals).
5. If any logical gap, ambiguous test failure, or architectural uncertainty
   arises during gate preparation, the agent **MUST halt** and present its
   findings as a clear, focused inquiry to the project owner. **If an
   interactive question/decision tool is available in the current
   environment, use it** (with `multiple: true` for decision options,
   `custom: true` for open-ended clarification). **If no such tool is
   available, present the same structured inquiry as plain text in the
   response and explicitly halt, waiting for the owner's reply before
   proceeding.** The agent is strictly forbidden from proceeding with code
   edits until the owner explicitly answers or chooses a decision option.
6. **SUMMARIZE** the locked contract in writing using the template below.
7. **CONFIRM** owner says "proceed" or "locked" before touching code.
8. **Dependency & Wiring Map (WP2):** if the change removes/changes a feature,
   migrates, refactors, changes schema/callbacks, or changes module boundaries,
   the contract MUST include a completed **Dependency & Wiring Map**
   (Section 2.4.2). The gate refuses to lock without it. Dispositions in the
   map are verified after implementation by grep + the reverse-wiring guard
   (`tests/test_wiring.py`) + the dead-reference guard
   (`tests/test_dead_code_guard.py`).

> **Owner experience note:** The project owner is not a professional developer.
> When presenting rules, options, and trade-offs during this gate, the agent
> MUST explain each option in plain, non-jargon language. Define technical
> terms if they are unavoidable. State clearly what each option does in
> practice, what it costs (time, complexity, money if applicable), and why the
> recommended option is preferred. Do not assume familiarity with Python
> tooling, testing patterns, or deployment concepts.

**VIOLATION CONSEQUENCE**: If the agent implements without a LOCKED gate, the
owner may discard all uncommitted changes, require full rework from the gate,
and/or terminate the session. No exceptions.

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

#### 2.4.2 Dependency & Wiring Map

For any contract that removes/changes a feature, migrates, refactors, changes
schema/callbacks, or changes module boundaries, the agent MUST complete this
map BEFORE the owner locks the contract. It forces the agent to enumerate
every dependent feature up front instead of leaving a silent half-wiring.
Dispositions (`update` / `remove` / `keep`) are then verified after
implementation by grep, the reverse-wiring guard (`tests/test_wiring.py`), and
the dead-reference guard (`tests/test_dead_code_guard.py`). Full template and
verification rule: see the `contract-lock-gate` and `callback-wiring` skills.

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
  - `handlers/admin.py`: Admin panel **thin dispatcher** — owner gate, callback routing (`_handle_admin_callback`) by prefix to the domain sub-routers below, text-input awaiting dispatch (`_handle_admin_text_input`), and admin-infra handlers (backup/restore, broadcast, phonetic / log-level / user-activity settings). Domain logic lives in the submodules.
  - `handlers/admin_stats.py`: Admin **stats** sub-router (`handle_admin_stats`) and stats keyboards.
  - `handlers/admin_plans.py`: Admin **plans** sub-router (`handle_plan_callback`), plan wizard, and plan keyboards.
  - `handlers/admin_cost.py`: Admin **LLM cost / pricing** sub-router (`handle_cost_callback`, `_handle_llm_callback`) and cost keyboards.
  - `handlers/admin_ai.py`: Admin **AI presets / fallback / custom-test** sub-router (`handle_ai_callback`) and AI settings panels.
  - `handlers/user.py`: User settings handlers (language, goal, level).
  - `handlers/help_command.py`: User **help** module — `/help` + "راهنما" panel (`send_help_panel`), inline help-section callback dispatch (`handle_help_callback`), content-driven `HELP_SECTIONS` registry.
  - `handlers/srs_handler.py`: SRS review handlers.
- `services/`: Domain services.
  - `services/db/`: SQLite schema, migrations, transactions, persistence, quotas, daily-card state, delivery queue state, saved-word state, and plan-spec state. `services/db/__init__.py` is a thin re-export façade + shared helpers; `schema.py` owns schema/migrations, `plans.py` seeds and CRUDs the `plans` table, `settings.py` owns settings accessors, `cost_tracking.py` owns LLM cost analytics, and `preset_registry.py` owns AI preset/fallback/hourly-usage logic.
  - `services/fsrs_core.py`: Pure FSRS-6 engine (w0-w20 constants, DSR formulas, no side effects).
  - `services/word_query.py`: Pure orchestration core for the custom-word query flow — `ask` (validate→reserve→AI→persist), `prepare` (toggle translations view), `toggle_save` (save/remove saved word). Stateless functions over `services/db/*` + `validation`; no Telegram imports. Handlers (`bot.py` ask-word block, `handlers/user.py` prepare, `handlers/srs_handler.py` toggle) stay thin adapters.
  - `services/ai/`: OpenAI-compatible client, provider settings, JSON extraction, AI response validation, system prompts, AI content generation, and provider presets.
  - `services/utils/`: Utility modules.
    - `services/utils/callback_notifications.py`: Deep callback-query notification seam; semantic intent mapping, empty acknowledgements, and expected Telegram callback-answer failure handling.
    - `services/utils/formatting.py`: Learner-facing message formatting and escaping behind a stable interface.
    - `services/utils/helpers.py`: Shared helper functions (retry, cancel detection, etc.).
    - `services/utils/validation.py`: Pure custom-word input validation seam — `validate_word_query(text, language) -> Optional[error_key]` (digit rejection, Unicode `isalpha`, no vowel heuristic).
  - `services/scheduling.py`: Pure session sizing, slot planning, and timezone-aware planned timestamps.
  - `services/tts.py`: Text-to-Speech generation using Edge TTS.
  - `services/session/`: Pure FSRS session engine (frontend-agnostic).
    - `services/session/__init__.py`: Public API — `build_session_list()`, `generate_tier3_node()`, `SessionNode`.
    - `services/session/assembly.py`: 3-tier priority assembler (Tier 1 due → Tier 2 first-exposure → Tier 3 AI refill). `generate_tier3_node()` is currently a stub (returns `None`) pending Phase 3b+.
    - `services/session/grade_policy.py`: `GradePolicy`, `GRADE_POLICIES`, `resolve_grade()`, activity renderers.
  - `handlers/study_handler.py`: Study-session handler — `handle_study_start()`, `advance_session()`, grade-first-exposure relay.
- `config/`: Configuration and metadata.
  - `config/__init__.py`: Environment and deployment settings; it must not become a second learner-option registry.
  - `config/catalog.py`: Canonical language, goal, and level metadata.
  - `config/keyboards.py`: Telegram menus and callback identifiers.
- `tests/test_integration/`: Handler-level integration tests simulating real user flows (see Integration Test Protocol).
  - `tests/test_integration/helpers.py`: Shared helpers for update/context construction and DB snapshot management.
- `.github/workflows/ci.yml`: GitHub Actions CI — runs lint, compile, tests, dashboard generation, and whitespace checks on push/PR to `main`.

Prefer extending an existing module and convention over introducing a new
abstraction. Keep runtime behavior separate from issue-review tooling.

### Module change guard

If the module structure changes (add, rename, split, or remove), the agent
MUST update the responsibilities table above AND the scan-target paths in
`tests/test_wiring.py` — also update `.opencode/skills/parallel-work-guard/SEAMS.md`
to keep the seam registry current.

### Callback Routing Map

The full Telegram callback-prefix → handler-module → entry-function map is
maintained in the `callback-wiring` skill (load it before adding/changing any
callback prefix or keyboard). When tracing or adding a callback, load that
skill first; it also holds the §2.4.2 Dependency & Wiring Map template and the
wiring/verification guards.

### Catalog rule

Language, goal, and level identifiers and learner-facing metadata belong in
`config/catalog.py`. Do not create parallel dictionaries in `config/__init__.py`,
`services/ai/prompts.py`, `bot.py`, or `config/keyboards.py`. New options must:

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
and LTR (English, code, variables, numbers). **Every dynamic value** that
originates from the AI, the database, or user input **MUST be passed through
the centralized escaping function in `services/utils/formatting.py`** before
being interpolated into any MarkdownV2 template string in `bot.py`. Never
concatenate a raw dynamic value directly into a reply string. If a value is
already known to be pre-escaped or is a static, hardcoded literal, that must
be stated explicitly in a code comment at the call site.

The full escaping contract, special-character list, code examples, and testing
requirements live in the `persian-formatting` skill — load it before adding or
modifying any learner-facing message.

## 4. Audit and Code-Review Workflow

When asked to audit or review the project, load the `audit-workflow` skill and
follow it. Its core steps: read the source-of-truth documents (§2), inspect
all relevant modules and tests, trace data/control flow across handlers,
callbacks, AI calls, SQLite writes/migrations, scheduled delivery/retries,
timezone boundaries, and quotas; compare each existing issue with current code
evidence; classify findings by impact and confidence; record findings as
GitHub Issues; reconcile consequences in `ROADMAP.md`; and run focused plus
repository-wide checks before reporting.

**Context economy:** when investigating a bug or making a targeted change,
read the specific function/handler and its direct dependencies first rather
than the entire module or repository, unless the reported behavior requires
tracing broader data/control flow. Expand scope only as evidence demands it.

If a product or safety decision cannot be inferred, ask one focused question;
do not silently choose a policy that changes user limits, cost exposure, or
stored learning data.

## 5. Implementation Workflow

For a non-trivial task:

0. **Contract lock confirmed per Section 2.4 (Mandatory Pre-Implementation Contract Lock Gate).**
1. Implement on current branch (or stash changes); run full validation (§6).
2. **Create a fresh feature branch from the latest `origin/main`** using
   convention: `type/short-desc` (e.g., `feat/custom-words`, `fix/collision-retry`).
3. **Write focused unit tests** in `tests/` for any new logic, edge cases,
   database schema changes, or callback routing changes. For any change that
   touches `callback_data` strings, `callback_router` dispatch conditions, or
   sub-router action patterns, a cross-module callback wiring integrity test
   MUST be added or updated (see `tests/test_wiring.py`). For behavioral
   changes (handler logic, keyboard construction, database writes, quota
   enforcement, or AI interaction), add handler-level integration tests in
   `tests/test_integration/` following the Integration Test Protocol (§6).
   **Tests must be written from the user-facing behavior spec and the locked
   contract, not from the implementation's internal choices.**
4. Stage modified files explicitly: `git add file1.py file2.py` (never `git add .`).
5. Commit with Conventional Commits format: `type(scope): subject`.
6. Push branch and create PR via `gh pr create --fill --base main`. If the PR
   resolves tracked issues, link them in the body (e.g., "Resolves #N").
7. Owner reviews and merges on GitHub using **Squash and merge**. If the owner
   explicitly instructs "merge it" (or equivalent), the agent may run
   `gh pr merge --squash` on the owner's behalf, confirming CI passes first.
8. After merge, clean up locally: `git checkout main && git pull && git branch -d branch-name`.
9. Update GitHub Issues and `ROADMAP.md` as required by §2; apply the
   Documentation Update Protocol (§8).
10. Run the validation commands below.
11. After PR creation, run `gh pr checks` to monitor CI. If checks fail,
    apply the Error Recovery Protocol (§7).

For full branch/PR/merge/`gh` detail, load the `git-protocol` skill.

Do not combine unrelated user-facing features, broad refactors, and issue
cleanup in one PR. If a discovered issue is outside the requested scope,
record it rather than silently expanding the implementation.

### Independent Review Subagent (mandatory for non-trivial changes)

Before committing any change that affects behavior, persistence, quotas,
scheduling, callbacks, AI contracts, module boundaries, or a schema
migration, the implementing agent MUST launch a separate reviewer subagent
(`hamzaboon-reviewer`, defined in §10) with fresh context, so that the
implementation is not reviewed by the same context that produced it. The
reviewer assumes the implementation is wrong until proven correct, reviews
the diff against the locked contract and behavior spec, reports only (it
MUST NOT edit files), and checks for confirmed bugs, spec-vs-contract gaps,
leftover old symbols, state leaks, restart safety, quota/date boundaries,
callback wiring, test independence, and scope violations.

The implementing agent fixes confirmed findings and re-runs the reviewer
until none remain. If the reviewer surfaces a genuine ambiguity or product
decision, the implementing agent MUST halt and ask the owner per §2.4.
Trivial, non-behavioral changes (typos, comments, docs) skip this step.

### Reviewer tier (cheap model for trivial edits)

| Change scope | Reviewer required? | Default model |
|---|---|---|
| Trivial (1–2 line behavioral swap, doc/string fix) | Skip subagent, OR run on cheap model | Tencent Hy3 (free) via Kilo Gateway |
| Schema / callback / quota / AI / multi-file | Full independent review | Override to a stronger model per run |
| Non-behavioral (typos, comments, docs, formatting) | Skip (fast-track) | N/A |

The `hamzaboon-reviewer` agent defaults to the cheap Tencent Hy3 model via Kilo Gateway. For
risky changes (schema, callbacks, quotas, AI), the invoking agent should pass
a stronger model at invocation time. The reviewer remains read-only
(`edit: deny`, `bash` limited to `ruff`/`pytest`/`git diff`/`git log`/`grep`)
regardless of model tier.

## 6. Required Validation

The validation skill (`hamzaban-validation`) has two tiers. Choose based on change scope:

- **Full suite** (behavioral changes — handlers, DB, callbacks, AI, quotas, schemas, production `.py`): `pytest`, `compile_all.py`, `ruff F821/F811`, `generate_dashboard.py`, `git diff --check`.
- **Lightweight path** (non-behavioral changes — docs, skills, agents, plans, formatting, comments, test-only): `git diff --check` only.

Load `hamzaban-validation` before committing or creating a PR and select the appropriate tier. CI always runs the full suite; the lightweight path is a local-only optimization.

**Locked test worker rule:** local runs MUST use `python -m pytest tests/ -n 14`
(the machine has 24 logical cores; `-n 14` is the fast-and-stable count, ~2x
faster than the CI count). The CI count (`-n 4`, `.github/workflows/ci.yml`) is
only for matching GitHub Actions output exactly. Never use `-n 14` in CI files,
and never default local runs to the CI count.

For changes to a specific subsystem, add focused tests before relying on the
full suite: scheduling/delivery (queue state, retry budget, backoff, restart
safety, shared slots), AI (timeout, JSON validation, limiter, async
offloading), callbacks (authorization, catalog validation, wiring integrity),
quotas/saved words (transaction races, date boundaries, normalization,
duplicates), SRS/broadcasts (retry, chunking, partial-failure progress), and
schema changes (fresh DB + migration from prior schema).

Do not claim CI success from local tests. Report CI based on the repository
checks (GitHub Actions, `.github/workflows/ci.yml`) after the PR is opened.

### Integration Test Protocol

For behavioral changes (callback routing, handler logic, keyboard construction,
database writes, quota enforcement, or AI interaction), the agent MUST add or
update handler-level integration tests in `tests/test_integration/` following
the **Integration Test Protocol** — the full protocol (scope and coverage,
database snapshot isolation, mocked Telegram via `AsyncMock`, AI mocking with a
1000-token real-AI budget, test-file conventions, and the contract-lock
requirements for new tests) is enforced by the `integration-test-proto` skill.
Load it before writing any integration test.

### Handling Broken or Outdated Tests

If a test fails because the underlying product logic was intentionally changed
or deprecated:

a) The agent **MUST NOT** silently delete, disable, or ignore the test.
b) The agent **MUST NOT** revert correct code modifications just to make an outdated test pass.
c) The agent **MUST** determine if the failure is due to a bug or an
   intentional logic change. If intentional, update or rewrite the test to
   reflect the new canonical behavior, ensuring coverage remains intact.
d) If the agent is uncertain whether a test failure represents a regression or
   an obsolete expectation, it **MUST halt and ask the project owner** per the
   fallback protocol in §2.4.

## 7. Git and Security Discipline

### Mandatory Pre-Commit Validation Gate

**BEFORE ANY COMMIT, the agent MUST:**

1. Run the full validation suite (§6, via `hamzaban-validation`).
2. Run `git diff --check` and `git diff --staged --check` — no whitespace errors.
3. Verify no secrets, credentials, tokens, API keys, or generated secrets in staged changes.
4. Confirm single logical change per commit (§5 steps 3–4).
5. Verify branch naming convention: `type/short-desc` with type in `feat|fix|docs|refactor|test|chore`.
6. While `tests/test_wiring.py` and `tests/test_formatting.py` are recommended
   locally, any CI failure in these tests triggers the Error Recovery Protocol
   — fix and re-push immediately. Unlike other tests, `tests/test_wiring.py`
   performs cross-module introspection and cannot be faked or satisfied by
   local-only changes.
7. **Definition of Done** — every commit proves each applicable criterion:
   - New or changed behavior is covered by a focused test, and by an
     integration test in `tests/test_integration/` when the change touches
     handler logic, keyboards, callbacks, DB writes, quotas, or AI;
   - No leftover references to symbols that this change was meant to remove
     (enforced by the dead-reference guard `tests/test_dead_code_guard.py` and
     the reverse-wiring guard `tests/test_wiring.py`);
   - Schema changes are tested on BOTH a fresh database and an upgrade from
     the prior schema;
   - GitHub Issues and `ROADMAP.md` are updated per §2;
   - Where the Independent Review Subagent applies (§5), it reported no
     confirmed findings after the fix cycle.

> **Phase 2 — F401 (unused imports):** When the codebase is ready for a stricter
> rule budget, run `ruff check --fix --select F401` to auto-clean unused
> imports, review the changes manually, then add `F401` to `ruff.toml`'s
> `select` list and update this gate accordingly. Do not add F401 before the
> cleanup pass is done and reviewed.

**VIOLATION CONSEQUENCE**: If the agent commits without passing the validation gate, the owner may discard the commit, require rework from a clean state, and/or terminate the session. No exceptions.

**GATE KEYWORD**: The agent must include **`<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>`** in its response before any commit.

### Git protocol, PRs, gh CLI, security, and recovery

All branch/commit/PR/`gh` rules (commit format, explicit staging, no amend, no
destructive git, branch naming, squash-and-merge, post-merge cleanup, allowed
`gh` operations, `gh` token safety, PowerShell backtick safety, subagent
non-ASCII sanitization, security rules, and the Error Recovery Protocol) are
enforced by the **`git-protocol` skill**. Load it before running any git/gh
operation, and follow it exactly.

<!-- TODO: Owner to decide on a convention for preventing concurrent agent edits on the same branch/files (see AGENTS.md #10). -->

## 8. Documentation Update Protocol

Keep the documentation ecosystem coherent after every meaningful code or
product change. The **`documentation-protocol` skill** enforces the full
"what to update and when" matrix (status/decisions → `project_status.json` +
dashboard regeneration, roadmap narrative → `ROADMAP.md`, module structure →
AGENTS.md §3 + `tests/test_wiring.py` scan paths, tooling → `README.md`, plans →
`docs/plans/` with archive to `docs/archive/`, issues, vision doc, AGENTS.md)
plus the canonical-source and staleness-prevention rules. Load it after any
meaningful code or product change, and follow it exactly.

## 9. Product Scope Guardrails

For product direction, consult the locked plans and theme indexes, GitHub
Issues, and `ROADMAP.md`. This file is not a roadmap.

## 10. OpenCode Skills, Subagents, and Plan Persistence

<!-- [opencode-setup:start] -->

This section is a delimited, revertible block. It defines how skills and
subagents are loaded and how plans must be persisted. Reverting the whole
setup = delete this block (plus the `.gitignore` `[opencode-setup]` block and
the `.opencode/` folders). See `docs/archive/plan-opencode-tooling-setup-2026-08-05.md` (completed setup plan).

### 10.1 Skill loading policy

Skills are loaded **lazily and only when relevant** to control token usage —
they are NOT injected into every session. The agent loads a skill via the
`skill` tool only when the task matches the skill's description. Repo-specific
skills live in `.opencode/skills/`; general-purpose reusable skills live
globally in `~/.config/opencode/skills/` (shared across all projects).

**Compliance rule:** when a trigger in §10.2 matches the current task, loading
the corresponding skill is MANDATORY, not optional. The agent MUST load the
skill before proceeding with the matching action, and MUST follow its contents
exactly. Loading a skill and ignoring its rules is a compliance violation.

### 10.2 Skills map (mandatory load triggers)

Skills are loaded **lazily on trigger only**. No skill is pre-injected. When a
trigger matches, loading is mandatory; when it does not match, the skill is not
loaded. Each row below has a single conditional trigger sentence.

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
| `codebase-design` | Designing or refactoring a module's interface (global skill at `~/.config/opencode/skills/codebase-design`). |
| `i18n-accessibility` | Auditing or adding RTL/bidi, `lang`/`dir`, mixed-direction forms, or icon mirroring. |
| `core-web-vitals` | Asked to improve LCP/INP/CLS or page experience. |
| `frontend-ui-engineering` | Building or modifying UI components, pages, or interfaces. |
| `reviewing-interface-quality` | Asked to review, audit, or critique an interface, or as a pre-ship UI gate. |
| `graphify-index` | Structural queries or large refactors needing symbol relationship queries. |
| `spec-to-tickets` | A complex task needs per-phase breakdown before execution. |
| `reviewing-security` | Reviewing code for security before merging or shipping, or when a change touches untrusted input, auth, secrets, SQL, subprocess, paths, or outbound requests. |
| `evolving-apis-and-schemas` | Changing anything other systems or stored data depend on: schema, API, enum, queue format, migration. |
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
test-master, code-reviewer, debugging-wizard, accessibility,
frontend-design, testing-webapps, investigating-performance,
reviewing-interface-quality. These may be used across any
project; they are optional conveniences, not HamZaban-specific gates.

MattPocock workflow skills are installed globally and load lazily when their
trigger matches. Follow his workflow for the parts HamZaban does not already
lock down with a repo-local gate:

- Owner-triggered slash commands (only fire when the human types them, mirroring
  MattPocock's `disable-model-invocation` skills): `/grill-me`, `/grill-with-docs`,
  `/to-spec`, `/to-tickets`, `/triage`, `/implement`, `/handoff`, `/teach`,
  `/to-questionnaire`, `/wait-what`, `/improve-codebase-architecture`.

Where a MattPocock skill overlaps a repo-local gate (e.g. `diagnosing-bugs` vs
`bug-diagnosis`, `tdd` vs `tdd-enforcement`, `code-review` vs the Independent
Review Subagent in §5), the repo-local gate remains canonical and takes
precedence; the global skill is a supporting refinement, not a replacement.
When asked to plan a change, use `/to-spec` → `/to-tickets` to keep the
grill-to-spec / spec-to-tickets discipline aligned with MattPocock's workflow.

### 10.3 Lean subagents

`.opencode/agents/` defines specialized subagents with tightly scoped tool
permissions to minimize per-turn prompt overhead and prevent out-of-domain
edits. Use them for their domain:

| Subagent | Domain | Key permission |
|---|---|---|
| `hamzaboon-db` | `services/db/*`, `services/fsrs_core.py` | bash → db/reviews/fsrs/migrations tests only |
| `hamzaboon-ai` | `services/ai/*` | bash → ai tests only |
| `hamzaboon-handler` | `handlers/*`, `config/keyboards.py`, `bot.py` | bash → integration/wiring/formatting tests only |
| `hamzaboon-reviewer` | independent review | `edit: deny`; read-only |

The Independent Review Subagent requirement (§5) is satisfied by
`hamzaboon-reviewer`.

### 10.4 Plan persistence rule

When a locked plan begins execution, the agent MUST persist the full plan with
per-phase/step progress status to `.opencode/plans/<theme>/plan-*.md`, register
it in that theme's `index.md`, and cross-reference it in the global
`.opencode/plans/TICKETS.md` register. Update the plan STATE line, theme index,
and global ticket entry after each implementation step. This keeps the plan
complete and current so that continuation after context compaction or in a new
chat produces correct results, not corrupted or gap-filled outcomes.

The global ticket register is a cross-reference only: GitHub Issues remain the
canonical source for issue state, `project_status.json` remains canonical for
phase and decision status, and plan files remain canonical for implementation
details. Never silently renumber a plan's internal tickets; record the mapping
in `TICKETS.md` instead.

For complex/thorough tasks with nuances and critical module changes (schema
migrations, callback routing, module boundary changes, multi-file refactors),
the agent MUST create a per-phase plan file for each phase of the main plan
(`.opencode/plans/plan-<main>-phase-<NN>-<topic>.md`). This forces each phase's
details to be specified up front and prevents silent self-filling of logical
gaps. Plans that introduce or change behavior must trace back to their locked
Contract Lock rules.

**Archive rule:** when a plan is done and completely evaluated, it moves to
`docs/archive/` (with a date suffix). `.opencode/plans/` keeps only active or
in-progress plans.

### 10.5 Parallel Work Claims

Before any Contract Lock Gate reaches GATE STATUS: LOCKED, the agent MUST run
the parallel-work-guard skill to check the shared claims file resolved from
the common Git directory (`<git-common-dir>/parallel-work-claims.json`) for
seam-level claim overlaps with other in-progress branches/worktrees, per the
locked rules below.

1. Conflict unit is the seam registry (SEAMS.md), not file diffs.
2. Claims are written to the shared common-Git-directory claims file at GATE
   STATUS: LOCKED, not to tracked worktree files.
3. Overlap = warn with the exact resource named + explicit owner decision
   required (proceed anyway / wait). Never silent block, never silent proceed.
4. Claims are removed on post-merge cleanup (§5 step 8); claims older than 14
   days are flagged for owner review, not auto-deleted. Malformed registry data
   halts claim-guarded work and requests owner repair; unrelated read-only
   investigation may continue.
5. Deep-module seam review is folded into the existing hamzaboon-reviewer
   checklist (§10.3) — no new subagent.

Full mechanics: `parallel-work-guard` skill. Seam registry: `SEAMS.md` (same
skill folder).

Before creating or starting work in a parallel branch or worktree, the agent
MUST load `parallel-work-guard`, resolve the shared claims file from the common
Git directory, check every affected canonical seam in `SEAMS.md`, and record a
claim after the contract reaches `GATE STATUS: LOCKED`. A dirty or unrelated
worktree MUST NOT be overwritten; propagate shared documentation changes only
through a clean, explicit update or a later owner-approved synchronization.

<!-- [opencode-setup:end] -->

## Appendix A: Agent Self-Check Checklist

**Context Refresh Protocol**: At the start of every new session or major task, the agent SHOULD silently verify or explicitly output this checklist to refresh context-window constraints before proceeding.

Before every implementation message, the agent MUST verify (full details in §2.4 + `contract-lock-gate` skill):

- [ ] All logical gaps identified and presented as numbered rules with recommended option + ≥1 alternative in a comparison table
- [ ] Owner has explicitly chosen each rule independently; Contract Lock Template filled completely
- [ ] Owner confirmation quoted ("proceed" or "locked"); GATE STATUS = LOCKED
- [ ] `<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>` keyword present
- [ ] No code changes proposed or implemented before gate lock
- [ ] Callback routing impact assessed; if affected, wiring integrity test specified in contract
- [ ] §2.2/§2.3 compliance: no invented behavior, no silent scope widening
- [ ] Owner inquiries made via `question` tool (`multiple: true` for decisions, `custom: true` for clarifications); options explained in plain language

Before every commit, the agent MUST verify (full details in §6, §7, `pre-commit-gate` + `git-protocol` skills):

- [ ] Full validation suite passed (§6); `git diff --check` and `git diff --staged --check` clean
- [ ] No secrets in staged changes; single logical commit (Conventional Commits); explicit `git add file1.py file2.py` only
- [ ] Branch name follows `type/short-desc` convention
- [ ] `<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>` keyword present
- [ ] Test failures classified (bug vs. intentional change); uncertain cases resolved via `question` tool (`custom: true`) per §2.4 fallback
- [ ] CI checks passed (`gh pr checks`) or owner accepted failure before merge

(End of file)
