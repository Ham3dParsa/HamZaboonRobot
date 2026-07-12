# HamZaban — Issues Export

> Review note: this Markdown file is the canonical issue source. `issues.html`
> is a local review/export view and may lag behind this file.

# عدم کش کارت روزانه – هزینه‌ی اضافی و گیج‌کننده

- ID: 1
- Module: bot.py
- Function: send_daily_card_now
- Priority: بالا

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
- Priority: بالا

## Problem
کاربر می‌تواند واژه‌ی دلخواه ثبت کند و due_words_for_user تعداد واژه‌های سررسید را نشان می‌دهد، ولی هیچ Jobای برای ارسال خودکار آن‌ها وجود ندارد.

## Solution
یک Job جدید (مثلاً هر روز ساعت ۱۰ صبح) اضافه کنید که برای هر کاربر، واژه‌های سررسید را گرفته و به صورت یک پیام گروهی یا جداگانه ارسال کند. پس از ارسال، تابع advance_word_review را برای هر واژه صدا بزنید تا زمان مرور بعدی محاسبه شود.

## Note
اش

---

# مدیریت Rate Limit تلگرام در ارسال همگانی و Job روزانه

- ID: 3
- Module: bot.py
- Function: daily_job / admin_broadcast
- Priority: متوسط

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
- Priority: پایین

## Problem
LANG_NAMES_FA به صورت دستی تعریف شده و اگر زبانی به SUPPORTED_LANGS اضافه شود، باید در دو جا به‌روز شود.

## Solution
در prompts.py، LANG_NAMES_FA را با from config import SUPPORTED_LANGS بسازید: LANG_NAMES_FA = {code: name for code, name in SUPPORTED_LANGS.items()} سپس در پرامپت‌ها از LANG_NAMES_FA.get(lang, lang) استفاده کنید.

---

# خطا در _extract_json هنگام عدم وجود JSON

- ID: 5
- Module: ai.py
- Function: _extract_json
- Priority: متوسط

## Problem
اگر مدل هیچ JSONای برنگرداند، re.search موفق نمی‌شود و json.loads("") خطا می‌دهد. در ask_json این خطا گرفته نمی‌شود و به بالا می‌رود.

## Solution
در _extract_json، اگر JSON پیدا نشد، یک استثنای سفارشی پرتاب کنید یا {} برگردانید. در ask_json، خطا را catch کرده و پیام مناسب به کاربر نشان دهید (در حال حاضر در bot.py catch می‌شود، ولی بهتر است خود ask_json یک None برگرداند و بالادست مدیریت کند).

---

# عدم استفاده از advance_word_review در هیچ‌کجای کد

- ID: 6
- Module: db.py / bot.py
- Function: advance_word_review
- Priority: متوسط

## Problem
تابع advance_word_review تعریف شده ولی هیچ‌گاه صدا زده نمی‌شود.

## Solution
پس از پیاده‌سازی ارسال یادآوری (مشکل شماره ۲)، پس از ارسال هر واژه، این تابع را صدا بزنید.

---

# ذخیره‌سازی API Key به صورت متن ساده در دیتابیس

- ID: 7
- Module: db.py
- Function: جدول settings
- Priority: پایین

## Problem
کلید API به صورت plaintext در دیتابیس ذخیره می‌شود که در صورت نفوذ به دیتابیس، لو می‌رود.

## Solution
از یک رمزنگاری ساده (مثلاً Fernet با کلید ثابت در env) برای ذخیره و بازیابی استفاده کنید. یا حداقل در README هشدار دهید که دیتابیس را امن نگه دارند.

---

# عدم استفاده از timezone در تاریخ‌گذاری

- ID: 8
- Module: db.py
- Function: touch_streak / can_ask_word / add_saved_word
- Priority: پایین

## Problem
استفاده از datetime.date.today() بر اساس ساعت سیستم است. اگر سرور در منطقه‌ی زمانی متفاوتی باشد، ممکن است روزها جابجا شوند.

## Solution
از pytz یا datetime.timezone.utc استفاده کنید و ساعت ارسال روزانه (DAILY_SEND_HOUR) را بر اساس UTC تنظیم کنید. یا یک تنظیمات timezone برای کاربر اضافه کنید (پیچیده‌تر).

