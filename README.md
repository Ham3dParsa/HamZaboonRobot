# هم‌زبان — ربات تلگرام آموزش زبان

هم‌زبان یک ربات تلگرام برای فارسی‌زبان‌هاست که یادگیری را به صورت
جلسه‌ی مطالعه‌ی pull-based ارائه می‌کند: کاربر دکمه‌ی «شروع مطالعه امروز» را
می‌زند، یک جلسه شامل مرورهای سررسیدشده و کارت‌های جدید می‌بیند و با نمره‌دهی
FSRS پیش می‌رود. واژگان، مثال‌ها، نکته‌ی گرامری و تلفظ همه AI-generated هستند.
نسخه‌ی فعلی روی کنترل هزینه‌ی API، جلوگیری از تکرار، ذخیره‌ی امن و تجربه‌ی
جلسه‌ای قابل اعتماد تمرکز دارد — بدون ارسال پوش روزانه.

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
  - `services/db/` — SQLite، مهاجرت‌ها، کاربران، کارت‌ها، SRS و کش‌ها.
  - `services/ai/` — کلاینت OpenAI، اعتبارسنجی JSON، پرامپت‌ها، تولید محتوا و presets.
  - `services/utils/` — قالب‌بندی MarkdownV2 و توابع کمکی.
  - `services/scheduling.py` — سهمیه‌ی جلسه‌ی روزانه (sessions per day) بر اساس پلن و کلید روز اپ.
  - `services/session/` — موتور جلسه‌ی FSRS (build_session_list، grade_policy، summary).
  - `services/tts.py` — تولید گفتار با Edge TTS.
- `handlers/` — هندلرهای تلگرام.
  - `handlers/study_handler.py` — جلسه‌ی مطالعه‌ی pull-based.
  - `handlers/srs_handler.py` — نمره‌دهی first-exposure و مرور FSRS.
  - `handlers/user.py` — تنظیمات کاربر: زبان، هدف، سطح.
  - `handlers/admin.py` — پنل مدیریت و تنظیمات AI.
- `bot.py` — نقطه ورود، هندلرها و jobهای نگهداری (سلامت اتصال، پاکسازی query_results، ریست grace).
- [GitHub Issues](https://github.com/Ham3dParsa/HamZaboonRobot/issues) —
  مخزن اصلی رکوردهای مهندسی (ویژگی، باگ، ریسک، پژوهش، تصمیم).

## مدل مطالعه و کنترل هزینه‌ی AI

- مطالعه pull-based است: کاربر «شروع مطالعه امروز» را می‌زند، `services/scheduling.py`
  یک اسلات جلسه مصرف می‌کند و `services/session/build_session_list` جلسه را می‌سازد
  (Tier 1 مرورهای سررسیدشده، Tier 2 کارت‌های first-exposure، Tier 3 تولید AI که فعلا stub است).
- کارت‌ها در `saved_words` با payload کامل ذخیره می‌شوند؛ مرور، نمایش و گزارش پایان جلسه
  بدون API call جدید انجام می‌شود. restart یا کلیک تکراری باعث تولید دوباره نمی‌شود.
- پرسش واژه‌ی آزاد (`پرسش واژه`) سهمیه‌ی روزانه‌ی جدا دارد و نتیجه در `query_results`
  با TTL سی روزه کش می‌شود؛ انتخاب تکراری همان واژه بین reuse رایگان و تولید تازه حق انتخاب می‌دهد.
- پرامپت کارت‌ها واژه‌های اخیر کاربر را به صورت avoid-list می‌گیرد تا تکرار در روزهای نزدیک کم شود.
- نکته‌های گرامری بخشی از کارت هستند، نه ارسال روزانه‌ی جدا.
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
- نمایش کارتِ کامل و گزارش پایان جلسه (بدون نیاز به فراخوانی AI جدید) بر مبنای
  داده‌های ذخیره‌شده انجام می‌شود؛ پیشرفت فاصله‌ها تنها پس از نمره‌دهی صریح کاربر advance می‌شود.

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

