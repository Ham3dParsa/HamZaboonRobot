# هم‌زبان — ربات تلگرام آموزش زبان

هم‌زبان یک ربات تلگرام برای فارسی‌زبان‌هاست که واژگان، مثال‌ها، نکته‌های
گرامری و مرور فاصله‌دار را با محتوای تولیدشده توسط AI ارائه می‌کند. نسخه‌ی
فعلی روی کنترل هزینه‌ی API، جلوگیری از محتوای تکراری، ذخیره‌سازی امن‌تر داده‌ی
آموزشی و ارسال قابل‌اعتماد تمرکز دارد.

## اجرا

```bash
python -m venv .venv
source .venv/bin/activate   # ویندوز: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # مقادیر واقعی را فقط در .env وارد کن
python bot.py
```

برای بررسی سریع بدون اجرای ربات:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile config.py catalog.py scheduling.py db.py prompts.py ai.py keyboards.py bot.py issues/validate.py
.venv/bin/python issues/validate.py check
```

## ساختار

- `config.py` — تنظیمات محیط، پلن‌ها، سهمیه‌ها، تایم‌زون و محدودکننده‌ها.
- `catalog.py` — منبع واحد زبان‌ها، اهداف، سطح‌ها و برچسب‌های نمایشی.
- `db.py` — SQLite، migrationها، کاربران، کارت‌ها، صف ارسال، SRS و cacheهای کم‌هزینه.
- `prompts.py` — promptهای JSON-only و guardrailهای جلوگیری از تکرار.
- `ai.py` — کلاینت OpenAI-compatible، timeout، استخراج JSON و اعتبارسنجی کارت.
- `scheduling.py` — برنامه‌ریزی pure برای sessionهای روزانه و ظرفیت slotها.
- `keyboards.py` — reply/inline keyboardها و callbackهای کوتاه.
- `bot.py` — handlerهای تلگرام، orchestration، صف ارسال، SRS و retryهای Telegram.
- `issues/issues.json` — منبع canonical وضعیت bug/riskها؛ برای اعتبارسنجی از
  `issues/validate.py check` استفاده کن.

## کنترل هزینه و کیفیت AI

- کارت‌های روزانه در `daily_cards` ذخیره می‌شوند و درخواست‌های بعدی از همان
  cache استفاده می‌کنند؛ restart یا کلیک تکراری نباید باعث API call تکراری شود.
- مسیر دستی، یک reservoir کوچک ۲ تا ۶ کارتی را آماده می‌کند تا هر کارت با یک
  prompt جداگانه ساخته نشود، اما کل سهمیه‌ی روز را هم بی‌دلیل پیش‌مصرف نمی‌کند.
- مسیر زمان‌بندی‌شده فقط session لازم را تولید می‌کند و ارسال‌ها را از صف
  durable با retry و backoff انجام می‌دهد.
- prompt کارت‌ها علاوه بر واژه‌های همان روز، یک لیست کوتاه از واژه‌های اخیر
  کاربر را هم avoid می‌کند تا تکرار واژه در روزهای نزدیک کمتر شود.
- نکته‌های گرامری عنوان‌های اخیر همان کاربر/زبان را در `grammar_tips` ذخیره
  می‌کنند و در prompt بعدی به‌صورت `avoid_topics` کوتاه ارسال می‌شوند؛ بنابراین
  مدل همچنان محتوا را تولید می‌کند، ولی از تکرار موضوعات اخیر منع می‌شود.
- `AI_MAX_CONCURRENCY`، `AI_MAX_REQUESTS_PER_MINUTE` و `AI_TIMEOUT_SECONDS`
  نرخ و زمان انتظار provider را محدود می‌کنند؛ `AI_MAX_OUTPUT_TOKENS` سقف
  خروجی و `AI_TEMPERATURE` میزان تصادفی‌بودن پاسخ JSON را کنترل می‌کند.
- هر تماس AI نوع درخواست، مدل، latency و token usage گزارش‌شده توسط provider
  را log می‌کند. سهمیه‌ی پرسش واژه یا نکته‌ی گرامری هم در خطای provider پس
  داده می‌شود تا درخواست ناموفق از سهمیه‌ی کاربر کم نشود.

## SRS و مرور

- نتیجه‌ی معتبر پرسش واژه با payload کامل کارت در `saved_words.card_data`
  ذخیره می‌شود؛ SRS برای نمایش reminder کامل نیازی به API call جدید ندارد.
- reminderهای SRS کارت کامل را نمایش می‌دهند و با دکمه‌های کاربرمحور
  «یادم بود» و «فردا دوباره» جلو می‌روند.
- فاصله‌ی مرور فقط بعد از تعامل کاربر advance می‌شود، نه صرفاً بعد از این‌که
  Telegram پیام reminder را قبول کرد. reminderهای ارسال‌شده تا زمان پاسخ کاربر
  در وضعیت pending می‌مانند تا تکرار ناخواسته رخ ندهد.

## نکات ادغام با AI API و GapGPT

1. کلید API را در چت، commit، log یا issue evidence قرار نده. اگر قبلاً کلیدی
   را در چت paste کرده‌ای، آن را از پنل provider revoke/rotate کن.
2. `AI_BASE_URL` برای GapGPT یک endpoint سازگار با OpenAI SDK است؛ به همین دلیل
   پروژه از پکیج رسمی `openai` استفاده می‌کند.
3. `AI_MODEL` را از مستندات لحظه‌ای provider تنظیم کن. نام مدل در admin panel
   هم قابل تغییر است و نباید در promptها hardcode شود.
4. مقدارهای `.env` bootstrap هستند؛ owner می‌تواند base URL/model/key را از
   پنل مدیریت عوض کند. دیتابیس SQLite را مثل secret store محافظت کن، چون key
   runtime در جدول settings ذخیره می‌شود.
5. log فعلی latency، token usage و cost telemetry خام را ثبت می‌کند. owner
   می‌تواند از پنل مدیریت، قیمت ورودی/خروجی به ازای یک میلیون توکن و نرخ
   USD→تومان را override کند و داشبورد هزینه‌ی LLM را بر اساس پلن، کاربر،
   مدل، نوع درخواست و وضعیت خطا فیلتر کند.

## محدودیت‌های عمدی MVP

- بدون تصویر AI، گروه/leaderboard، پرداخت خودکار و placement test رایگان.
- ارتقای پلن فعلاً دستی و owner-only است.
- محتوای آموزشی learner-facing باید AI-generated بماند؛ cache و avoid-list فقط
  برای کنترل هزینه و جلوگیری از تکرار استفاده می‌شوند، نه جایگزینی محتوای ثابت.
