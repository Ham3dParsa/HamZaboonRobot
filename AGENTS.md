# HamZaban Agent Guidance

Operating agreement for AI agents, Devin sessions, and human contributors on
HamZaban. When this file, `ROADMAP.md`, or the user's request conflict, follow
the more specific and more recent instruction.

GitHub Issues are the canonical issue registry; `ROADMAP.md` is product
direction. Neither `project_status.json` nor any generated view is canonical.

_Last updated: 2026-08-18._

## 1. Product

Telegram language-learning assistant for Persian speakers. MVP: AI-generated
vocabulary cards + grammar tips; pull-based study sessions with saved-word
spaced repetition (FSRS-6); language/goal/level preferences; Free/Bronze/Silver/
Gold/Emerald session limits; owner-only admin. No daily push delivery.

Priorities: safe understandable Telegram UX; predictable AI/Telegram resource
use; durable, restart-safe background work; correct quotas/dates/idempotency;
no duplicated language/goal registries. Learner-facing educational content
stays AI-generated through the existing prompt+validation flow.

## 2. Contract Lock Gate (mandatory, before ANY code change)

Every code change — exploratory, trivial, bug fix, or major — requires a
locked contract BEFORE touching code:

1. STOP. Identify every logical gap, algorithm decision, product rule.
2. Assess callback-routing impact (see `callback-wiring` skill).
3. Present each gap as a **numbered rule** with a recommended option, ≥1
   alternative, and trade-offs in plain language (owner is not a developer).
4. Owner chooses each rule independently (no blanket approval).
5. Fill the Contract Lock Template; owner must say "proceed" or "locked".
6. Include `<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>`
   before any implementation.

Fast-track exception (non-behavioral only: typos, comments, docs, formatting,
test-only with no behavior change) skips the full gate — state it under
`<SYSTEM_GATE>` and proceed.

Full protocol lives in the `contract-lock-gate` skill. **Load it before any
code change.**

**Logic-lock rule:** Never invent missing algorithmic behavior, silently widen
scope, or lock a product/architecture decision to close an inferred gap. Report
what changed, what was deliberately not changed, what remains uncertain.

**Bounded cleanup allowance:** a PR may delete provably-dead code only in the
files it already touches, declared in the contract, with zero behavioral change.

## 3. Semantic Centralization (single source of truth)

Every domain concept MUST have exactly one owning module under `services/` or
`config/`:

- **NO parallel fallbacks** — no duplicate dictionaries/defaults outside the owner.
- **NO business logic in `config/` or `services/utils/`** — `config/` is static
  metadata + env bindings; `services/utils/` is domain-agnostic helpers.
- **Pre-implementation scan** — before touching domain logic, run
  `grep -rn "<keyword>" services/ config/ handlers/` and locate every source.
  If duplicates exist, state the target single-source module and plan removal.

**Enforcement:** `tests/test_single_source_of_truth.py` (CI) fails if a curated
domain keyword appears in any file outside its owner module. Add keywords there,
not in prose.

## 4. Repository Architecture

- `bot.py`: thin entry point — handlers, callback dispatch (`callback_router`).
- `services/routing.py`: central callback registry `ROUTES` + `register()`. Longest-prefix match, owner-gate, single-answer guarantee.
- `handlers/`: Telegram handlers.
  - `handlers/admin.py`: thin admin dispatcher; registers admin/llm routes in `services/routing`; admin awaiting flows in `handlers/flows.py`; admin-infra handlers (backup/restore, broadcast, settings).
  - `handlers/flows.py`: central awaiting text-input flow registry — `AwaitingFlow`, `register_flow()`, `resolve_flow()`, `text_router()` (only entry `bot.py` calls).
  - `handlers/admin_stats.py`, `admin_plans.py`, `admin_cost.py`, `admin_ai.py`: admin sub-routers (stats / plans / cost / AI presets).
  - `handlers/admin_backup.py`: admin backup/restore sub-router (`handle_admin_backup_callback`, `cmd_backup`, `cmd_restore`, `handle_restore_doc`, `auto_backup_job`, `admin_restore`/`admin_archive_chat_id` flows).
  - `handlers/user.py`: user settings (language, goal, level).
  - `handlers/help_command.py`: `/help` + "راهنما" panel — `send_help_panel`, `handle_help_callback`, `HELP_SECTIONS`.
  - `handlers/srs_handler.py`: SRS review / first-exposure grading.
