# HamZaban Roadmap

## Product Goal

HamZaban is a Telegram-based language-learning assistant for Persian-speaking
learners. It provides personalized vocabulary, grammar lessons, spaced
repetition, and daily learning content across multiple target languages.

The roadmap prioritizes reliable learning value, predictable AI costs, clear
Telegram UX, and an architecture that can support additional languages without
rewriting the core content flow.

## Current Scope

The project is an MVP with:

- AI-generated vocabulary and grammar content
- Daily vocabulary cards cached in SQLite
- User language and learning-goal preferences
- Saved words with simple spaced repetition
- Free, Silver, and Gold plan limits
- Owner-only administrative settings and per-user plan assignment
- An explicit owner bypass for plan limits during development

## Project Status Model

This document is the human-readable product narrative. Machine-readable
status is maintained in `project_status.json`. Engineering records are tracked on
[GitHub Issues](https://github.com/Ham3dParsa/HamZaboonRobot/issues).

The read-only dashboard at `issues/project_status.html` is generated from
`project_status.json`. It is an exported review surface, not an editor: browser
state, `localStorage`, and generated HTML data are never authoritative.

Every implementation phase uses the same board:

- **Done** — verified scope already delivered.
- **In progress** — active work or partial implementation.
- **To-do** — planned work not yet delivered.
- **Acceptance criteria** — the evidence required before the phase is complete.

Engineering records are categorized as `feature`, `bug`, `risk`, `tech-debt`,
`research`, or `decision`. Issue status, phase status, and decision status are
separate concepts and must not be conflated.

<!-- _Status data is maintained in `project_status.json`; see `issues/project_status.html` for the visual dashboard._ -->

## Product Layers (MVP / Measurement / Future Bets)

This roadmap is organized around three concerns. The discipline is that real-user evidence — not feature enthusiasm — drives the roadmap forward.

- **Layer 1 — Core MVP (phases 1–6):** prove the loop — a user arrives, does a study session, learns something useful, reviews it, returns. This is the active build. "Stable" here does **not** mean feature-complete; it means the core loop is reliable enough that observed user behavior reflects product value rather than breakage: onboarding works, sessions start, cards generate and display correctly, SRS and review scheduling work, sessions complete without serious crashes, data is not corrupted, and AI cost stays controlled.
- **Companion — Measurement (runs concurrently with Layer 1, not after it):** from the first real user, capture the minimum signal needed to judge whether the Core MVP loop is actually valuable — e.g. onboarding completion, study start/complete, cards shown, words saved, reviews completed, returns, drop-off points, and AI cost. This is deliberately lightweight (a small set of lifecycle events), not a deferred analytics platform. It must exist during the MVP because the purpose of an MVP is to learn from real-user behavior.
- **Layer 3 — Future Bets (Phase 7, "Later product phases", deferred items):** gamification beyond streak, quizzes, social, advanced personalization, richer plans, additional AI surfaces. Until real-user data exists, these are **hypotheses, not roadmap commitments**. Trigger-gated items (e.g. content pooling at `DAU ≥ 50`) already encode this rule.

**Rule:** do not promote a Layer 3 item into active work on speculation. Measurement accompanies the MVP from day one; it is not a later phase. Real-user signal — not the volume of features built — decides what gets built next.

## Roadmap Board

### Done

- AI-generated vocabulary and grammar content
- Daily vocabulary cards cached in SQLite
- User language and learning-goal preferences
- Saved words with simple spaced repetition
- Free, Silver, and Gold plan limits
- Owner-only administrative settings and per-user plan assignment
- Explicit owner bypass for plan limits during development
- Stable issue registry workflow with `issues/issues.json` as canonical data
- Study-session resume UX: re-entering an active session always sends a fresh
  card and inactivates the old one; plan-edit wizard back button, skip
  semantics, quota/display grouping with per-field hints and pending-value
  display. Card "report" button deferred to #259.

### In progress

- Adaptive SRS core and real-progress scoring

### Deferred (awaiting trigger condition)

- Segment-level content pooling — deferred until DAU ≥ 50 AND at least one segment has ≥10 shared items with ≥2 users. See [`docs/plans/content/plan_pooling.md` § Sequencing](docs/plans/content/plan_pooling.md) for rationale and trigger verbatim.

### Next

- Mini-quiz platform, starting with weekly challenge modes and progressing toward placement and knowledge-estimate quizzes
- Structured language/goal/level Q&A with strong guardrails against irrelevant prompts
- Social profile surfaces for points, retained cards, quiz stats, and followable friends

### Later

- Additional languages only through the canonical `catalog.py` registry
- Measurement-informed advanced learning and personalization
- Broader social competition features if the minimal friend/follow model proves motivating

## Implementation Status

Completed on the current main branch:

- Phase 1: validated card schema, safe JSON handling, and example
  translations
- Phase 2: manual proficiency levels, CEFR labels, and German support
- Phase 3 baseline: on-demand/manual card generation, scheduled session
  planning, persisted daily cards, duplicate filtering, and partial-batch
  retry
- Phase 4 baseline: interactive next-card flow with persisted daily progress
- Phase 6 baseline: durable load-aware scheduled delivery, per-user queue
  states, bounded provider/Telegram concurrency, and restart recovery
- Phase 6 hardening: bounded delivery retries with exponential backoff,
  explicit AI timeout/offloading, shared Telegram retry handling, chunked SRS
  reminders, timezone-consistent day boundaries, callback validation, atomic
  word-query reservations, and idempotent saved-word persistence
- Cross-cutting option catalog: language, goal, and level metadata now live in
  `catalog.py` and are consumed by prompts, keyboards, bot status, and
  database defaults
- Batch generation infrastructure with duplicate filtering and partial-batch
  retry
- Plan access controls, owner bypass, and owner-only per-user plan assignment
- Operational configuration contract with readable clock values, shared
  timezone support for scheduled jobs, and explicit per-plan quotas
- Read-only project-status dashboard (`issues/project_status.html`) joined
  from `project_status.json` and canonical structured issue data in
  `issues/issues.json`; `issues/issues.html` remains a compatibility redirect
   and `hamzaban-issues.md` is an optional Markdown export for review
- Dashboard UX overhaul: responsive 1440p grid layout, clickable cross-tab stat cards, fixed progress bars for complete phases, corrected decision action links (phase anchors + issue links), and `--watch`/`--serve` CLI for live editing
- Custom-word query improvements: daily quota visibility, persistent
  short-lived query identity, inline `Add to review`, and removal of the
  standalone manual-save action from the primary menu
- Saved-word SRS reminders now retain complete validated cards, wait for an
  explicit learner response, and offer user-scoped remember/defer controls.
- Recent daily vocabulary and grammar-tip titles are supplied to the model as
  bounded avoid-lists to reduce repetition without replacing AI generation.
- AI output length and temperature are configurable and token usage is logged
  for each request.
- TTS pronunciation via Edge TTS (free): on-demand 🔊 تلفظ button on all card
  types, premium-only (Silver/Gold), filesystem caching, send_voice() output.
  New tts.py module (now services/tts.py) with no provider abstraction layer.
- Package restructuring: all flat Python modules moved into config/,
  handlers/, services/ai/, services/utils/, services/db/ packages. Absolute
  imports throughout. AGENTS.md responsibilities table updated. Stale audit
  and plan markdown files removed or archived. All 172 tests pass.
- Card and daily-batch provider responses support an internal `compact_json`
  wire format with a rollback-only `json` mode; this serialization choice is
  deliberately independent from learner-facing card detail.
- The compact JSON rollout preserved the canonical storage contract, but its
  prompt template also relaxed the prior card-richness examples; translation
  reveal remains tracked in issue `55` after the richness contract was restored
  in issue `54`.
- Daily batch validation now distinguishes provider success from a batch with
  no usable cards, records safe rejection diagnostics, and preserves the
  retry path.
- Colored structured logging with COST log level, USER_ACTIVITY level,
  runtime log level control, preset-switch audit logs, and colored severity
  pipe format (#204, #205).
- AI model benchmark tool with cost/retry/report pipeline (#206).
- Fallback chain schema and UX: per-preset cost fields, group_label,
  in_fallback_chain, and preset_name columns (#207); per-preset cost fields
  with global fallback (#208); preset group/pagination, full edit wizard with
  confirm dialog (#208); compact fallback chain UX with rank jump and
  consumption view (#208); help pages and last-successful-preset tracking
  (#208); extended preset edit wizard (#209).
- Admin AI Preset panel audit rework (#330): Phase 1 cosmetic (R6/R8/R9/R15),
  Phase 2 DB correctness (R1/R2/R10/R12/R13/R14) — both in PR #333; Phase 3
  handlers/UX (R3 delete confirm, R4 duplicate preset, R5 wizard back +
  current/draft display, R7 usage pagination) in PR #334 (+ follow-up #335).
  Remaining: Phase 4 (is_custom/builtin removal, #330 F1), Phase 5 (secure
  keys), Phase 6 (activation=preferred), Phase 7 (reasoning-effort).
- Integration tests for fallback chain behavior.
- Blocked-user detection to prevent wasted AI and Telegram API calls on
  users who have blocked the bot (#210).
- Documentation ecosystem overhaul: README, AGENTS.md, ROADMAP.md, and
  CI/CD pipeline improvements (#211).

## Locked Direction: Adaptive SRS Core and Real-Progress Scoring

The next highest-priority product direction is adaptive spaced repetition,
ahead of content pooling and advanced analytics. The complete implementation
plan is in `Plan_srs_core.md`; this section is the product-level source of
truth for its locked behavior.

The following decisions are locked:

- A pending SRS reminder has a 48-hour grace window. After that window,
  unanswered delivery is counted as unanswered for the rolling completion
  rate and must not suppress future reminders indefinitely.
- The rolling completion rate uses the previous seven days of sent reminders
  and explicit learner responses. Both `remembered` and `review again
  tomorrow` count as answered; sending a reminder or touching a streak does
  not count as learning.
- Initial daily reminder caps equal the existing plan daily-card allowances:
  Free 3, Silver 12, and Gold 30. The cap adjusts by one reminder per day:
  at least 70% completion increases it, below 40% decreases it, and the
  middle band holds it steady. The cap is always bounded between 1 and the
  effective plan ceiling.
- Existing users with a null cap are seeded from their current plan
  allowance. Cap adjustment is idempotent per application day, including
  startup catch-up replay.
- When due reminders exceed the cap, the most overdue words are selected
  first. Conversation-oriented goals may use multiple short windows, while
  exam-oriented goals may use fewer consolidated windows. Travel-specific
  frequency bias is deferred.
- A goal change applies to the next daily planning cycle. Already-queued
  reminders keep their current pacing shape, matching the existing daily
  session snapshot rule.
- Retention points are awarded only after a successful learner review action:
  interval indexes 1, 2, 3, and 4 award 1, 3, 6, and 10 points respectively.
  Reaching the 30-day checkpoint also awards a one-time 10-point mastery
  bonus. Generating content, receiving reminders, and streak length award no
  retention points.
- `retention_events` is append-only and prevents duplicate milestone awards.
  The displayed streak remains separate from words retained and the
  seven-day retention rate.

Implementation is phased: add the additive schema and migration coverage,
then overdue ordering, cap calculation and idempotency, goal-shaped delivery,
retention-event logging, and finally the user-facing progress indicators.
The first implementation slice must not change the existing interval
schedule or award points for delivery success alone.

## Locked Direction: Segment-Level Content Pooling

> **Deferred** — see [`docs/plans/content/plan_pooling.md` § Sequencing](docs/plans/content/plan_pooling.md) for trigger condition and independence analysis.

The next cost-control direction is a shared, source-agnostic content pool
keyed by `(target_lang, goal, level, source_kind, item_key)`. It must reuse
validated AI-generated content across learners in the same segment without
replacing the existing per-user avoid-lists or duplicate guards.

The following product decisions are locked:

- Daily/manual cards enter the pool after the existing card validation and
  accepted-storage path.
- A custom-word result enters the pool only after the learner explicitly adds
  it to SRS/review.
- A grammar tip is always retained in the learner's personal history, but
  enters the shared pool only after the learner explicitly recommends it.
  Recommendation candidates use validation fields returned by the original
  grammar-generation response; a second provider call is not allowed solely
  for pooling.
- Pool hits consume the normal learner-facing feature quota, but do not
  consume provider budget. They are recorded as zero-cost `pool_hit`
  telemetry, distinct from provider generations and failures.
- The pool uses one deployment-configurable inventory floor, initially
  `10` distinct eligible items per segment/source. A thin pool falls back to
  fresh generation.
- The additive SQLite schema reserves `source_kind` values for
  `daily_card`, `saved_query_card`, `grammar_tip`, and `quiz_item`. Word keys
  reuse the database normalization contract
  (`" ".join(value.split()).casefold()`); grammar topics use the same
  whitespace/case normalization until a dedicated topic-key contract is
  introduced.
- Pool entries survive learner-data resets and have no time-based expiry.
  Quality governance is community-driven: reports and ratings can drive
  retirement, owner removal requires approval, and automatic retirement plus
  admin review are later implementation phases.
- Points/rewards for recommendations are deferred until a reward ledger
  exists; recommendation must not silently create an untracked balance.

Implementation is intentionally phased: add the additive table and write
instrumentation first, then gated reads, saved-query and grammar
recommendation paths, pool telemetry, and inventory selection. Mini-quiz
read/write behavior remains deferred; only its reserved source kind ships
with the shared schema. The complete locked plan lives in
`docs/plans/content/plan_pooling.md`; this section and the canonical issue registry remain the
product-level source of truth.

The remaining work is tracked in the explicit ToDo section near the end of
this document. AI Mini Quizzes remain downstream of the adaptive SRS core,
and configuration and quota semantics must stay consistent with the decisions
below.

## Latest Code Review

Review scope: every Python module, all tests, `ROADMAP.md`,
`hamzaban-issues.md`, and the static `issues/project_status.html` dashboard on the
current `main` branch.

### Audit result

- The canonical issue registry was pruned to the remaining open and
  accepted-risk items after verifying the previously resolved findings in
  code.
- The active registry now tracks the issue-tooling phase-grouping
  improvement, the segment-level content-pooling work, the adaptive SRS core
  slice, and the documented plaintext-runtime-secret MVP risk.

### Open bugs and engineering risks found in this review

- Runtime API keys remain stored as plaintext in the SQLite settings table;
  this is an explicitly documented MVP risk.
- The current tests cover catalog/configuration and scheduling policy, but not
  all callback authorization, provider failure, Telegram retry, SRS chunking,
  migration, or reset behavior.

### Efficiency observations

- Each database helper opens a new SQLite connection; this is acceptable for
  the MVP but increases overhead during queue dispatch and broadcasts.
- Queue dispatch processes all due rows sequentially in one job invocation;
  the Telegram semaphore limits sends but does not provide fair concurrent
  progress across users.
- The scheduler's load accounting is in-memory and rebuilt each daily run;
  it is safe to recompute but does not reflect manually inserted queue rows
  from another worker.

### Review question still open

- Should plan quota changes apply immediately to already-queued daily sessions,
  or only to sessions planned after the change?

The reliability-hardening policy is locked for this implementation: failed
delivery sessions use bounded exponential retries and become terminal after
the configured attempt budget.

The issue-tooling ownership is locked: `issues/issues.json` is canonical for
engineering records, `project_status.json` is canonical for phase and decision
status, and `issues/project_status.html` is a read-only joined view. The
compatibility page `issues/issues.html` only redirects to the new dashboard.
`hamzaban-issues.md` remains an optional export generated only when a review
snapshot is needed.

Issue records carry explicit `category`, `phase`, `roadmap_refs`,
`decision_refs`, and dependency metadata. `issues/validate.py check` verifies
the references in both directions and rejects unassigned or multiply assigned
issues.

## Locked Architectural Decision

### Canonical Language and Learning-Option Registry

The current implementation keeps overlapping display-name and behavior
registries in multiple modules, for example `config.SUPPORTED_LANGS` versus
`prompts.LANG_NAMES_FA`, and `config.GOALS` versus `prompts.GOALS_FA`. This
means adding, removing, or changing a language or goal requires editing
several unrelated files and can silently produce inconsistent menus, prompts,
validation, or fallback behavior.

Before adding more languages or language-specific features, introduce one
canonical registry for learner-facing learning options. The registry should
own, or explicitly reference, the metadata needed by all consumers:

- stable language and goal identifiers
- Persian display names
- availability and rollout status
- prompt guidance and language-specific content rules
- example-language labels and formatting requirements
- validation/default behavior for unsupported or retired options

Modules such as `bot.py`, `keyboards.py`, and `prompts.py` must consume this
registry rather than maintaining parallel dictionaries. Language-specific
prompt guidance may remain structured data or dedicated strategy objects, but
each supported identifier must have exactly one registered source of truth.
Existing database values and callback identifiers must remain backward
compatible during migration.

**Locked decision:** the canonical registry lives in a dedicated module named
`catalog.py` (or the equivalent `domain_options.py` if the implementation
needs a more domain-oriented name). `config.py` remains responsible for
runtime and deployment settings only; `prompts.py`, `bot.py`, and
`keyboards.py` import the registry instead of defining parallel option maps.
The next language addition must use this contract.

**Acceptance criteria**

- Adding or retiring a language or goal changes one registry and its focused
  tests, not duplicated display-name dictionaries across modules.
- Menus, onboarding, settings, validation, fallback labels, and prompts
  derive their identifiers and display names from the same registry.
- Language-specific prompt rules remain explicit, testable, and do not leak
  into unrelated UI configuration.
- A registry consistency test fails when an option is referenced by one
  consumer but missing metadata in the canonical source.
- Existing stored language/goal IDs continue to load safely, including
  retired IDs with a controlled fallback.

## Locked Operational Configuration Decisions

- The configuration contract uses one shared IANA timezone for all scheduled
  behavior. The default is `APP_TIMEZONE=Asia/Tehran`.
- Human-editable clock settings use local `HH:MM` values:
  `ACTIVE_WINDOW_START`, `ACTIVE_WINDOW_END`, `PREFERRED_DELIVERY_TIME`, and
  `SRS_REMINDER_TIME`.
- The environment file provides global defaults. Per-user preferred delivery
  time, active window, and optional daily card limit remain database-backed
  overrides.
- Plan quotas are managed at runtime from the `plans` database table, not from
  deployment environment variables. The DB is the sole source of truth for the
  five plans (free / bronze / silver / gold / emerald): per-day session count,
  cards per session, and daily word-query quota. The admin plan-manager wizard
  edits and toggles these rows; `DB` seed values apply only on a fresh database.
- AI base URL, model, and API key in `.env` are bootstrap defaults only;
  owner/admin runtime overrides remain supported. Real secrets must never be
  committed.
- `OWNER_BYPASS_LIMITS=false` is the production-safe default. Development
  sessions may opt in explicitly.
- `.env.example` is organized into beginner settings and an Advanced
  scheduling/safety section. Advanced settings document units and safe
  operational ranges.
- SRS review intervals `[1, 3, 7, 16, 30]` remain product logic in code;
  only the reminder time is deployment-configurable.

## Locked Product Decisions

- Each vocabulary card is sent as a separate Telegram message.
- Manual card retrieval is on demand: the first request may prime one bounded
  2–6-card reservoir, but only the requested card is revealed and subsequent
  requests reuse the persisted reservoir.
- The manual flow must not generate the user's entire daily allowance before
  the user requests it.
- Automatic daily delivery remains a separate scheduled flow and may generate
  the user's full allowance in a controlled batch before sending separate
  messages with a short delay.
- Manual and scheduled flows share persisted cards and duplicate-avoidance
  rules, but they do not have to share the same generation granularity.
- The effective daily allowance is the lower of the plan allowance and an
  optional user-configured daily limit. A user cannot configure a limit above
  the plan allowance.
- LLM generation batches and learner-facing delivery sessions are separate
  concepts. LLM batches are usually 2–6 cards for efficiency; delivery
  sessions are derived from the effective allowance and active delivery window.
- Serialization compactness must never define educational richness. Daily,
  batch, and custom-word generation share the same content-quality contract:
  two paired examples by default, and at least two distinct synonyms or
  antonyms whenever the model identifies a meaningful populated list; an
  unavailable optional field may remain empty.
- Session sizing uses per-plan values read from the `plans` DB table rather
  than a formula over the total allowance: each plan stores its daily session
  budget (`max_sessions`) and target cards per session
  (`cards_per_session`). A study session produces up to `cards_per_session`
  nodes; the scheduler daily budget is `max_sessions`. Remaining day logic
  keeps a soft target: `S` sessions partition the effective allowance as
  evenly as possible, with session sizes differing by at most one card.
- The default educational bounds are configurable policy constants:
  `min_sessions = 3`, `max_sessions = 6`, and `target_cards_per_session = 3`.
  They are not tied to a plan name, so new plans inherit the same behavior
  unless the DB plan row overrides `max_sessions` / `cards_per_session`.
- Plan limits are therefore expressed as concrete DB values:
  - free → 2 sessions × 3 cards/session, query quota 2
  - bronze → 3 × 3, query quota 4
  - silver → 3 × 5, query quota 7
  - gold → 4 × 7, query quota 12
  - emerald → 5 × 9, query quota 20
- Users can choose a preferred delivery start time. It is a soft target, not
  a promise that all users will receive content at the exact same minute.
- The scheduler spreads sessions across the user's active day and shifts them
  within an allowed window when a preferred time is overloaded.
- Missed sessions do not create a large backlog message. Pending content is
  rolled forward while preserving the plan's session-size limit.
- The primary manual menu action is named `🃏 فلش‌کارت امروز` (or an equivalent
  wording that clearly communicates on-demand cards).
- Every manual card shows progress against the effective daily allowance and
  provides an inline `Next card` action until the allowance is consumed.
- When the daily allowance is complete, the completion message should expose a
  review entry point for today’s cards and recent prior days stored in
  `daily_cards`.
- Review navigation should include a dedicated hub plus same-message
  previous/next controls for already persisted cards; this is core UX, not a
  premium upsell.
- Reminder copy should be friendly, progress-aware, and action-oriented. It
  may mention streaks, due reviews, or remaining workload, but it must stay
  separate from cadence and scoring rules.
- Example translations are stored with the card but remain hidden until the
  user presses an inline `Prepare translations` button. The bot edits the
  same message, removes that preparation control, keeps the `•` example
  prefix, and places the paired translations on the next line inside a
  Telegram spoiler.
- A successful custom-word query shows the user's daily usage and remaining
  allowance. The result offers an inline action to add that word to spaced
  repetition.
- Grammar tips use the same per-plan daily cap as custom-word queries, with an
  atomic reserve before the AI call.
- The separate `Save a custom word` menu action is removed from the primary
  user menu; the persistence and SRS backend remain available to the query
  flow.
- A protected owner-only learning-data reset is available with explicit
  confirmation. It clears users, saved words, and daily cards while preserving
  AI settings.
- Grammar concepts include both the Persian label and the target-language or
  Latin equivalent, such as `صفت (Adjective)`.
- Every user can set their level manually.
- The level selector uses simple labels with CEFR equivalents:
  - Beginner — A1/A2
  - Intermediate — B1/B2
  - Advanced — C1/C2
- Advanced goal options are language-aware. Language-specific options such as
  TOEFL / IELTS remain English-only, while richer goal groups are a premium
  layer rather than a core-flow requirement.
- Smart placement testing is available only to Silver and Gold users.
- Language, learning goal, and proficiency level are independent user
  attributes.
- German is added as a supported language with German-specific content rules,
  rather than treating it as a renamed English prompt.

## Delivery Principles

1. Prefer one reliable, validated content contract over loosely structured AI
   output.
2. Generate content in batches of 2-6 to reduce prompt overhead, latency, and
   duplicate vocabulary where batch generation is appropriate. A generation
   batch must not be confused with a learner-facing session, and the manual
   flow must not pre-generate content the user has not requested.
3. Cache generated daily content before sending it.
4. Keep the primary card readable; put optional detail behind interaction.
5. Keep language-specific grammar and assessment rules explicit and extensible.
6. Never expose raw AI errors, malformed JSON, or provider details to users.
7. Keep blocking provider calls out of the async Telegram event loop and
   isolate concurrent work per user.
8. Measure usage and quality before adding complex personalization.

## Implementation Phases

### Phase 1: Content Schema and Validation

**Status:** Complete
**Done:** Versioned card fields, validation, paired examples/translations, and safe malformed-output handling.
**In progress:** None.
**To-do:** Keep migration and validation coverage current as additive fields are introduced.

Define and validate a versioned vocabulary-card contract containing:

- `word`
- `phonetic`
- `fa_meaning`
- `fa_explanation`
- `synonyms`
- `antonyms`
- `examples`
- `example_translations`
- `grammar_tip`

Add validation for required fields, field types, example/translation pairing,
and safe fallback behavior when the model returns incomplete or malformed JSON.

**Acceptance criteria**

- Every stored card conforms to the schema.
- Invalid model output is rejected or repaired without reaching the user.
- Each example has exactly one corresponding translation.
- Existing cached cards remain readable during the schema transition.

### Phase 2: Manual Proficiency Level and German Support

**Status:** Complete
**Done:** Independent proficiency level, CEFR labels, German support, and language-specific guidance.
**In progress:** None.
**To-do:** Add future languages only through the canonical catalog.

Add an independent proficiency-level field to the user profile. Let all users
choose a simple level label and show its CEFR equivalent.

Apply the selected level to vocabulary, grammar, custom-word, and batch prompts.
Add German to the supported-language configuration and define German-specific
guidance for:

- Noun gender: `der`, `die`, and `das`
- Cases: `Nominativ`, `Akkusativ`, `Dativ`, and `Genitiv`
- Verb conjugation
- Word order and verb placement
- Compound words and capitalization

Other languages must retain language-specific prompt guidance instead of
sharing assumptions from English.

**Acceptance criteria**

- Users can set and change their level from settings.
- The stored profile keeps language, goal, and level separately.
- German can be selected during onboarding and from language settings.
- Generated German content follows German orthography and grammar conventions.
- The selected level visibly influences generated content.

### Phase 3: Controlled Generation and Daily Card Storage

**Status:** In progress
**Done:** Bounded manual and scheduled batches, persistence, duplicate filtering, and partial retry.
**In progress:** Segment-level pooling design and validated reuse boundaries.
**To-do:** Implement additive pool storage, gated writes/reads, telemetry, and inventory selection (issue `40`).

Support two deliberate generation modes:

- **On-demand manual mode:** prime at most one bounded 2–6-card reservoir when
  needed, persist it, and reveal only the next requested card.
- **Scheduled delivery mode:** generate only the next learner-facing session,
  using the plan template and an internal LLM batch of 2–6 where appropriate.

The shared storage and validation layer must:

- Request only the number of cards needed for the selected mode.
- Split scheduled delivery into plan-specific sessions instead of generating
  the full daily allowance at the beginning of the day.
- Avoid words already generated for that user on the same date.
- Avoid a bounded recent cross-day vocabulary list for the same user.
- Reject duplicates within the batch.
- Persist cards individually in the existing `daily_cards` table.
- Retry only the missing portion when a batch is incomplete.
- Avoid regenerating cards after a restart or duplicate trigger.
- Prevent manual and scheduled flows from generating the same card range
  concurrently.

**Acceptance criteria**

- A manual first-card request creates at most one bounded reservoir and reveals
  only one card.
- A scheduled delivery never generates the user's entire daily allowance just
  because the day started.
- A scheduled session respects the formula-derived session count and the
  effective daily allowance.
- No daily batch contains duplicate normalized words.
- A partial or malformed response does not discard valid cards.
- Manual and automatic flows can reuse the same persisted cards without
  forcing manual users to pre-generate their full allowance.

### Phase 4: Interactive Card UX

**Status:** In progress
**Done:** Persisted next-card flow, cached-card rendering, and internal compact JSON separation.
**In progress:** Project-status tooling and the brief/detailed presentation contract.
**To-do:** Translation reveal, content-richness restoration, premium presentation controls, and regression contracts (issues `27`, `51`–`55`).

Add inline controls for:

- Showing example translations
- Requesting the next card on demand
- Showing the effective daily allowance and progress
- Saving the current card or queried word for spaced repetition
- Choosing a learner-facing `brief` or `detailed` presentation, without
  changing the validated card payload or the AI output serialization

Show readable progress, such as `Card 2 of 5`, where the count has a defined
meaning: generated, delivered, and viewed state must not be conflated. Provide
a clear completion message when the daily allowance has been consumed.
Callback handlers must be safe against repeated clicks, stale card references,
and callbacks issued by a different user.

Presentation detail is a deterministic rendering concern. The detailed mode
is the default and retains two paired examples; brief mode is a shorter view
of the same cached card. Neither mode may trigger an AI request, alter quota
usage, mutate `daily_cards`, `saved_words.card_data`, or create a second card
schema. The same policy applies to daily cards, custom-word results, saved-word
reminders, and future content-pool hits.

The locked product policy is: users use the deployment global default until an
eligible premium user chooses a presentation in the settings menu; the
default is `detailed` unless `DEFAULT_PRESENTATION` changes. Only Silver and
Gold users may persist `brief` or `detailed`. Invalid values and downgraded
users fall back to the global default. This is a presentation-policy change
over cached cards, not an AI or database-schema format change, and
`AI_CARD_OUTPUT_FORMAT` remains internal.

**Acceptance criteria**

- Users can reveal translations without receiving a duplicate card.
- Users can request the next card without receiving cards they did not request.
- Users can move through already persisted cards without another AI request.
- Card controls remain associated with the correct stored card.
- Repeated or stale callbacks do not corrupt progress state.
- Detailed rendering shows two example/translation pairs by default, while
  brief rendering remains readable and safely handles absent optional
  synonyms, antonyms, or grammar details.
- Generation and validation preserve the content-quality contract across
  compact daily cards, six-card batches, and custom-word cards: two paired
  examples, plus at least two distinct items for each meaningful populated
  synonym or antonym list.
- The default card message hides example translations and exposes an
  authorized inline `Prepare translations` action that appends paired
  translations as Telegram spoilers without sending a duplicate card.
- Translation preparation is idempotent, rejects stale or cross-user
  callbacks, and reuses cached card JSON. Valid cards make no AI request and
  have no quota, SRS, pool, or persistence side effects. Invalid legacy cards
  receive at most one targeted repair patch; only repaired fields are
  atomically persisted, and failed repairs block delivery without changing
  learning state.
- Review entry points should be available as a dedicated hub for all users,
  and previous/next controls should edit the active message rather than
  forcing a replacement card whenever Telegram allows it.
- Reminder copy should be friendly, progress-aware, and action-oriented. It
  may mention streaks, due cards, or today's remaining workload, but cadence
  and scoring stay separate from the wording.
- Eligible premium users can choose brief or detailed rendering from the
  settings menu; ineligible users receive the global default and a safe
  explanation. No per-card presentation action is exposed.
- Rendering either mode reuses the same validated cached payload and does not
  change AI request counts, quotas, SRS state, pool identity, or stored JSON.
- The internal `AI_CARD_OUTPUT_FORMAT` setting is never exposed as a learner
  preference or allowed to change visible educational detail.
- Advanced goal options are language-aware and premium-gated. The core goal
  list stays simple for everyone; richer goals are a later premium layer.

### Phase 5: Custom-Word Queries and Spaced-Repetition Capture

**Status:** In progress
**Done:** Quota visibility, persistent query identity, idempotent Add to review, and complete cached review payloads.
**In progress:** DB-driven plan specs — plan limits (daily sessions, cards per session, word-query quota) live in the `plans` DB table (free/bronze/silver/gold/emerald), seeded on first run and editable via the admin plan-manager wizard; env-var plan limits removed.
**To-do:** Finish the remaining custom-word UX and review-entry acceptance criteria.

Extend the custom-word flow so that:

- Free users see `used / limit` before and after a query.
- Silver and Gold users see usage while retaining their configured access.
- A successful query exposes an idempotent `Add to review` action.
- The saved entry uses the validated card word and the user's target language.
- Duplicate saves for the same user, word, and language are prevented.
- Query results referenced by callbacks have a short-lived persistent identity;
  full card content is not packed into Telegram callback data.
- The existing review intervals remain the source of truth for the first
  reminder and subsequent reviews.
- A saved review entry retains the validated card payload needed to render a
  complete reminder without another AI request.
- An SRS reminder renders the complete stored card and provides safe controls
  for learner confirmation or deferral.
- Review intervals advance from an explicit learner action, not merely because
  Telegram accepted an automated reminder.

The standalone custom-word registration button is removed from the primary
menu, but the database save and SRS functions remain internal capabilities.

**Acceptance criteria**

- A successful query reports the updated daily usage.
- A user can add a queried word to review without retyping it.
- Repeated clicks do not create duplicate SRS entries.
- The existing SRS job can find and deliver the saved word.

### Phase 6: Reliable Delivery, Concurrency, and Data Lifecycle

**Status:** In progress
**Done:** Durable queues, bounded retries, async-safe provider calls, callback validation, and restart recovery.
**In progress:** FSRS-6 migration — Phase 1 (core engine + session engine shell merged, 4-button UI live) and Phase 3a (`daily_cards` → `saved_words` first-exposure migration and schema columns) are done. The saved-word origin backfill is deployed and verified on the live database (510 `legacy_daily`, 22 `manual`); Phase 2b stale-flow cleanup (daily-table/runtime removal) is under PR validation, followed by Phase 3b FSRS data wiring. See `docs/plans/fsrs/plan_fsrs_migration_v2.md`, `docs/plans/fsrs/plan_daily_cards_migration.md`, `docs/plans/fsrs/plan_fsrs_session_cleanup.md`.
**To-do:** Resolve issues `42`–`47`, `49`, `50`, and `66` with focused idempotency, migration, reliability, and progress tests.

Make manual generation and scheduled delivery restart-safe and isolated per
user. Add:

- User-configurable preferred delivery start time and an active delivery
  window
- A durable per-user session queue with planned delivery timestamps
- Load-aware slot selection that treats preferred time as a soft target
- Capacity buckets for provider requests and Telegram sends
- A global AI concurrency/request limiter
- Short delays between cards in one learner session
- Bounded retries for Telegram delivery errors
- Per-user error logging
- Idempotent daily dispatch
- Durable per-user dispatch state such as `pending`, `processing`, `sent`,
  and `failed`
- Per-user locks or equivalent coordination for manual and scheduled work
- Async-safe provider calls that do not block the Telegram event loop
- A clear user-facing fallback when content generation fails
- Friendly reminder copy that can mention streak, due reviews, or remaining
  workload without changing cadence or scoring
- Session-size limits that prevent a missed schedule from becoming a burst
- Fair scheduling across users when preferred time buckets are saturated
- An owner-only learning-data reset with two-step confirmation
- Scoped reset behavior that clears users, saved words, and daily cards while
  preserving AI settings

**Acceptance criteria**

- A restart does not regenerate or resend completed daily content.
- One user's failure does not stop delivery to other users.
- Telegram rate limits are handled without unbounded retries.
- A large user base does not cause an unbounded LLM request burst at the
  configured default hour.
- Preferred delivery times are respected when capacity allows and shifted
  predictably when capacity is saturated.
- Session sizes remain within the configured educational bounds, regardless of
  plan names or the number of plans.
- Manual retrieval and scheduled delivery remain consistent without sharing a
  global blocking queue.
- A reset cannot be triggered by a non-owner or a single accidental click.

### Phase 7: Premium Smart Placement Test

**Status:** Planned
**Done:** Product direction and premium boundary documented.
**In progress:** None.
**To-do:** Implement only after the core learning loop and measurement contracts are stable.

Provide Silver and Gold users with an optional adaptive placement flow.
Free users retain manual level selection.

The placement flow should:

1. Explain the purpose, approximate duration, and ability to skip.
2. Ask five to eight progressive questions.
3. Mix vocabulary, grammar, translation, and sentence-comprehension tasks.
4. Adjust difficulty based on previous answers.
5. Produce a recommended simple level and CEFR equivalent.
6. Report strengths, weaknesses, and a recommended starting point.
7. Ask the user to confirm before saving the result.
8. Allow a retry or manual correction.

Each supported language must define its own question types, difficulty
guidance, and evaluation rules.

**Acceptance criteria**

- Free users cannot start the AI placement test.
- Silver and Gold users can start, cancel, retry, and confirm the test.
- The result includes both a simple label and a CEFR equivalent.
- The result is stored independently of the user's learning goal.
- The test does not expose the underlying prompt or raw model output.

### Phase 8: Measurement and Advanced Learning

**Status:** Planned
**Done:** Measurement goals and mini-quiz dependency order documented.
**In progress:** None.
**To-do:** Add feedback capture, cost/quality dashboards, and advanced learning features (issue `48`).

After the core flow is stable, record:

- AI request count and latency
- Estimated token or provider cost
- JSON validation and repair rates
- Duplicate-word rate
- Translation-button usage
- Saved-word and reminder-button usage
- Placement-test completion and correction rates

Use these measurements before introducing CEFR granularity, collocations,
advanced personalization, or additional paid features.

### Future Feature: AI Mini Quizzes

This feature is intentionally downstream of the core card flow. It should
reuse the existing AI generation and validation pipeline rather than creating
a separate lesson system.

**MVP scope**

- Quizzes are short and optional.
- Questions are generated from already-learned material: the current card,
  saved words, or recent review items.
- The first release may use a single prompt per quiz or a very small fixed
  set of questions.
- Quiz output is validated with the same safety rules as card content.
- Only lightweight attempt/result data is stored.
- Quiz delivery must never delay or block the main daily-card flow.

**Locked MVP logic**

- The MVP is a recall/review feature, not a new study path.
- Incorrect answers can be recorded, but they do not trigger adaptive follow-up
  in the first release.
- Premium plans may later add educational tips based on mistakes, extra hints,
  and richer feedback.
- Future enhancements must be additive so the base quiz flow stays simple and
  cheap to maintain.

**Acceptance criteria**

- The quiz starts from existing learning data, not from a new content model.
- Bad AI output fails safely through the current validation path.
- The quiz feature can be shipped without changing the daily-card contract.
- Premium extensions can be layered on later without redesigning the MVP data
  model.

## Remaining ToDo

### Reliability and data lifecycle follow-ups

- Add the owner-only two-step learning-data reset with scoped preservation of
  AI settings.
- Add explicit UI for per-user preferred delivery time, active window, and
  optional daily card limit, using the application timezone.
- Add timezone-aware per-user UI and migration coverage for existing
  installations, including stored delivery timestamps.
- Finish the owner-facing LLM cost dashboard with hybrid pricing overrides,
  per-request accounting, plan/user/model filters, and monthly projections.
- Add provider cost/latency, validation, duplicate, delivery, and SRS usage
  measurements before advanced personalization.
- Expand tests around callback authorization, provider failures, Telegram retry
  behavior, SRS chunking, migrations, and reset safeguards.
- Revisit the locked segment-level content-pooling slices when the trigger
  condition is met (DAU ≥ 50 AND ≥1 segment with ≥10 items × ≥2 users), starting with the
  additive SQLite schema and validated daily-card write path.
- Add explicit migration and cross-segment isolation tests for the shared pool.
- Define and implement community rating/report thresholds, owner approval
  workflow, and automatic retirement only after the reward/admin primitives
  are scoped.

### Saved-word SRS follow-ups

- Add explicit migration tests for legacy databases without card payload or
  pending-review columns.
- Measure review completion, deferral, and stale-pending rates before changing
  the interval policy.
- Implement the locked adaptive SRS core in `Plan_srs_core.md`, including the
  48-hour pending grace window, plan-bounded daily caps, overdue-first
  selection, goal-shaped delivery, append-only retention events, and separate
  progress indicators.
- Resolve the five adaptive-SRS audit records in `issues/issues.json` with
  focused migration, restart/idempotency, abuse-resistance, and backward-
  compatibility tests before marking them resolved.

### Custom-word safety and menu ergonomics follow-ups

- Keep the saved-review action label aligned with its actual behavior and
  preserve the target language on persisted query results for future
  multi-language review flows.
- Implement issue `51`: add a deterministic brief/detailed presentation layer
  over canonical cached cards across daily, custom-word, SRS, and pool paths.
- Issue `52` is resolved: the global fallback, premium-only persistent
  preference, settings-menu control, invalid/downgrade fallback, and hidden
  `AI_CARD_OUTPUT_FORMAT` boundary are implemented and tested.
- Implement issue `53`: add regression and persistence tests for example and
  translation pairing, optional fields, cache reuse, pool reuse, idempotent
  rendering, and no-AI/no-quota side effects.
- Implement issue `54`: restore the pre-compact card content-richness contract
  without abandoning compact JSON or making genuinely unavailable optional
  fields mandatory.
- Implement issue `55`: implement the stored-translation spoiler/reveal flow
  and its authorized, idempotent, no-side-effect callbacks.

### Later product phases

- Decide whether the global default remains detailed or changes to minimal
  cards with a premium inline `More details` action; implement the approved
  policy only after issues `51`–`55` pass their rendering and persistence
  contracts.
- Premium or user-configurable brief/detailed card presentation after the
  deterministic rendering contract is implemented and tested.
- Phonetic presentation controls with legacy-card repatching, so learners can
  view IPA phonetics without losing stored content.
- A dedicated owner flow for adding, disabling, or removing supported
  languages, with the canonical catalog remaining the source of truth.
- Premium smart placement testing for Silver and Gold.
- Premium vocabulary-knowledge estimation testing so Gold users can get a
  general estimate of how many words they know, separate from bot progress
  metrics.
- Premium reward surfaces, badges, and extra gamification beyond streak.
- AI Mini Quizzes after the MVP above proves stable:
  - weekly public challenge quizzes for all users or by language/level/goal;
  - placement quizzes to estimate current proficiency;
  - vocabulary-knowledge estimation quizzes with their own scoring model;
  - card-driven quizzes based on a user's saved vocabulary and grammar history.
- Structured language/goal/level Q&A flows that return polished, structured
  LLM answers while rejecting irrelevant or wasteful prompts early.
- Premium language- and goal-specific expansion packs beyond the core goal
  selector.
- Measurement-informed advanced learning and personalization.
- Social follow/friend features built around profile stats, retained cards,
  and quiz progress, with lightweight Duolingo-style motivation rather than
  a full social network.
- Additional languages only through the canonical `catalog.py` registry.
- Keep `issues/issues.json` as the canonical issue source, validate it with
  `issues/validate.py`; generate the Markdown report or HTML fallback only
  when a human review snapshot is needed.

### Delivered reliability fixes

- Custom-word requests now validate short, language-like input before the AI
  call, rejecting long or clearly unrelated text and preserving quota.
- Awaiting flows now expose shared cancel/back controls through both inline
  callbacks and typed shortcuts so users can exit prompts cleanly.
- Manual daily-card requests now prime a shared 2–6 card reservoir on the
  first request of the day instead of forcing a fresh LLM call for every
  button press.
- Startup catch-up now replays missed `daily_job`, `delivery_dispatch_job`,
  and `srs_job` work shortly after process start so downtime does not skip
  queue planning or reminders.
- Daily-card sessions now lock to the first generated language / goal / level
  snapshot for that day, so mid-session profile edits cannot mix languages
  inside one allowance.
- Review-history navigation now paginates by week with older/newer controls
  instead of showing a flat list once the history grows.
- Streak now updates on the first meaningful user interaction of the day, so
  manual card requests and core learning flows count while scheduled delivery
  only reports the current streak.
- A shared LLM wait-state helper now shows a clearer “still working” signal
  for daily cards, grammar tips, and custom-word lookups instead of relying
  only on Telegram typing indicators.
- Saved words retain validated card JSON; SRS reminders render complete cards
  and wait for explicit, user-scoped remember/defer actions.
- Recent daily words and grammar-tip topics are sent as short avoid-lists to
  reduce repetition while preserving AI-generated content.
- If a provider batch contains only avoid-list collisions, retries preserve
  validator-level deduplication but omit the prompt list to avoid model
  anchoring on forbidden examples.
- Provider calls use configurable temperature/output caps and emit structured
  latency/token logs; failed custom-word or grammar calls refund reservations.
- Callback edits use a shared fallback that sends a replacement message when
  the original Telegram message is stale or unavailable.
- The owner-only LLM cost dashboard now exposes per-request accounting,
  plan/user/model/outcome filters, price overrides, monthly projections, and
  a compact English overview with KPI hierarchy, failure alerts, ranked
  breakdowns, optional recent requests, and range presets.

## Out of Scope for the Current MVP

- AI-generated images
- Groups, leaderboards, or social ranking
- Automatic payment and plan upgrades
- AI placement testing for Free users
- Etymology and long-form linguistic history
- Fully customizable delivery time and daily card count
- Complex proficiency analytics before usage data is available
- A separate manual save flow outside a queried card

## Overall Success Criteria

The roadmap is successful when HamZaban provides:

- Validated, readable, and language-appropriate learning cards
- Significantly lower API overhead through batch generation
- On-demand manual cards that do not pre-consume the full daily allowance
- No duplicate daily vocabulary
- Clear interactive Telegram delivery with visible usage and progress
- A queried word can be added to spaced repetition in one action
- Reliable scheduled sending across restarts and individual failures
- Manual level control for every user
- Premium smart placement testing with transparent results
- A clean path for adding languages without rewriting core business logic
