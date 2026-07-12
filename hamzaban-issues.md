# HamZaban — Issues Export

> Generated from `issues/issues.json`; edit the JSON or use the issue app.
> Last synchronized: 2026-07-12

# عدم کش کارت روزانه – هزینه‌ی اضافی و گیج‌کننده

- ID: 1
- Module: bot.py
- Function: send_daily_card_now
- Priority: high
- Status: Resolved
- Roadmap refs: —
- Evidence: —

## Problem
هر بار که کاربر دکمه‌ی «واژه‌ی امروز» را می‌زند، یک کارت جدید از مدل زبانی گرفته می‌شود. این هم هزینه‌ی API را افزایش می‌دهد و هم مفهوم «کارت روزانه» را نقض می‌کند (کاربر باید همان کارت را ببیند).

## Solution
یک ستون daily_card (JSON یا TEXT) و daily_card_date به جدول users اضافه کنید. در send_daily_card_now و daily_job، ابتدا چک کنید که آیا امروز کارت از قبل تولید شده است. اگر بله، همان را برگردانید؛ در غیر این صورت تولید کنید و ذخیره کنید. در db.py توابع get_daily_card(user_id) و set_daily_card(user_id, card_json) اضافه کنید.

## Note
 کاربر رایگان باید 3 کارت روزانه داشته باشد که قابل مرور هستند.

---

# عدم ارسال یادآوری واژه‌های ذخیره‌شده (SRS)

- ID: 2
- Module: bot.py
- Function: —
- Priority: high
- Status: Partial
- Roadmap refs: —
- Evidence: —

## Problem
کاربر می‌تواند واژه‌ی دلخواه ثبت کند و due_words_for_user تعداد واژه‌های سررسید را نشان می‌دهد، ولی هیچ Jobای برای ارسال خودکار آن‌ها وجود ندارد.

## Solution
یک Job جدید (مثلاً هر روز ساعت ۱۰ صبح) اضافه کنید که برای هر کاربر، واژه‌های سررسید را گرفته و به صورت یک پیام گروهی یا جداگانه ارسال کند. پس از ارسال، تابع advance_word_review را برای هر واژه صدا بزنید تا زمان مرور بعدی محاسبه شود.

---

# مدیریت Rate Limit تلگرام در ارسال همگانی و Job روزانه

- ID: 3
- Module: bot.py
- Function: daily_job / admin_broadcast
- Priority: medium
- Status: Partial
- Roadmap refs: —
- Evidence: —

## Problem
ارسال همزمان پیام به تعداد زیاد ممکن است باعث خطای Too Many Requests از سمت تلگرام شود.

## Solution
از asyncio.sleep بین هر چند پیام استفاده کنید (مثلاً هر ۱۰ پیام ۰.۵ ثانیه مکث). یا از telegram.ext با Application و JobQueue به صورت تکی ارسال کنید.

## Note
این مشکل فعلا فوریت ندارد اما برای این که بعدا و با هجوم کاربران و وظایف دچار مشکل نشویم بهتر است از همین الان به فکر آن روز باشیم!

---

# همگام‌سازی نبودن نام زبان‌ها در prompts.py و config.py

- ID: 4
- Module: prompts.py
- Function: LANG_NAMES_FA
- Priority: low
- Status: Resolved
- Roadmap refs: —
- Evidence: —

## Problem
LANG_NAMES_FA به صورت دستی تعریف شده و اگر زبانی به SUPPORTED_LANGS اضافه شود، باید در دو جا به‌روز شود.

## Solution
در prompts.py، LANG_NAMES_FA را با from config import SUPPORTED_LANGS بسازید: LANG_NAMES_FA = {code: name for code, name in SUPPORTED_LANGS.items()} سپس در پرامپت‌ها از LANG_NAMES_FA.get(lang, lang) استفاده کنید.

---

# خطا در _extract_json هنگام عدم وجود JSON

- ID: 5
- Module: ai.py
- Function: _extract_json
- Priority: medium
- Status: Resolved
- Roadmap refs: —
- Evidence: —

## Problem
اگر مدل هیچ JSONای برنگرداند، re.search موفق نمی‌شود و json.loads("") خطا می‌دهد. در ask_json این خطا گرفته نمی‌شود و به بالا می‌رود.

## Solution
در _extract_json، اگر JSON پیدا نشد، یک استثنای سفارشی پرتاب کنید یا {} برگردانید. در ask_json، خطا را catch کرده و پیام مناسب به کاربر نشان دهید (در حال حاضر در bot.py catch می‌شود، ولی بهتر است خود ask_json یک None برگرداند و بالادست مدیریت کند).

---

# عدم استفاده از advance_word_review در هیچ‌کجای کد