- `services/`: domains.
  - `services/fsrs_core.py`: pure FSRS-6 engine (no side effects).
  - `services/plan_fields.py`: canonical admin-editable plan-field schema (mirrors `services/ai/preset_fields.py`); drives the plan-manager wizard in `handlers/admin_plans.py`.
  - `services/word_query.py`: pure custom-word query orchestration (`ask`, `toggle_save`); no Telegram imports.
- `services/activity_log.py`: single owner of the `USER_ACTIVITY` diagnostic log (`log_user_activity`); consolidates the former logging blocks in `handlers/user.py` and `handlers/srs_handler.py`.
  - `services/db/`: SQLite schema/migrations/persistence/quota. `__init__.py` thin re-export façade; `schema.py` owns schema/migrations; `plans.py` seeds+CRUDs plans; `settings.py` settings accessors; `cost_tracking.py` LLM cost; `preset_registry.py` AI preset/fallback/hourly-usage; `display_toggles.py` display-toggle state + precedence; `key_crypto.py` key encryption (fail-closed); `session_reports.py` persisted post-session report store (R10).
  - `services/ai/`: OpenAI-compatible client, JSON extraction, validation, prompts, generation, presets. `preset_fields.py` owns canonical AI-preset field schema. `ai_read_cache.py` owns the hot-path TTL read caches (fallback chain, LLM cost profile) for BOT-1/2 amplification reduction.
  - `services/utils/`: `callback_notifications.py`, `formatting.py` (escaping), `helpers.py` (retry/cancel), `validation.py`.
  - `services/scheduling.py`: pure session sizing, slot planning, timezone-aware timestamps.
  - `services/tts.py`: Edge TTS pronunciation.
  - `services/session/`: pure FSRS session engine — `__init__.py` (`build_session_list`, `generate_tier3_node`), `assembly.py`, `grade_policy.py`, `summary.py` (post-session report builder).
  - `handlers/study_handler.py`: study-session handler.
- `config/`: `__init__.py` env/deployment settings (not a second registry), `catalog.py` (canonical language/goal/level metadata), `plan_identity.py` (canonical plan-set membership + premium tiering), `keyboards/__init__.py + keyboards/*.py` (menus + callback identifiers).
- `tests/test_integration/`: handler-level integration tests.

**Module change guard:** if module structure changes (add/rename/split/remove),
update this table, `tests/test_wiring.py` scan targets, and
`.opencode/skills/parallel-work-guard/SEAMS.md`.

**Prefer extending an existing module and convention** over a new abstraction.

### Callback Routing

The full callback-prefix → handler → entry-function map lives in the
`callback-wiring` skill. Load it before adding/changing any callback prefix or
keyboard.

## 5. Reliability Rules

- Use `APP_TIMEZONE` for application-day; UTC for processing metadata.
- Keep AI calls behind the global concurrency/request limiter and an explicit
  timeout — never run blocking sync provider calls on async Telegram handlers.
- Route session rendering, SRS grading, and broadcasts through the shared
  Telegram retry/concurrency path. Retries bounded, back off via shared
  helpers, terminal after the attempt budget.
- Quota checks that reserve usage must be atomic. Saved-word writes normalized + idempotent.
- Preserve restart safety; avoid duplicate cards/messages/provider requests.
- **Secrets:** never expose API keys/tokens in code, logs, tests, commits,
  issues, or PRs. AI keys encrypted at rest (Fernet) via
  `services/db/key_crypto.py`; fail-closed (missing master key ⇒ no key
  resolves, never plaintext). Document new env vars in `.env.example`.
