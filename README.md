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
git diff --check
```

تولید چنج‌لاگ (git-cliff باید در PATH باشد):

```bash
.venv/bin/python scripts/generate_changelog.py
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
- [GitHub Issues](https://github.com/Ham3dParsa/HamZaboonRobot/issues) —
  مخزن اصلی رکوردهای مهندسی (ویژگی، باگ، ریسک، پژوهش، تصمیم).

## کنترل هزینه و کیفیت AI

- کارت‌های آماده‌ی مرور در `saved_words` همراه با payload کامل کارت ذخیره
  می‌شوند؛ restart یا کلیک تکراری نباید باعث API call تکراری شود.
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

## مکانیزم SRS و مرور (FSRS)

- این پروژه به سمت پیاده‌سازی و به‌کارگیری مدل FSRS-6 پیش رفته است. هسته‌ی
  الگوریتم در `services/fsrs_core.py` قرار دارد و مستندسازی کامل پارامترها و
  تغییرات نسبت به FSRS-5 در `docs/FSRS_v6.md` آماده است.
- ساختار داده‌ها و ستون‌های بانکی برای FSRS موجود هستند: `saved_words` اکنون
  ستون‌هایی مانند `first_exposure_done`, `stability`, `difficulty` را نگه می‌دارد
  و `saved_words.card_data` همچنان payload کامل کارت معتبر را ذخیره می‌کند.
- مهاجرت از `daily_cards` به `saved_words` برای آماده‌سازی کارت‌ها به‌عنوان
  Tier-2 (pre-first-exposure) تکمیل شده‌است. پس از مهاجرت، جدول‌ها و APIهای
  قدیمی daily از مسیر runtime حذف شده‌اند.
- UX مرور از بازخورد ۲-دکمه‌ای قدیمی به یک UI چهار-دکمه‌ای FSRS (Again/Hard/Good/Easy)
  ارتقا یافته — gradeها به‌صورت کامل برای FSRS-6 ثبت می‌شوند.
- فرمول short-term stability به‌صورت پیش‌فرض فعال است (`enable_short_term=True`):
  مرور در همان روز از `short_term_stability` استفاده می‌کند و اولین exposure دیگر به
  فاصله‌ی یک روزه محدود نیست.
- یادآورها و نشان دادن کارتِ کامل (بدون نیاز به فراخوانی AI جدید) بر مبنای
  داده‌های ذخیره‌شده انجام می‌شود؛ پیشرفت فاصله‌ها تنها پس از تعامل کاربر advance می‌شود.

### وضعیت مهاجرت و کارهای باقی‌مانده FSRS
- زنجیره‌ی مهاجرت FSRS-6 تکمیل شده است: purge جدول‌ها و جریان‌های قدیمی daily (PR #300،
  با origin backfill در PR #304)، schema زمان‌بندی timestamp (PR #318) و سیم‌کشی رفتار FSRS
  شامل انتقال‌های اتمی `GradeResult`، انتخاب سررسید با اولویت DSR و یکپارچگی handler/UX
  (PR #336) همگی مرج شده‌اند.
- short-term mode به‌صورت سراسری فعال است؛ اولین exposure دیگر به یک روز محدود نیست و
  سررسید همان روز در جلسه‌ی بعدی بررسی می‌شود (بدون عبور از سهمیه).
- کار باقی‌مانده (Phase 3b+):
  - Tier-3 تولید AI (`generate_tier3_node`) — در حال حاضر stub است.

## محدودیت‌های عمدی MVP

- بدون تصویر AI، گروه/leaderboard، پرداخت خودکار و placement test رایگان.
- ارتقای پلن فعلاً دستی و owner-only است.
- محتوای آموزشی learner-facing باید AI-generated بماند.