- ID: 6
- Module: db.py / bot.py
- Function: advance_word_review
- Priority: medium
- Status: Resolved
- Roadmap refs: —
- Evidence: —

## Problem
تابع advance_word_review تعریف شده ولی هیچ‌گاه صدا زده نمی‌شود.

## Solution
پس از پیاده‌سازی ارسال یادآوری (مشکل شماره ۲)، پس از ارسال هر واژه، این تابع را صدا بزنید.

---

# ذخیره‌سازی API Key به صورت متن ساده در دیتابیس

- ID: 7
- Module: db.py
- Function: جدول settings
- Priority: low
- Status: Open
- Roadmap refs: —
- Evidence: —

## Problem
کلید API به صورت plaintext در دیتابیس ذخیره می‌شود که در صورت نفوذ به دیتابیس، لو می‌رود.

## Solution
از یک رمزنگاری ساده (مثلاً Fernet با کلید ثابت در env) برای ذخیره و بازیابی استفاده کنید. یا حداقل در README هشدار دهید که دیتابیس را امن نگه دارند.

---

# عدم استفاده از timezone در تاریخ‌گذاری

- ID: 8
- Module: db.py
- Function: touch_streak / can_ask_word / add_saved_word
- Priority: low
- Status: Partial
- Roadmap refs: —
- Evidence: —

## Problem
استفاده از datetime.date.today() بر اساس ساعت سیستم است. اگر سرور در منطقه‌ی زمانی متفاوتی باشد، ممکن است روزها جابجا شوند.

## Solution
از pytz یا datetime.timezone.utc استفاده کنید و ساعت ارسال روزانه (DAILY_SEND_HOUR) را بر اساس UTC تنظیم کنید. یا یک تنظیمات timezone برای کاربر اضافه کنید (پیچیده‌تر).

---

# استفاده از edit_message_text بدون مدیریت خطا هنگام ویرایش پیام قدیمی

- ID: 9
- Module: bot.py
- Function: on_lang_selected / on_goal_selected / on_lang_changed / on_goal_changed / admin_callback
- Priority: medium
- Status: Open
- Roadmap refs: —
- Evidence: —

## Problem
اگر کاربر روی دکمه‌ای کلیک کند که پیام قبلاً حذف شده باشد، edit_message_text خطا می‌دهد و کرش می‌کند.

## Solution
تمام edit_message_textها را در try/except با telegram.error.BadRequest بپوشانید و در صورت خطا، یک پیام جدید ارسال کنید. یا از answer_callback_query با show_alert استفاده کنید و پیام را عوض نکنید (که فعلاً این کار را نمی‌کند).

---

# عدم محدودیت در دریافت کارت روزانه برای کاربران غیر onboarded

- ID: 10
- Module: bot.py
- Function: send_daily_card_now
- Priority: none
- Status: Resolved
- Roadmap refs: —
- Evidence: —

## Problem
اگر کاربری /start را نزده باشد و مستقیم دکمه را بزند، پیام «اول باید /start رو بزنی.» نشان داده می‌شود. این درست است، ولی دکمه‌ها تا زمانی که کاربر onboarded نشده باشد نمایش داده نمی‌شوند (چون منوی اصلی را نمی‌بیند). پس خطری ندارد.

## Solution
— (این مورد یک باگ واقعی نیست، فقط یک رفتار صحیح است که بررسی شد.)

---

# ارسال پیام همگانی بدون تأخیر ممکن است با محدودیت مواجه شود

- ID: 11
- Module: bot.py
- Function: admin_broadcast
- Priority: medium
- Status: Partial
- Roadmap refs: —
- Evidence: —

## Problem
همانند شماره ۳ — ارسال همزمان پیام به تعداد زیاد ممکن است باعث خطای Too Many Requests شود.

## Solution
مشابه راه‌حل شماره ۳: از asyncio.sleep بین هر چند پیام استفاده کنید یا از JobQueue استفاده کنید.

## Note
این مشکل فعلا فوریت ندارد اما برای این که بعدا و با هجوم کاربران و وظایف دچار مشکل نشویم بهتر است از همین الان به فکر آن روز باشیم!

---

# عدم مدیریت timeout برای درخواست‌های AI

- ID: 12
- Module: ai.py
- Function: client.chat.completions.create
- Priority: low
- Status: Open
- Roadmap refs: —
- Evidence: —

## Problem
پیش‌فرض timeout ندارد و ممکن است درخواست به دلیل کندی شبکه یا سرویس، مدت‌ها معلق بماند.

## Solution
در OpenAI هنگام ساخت کلاینت، timeout تنظیم کنید: OpenAI(base_url=base_url, api_key=api_key, timeout=30.0)

---

# عدم استفاده از log در بخش‌های مهم (به جز خطاها)

