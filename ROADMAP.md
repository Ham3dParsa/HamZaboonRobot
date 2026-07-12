# HamZaboon Roadmap

## Product Goal

HamZaboon is a Telegram-based language-learning assistant for Persian-speaking
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
- Local issue-review manager (`issues/issues.html`) backed by canonical
  structured issue data in `issues/issues.json`; `hamzaban-issues.md` is an
  optional Markdown export for review
- Custom-word query improvements: daily quota visibility, persistent
  short-lived query identity, inline `Add to review`, and removal of the
  standalone manual-save action from the primary menu

The remaining work is tracked in the explicit ToDo section near the end of
this document. The next user-facing feature now shifts to AI Mini Quizzes,
but configuration and quota semantics must stay consistent with the decisions
below.

## Latest Code Review

Review scope: every Python module, all tests, `ROADMAP.md`,
`hamzaban-issues.md`, and the static `issues/issues.html` manager on the
current `main` branch.

### Confirmed resolved from the issue export

- Daily cards are persisted per user/date/index; manual retrieval and
  scheduled delivery reuse the same storage.
- SRS reminders are scheduled and `advance_word_review` is called after a
  successful reminder message.
- Language, goal, and level metadata are centralized in `catalog.py`.
- `_extract_json` now raises a clear parsing error instead of attempting to
  decode an empty string.
- Empty grammar tips are omitted from formatted cards.
- Goal hints and fallback labels are catalog-backed.
- The non-onboarded-card item is expected guard behavior, not a defect.

### Partially resolved

- Logging exists for failures and some admin actions, but important lifecycle
  events and delivery metrics are not structured or complete.
- The issue manager is useful for local review, but browser `localStorage`
  remains local draft state and must not be treated as committed issue data.

### Open bugs and engineering risks found in this review

- Several `edit_message_text` calls still lack a centralized fallback when a
  callback refers to a deleted or outdated Telegram message.
- API keys remain stored as plaintext in the SQLite settings table.
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

The issue-tooling ownership is locked: `issues/issues.json` is canonical,
`issues/issues.html` reads the canonical data, and `hamzaban-issues.md` is an
optional export generated only when a review snapshot is needed.

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
- Plan quotas are explicit deployment settings:
  `FREE_DAILY_CARD_LIMIT=3`, `SILVER_DAILY_CARD_LIMIT=12`, and
  `GOLD_DAILY_CARD_LIMIT=30`.
- Custom-word query quotas are also explicit:
  `FREE_DAILY_WORD_QUERY_LIMIT=3`, `SILVER_DAILY_WORD_QUERY_LIMIT=16`, and
  `GOLD_DAILY_WORD_QUERY_LIMIT=40`. `-1` means unlimited.
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
- Manual card retrieval is on demand: the first request generates one card,
  and each subsequent request asks for the next card.
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
- Session sizing uses a plan-agnostic formula rather than a plan-name lookup:
  - Let `L` be the effective daily allowance.
  - Target roughly 3 cards per learner-facing session.
  - Choose `S = min(L, max_sessions, max(min_sessions, ceil(L / 3)))`,
    further constrained by the number of feasible time slots in the user's
    active window.
  - Partition `L` as evenly as possible across `S` sessions; session sizes
    may differ by at most one card.
- The default educational bounds are configurable policy constants:
  `min_sessions = 3`, `max_sessions = 6`, and `target_cards_per_session = 3`.
  They are not tied to Free, Silver, or Gold, so new plans inherit the same
  behavior automatically.
- Examples of the formula:
  - `L=4` → 3 sessions containing 2, 1, and 1 cards
  - `L=12` → 4 sessions of 3 cards
  - `L=24` → 6 sessions of 4 cards
  - `L=30` → 6 sessions of 5 cards
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
- Example translations are stored with the card but remain hidden until the
  user presses an inline `Show translations` button.
- A successful custom-word query shows the user's daily usage and remaining
  allowance. The result offers an inline action to add that word to spaced
  repetition.
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

Support two deliberate generation modes:

- **On-demand manual mode:** generate and persist only the next requested card.
- **Scheduled delivery mode:** generate only the next learner-facing session,
  using the plan template and an internal LLM batch of 2–6 where appropriate.

The shared storage and validation layer must:

- Request only the number of cards needed for the selected mode.
- Split scheduled delivery into plan-specific sessions instead of generating
  the full daily allowance at the beginning of the day.
- Avoid words already generated for that user on the same date.
- Reject duplicates within the batch.
- Persist cards individually in the existing `daily_cards` table.
- Retry only the missing portion when a batch is incomplete.
- Avoid regenerating cards after a restart or duplicate trigger.
- Prevent manual and scheduled flows from generating the same card range
  concurrently.

**Acceptance criteria**

- A manual first-card request creates at most one new card.
- A scheduled delivery never generates the user's entire daily allowance just
  because the day started.
- A scheduled session respects the formula-derived session count and the
  effective daily allowance.
- No daily batch contains duplicate normalized words.
- A partial or malformed response does not discard valid cards.
- Manual and automatic flows can reuse the same persisted cards without
  forcing manual users to pre-generate their full allowance.

### Phase 4: Interactive Card UX

Add inline controls for:

- Showing example translations
- Requesting the next card on demand
- Showing the effective daily allowance and progress
- Saving the current card or queried word for spaced repetition

Show readable progress, such as `Card 2 of 5`, where the count has a defined
meaning: generated, delivered, and viewed state must not be conflated. Provide
a clear completion message when the daily allowance has been consumed.
Callback handlers must be safe against repeated clicks, stale card references,
and callbacks issued by a different user.

**Acceptance criteria**

- Users can reveal translations without receiving a duplicate card.
- Users can request the next card without receiving cards they did not request.
- Users can move through already persisted cards without another AI request.
- Card controls remain associated with the correct stored card.
- Repeated or stale callbacks do not corrupt progress state.

### Phase 5: Custom-Word Queries and Spaced-Repetition Capture

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

The standalone custom-word registration button is removed from the primary
menu, but the database save and SRS functions remain internal capabilities.

**Acceptance criteria**

- A successful query reports the updated daily usage.
- A user can add a queried word to review without retyping it.
- Repeated clicks do not create duplicate SRS entries.
- The existing SRS job can find and deliver the saved word.

### Phase 6: Reliable Delivery, Concurrency, and Data Lifecycle

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
- Add provider cost/latency, validation, duplicate, delivery, and SRS usage
  measurements before advanced personalization.
- Expand tests around callback authorization, provider failures, Telegram retry
  behavior, SRS chunking, migrations, and reset safeguards.

### Later product phases

- Premium smart placement testing for Silver and Gold.
- AI Mini Quizzes after the MVP above proves stable.
- Measurement-informed advanced learning and personalization.
- Additional languages only through the canonical `catalog.py` registry.
- Keep `issues/issues.json` as the canonical issue source, validate it with
  `issues/validate.py`; generate the Markdown report or HTML fallback only
  when a human review snapshot is needed.

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

The roadmap is successful when HamZaboon provides:

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