---

# استفاده از edit_message_text بدون مدیریت خطا هنگام ویرایش پیام قدیمی

- ID: 9
- Module: bot.py
- Function: on_lang_selected / on_goal_selected / on_lang_changed / on_goal_changed / admin_callback
- Priority: متوسط

## Problem
اگر کاربر روی دکمه‌ای کلیک کند که پیام قبلاً حذف شده باشد، edit_message_text خطا می‌دهد و کرش می‌کند.

## Solution
تمام edit_message_textها را در try/except با telegram.error.BadRequest بپوشانید و در صورت خطا، یک پیام جدید ارسال کنید. یا از answer_callback_query با show_alert استفاده کنید و پیام را عوض نکنید (که فعلاً این کار را نمی‌کند).

---

# عدم محدودیت در دریافت کارت روزانه برای کاربران غیر onboarded

- ID: 10
- Module: bot.py
- Function: send_daily_card_now
- Priority: —

## Problem
اگر کاربری /start را نزده باشد و مستقیم دکمه را بزند، پیام «اول باید /start رو بزنی.» نشان داده می‌شود. این درست است، ولی دکمه‌ها تا زمانی که کاربر onboarded نشده باشد نمایش داده نمی‌شوند (چون منوی اصلی را نمی‌بیند). پس خطری ندارد.

## Solution
— (این مورد یک باگ واقعی نیست، فقط یک رفتار صحیح است که بررسی شد.)

---

# ارسال پیام همگانی بدون تأخیر ممکن است با محدودیت مواجه شود

- ID: 11
- Module: bot.py
- Function: admin_broadcast
- Priority: متوسط

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
- Priority: پایین

## Problem
پیش‌فرض timeout ندارد و ممکن است درخواست به دلیل کندی شبکه یا سرویس، مدت‌ها معلق بماند.

## Solution
در OpenAI هنگام ساخت کلاینت، timeout تنظیم کنید: OpenAI(base_url=base_url, api_key=api_key, timeout=30.0)

---

# عدم استفاده از log در بخش‌های مهم (به جز خطاها)

- ID: 13
- Module: bot.py
- Priority: پایین

## Problem
لاگ‌های کمی برای رویدادهای مهم وجود دارد.

## Solution
لاگ‌های بیشتری برای رویدادهای مهم مانند ورود کاربر جدید، تغییر پلن، ارسال کارت روزانه و ... اضافه کنید تا دیباگ و تحلیل رفتار کاربر راحت‌تر شود.

---

# format_card در صورت خالی بودن grammar_tip یک خط خالی اضافه می‌کند

- ID: 14
- Module: bot.py
- Function: format_card
- Priority: پایین

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
- Priority: پایین

## Problem
دیکشنری goal_hint به صورت جداگانه تعریف نشده و اگر هدفی در آن نبود، از یک مقدار پیش‌فرض استفاده نمی‌شود.

## Solution
دیکشنری goal_hint را به صورت جداگانه تعریف کنید و اگر هدفی در آن نبود، از یک مقدار پیش‌فرض استفاده کنید.

---

# وضعیت بازبینی issues 1 تا 15 در main فعلی

## حل‌شده

- 1: کش کارت روزانه با جدول `daily_cards` و progress پایدار پیاده شده است.
- 4: registryهای زبان/هدف/سطح به `catalog.py` منتقل شده‌اند.
- 5: نبود JSON اکنون با خطای مشخص مدیریت می‌شود.
- 6: `advance_word_review` در Job مرور SRS استفاده می‌شود.
- 10: رفتار فعلی یک guard صحیح برای کاربر onboard نشده است، نه باگ.
- 14: `format_card` نکته‌ی گرامری خالی را نمایش نمی‌دهد.
- 15: hint اهداف و fallbackها در catalog متمرکز شده‌اند.

## حل‌شده اما نیازمند سخت‌سازی

- 2: Job یادآوری SRS وجود دارد، اما باید chunking، retry و rate-limit مشترک
  اضافه شود.
- 3 و 11: ارسال زمان‌بندی‌شده محدود و retry می‌شود، اما broadcast و SRS هنوز
  از همان مسیر امن استفاده نمی‌کنند.
