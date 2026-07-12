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
- Batch generation infrastructure with duplicate filtering and partial-batch
  retry
- Plan access controls, owner bypass, and owner-only per-user plan assignment

The next implementation work is the on-demand interactive card flow,
custom-word usage visibility, one-action SRS capture, concurrency isolation,
and protected learning-data reset described below.

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
- The primary manual menu action is named `🃏 فلش‌کارت امروز` (or an equivalent
  wording that clearly communicates on-demand cards).
- Every manual card shows progress against the effective daily allowance and
  provides an inline `Next card` action until the allowance is consumed.
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
2. Generate content in batches to reduce prompt overhead, latency, and
   duplicate vocabulary where batch generation is appropriate; do not
   pre-generate content that a manual user has not requested.
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
- **Scheduled delivery mode:** generate a validated batch when automatic
  delivery needs the user's remaining allowance.

The shared storage and validation layer must:

- Request the exact number of cards needed for the selected mode.
- Avoid words already generated for that user on the same date.
- Reject duplicates within the batch.
- Persist cards individually in the existing `daily_cards` table.
- Retry only the missing portion when a batch is incomplete.
- Avoid regenerating cards after a restart or duplicate trigger.
- Prevent manual and scheduled flows from generating the same card range
  concurrently.

**Acceptance criteria**

- A manual first-card request creates at most one new card.
- A complete scheduled Gold delivery uses at most one successful generation
  request when the provider returns a valid batch.
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

- Short delays between messages
- Bounded retries for Telegram delivery errors
- Per-user error logging
- Idempotent daily dispatch
- Durable per-user dispatch state such as `pending`, `processing`, `sent`,
  and `failed`
- Per-user locks or equivalent coordination for manual and scheduled work
- Async-safe provider calls that do not block the Telegram event loop
- A clear user-facing fallback when content generation fails
- An owner-only learning-data reset with two-step confirmation
- Scoped reset behavior that clears users, saved words, and daily cards while
  preserving AI settings

**Acceptance criteria**

- A restart does not regenerate or resend completed daily content.
- One user's failure does not stop delivery to other users.
- Telegram rate limits are handled without unbounded retries.
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
