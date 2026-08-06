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
.venv/bin/python -m pytest tests/ -n 14
.venv/bin/python scripts/compile_all.py
.venv/bin/python -m ruff check --select F821,F811
.venv/bin/python scripts/generate_dashboard.py
git diff --check
```

## ساختار

- `config/` — تنظیمات محیط، پلن‌ها، سهمیه‌ها، منطقه زمانی، کاتالوگ زبان‌ها و کیبوردها.
  - `config/__init__.py` — تنظیمات و محدودکننده‌ها.
  - `config/catalog.py` — منبع واحد زبان‌ها، اهداف، سطح‌ها و برچسب‌های نمایشی.
  - `config/keyboards.py` — کیبوردهای پاسخ و درون‌خطی و callbackهای کوتاه.
- `services/` — لاجیک اصلی دامنه.
  - `services/db/` — SQLite، مهاجرت‌ها، کاربران، کارت‌ها، صف ارسال، SRS و کش‌ها.
  - `services/ai/` — کلاینت OpenAI، اعتبارسنجی JSON، پرامپت‌ها، تولید محتوا و presets.
  - `services/utils/` — قالب‌بندی MarkdownV2 و توابع کمکی.
  - `services/scheduling.py` — برنامه‌ریزی جلسه‌های روزانه و ظرفیت اسلات‌ها.
  - `services/tts.py` — تولید گفتار با Edge TTS.
- `handlers/` — هندلرهای تلگرام.
  - `handlers/user.py` — تنظیمات کاربر: زبان، هدف، سطح.
  - `handlers/admin.py` — پنل مدیریت و تنظیمات AI.
  - `handlers/srs_handler.py` — مرور فاصله‌دار (SRS).
- `bot.py` — نقطه ورود، مدیریت‌کننده‌های تلگرام، هماهنگ‌سازی و صف ارسال.
- `project_status.json` — فهرست ماشین‌خوان از فازها، وابستگی‌ها و
  قفل تصمیم‌ها. داشبورد فقط‌خواندنی در `issues/project_status.html` از این
  فایل ساخته می‌شود.
- `scripts/generate_dashboard.py` — تولیدکننده‌ی داشبورد HTML.
- [GitHub Issues](https://github.com/Ham3dParsa/HamZaboonRobot/issues) —
  مخزن اصلی رکوردهای مهندسی (ویژگی، باگ، ریسک، پژوهش، تصمیم).

## کنترل هزینه و کیفیت AI

- کارت‌های روزانه در `daily_cards` ذخیره می‌شوند و درخواست‌های بعدی از همان
  cache استفاده می‌کنند؛ restart یا کلیک تکراری نباید باعث API call تکراری شود.
- مسیر دستی، یک reservoir کوچک ۲ تا ۶ کارتی را آماده می‌کند تا هر کارت با یک
  prompt جداگانه ساخته نشود، اما کل سهمیه‌ی روز را هم بی‌دلیل پیش‌مصرف نمی‌کند.
- مسیر زمان‌بندی‌شده فقط session لازم را تولید می‌کند و ارسال‌ها را از صف
  durable با retry و backoff انجام می‌دهد.
- پرامپت کارت‌ها علاوه بر واژه‌های همان روز، یک لیست کوتاه از واژه‌های اخیر
  کاربر را هم avoid می‌کند تا تکرار واژه در روزهای نزدیک کمتر شود.
- نکته‌های گرامری عنوان‌های اخیر همان کاربر/زبان را در `grammar_tips` ذخیره
  می‌کنند و در prompt بعدی به‌صورت `avoid_topics` کوتاه ارسال می‌شوند.
- پارامترهای `AI_MAX_CONCURRENCY`، `AI_MAX_REQUESTS_PER_MINUTE` و `AI_TIMEOUT_SECONDS`
  نرخ و زمان انتظار provider را محدود می‌کنند.
- خروجی کارت و batch به‌صورت پیش‌فرض `compact_json` است.
- هر تماس AI نوع درخواست، مدل، latency و token usage را log می‌کند.

## مکانیزم SRS و مرور

- نتیجه‌ی معتبر پرسش واژه با payload کامل کارت در `saved_words.card_data`
  ذخیره می‌شود؛ SRS برای نمایش reminder کامل نیازی به API call جدید ندارد.
- reminderهای SRS کارت کامل را نمایش می‌دهند و با دکمه‌های کاربرمحور
  «یادم بود» و «فردا دوباره» جلو می‌روند.
- فاصله‌ی مرور فقط بعد از تعامل کاربر advance می‌شود.

## محدودیت‌های عمدی MVP

- بدون تصویر AI، گروه/leaderboard، پرداخت خودکار و placement test رایگان.
- ارتقای پلن فعلاً دستی و owner-only است.
- محتوای آموزشی learner-facing باید AI-generated بماند.