- **SQLite concurrency:** writes use immediate/exclusive transactions; never
  hold an open transaction across an awaited async call.

**AI cost discipline:** state token/cost impact in the contract lock. Prefer
cached/pooled content over a new AI call. Any change raising per-user/per-day
AI call volume needs explicit owner approval, even under fast-track.

**Localization:** all learner-facing text must be correct Persian. Every dynamic
value from AI/DB/user input MUST pass through `services/utils/formatting.py`
before MarkdownV2 interpolation. Load `persian-formatting` before changing any
learner-facing message.

## 6. Implementation Workflow

Load the relevant skill by trigger (see §9). Core discipline:

0. Contract locked (§2) before any code.
1. Worktree Isolation Gate — primary worktree (`HamZaban` root) stays on `main`
   and stays clean: never `git checkout`/`switch`/`branch` there. For every
   task, create an isolated worktree at `.worktrees/<type/short-desc>` via
   `git worktree add .worktrees/<branch> -b <branch> origin/main` (see
   `using-git-worktrees` + `parallel-work-guard`), `cd` there, and do ALL
   edits/commits/tests inside it (`git rev-parse --show-toplevel` ≠ primary).
   Gate passes when `git -C <primary> branch --show-current == main` and
   `git -C <primary> status --porcelain` clean, and `git worktree list` shows
   the task worktree. If primary is dirty, treat it as read-only — do not
   stash/commit it.
2. Write focused tests from the behavior spec + locked contract, not internals.
   Behavioral changes (handlers/keyboards/DB/quota/AI/callbacks) need
   `tests/test_integration/`; callback/router changes need a
   `tests/test_wiring.py` test.
3. Independent Review Gate — mandatory for behavioral changes: if change touches
   handlers/DB/callbacks/AI/quota/schema/production `.py` (same scope as §7 Full
   suite), launch `hamzaban-reviewer` via `Task(subagent_type="hamzaban-reviewer")`
   BEFORE `pre-commit-gate`. Gate passes only when reviewer reports `0 confirmed
   findings` or every confirmed finding is fixed and re-verified. Include
   `<SYSTEM_GATE> Independent review required before commit </SYSTEM_GATE>`.
   Fast-track docs/skills/agents/plans/formatting/comments/test-only (no behavior
   change) skips this step — state it under `<SYSTEM_GATE>`.
4. Stage explicitly (`git add file.py` — never `git add .`); Conventional
   Commits; push; open PR via `gh pr create --fill --base main` linking issues.
5. Owner merges **Squash and merge**; agent may `gh pr merge --squash` only on
   explicit "merge it" after CI passes. Cleanup worktree, delete branch, release
   parallel claim, update issues/ROADMAP.
6. Don't combine unrelated features/refactors/issue-cleanup in one PR.

**Route-delete rule:** routing a caller to a new path MUST delete the old path
in the same PR — enforced by the dead-reference guard
(`tests/test_dead_code_guard.py`). Never leave an old definition alive and
unreferenced.

**Test-sync rule:** a behavior change MUST update its test(s) in the same PR.
Do not silently delete/disable a failing test or revert correct code to make it
pass. Classify failure as bug vs. obsolete; if uncertain, ask per §2.

## 7. Required Validation

- **Full suite** (behavioral: handlers/DB/callbacks/AI/quota/schema/production `.py`): `pytest`, `compile_all.py`, `ruff F821/F811`, `git diff --check`.
- **Lightweight path** (non-behavioral: docs/skills/agents/plans/formatting/comments/tests): `git diff --check` only.

Local runs use `python -m pytest tests/ -n 14`. CI uses `-n 4`. Load
`hamzaban-validation` before committing/PR.

