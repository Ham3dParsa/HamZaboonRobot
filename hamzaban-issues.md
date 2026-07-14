# HamZaban — Issues Export

> Generated from `issues/issues.json`; edit the JSON or use the issue app.
> Last synchronized: 2026-07-14

# ذخیره‌سازی API Key به صورت متن ساده در دیتابیس

- ID: 7
- Module: db.py
- Function: جدول settings
- Priority: low
- Status: Accepted risk
- Category: risk
- Phase: phase-4
- Roadmap refs: runtime-configuration
- Evidence: README.md documents that AI API keys are bootstrap/runtime secrets and warns that the SQLite DB/settings table must be protected; no encryption layer is implemented yet.

## Problem
کلید API به صورت plaintext در دیتابیس ذخیره می‌شود که در صورت نفوذ به دیتابیس، لو می‌رود.

## Solution
از یک رمزنگاری ساده (مثلاً Fernet با کلید ثابت در env) برای ذخیره و بازیابی استفاده کنید. یا حداقل در README هشدار دهید که دیتابیس را امن نگه دارند.

## Note
Accepted for MVP because adding encrypted secret-at-rest storage needs a dedicated secret-management decision and dependency review.

---

# issues.json phase-aware grouping ندارد

- ID: 27
- Module: issues/issues.json / project_status.json / issues/project_status.html
- Function: schema / explorer filters
- Priority: medium
- Status: Resolved
- Category: tech-debt
- Phase: phase-4
- Roadmap refs: issue-tooling
- Evidence: The registry now has first-class phase data; the remaining work is to keep phase assignments and the read-only project-status dashboard synchronized through validation.

## Problem
فقط status، priority و roadmap_refs ذخیره می‌شوند؛ برای batchهای مبتنی بر phase یا alignment دقیق‌تر با ROADMAP.md یک فیلد صریح phase وجود ندارد و UI هم آن را نشان نمی‌دهد.

## Solution
فیلدهای category و phase را canonical کنید، phase/decision index را در project_status.json نگه دارید، و داشبورد read-only را با validate روی هر دو منبع هم‌راستا کنید.

## Note
این یک بهبود ساختاری است و باید بدون شکستن backward compatibility اضافه شود.

---

# استخر مشترک محتوای آموزشی در سطح segment هنوز پیاده‌سازی نشده است

- ID: 40
- Module: db.py / bot.py / ai.py / config.py
- Function: content_pool schema, daily-card generation, custom-word save, grammar recommendation
- Priority: high
- Status: Open
- Category: feature
- Phase: phase-3
- Roadmap refs: cost-control, measurement-and-observability, data-lifecycle, future-mini-quizzes
- Evidence: db.py currently has per-user saved_words, daily_cards, query_results, and grammar_tips but no content_pool table; bot.py generation paths are _generate_daily_batch, send_grammar_tip, and text_router custom-word flow; db.py:_normalize_word defines the existing whitespace-collapse + casefold contract; plan_pooling.md and ROADMAP.md record the locked pooling policy.

## Problem
محتوای معتبر و AI-generated هر کاربر فقط در daily_cards، saved_words یا grammar_tips همان کاربر باقی می‌ماند و بین کاربران دارای target_lang، goal و level یکسان reuse نمی‌شود. با رشد کاربران، این مسیر باعث تماس‌های تکراری LLM می‌شود. در عین حال، pooling نباید avoid-list، deduplication، quota، مرزبندی segment یا اصل تولیدشدن محتوا توسط AI را تضعیف کند.

## Solution
یک جدول additive به نام content_pool با کلید یکتای target_lang + goal + level + source_kind + item_key اضافه کنید و source_kindهای daily_card، saved_query_card، grammar_tip و quiz_item را از ابتدا رزرو کنید. کارت روزانه فقط پس از validation و ذخیره‌ی پذیرفته‌شده، نتیجه‌ی custom word فقط پس از Add to review، و نکته‌ی گرامری فقط پس از recommendation صریح کاربر و validation فیلدهای همراه همان پاسخ اولیه وارد pool شود؛ برای validation گرامر تماس دوم LLM مجاز نیست. Pool hit باید با همان quota محصول مصرف شود اما telemetry نوع pool_hit و هزینه‌ی صفر داشته باشد. انتخاب pool باید با تراکنش BEGIN IMMEDIATE، رعایت کلید کامل segment و حذف itemهای موجود در داده‌ی همان کاربر انجام شود. inventory floor اولیه ۱۰ آیتم distinct در هر segment/source و قابل تنظیم در deployment است.