- 8: scheduler از timezone تنظیم‌شده استفاده می‌کند، اما توابع روزمحور
  دیتابیس هنوز در همه‌جا از timezone برنامه استفاده نمی‌کنند.
- 13: logging پایه وجود دارد، ولی eventهای lifecycle و متریک‌ها کامل نیستند.

## باز

- 7: API key همچنان plaintext در جدول settings ذخیره می‌شود.
- 9: برخی `edit_message_text`ها برای پیام حذف‌شده یا قدیمی fallback متمرکز
  ندارند.
- 12: timeout صریح برای OpenAI client تنظیم نشده است.

---

# یافته‌های جدید در بازبینی کامل کد

# Retry نامحدود برای صف delivery

- ID: 16
- Module: bot.py / db.py
- Priority: بالا

## Problem
صف‌های `failed` در هر tick دوباره claim می‌شوند و retry budget، backoff یا
وضعیت terminal ندارند. خطای دائمی می‌تواند باعث تلاش بی‌نهایت و مصرف دوباره‌ی
AI/Telegram شود.

## Solution
برای هر queue row سقف تلاش، backoff زمان‌دار و وضعیت manual-retry/terminal
تعریف کنید و تعداد تلاش و آخرین خطا را در admin metrics نمایش دهید.

# اجرای synchronous درخواست AI داخل handlerهای async

- ID: 17
- Module: bot.py
- Priority: بالا

## Problem
مسیر custom-word و grammar مستقیماً `ai.ask_card`/`ai.ask_json` را در handler
async اجرا می‌کند و در زمان کندی provider، event loop تلگرام را متوقف می‌کند.

## Solution
همه‌ی تماس‌های blocking را با `asyncio.to_thread` یا کلاینت async اجرا کنید و
timeout صریح provider را اضافه کنید.

# اعتبارسنجی ناقص callbackهای زبان و هدف

- ID: 18
- Module: bot.py
- Priority: بالا

## Problem
callback مربوط به level اعتبارسنجی می‌شود، اما callbackهای language و goal
قبل از ذخیره‌سازی علیه `catalog.py` بررسی نمی‌شوند. یک callback دست‌کاری‌شده
می‌تواند مقدار نامعتبر در profile ذخیره کند.

## Solution
اعتبارسنجی identifierها را در یک helper متمرکز کنید و برای language/goal/level
قبل از هر تغییر profile از آن استفاده کنید.

# quota غیراتمی و ذخیره‌ی واژه‌ی تکراری

- ID: 19
- Module: bot.py / db.py
- Priority: بالا

## Problem
سقف custom-word قبل از ورود واژه بررسی و بعداً جداگانه increment می‌شود؛
درخواست‌های هم‌زمان می‌توانند سقف را دور بزنند. همچنین `saved_words` برای
یک کاربر/زبان/واژه محدودیت uniqueness ندارد و کلیک یا ورود تکراری رکوردهای
تکراری می‌سازد.

## Solution
رزرو quota و increment را در transaction انجام دهید و برای واژه‌ی normalize‌شده
یک کلید idempotent تعریف کنید.

# SRS و broadcast بدون مسیر مشترک rate-limit

- ID: 20
- Module: bot.py
- Priority: متوسط

## Problem
ارسال SRS و broadcast مستقیماً `send_message` را صدا می‌زنند و از semaphore،
RetryAfter، retry محدود و chunking استفاده نمی‌کنند.

## Solution
یک sender مشترک با محدودیت concurrency، handling خطای Telegram و تقسیم پیام
بسازید و همه‌ی مسیرهای همگانی را از آن عبور دهید.

# ناهماهنگی منبع issues.html و Markdown

- ID: 21
- Module: issues.html / hamzaban-issues.md
- Priority: پایین

## Problem
`issues.html` داده‌ی issue را داخل JavaScript کپی می‌کند و تغییرات/یادداشت‌های
`localStorage` را جدا نگه می‌دارد. بنابراین HTML می‌تواند با فایل Markdown
canonical یا وضعیت واقعی کد متفاوت باشد.

## Solution
Markdown را تنها منبع نگه دارید و HTML را از آن تولید/refresh کنید، یا در
README صریحاً HTML را فقط view محلی بدانید و قبل از هر review آن را sync کنید.