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
- Owner-only administrative settings

## Locked Product Decisions

- Each vocabulary card is sent as a separate Telegram message.
- Daily cards are generated in a batch instead of one API request per card.
- Automatic daily delivery sends all cards included in the user's plan as
  separate messages with a short delay between messages.
- Example translations are stored with the card but remain hidden until the
  user presses an inline `Show translations` button.
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
   duplicate vocabulary.
3. Cache generated daily content before sending it.
4. Keep the primary card readable; put optional detail behind interaction.
5. Keep language-specific grammar and assessment rules explicit and extensible.
6. Never expose raw AI errors, malformed JSON, or provider details to users.
7. Measure usage and quality before adding complex personalization.

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

### Phase 3: Batch Generation

Replace per-card generation with a single request that returns an array of
validated cards for the user's daily allowance.

The batch flow must:

- Request the exact number of cards needed.
- Avoid words already generated for that user on the same date.
- Reject duplicates within the batch.
- Persist cards individually in the existing `daily_cards` table.
- Retry only the missing portion when a batch is incomplete.
- Avoid regenerating a completed daily batch after a restart or duplicate
  trigger.

**Acceptance criteria**

- A complete Gold batch uses at most one successful generation request.
- No daily batch contains duplicate normalized words.
- A partial or malformed response does not discard valid cards.
- Manual and automatic daily-card flows use the same cached content.

### Phase 4: Interactive Card UX

Add inline controls for:

- Showing example translations
- Requesting the next card
- Saving a word

Show readable progress, such as `Card 2 of 5`, and provide a clear completion
message when the daily allowance has been consumed. Callback handlers must be
safe against repeated clicks and stale card references.

**Acceptance criteria**

- Users can reveal translations without receiving a duplicate card.
- Users can move through the daily set without another AI request.
- Card controls remain associated with the correct stored card.
- Repeated or stale callbacks do not corrupt progress state.

### Phase 5: Reliable Daily Delivery

Make scheduled delivery restart-safe and isolated per user. Add:

- Short delays between messages
- Bounded retries for Telegram delivery errors
- Per-user error logging
- Idempotent daily dispatch
- A clear user-facing fallback when content generation fails

**Acceptance criteria**

- A restart does not regenerate or resend completed daily content.
- One user's failure does not stop delivery to other users.
- Telegram rate limits are handled without unbounded retries.
- Manual retrieval and scheduled delivery remain consistent.

### Phase 6: Premium Smart Placement Test

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

### Phase 7: Measurement and Advanced Learning

After the core flow is stable, record:

- AI request count and latency
- Estimated token or provider cost
- JSON validation and repair rates
- Duplicate-word rate
- Translation-button usage
- Saved-word usage
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

## Overall Success Criteria

The roadmap is successful when HamZaboon provides:

- Validated, readable, and language-appropriate learning cards
- Significantly lower API overhead through batch generation
- No duplicate daily vocabulary
- Clear, interactive Telegram delivery
- Reliable scheduled sending across restarts and individual failures
- Manual level control for every user
- Premium smart placement testing with transparent results
- A clean path for adding languages without rewriting core business logic