## Note
تصمیم‌های محصول قفل شده‌اند: pool در reset داده‌ی learner باقی می‌ماند، expiry زمانی ندارد، و retirement آینده با rating/report جامعه و حذف owner با approval اداره می‌شود. points تا زمان وجود reward ledger به تعویق افتاده است. thresholds رأی‌دهی، cron retirement و پنل review در scope بعدی هستند. فکر میکنم اگر دیتابیس جداگانه ای، یعنی یک فایل جدا به عنوان دیتابیس هر زبان داشته باشیم ایده خوبی باشد اما مطمئن نیستم.

---

# Pending شدن یادآوری SRS می‌تواند completion rate را برای همیشه مخدوش کند

- ID: 42
- Module: db.py / bot.py
- Function: mark_word_review_pending / due_words_for_user / srs_job
- Priority: high
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: adaptive-srs-core
- Evidence: db.py:due_words_for_user excludes review_status='pending' indefinitely and no expiry/grace-window query exists; bot.py:srs_job sets review_status='pending' after successful reminder delivery, so unanswered reminders can suppress future reminders forever.

## Problem
یادآوری ارسالی در saved_words به وضعیت pending می‌رود، اما pending فعلی timeout ندارد و due_words_for_user آن را تا پاسخ کاربر کنار می‌گذارد. در نتیجه یک یادآوری بی‌پاسخ می‌تواند برای همیشه در محاسبه‌ی completion rate مبهم بماند و رفتار pacing را سرکوب کند.

## Solution
grace window یادآوری pending را ۴۸ ساعت قفل کنید. پس از آن، ردیف بی‌پاسخ در مخرج completion rate هفت‌روزه به‌عنوان unanswered حساب شود و دوباره pending دائمی نباشد؛ این تغییر باید بدون advance کردن interval و بدون تولید reminder تکراری خارج از سیاست cap انجام شود.

## Note
تصمیم محصول قفل شد: grace window برابر ۴۸ ساعت است. پیاده‌سازی و تست آن هنوز باقی است.

---

# تنظیم cap روزانه‌ی SRS در catch-up یا restart می‌تواند دوبار اعمال شود

- ID: 43
- Module: db.py / bot.py
- Function: srs_job / startup_catch_up_job
- Priority: high
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: adaptive-srs-core
- Evidence: db.py:users has no reminder-cap columns or application-day idempotency field; bot.py:startup_catch_up_job invokes srs_job and the regular daily schedule can invoke it again on the same application day.

## Problem
Adaptive SRS هنوز cap یا زمان آخرین adjustment ندارد. بعد از پیاده‌سازی cap، startup catch-up و اجرای معمول همان روز نباید بتوانند adjustment روزانه را دوبار انجام دهند.

## Solution
ستون‌های daily_reminder_cap و reminder_cap_updated_at را additive اضافه کنید و adjustment را با همان application-day در تراکنش محافظت کنید. seed اولیه برای کاربران قدیمی برابر allowance فعلی plan باشد؛ cap با step برابر ۱، کف ۱، و سقف مؤثر plan تغییر کند.

## Note
تصمیم محصول قفل شد: Free/Silver/Gold به‌ترتیب ۳/۱۲/۳۰، step برابر ۱، و اجرای adjustment حداکثر یک‌بار در هر روز برنامه است.

---

# تغییر goal وسط روز باید با pacing زمان‌بندی‌شده سازگار بماند

- ID: 44
- Module: db.py / bot.py / scheduling.py
- Function: set_user_goal / srs_job / daily planning
- Priority: medium
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: adaptive-srs-core
- Evidence: db.py:set_user_goal updates users.goal immediately, while current SRS delivery has no goal-aware pacing selection; daily_card_sessions snapshots daily-card content but not SRS pacing shape.

## Problem
goal کاربر در هر زمان قابل تغییر است، اما adaptive pacing هنوز قرارداد مشخصی برای reminderهای از قبل برنامه‌ریزی‌شده ندارد. اعمال فوری تغییر می‌تواند shape صف موجود را در میانه‌ی روز عوض کند.

## Solution
goal جدید را از daily planning cycle بعدی در pacing اعمال کنید و reminderهای از قبل queued را با shape فعلی ارسال کنید. این قرارداد باید با snapshot فعلی daily_card_sessions هم‌راستا بماند و در تست تغییر goal وسط چرخه پوشش داده شود.

## Note
تصمیم محصول قفل شد: اثرگذاری از planning cycle بعدی؛ صف موجود تغییر نمی‌کند.

---

# مسیر points جدید باید در برابر toggle سریع review مقاوم باشد

- ID: 45
- Module: db.py / bot.py
- Function: advance_word_review / defer_word_review / retention_events
- Priority: high
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: adaptive-srs-core
- Evidence: db.py:advance_word_review and defer_word_review update only rows in pending state, but there is no retention_events table or points/progress read model; defer_word_review also leaves interval_idx unchanged despite the plan's reset wording.