- ID: 13
- Module: bot.py
- Function: —
- Priority: low
- Status: Partial
- Roadmap refs: —
- Evidence: —

## Problem
لاگ‌های کمی برای رویدادهای مهم وجود دارد.

## Solution
لاگ‌های بیشتری برای رویدادهای مهم مانند ورود کاربر جدید، تغییر پلن، ارسال کارت روزانه و ... اضافه کنید تا دیباگ و تحلیل رفتار کاربر راحت‌تر شود.

---

# format_card در صورت خالی بودن grammar_tip یک خط خالی اضافه می‌کند

- ID: 14
- Module: bot.py
- Function: format_card
- Priority: low
- Status: Resolved
- Roadmap refs: —
- Evidence: —

## Problem
اگر grammar_tip خالی باشد، یک خط خالی اضافی در خروجی ایجاد می‌شود.

## Solution
قبل از اضافه کردن بخش گرامر، چک کنید که grammar_tip خالی نباشد: if grammar_tip: lines.append(f"
✍️ *نکته‌ی گرامری:*
{grammar_tip}")

---

# پرامپت daily_card_system_prompt برای اهداف جدید قابل گسترش نیست

- ID: 15
- Module: prompts.py
- Function: daily_card_system_prompt
- Priority: low
- Status: Resolved
- Roadmap refs: —
- Evidence: —

## Problem
دیکشنری goal_hint به صورت جداگانه تعریف نشده و اگر هدفی در آن نبود، از یک مقدار پیش‌فرض استفاده نمی‌شود.

## Solution
دیکشنری goal_hint را به صورت جداگانه تعریف کنید و اگر هدفی در آن نبود، از یک مقدار پیش‌فرض استفاده کنید.

---

# Retry نامحدود برای صف delivery

- ID: 16
- Module: bot.py / db.py
- Function: delivery queue
- Priority: high
- Status: Open
- Roadmap refs: —
- Evidence: —

## Problem
صف‌های failed بدون سقف تلاش یا backoff در هر tick دوباره تلاش می‌شوند و خطای دائمی می‌تواند مصرف API و Telegram را بی‌نهایت تکرار کند.

## Solution
Retry budget، backoff و وضعیت terminal/manual-retry اضافه کنید.

---

# اجرای synchronous درخواست AI داخل handlerهای async

- ID: 17
- Module: bot.py
- Function: custom-word / grammar handlers
- Priority: high
- Status: Open
- Roadmap refs: —
- Evidence: —

## Problem
تماس مستقیم با کلاینت synchronous در زمان کندی provider event loop تلگرام را متوقف می‌کند.

## Solution
همه‌ی تماس‌های blocking را با asyncio.to_thread یا کلاینت async اجرا و timeout صریح تنظیم کنید.

---

# اعتبارسنجی ناقص callbackهای زبان و هدف

- ID: 18
- Module: bot.py
- Function: callback_router
- Priority: high
- Status: Open
- Roadmap refs: —
- Evidence: —

## Problem
callbackهای language و goal قبل از ذخیره‌سازی علیه catalog بررسی نمی‌شوند.

## Solution
اعتبارسنجی identifierها را قبل از هر تغییر profile متمرکز کنید.

---

# quota غیراتمی و ذخیره‌ی واژه‌ی تکراری

- ID: 19
- Module: bot.py / db.py
- Function: can_ask_word / add_saved_word
- Priority: high
- Status: Open
- Roadmap refs: —
- Evidence: —

## Problem
بررسی و increment سقف جدا هستند و saved_words نیز uniqueness ندارد.

## Solution
رزرو quota را transactionی کنید و ذخیره‌ی واژه را idempotent کنید.

---

# SRS و broadcast بدون مسیر مشترک rate-limit

- ID: 20
- Module: bot.py
- Function: srs_job / admin_broadcast
- Priority: medium
- Status: Open
- Roadmap refs: —
- Evidence: —

## Problem
این مسیرها مستقیماً send_message را صدا می‌زنند و retry، semaphore و chunking ندارند.

## Solution
یک sender مشترک مقاوم در برابر rate-limit برای همه‌ی ارسال‌های همگانی بسازید.

---

# ناهماهنگی منبع issues.html و Markdown

- ID: 21
- Module: issues.html / hamzaban-issues.md
- Function: ISSUES_DATA / localStorage
- Priority: low
- Status: Open
- Roadmap refs: —
- Evidence: —

## Problem
HTML داده‌ی issue و یادداشت‌ها را جداگانه نگه می‌دارد و ممکن است با Markdown canonical متفاوت شود.

## Solution
Markdown را تنها منبع نگه دارید و HTML را generate/refresh کنید یا آن را فقط view محلی مستند کنید.