**CHANGELOG:** `CHANGELOG.md` is generated by git-cliff from Conventional
Commits via `python scripts/generate_changelog.py` (git-cliff on PATH).
Regenerate it when a release or meaningful history accumulates. Do not edit by
hand. `scripts/generate_changelog.py --check` reports staleness locally (it is
NOT CI-gated, because git-cliff regenerates whole-history from HEAD, so a
byte-exact gate would false-fail after every commit until release tags exist).

Do not claim CI success from local runs — report repo checks after PR opens.

## 8. Git & Security Discipline

Every commit: reference `git-protocol` and `pre-commit-gate` skills. Include
`<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>` before
committing. Explicit staging only; Conventional Commits; branch `type/short-desc`;
`git diff --check` + `--staged --check` clean; no secrets staged; single logical
change. Never amend, never destructive git (`reset --hard`, force-push protected
branches).

## 9. Skills (load lazily on trigger only)

| Skill | Load when |
|---|---|
| `contract-lock-gate` | Any code change proposed. |
| `parallel-work-guard` | Working in parallel / creating a branch or worktree. |
| `git-protocol` | Any git or gh command. |
| `hamzaban-validation` | Preparing to commit or open a PR. |
| `kilo-ci-loop` | After PR push or before merge — poll Kilo + OpenCode deltas (token-efficient `id->h`), CI checks, and merge conflicts. |
| `pre-commit-gate` | Immediately before a commit. |
| `integration-test-proto` | Behavioral change: callbacks/handlers/DB/quota/AI. |
| `callback-wiring` | Adding/changing a callback prefix or keyboard. |
| `persian-formatting` | Adding/changing learner-facing Persian text. |
| `audit-workflow` | Asked to audit/review the project. |
| `documentation-protocol` | A meaningful change touched docs/status/roadmap/module structure. |
| `plan-persistence` | A plan is locked / after each implementation step. |
| `spec-to-tickets` | A complex task needs phase breakdown before execution. |
| `grill-to-spec` | Plan needs ambiguity resolution before execution. |
| `tdd-enforcement` | Writing new logic or modifying behavior during implementation. |

Subagents in `.opencode/agents/` — `hamzaban-reviewer`: read-only gate for
§6.3; `hamzaban-db`/`-ai`/`-handler`: domain helpers.

Global general skills (`~/.config/opencode/skills/`) are optional conveniences,
not HamZaban gates.

## 10. Plans & Parallel Work

- Locked plans persist to `.opencode/plans/<theme>/plan-*.md` with a top `STATE`
  line + theme `index.md` + `TICKETS.md` reference; update after each step. See
  `plan-persistence` skill.
- Before a contract reaches LOCKED, check the shared claims file
  (`<git-common-dir>/parallel-work-claims.json`) for seam overlaps (see
  `parallel-work-guard`). Claim seams at LOCK; release on post-merge cleanup.

## Communication

Be **terse**: state the point in a short paragraph or bullet list. Only expand
when the owner explicitly asks for detail. Bullets over prose.

## Appendix A: Self-Check

**Before implementation:** primary on `main` clean and worktree isolated (§6.1
gate passed: `git -C <primary> branch --show-current == main`, `git -C <primary>
status --porcelain` clean, work inside `.worktrees/<branch>`); all gaps as
numbered rules with options + trade-offs; owner chose each; Contract Lock
Template filled; `GATE STATUS = LOCKED`; `<SYSTEM_GATE> Contract lock required
before proceeding </SYSTEM_GATE>` present; no code before lock; callback impact
assessed; §2.2 §2.3 compliant; `grep` verified no duplicate domain logic (§3).

**Before commit:** work inside `.worktrees/<branch>` (§6.1 primary still on
`main` clean); validation suite passed (§7); `git diff --check` + staged clean;
no secrets; single logical commit; explicit `git add`; branch `type/short-desc`;
`<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>` present;
`<SYSTEM_GATE> Independent review required before commit </SYSTEM_GATE>` present
(§6.3 gate passed: `hamzaban-reviewer` Task completed — 0 confirmed findings or
all fixed and re-verified); failures classified (§6 Test-sync); dead references
removed (§6 Route-delete).