## Problem
advance_word_review و defer_word_review فعلاً با شرط review_status='pending' از تکرار یک پاسخ جلوگیری می‌کنند، اما retention_events هنوز وجود ندارد و milestone points در هیچ تراکنش append-only ثبت نمی‌شود.

## Solution
ثبت retention event و تغییر interval را در یک تراکنش اتمیک انجام دهید؛ برای هر saved_word و interval milestone فقط یک event مجاز باشد. امتیازها برای intervalهای ۱ تا ۴ برابر ۱، ۳، ۶ و ۱۰ هستند و رسیدن به interval چهار یک mastery bonus یک‌باره‌ی ۱۰ امتیازی دارد.

## Note
تصمیم محصول قفل شد: فقط پاسخ موفق learner امتیاز می‌دهد؛ generation، delivery و streak امتیاز retention ندارند. bonus نهایی باید با unique guard دوباره‌پذیر نباشد.

---

# کاربران قدیمی پس از migration نباید cap یادآوری صفر یا NULL داشته باشند

- ID: 46
- Module: db.py / config.py
- Function: init_db / plan allowance helpers
- Priority: high
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: adaptive-srs-core
- Evidence: db.py:init_db currently has no daily_reminder_cap or reminder_cap_updated_at migration; config.py defines the authoritative Free/Silver/Gold daily card allowances, but the live SRS job currently applies none of them.

## Problem
users موجود پیش از adaptive SRS ستون daily_reminder_cap ندارند و migration آن باید NULL را به رفتار قابل پیش‌بینی تبدیل کند. مقداردهی اشتباه می‌تواند در روز migration reminderهای کاربر را ناگهان به صفر یا سقف نامحدود تبدیل کند.

## Solution
migration را additive نگه دارید و cap اولیه‌ی NULL را از allowance فعلی plan seed کنید: Free=3، Silver=12، Gold=30، و plan ناشناخته با fallback فعلی Free. مقدار seed و هر adjustment بعدی باید با سقف مؤثر همان plan محدود بماند.

## Note
تصمیم محصول قفل شد: seed اولیه همان allowance فعلی plan است تا رفتار قدیمی به صفر سقوط نکند و cap قابل توضیح بماند.

---

# streak should advance only after all daily cards are seen and interacted with

- ID: 47
- Module: bot.py / db.py
- Function: daily card flow / streak tracking
- Priority: medium
- Status: Open
- Category: feature
- Phase: phase-6
- Roadmap refs: adaptive-srs-core
- Evidence: Current streak handling does not record a full daily-card completion gate tied to every card in the day.

## Problem
The product intent is that streak += 1 only when the user actually sees and interacts with every daily card for the day. The current flow does not yet model full-card completion as a distinct milestone.

## Solution
Track per-day exposure and interaction completion for daily cards, then increment streak only after the full daily set is completed. Keep the exact interaction rule and implementation details open for a later phase.

## Note
Future product intent only; the exact completion rule is intentionally not locked yet.

---

# daily and query cards should expose feedback buttons for future mini-quiz reminders

- ID: 48
- Module: bot.py / keyboards.py / db.py / ai.py
- Function: card rendering / feedback callbacks / reminder scheduling
- Priority: medium
- Status: Open
- Category: feature
- Phase: phase-8
- Roadmap refs: mini-quizzes
- Evidence: Card flows currently lack the proposed per-card feedback buttons and any follow-up scheduling based on those responses.

