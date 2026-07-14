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
- Evidence: db.py:due_words_for_user excludes review_status='pending' and no function currently expires pending rows; bot.py:srs_job sets review_status='pending' after successful reminder delivery.

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
- Evidence: db.py:users has no reminder-cap columns; bot.py:startup_catch_up_job can invoke srs_job after downtime and the regular daily schedule can invoke it again.

## Problem
Adaptive SRS هنوز cap یا زمان آخرین adjustment ندارد. startup catch-up عمداً srs_job را دوباره اجرا می‌کند، بنابراین adjustment روزانه بدون کلید idempotency می‌تواند در یک روز چند بار step بخورد.

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
- Evidence: db.py:set_user_goal updates users.goal immediately, while current SRS delivery has no persisted pacing-shape snapshot or goal-aware session selection.

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
- Evidence: db.py:advance_word_review and defer_word_review update only rows in pending state, but there is no retention_events table or points/progress read model.

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
- Evidence: db.py:init_db currently has no daily_reminder_cap or reminder_cap_updated_at migration; config.py defines the authoritative Free/Silver/Gold daily card allowances.

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
- Status: Open
- Category: feature
- Phase: phase-4
- Roadmap refs: interactive-card-ux, cost-control, data-lifecycle
- Evidence: The pre-compact prompts demonstrated two example/translation pairs and multiple optional synonym/antonym slots; the compact schema demonstrates one example pair and one optional slot. ai.py:validate_card accepts one non-empty example pair, and bot.py:format_card renders whatever counts the model returns without a brief/detailed policy.

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
- Status: Open
- Category: feature
- Phase: phase-4
- Roadmap refs: interactive-card-ux, premium-features, runtime-configuration
- Evidence: config.py currently exposes only the internal AI_CARD_OUTPUT_FORMAT values json and compact_json; users has no presentation preference column, and keyboards.py/bot.py have no brief/detailed settings flow.

## Problem
There is no user-visible setting for choosing brief versus detailed card messages, no documented global default for the presentation policy, and no entitlement rule for offering the preference as a premium option. A future implementation could accidentally expose an internal AI-format switch or leave stale preferences active after a plan downgrade.

## Solution
Define a separate presentation preference with stable values such as brief and detailed. Keep an admin/deployment default for all users, allow an explicitly documented per-user override only for eligible premium plans if product approval confirms that policy, and fall back safely to the global default when the user is ineligible or the value is invalid. Add settings UI plus an eligible-user inline action for opening the detailed version of an individual card, with plan-gated callbacks, migration coverage, and clear user-facing descriptions; do not expose AI_CARD_OUTPUT_FORMAT as the user setting.

## Note
Future premium/product decision. The entitlement, default mode, and whether Free users may choose both modes should be finalized before implementation.

---

# presentation variants need cache, pool, and regression contracts

- ID: 53
- Module: bot.py / db.py / tests
- Function: format_card / daily_cards / saved_words.card_data / content_pool rendering
- Priority: high
- Status: Open
- Category: tech-debt
- Phase: phase-4
- Roadmap refs: interactive-card-ux, data-lifecycle, measurement-and-observability
- Evidence: Current tests cover card validation and SQLite persistence, but no test selects a presentation mode or proves that rendering a cached daily, saved, or pooled card is side-effect free.

## Problem
Brief and detailed messages must be different views of one validated card, but there is no contract proving that rendering variants preserve example/translation pairing, optional synonym and antonym absence, cached-card reuse, and segment-level pool behavior. Without focused tests, a presentation feature could silently regenerate content, drop fields in persistence, or diverge between daily, query, and SRS paths.

## Solution
Add pure rendering tests for both modes, assert that two examples remain paired in detailed output, assert that missing optional fields render safely, and verify that daily_cards, saved_words.card_data, and future content_pool hits retain the same canonical payload regardless of selected mode. Add idempotency tests showing repeated rendering makes no AI request and does not alter quota, SRS state, pool identity, or stored JSON.

## Note
Keep this as a prerequisite for shipping the user preference. It should be implemented together with the presentation layer, not by weakening AI validation or duplicating database schemas.

---

# compact JSON rollout relaxed the card content richness contract

- ID: 54
- Module: prompts.py / ai.py / tests
- Function: _card_schema / validate_card / daily and custom-word generation
- Priority: high
- Status: Open
- Category: bug
- Phase: phase-4
- Roadmap refs: interactive-card-ux, cost-control, content-quality
- Evidence: c394115 changed prompts.py from two example/translation placeholders and multiple synonym/antonym placeholders to compact e/t/s/a placeholders with one example and explicit optionality. Current ai.py:validate_card requires only non-empty, equal-length examples and translations; bot.py:format_card displays all returned items without restoring the prior minimum.

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
- Status: Open
- Category: feature
- Phase: phase-4
- Roadmap refs: interactive-card-ux, data-lifecycle, premium-features
- Evidence: bot.py:format_card reads examples but never reads example_translations; keyboards.py:daily_card_keyboard returns only the next-card button and query_result_keyboard returns only Add to review; callback_router contains no translation callback branch.

## Problem
ROADMAP.md says example translations remain hidden until an inline Show translations action is pressed, but the current renderer omits example_translations entirely and the card keyboards expose only Next card, Add to review, and SRS actions. callback_router has no translation-reveal action, so stored translations cannot appear as a spoiler or be added to the current card message.

## Solution
Implement a deterministic translation-reveal interaction over the cached canonical card: render the primary card without translations, attach a user-scoped card reference, and reveal or append the correctly paired translations after an authorized callback. Repeated clicks must be idempotent, stale or cross-user references must be rejected, and the action must not call AI, change quota/SRS state, mutate card_data, or send a duplicate card. Add a separate premium-gated detailed-card action only after the default and entitlement policy is explicitly decided.

## Note
The roadmap statement is currently aspirational rather than implemented; this issue captures the implementation gap and the required no-side-effect contract.

---

# status changes need a validated review and synchronization workflow

- ID: 56
- Module: issues/status_editor.py / issues/validate.py / ROADMAP.md
- Function: project status editing and generated-view synchronization
- Priority: medium
- Status: Open
- Category: feature
- Phase: phase-4
- Roadmap refs: issue-tooling
- Evidence: The status editor validates and previews issue, phase, and decision changes, while validate.py synchronizes the dashboard and marked generated roadmap section.

## Problem
Editing issue records, phase status, and roadmap summaries manually can leave the dashboard or generated roadmap section stale or inconsistent.

## Solution
Provide a reviewable JSON patch workflow that validates the complete resulting model, previews the diff, updates canonical issue and project-status records, and regenerates only marked views while preserving human-written roadmap narrative.

## Note
This is project-governance tooling only; it must not alter Telegram runtime behavior, AI generation, quotas, or database state.