## Problem
Daily and query cards do not yet have the proposed inline actions ('I knew it', 'This is new for me', 'I'm not sure') and there is no lightweight response trail to drive later mini-quiz reminders generated by the bot from its own data pool.

## Solution
Add inline feedback controls to daily and query cards, record the user's response, and use that response history to schedule future mini-quiz-style follow-ups for the relevant language or card pool. Keep the cadence, scoring, and exact quiz logic open for later phases.

## Note
This is a future direction item; the mini-quiz logic is intentionally not locked yet.

---

# daily card count should be user-configurable up to the plan maximum and tied to streak completion

- ID: 49
- Module: bot.py / db.py / keyboards.py / config.py
- Function: daily card limits / streak tracking
- Priority: medium
- Status: Open
- Category: feature
- Phase: phase-6
- Roadmap refs: adaptive-srs-core
- Evidence: Current daily-card quotas are plan-bounded but not user-configurable, and streak updates are not keyed off a per-user target card count.

## Problem
Users should be able to choose how many daily cards they want to receive, as long as the number stays within their subscription plan ceiling. The streak rule should then respect that chosen target instead of a fixed allowance.

## Solution
Add a per-user daily-card target bounded by the active plan maximum, persist it, and use it as the completion gate for streak updates and daily planning. Keep the exact UI and streak-trigger details open for a later phase.

## Note
Future customization item; the exact streak trigger is intentionally not locked yet.

---

# add minimal network error handling for bot requests

- ID: 50
- Module: bot.py / ai.py / db.py
- Function: network requests / Telegram delivery / AI calls
- Priority: low
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: reliability-hardening
- Evidence: There is no single minimal network-error policy covering bot requests end-to-end, even though some paths already retry.

## Problem
Transient network failures can bubble up as generic errors without a small, consistent recovery path or a user-friendly fallback.

## Solution
Add lightweight retry or fallback handling for temporary network issues around Telegram and AI requests, keeping the scope minimal and focused on avoiding unnecessary user-visible failures.

## Note
Keep the fix small; this is not a full reliability overhaul.

---

# card presentation detail should be independent from AI output serialization

- ID: 51
- Module: bot.py / db.py / ai.py
- Function: format_card / daily delivery / custom-word results / SRS reminders
- Priority: medium
- Status: Resolved
- Category: feature
- Phase: phase-4
- Roadmap refs: interactive-card-ux, cost-control, data-lifecycle
- Evidence: Implemented bot.format_card(presentation='brief'|'detailed') over the existing canonical card payload. Detailed mode remains the default for daily, queried, saved/SRS, and other existing callers; brief mode renders only word, pronunciation, meaning, and explanation. The renderer performs no AI, quota, SRS, persistence, or schema work. Focused rendering tests pass.

## Problem
The AI wire format and the learner-facing message detail are separate concerns, but the current card prompt shape has already influenced visible richness such as the number of examples and synonyms. There is no explicit presentation layer that renders brief or detailed messages from the already validated and cached canonical card.

## Solution
Add a deterministic presentation policy over the canonical stored card: detailed remains the default and renders two paired examples, while brief renders a shorter message without changing the card payload. Apply the policy to daily cards, queried cards, saved-word reminders, and pool-served cards. Rendering must not call the AI, mutate cached content, alter quota accounting, or create a second card schema.

## Note
Future product direction. The compact JSON format is an internal provider optimization and must remain independent from this learner-facing preference.

---

# brief or detailed card preference needs explicit global and premium user controls

- ID: 52
- Module: config.py / db.py / keyboards.py / bot.py
- Function: presentation preference schema / settings UI / plan gating / callbacks
- Priority: medium
- Status: Resolved
- Category: feature
- Phase: phase-4
- Roadmap refs: interactive-card-ux, premium-features, runtime-configuration
- Evidence: config.py:DEFAULT_PRESENTATION and presentation_for_user define the global fallback and premium eligibility; db.py migrates and persists users.presentation_preference; keyboards.py exposes settings-menu choices only; bot.py applies the effective presentation to daily, scheduled, query, review, and SRS rendering and rejects ineligible callbacks; focused config, persistence, migration, menu, and downgrade tests pass.

## Problem
There is no user-visible setting for choosing brief versus detailed card messages, no documented global default for the presentation policy, and no entitlement rule for offering the preference as a premium option. A future implementation could accidentally expose an internal AI-format switch or leave stale preferences active after a plan downgrade.

## Solution
Define a separate presentation preference with stable values such as brief and detailed. Keep an admin/deployment default for all users, allow an explicitly documented per-user override only for eligible premium plans if product approval confirms that policy, and fall back safely to the global default when the user is ineligible or the value is invalid. Add settings UI plus an eligible-user inline action for opening the detailed version of an individual card, with plan-gated callbacks, migration coverage, and clear user-facing descriptions; do not expose AI_CARD_OUTPUT_FORMAT as the user setting.

## Note
Resolved with a separate learner-facing presentation preference. Users without an eligible stored preference use the deployment global default; premium users can persist brief or detailed from the settings menu. Invalid values and downgraded users safely fall back to the global default. AI_CARD_OUTPUT_FORMAT remains internal.

---

# presentation variants need cache, pool, and regression contracts

- ID: 53
- Module: bot.py / db.py / tests
- Function: format_card / daily_cards / saved_words.card_data / content_pool rendering
- Priority: high
- Status: Resolved
- Category: tech-debt
- Phase: phase-4
- Roadmap refs: interactive-card-ux, data-lifecycle, measurement-and-observability
- Evidence: tests/test_custom_word_query.py:rendering_does_not_mutate_cached_payload verifies brief/detailed rendering leaves the input payload unchanged; tests/test_reliability.py:rendering_keeps_persisted_card_payloads_unchanged verifies daily/query/saved card JSON remains identical after rendering; existing renderer tests still prove brief/detailed separation and paired-example output.

## Problem
Brief and detailed messages must be different views of one validated card, but there is no contract proving that rendering variants preserve example/translation pairing, optional synonym and antonym absence, cached-card reuse, and segment-level pool behavior. Without focused tests, a presentation feature could silently regenerate content, drop fields in persistence, or diverge between daily, query, and SRS paths.

## Solution
Add pure rendering tests for both modes, assert that two examples remain paired in detailed output, assert that missing optional fields render safely, and verify that daily_cards, saved_words.card_data, and future content_pool hits retain the same canonical payload regardless of selected mode. Add idempotency tests showing repeated rendering makes no AI request and does not alter quota, SRS state, pool identity, or stored JSON.

## Note
Resolved with focused regression tests proving brief/detailed rendering preserves the canonical payload across daily, query, and saved-word paths. Pool behavior remains a future contract because the pool table is not yet implemented.

---

# compact JSON rollout relaxed the card content richness contract

- ID: 54
- Module: prompts.py / ai.py / tests
- Function: _card_schema / validate_card / daily and custom-word generation
- Priority: high
- Status: Resolved
- Category: bug
- Phase: phase-4
- Roadmap refs: interactive-card-ux, cost-control, content-quality
- Evidence: prompts._card_schema now requests exactly two examples and translations in both compact and verbose formats. ai.validate_card requires exactly two paired examples and allows empty synonym/antonym lists while requiring at least two distinct items when populated. Focused compact-prompt, validation, batch, and rendering tests pass.

## Problem
The compact provider schema reduced more than key names: it changed the examples from two demonstrated pairs to one, made synonyms and antonyms explicitly optional without minimum counts, and shortened the grammar guidance. The validator still accepts one example/translation pair and one synonym or antonym, so structurally valid compact responses can be visibly poorer than pre-compact cards.

## Solution
Keep compact aliases strictly as an internal serialization optimization, while restoring a separate content-richness contract. Generation should request two paired examples and, when synonyms or antonyms are meaningfully available, at least two distinct items for each populated list. Validation and focused tests should reject malformed pair counts and one-item populated synonym/antonym lists without rejecting genuinely unavailable optional fields. Batch and custom-word paths must share the same contract.

## Note
Confirmed regression relative to commit c394115^; do not solve it by switching back to verbose JSON or by making optional educational fields mandatory when no meaningful item exists.

---

# example translations are stored but not implemented as Telegram spoilers

- ID: 55
- Module: bot.py / keyboards.py / db.py / tests
- Function: format_card / daily_card_keyboard / callback_router / cached card rendering
- Priority: high
- Status: Resolved
- Category: feature
- Phase: phase-4
- Roadmap refs: interactive-card-ux, data-lifecycle, premium-features
- Evidence: bot.py:format_card keeps the bullet example prefix and places the paired translation on the next line inside a spoiler while escaping the prepared label for MarkdownV2; bot.py:_prepare_cached_card still validates every cached display/resend, performs one minimal repair request when needed, persists repaired fields, and blocks unsafe delivery; callback helpers keep same-message paired spoilers and idempotent stale-callback handling; keyboards.py adds source-scoped Prepare translations callbacks; db.py adds ownership-checked atomic field patches; tests cover bullet layout, spoiler pairing, persistence, scoped controls, and rendering safety.

## Problem
ROADMAP.md says example translations remain hidden until an inline Show translations action is pressed, but the current renderer omits example_translations entirely and the card keyboards expose only Next card, Add to review, and SRS actions. callback_router has no translation-reveal action, so stored translations cannot appear as a spoiler or be added to the current card message.

## Solution
Implemented a deterministic translation-preparation interaction over cached canonical cards across daily, review, custom-word, and SRS flows. The initial Prepare translations action edits the existing message, appends paired Telegram spoilers, removes only itself, preserves other controls, and rejects stale or cross-user references. Valid cards remain zero-call; invalid legacy cards receive one field-level repair patch, are revalidated, and have only repaired fields atomically persisted. Failed repairs block delivery, preserve state, and emit safe user/admin diagnostics.

## Note
Resolved with the approved surgical legacy-card repair exception. Valid cached cards remain cached-only and incur no AI request; one targeted repair request is allowed only when local validation identifies missing or invalid fields.

---

# status changes need a validated review and synchronization workflow

- ID: 56
- Module: issues/status_editor.py / issues/validate.py / ROADMAP.md
- Function: project status editing and generated-view synchronization
- Priority: medium
- Status: Resolved
- Category: feature
- Phase: phase-4
- Roadmap refs: issue-tooling
- Evidence: PR #53 delivered status_editor.py preview/apply commands, full-model validation, and validate.py synchronization for the dashboard and marked generated roadmap section.

## Problem
Editing issue records, phase status, and roadmap summaries manually can leave the dashboard or generated roadmap section stale or inconsistent.

## Solution
Provide a reviewable JSON patch workflow that validates the complete resulting model, previews the diff, updates canonical issue and project-status records, and regenerates only marked views while preserving human-written roadmap narrative.

## Note
This is project-governance tooling only; it must not alter Telegram runtime behavior, AI generation, quotas, or database state.

---

# bot.py needs staged handler and presentation boundaries for maintainability

- ID: 57
- Module: bot.py / keyboards.py / future admin.py / future user.py / future formatting.py
- Function: handler registration, role-specific commands, callbacks, message formatting
- Priority: medium
- Status: Open
- Category: tech-debt
- Phase: phase-6
- Roadmap refs: reliability-and-data-lifecycle, issue-tooling
- Evidence: bot.py is 2,084 lines; admin handlers start at open_admin_panel/admin_callback, user flows include cmd_start/text_router/callback_router, and formatting/MarkdownV2 helpers include escape_mdv2, escape_mdv2_code, and format_card.

## Problem
bot.py currently contains more than 2,000 lines spanning user onboarding, daily delivery, SRS, custom-word queries, admin controls, callbacks, jobs, retry orchestration, MarkdownV2 escaping, and card rendering. As new features land, this increases the risk of accidental cross-flow changes and makes a future Telegram parse-mode migration unnecessarily broad.

## Solution
Plan a staged extraction: preserve handler and callback contracts while moving admin-only handlers to admin.py, user-facing command/state handlers to user.py, and formatting/escaping/rendering to formatting.py. Keep domain operations in existing services, avoid circular imports, add import-level and behavior regression tests, and migrate one boundary at a time rather than splitting files mechanically.

## Note
This is an architectural risk, not permission to refactor immediately. The module boundaries and extraction order require explicit agreement before runtime changes.

---

# project status needs an optional local web editor over the validated patch workflow

- ID: 58
- Module: issues/project_status.html / issues/status_editor.py / future local API
- Function: human-friendly issue and phase editing
- Priority: medium
- Status: Resolved
- Category: feature
- Phase: phase-4
- Roadmap refs: issue-tooling, interactive-card-ux
- Evidence: PR implementation adds issues/local_editor.py: a loopback-only standard-library server with one-time startup token, session cookie authentication, validated preview-before-apply flow, atomic generated-document writes, and a browser form for issue/phase/decision fields. Focused tests, full unittest discovery, py_compile, validate.py check, and a live login/root smoke test pass.

## Problem
The current dashboard is read-only and the safe editor is command-line based, so a project owner must prepare and run a JSON patch manually instead of editing status cards through a controlled local web interface.

## Solution
Add a local-only, authenticated editor backed by the existing validation boundary: load canonical state, edit issue/phase/decision fields, preview a diff, require explicit confirmation, write canonical JSON atomically, and regenerate marked views. The server must never accept arbitrary Markdown writes, browser-local state, or unauthenticated remote edits.

## Note
This is the next UX layer over issue 56, not a replacement for canonical JSON or validation. The local-server technology and authentication boundary must be agreed before implementation.

---

# SRS reminder delivery is not atomic across Telegram send and pending-state persistence

- ID: 59
- Module: bot.py / db.py
- Function: srs_job / mark_word_review_pending / due_words_for_user
- Priority: high
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: adaptive-srs-core, reliability-and-data-lifecycle
- Evidence: bot.py:srs_job sends via _send_with_retry before db.mark_word_review_pending; db.py:due_words_for_user excludes only rows already pending and mark_word_review_pending has no compare-and-set guard. No focused test covers a crash or overlap between send and persistence.

## Problem
The SRS job sends a reminder first and marks the word pending only afterward. A process crash or concurrent SRS invocation in that gap can send a duplicate reminder; there is no durable per-word claim or delivery idempotency record.

## Solution
Add a transactional per-word claim/state transition with a durable reminder attempt identity and recovery semantics. Make concurrent jobs unable to claim the same due word, persist enough state to resume after restart, and document the bounded duplicate risk inherent in Telegram's non-transactional external send.

## Note
This is a confirmed reliability gap in the current fixed SRS baseline and must be resolved before adaptive caps or completion-rate metrics are trusted.

---

# One SRS delivery error aborts the remaining due words for that user

- ID: 60
- Module: bot.py
- Function: srs_job
- Priority: medium
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: adaptive-srs-core, reliability-and-data-lifecycle
- Evidence: bot.py:srs_job opens one try block per active user and catches exceptions only after the for word in due loop, so one failure exits the remaining words for that user.

## Problem
The exception handler surrounds the entire due-word loop for one user. If card preparation or Telegram delivery fails for one word, later due words for that same user are skipped until a later SRS invocation, while other users continue.

## Solution
Handle failures per due word, record bounded retry/backoff state, and continue the user's batch. Preserve cap accounting and avoid marking a word pending unless its delivery attempt reaches the defined success boundary.

## Note
A three-user deployment is small, but a user with multiple due words can still receive an incomplete reminder set without a same-run retry path.

---

# A short restart can leave scheduled delivery permanently processing

- ID: 61
- Module: bot.py / db.py
- Function: requeue_stale_deliveries / daily_job / delivery_dispatch_job
- Priority: high
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: reliability-and-data-lifecycle
- Evidence: bot.py:daily_job calls db.requeue_stale_deliveries once, while delivery_dispatch_job only calls _dispatch_queue; db.py:get_delivery_queue filters out processing rows and requeue_stale_deliveries requires a 15-minute age.

## Problem
Startup requeues processing rows only when processing_started_at is older than 15 minutes. A crash followed by a restart within that window leaves the row in processing; dispatch reads only pending or retryable failed rows, and no repeating job requeues the row.

## Solution
Run stale-worker recovery from the repeating dispatcher as well as daily planning, or use a lease/heartbeat with a retryable deadline. Make recovery idempotent and preserve sent_count when resuming.

## Note
This can strand a user's current daily session after the exact restart scenario this audit was requested to assess.

---

# Scheduled delivery ignores the configured preferred delivery time

- ID: 62
- Module: bot.py / scheduling.py
- Function: _plan_daily_queue / plan_sessions / choose_load_aware_minute
- Priority: medium
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: reliability-and-data-lifecycle
- Evidence: bot.py:_plan_daily_queue reads preferred_delivery_minute; scheduling.py:plan_sessions computes ideal from candidates and passes ideal, not preferred_minute, to choose_load_aware_minute. Focused probe produced identical slots for preferred 08:00, 09:00, 15:00, and 20:00.

## Problem
_plan_daily_queue passes each user's preferred minute, but plan_sessions uses the evenly distributed active-window ideal as the preferred argument to choose_load_aware_minute. Different preferred times therefore produce the same default slot pattern.

## Solution
Use the user's preferred minute as the primary soft target for the first session and derive subsequent session ideals around it, while retaining active-window bounds, load-aware shifting, and deterministic behavior under saturation.

## Note
Messages remain inside the active window, so this is a scheduling-contract defect rather than an immediate data-loss risk.

---

# Scheduled delivery does not replay queue rows from previous offline dates

- ID: 63
- Module: bot.py / db.py
- Function: startup_catch_up_job / daily_job / delivery_dispatch_job
- Priority: medium
- Status: Open
- Category: bug
- Phase: phase-6
- Roadmap refs: reliability-and-data-lifecycle
- Evidence: bot.py:daily_job and delivery_dispatch_job pass only today's date to planning/dispatch; startup_catch_up_job invokes those same current-date jobs. No query or policy handles older delivery_date values.

## Problem
Startup catch-up plans and dispatches only the current application date. Pending or retryable rows for older dates are never selected, so downtime can permanently strand previously scheduled daily sessions.

## Solution
Define and implement a bounded replay policy for past delivery dates: select eligible non-terminal rows in order, preserve their original session/card ranges, enforce burst and per-user limits, and make replay idempotent. If product policy intentionally drops old sessions, mark them explicitly expired instead of leaving them ambiguous.

## Note
Current behavior is safe from duplicate queue creation but not complete from a learner-delivery perspective.

---

# Phonetic output should expose IPA, Latin, and Persian-script variants

- ID: 64
- Module: prompts.py / ai.py / bot.py / config.py / db.py / keyboards.py
- Function: phonetic prompt contract, legacy repair, and owner toggles
- Priority: medium
- Status: Resolved
- Category: feature
- Phase: phase-4
- Roadmap refs: phase-4-interactive-card-ux
- Evidence: prompts._card_schema and card_repair_system_prompt now require the three-line phonetic contract; ai.card_repair_fields marks legacy phonetics for repair; bot.format_card renders the enabled phonetic lines from db.get_phonetic_display_settings(); keyboards.admin_panel_keyboard exposes a phonetic settings submenu.

## Problem
A single stored phonetic string cannot satisfy users who want IPA, simple Latin syllables, and Persian-script pronunciation forms, and legacy cards keep replaying old single-script values.

## Solution
Make phonetic output a labeled multiline contract with IPA, Latin, and Persian lines; repair legacy cards when they are prepared for display; and let the owner toggle each representation from env defaults and the admin panel.

## Note
This stays compatible with AI generation and preserves cached cards by only repatching the phonetic field when it is legacy-formatted.

---

# Owner needs a dedicated add/remove language flow and cleaner admin-panel UX

- ID: 65
- Module: bot.py / keyboards.py / project_status.json / ROADMAP.md
- Function: owner language rollout controls and admin navigation
- Priority: medium
- Status: Open
- Category: feature
- Phase: phase-4
- Roadmap refs: phase-4-interactive-card-ux, later-product-phases
- Evidence: The owner panel is still a single inline keyboard in bot.py, and there is no language lifecycle submenu or catalog rollout workflow yet.

## Problem
The current admin panel is flat and text-heavy, so there is no structured flow for adding, disabling, or removing supported languages during rollout.

## Solution
Design a dedicated owner workflow for language lifecycle management, keep the canonical catalog as the source of truth, and refactor the admin panel into smaller discovery and action views.

## Note
Track this as a product/UX phase so future language rollouts can be controlled without ad hoc bot commands.

---

# learner reminders should sound friendly, progress-aware, and action-oriented

- ID: 66
- Module: bot.py / scheduling.py / db.py
- Function: daily_job / srs_job / delivery copy
- Priority: medium
- Status: Open
- Category: feature
- Phase: phase-6
- Roadmap refs: adaptive-srs-core
- Evidence: Current delivery copy is mostly status-oriented and does not yet have a dedicated progress-aware reminder template or CTA layer.

## Problem
Scheduled reminders are functionally correct but sound like plain notifications instead of a learning coach that references progress, streak, and the learner's current workload.

## Solution
Use templated reminder copy that stays separate from cadence logic but can reference today's remaining cards, due reviews, streak status, and a short question such as whether the learner has time right now.

## Note
Core UX for all users; no new reward model is implied.

---

# review cards need a dedicated review center with same-message prev/next and translation controls

- ID: 67
- Module: bot.py / keyboards.py / ROADMAP.md
- Function: review menu / card navigation / translation reveal
- Priority: medium
- Status: Open
- Category: feature
- Phase: phase-4
- Roadmap refs: phase-4-interactive-card-ux
- Evidence: The code already has review-related keyboards and prepare-translation flows, but there is no dedicated review hub in the main menu and some edits still fall back to sending a new message when Telegram refuses an edit.

## Problem
Review entry points are still buried inside today's card flow, and the current inline controls are not exposed as a dedicated review surface that keeps navigation and translation reveal on the same message.

## Solution
Add a top-level review hub that can open today's due cards and prior review dates, then keep previous, next, and translation actions as same-message edits instead of sending replacement messages whenever possible.

## Note
Core UX for all users; the review hub is not a premium upsell.

---

# goal-specific advanced options should be language-aware and premium-gated

- ID: 68
- Module: catalog.py / keyboards.py / prompts.py / bot.py
- Function: goal menu / prompt guidance / premium gating
- Priority: medium
- Status: Open
- Category: feature
- Phase: phase-4
- Roadmap refs: phase-4-interactive-card-ux, phase-2-manual-proficiency-level-and-german-support
- Evidence: GOALS is still a single flat registry and the existing goal picker does not vary by language or subscription tier.

## Problem
The current goal menu is too coarse for real learner intent, and some goals only make sense for specific languages. Users need richer choices such as travel, immigration, conversation, flirting, and domain-specific study paths.

## Solution
Split the goal catalog into a core set for everyone and an advanced layer for eligible premium users. Filter goals by target language where appropriate, keep the canonical registry as the source of truth, and avoid exposing language-inappropriate goals such as TOEFL/IELTS outside English.

## Note
Premium product choice; this is not just a localization tweak.

---

# extra gamification beyond streak should be a premium reward surface

- ID: 69
- Module: db.py / bot.py / ROADMAP.md
- Function: reward ledger / progress surfaces / profile views
- Priority: medium
- Status: Open
- Category: feature
- Phase: phase-8
- Roadmap refs: mini-quizzes, later-product-phases
- Evidence: The roadmap already separates streak from retention points, and the codebase does not yet have a reward ledger or badge surface.

## Problem
The live product only exposes streak as a progress indicator. There is no reward ledger, badge surface, or premium progress model distinct from learning retention.

## Solution
Keep streak and retention metrics separate from gamification, then add a premium reward layer for points, badges, or similar motivational surfaces only after the reward ledger and profile model are explicitly designed.

## Note
Premium-only by product choice; do not blend it with the learning score.

---

# card failure reasons need durable telemetry and operator reporting

- ID: 70
- Module: ai.py / bot.py / db.py / ROADMAP.md
- Function: batch validation / Telegram rendering / delivery error reporting
- Priority: high
- Status: Open
- Category: tech-debt
- Phase: phase-6
- Roadmap refs: adaptive-srs-core, reliability-and-data-lifecycle
- Evidence: Current ai._log_llm_request logs batch validation reasons, bot.py logs BadRequest/parse-mode failures, and delivery_queue.last_error keeps only per-row send errors; there is no single durable report table or dashboard section that aggregates these causes.

## Problem
Validation rejections, MarkdownV2 parse errors, and delivery failures are mostly visible only in logs, so operators cannot quickly answer why cards failed or whether the root cause is generation quality, formatting, or transport.

## Solution
Persist structured failure events with stage, user, request kind, error class, and compact diagnostics; expose the top reasons in the owner dashboard; and keep raw logs as a fallback rather than the primary report source.

## Note
Urgent reliability work: the reporting surface should separate AI-quality problems from Telegram formatting/send failures.
