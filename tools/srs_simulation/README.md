# SRS Simulation Tool — ابزار شبیه‌سازی مرور فاصله‌دار

A pure-Python offline simulator for the SRS session-based review engine.
It tests how different plan caps, backlog limits, and user behaviors affect
the learning queue **before** locking product numbers.

یک شبیه‌ساز آفلاین و مستقل برای موتور مرور فاصله‌دار SRS که به شما کمک می‌کند
پیش از نهایی‌سازی اعداد محصول، سناریوهای مختلف را تست کنید.

---

## Quick Start / شروع سریع

```bash
# Interactive mode / حالت تعاملی (پرسش و پاسخ)
python -m tools.srs_simulation

# Direct mode / حالت مستقیم
python -m tools.srs_simulation --plan free --days 30 --seed 42
python -m tools.srs_simulation --plan gold --days 90 --seed 7 --overflow-session-threshold 40
```

---

## What Each Parameter Means / توضیح پارامترها

### Plan / پلن

Controls the daily quota. Three tiers:
سقف روزانه را تعیین می‌کند. سه سطح:

| Plan | New cards/day | Queries/day | Sessions/day | Slots/day |
|------|---------------|-------------|--------------|-----------|
| **Free** / رایگان | 3 | 3 | 1 × 5 = 5 | 5 reviews |
| **Silver** / نقره‌ای | 8 | 10 | 4 × 5 = 20 | 20 reviews |
| **Gold** / طلایی | 12 | 14 | 10 × 5 = 50 | 50 reviews |

### `--days`

How many days to simulate. 30 = one month, 60-90 shows long-term trends.
چند روز شبیه‌سازی انجام شود. ۳۰ = یک ماه، ۶۰-۹۰ برای روند بلندمدت.

### `--daily-cards`

New vocabulary cards the system generates each day (AI budget).
تعداد کارت جدیدی که سیستم هر روز تولید می‌کند.

### `--word-query-cap`

How many "Ask a Word" queries the user can do per day.
تعداد پرسش‌های واژه در روز.

### `--word-query-save-prob`

Chance (0.0-1.0) that a word query gets saved for later review.
Default 0.5 = 50% of queries become review cards.
احتمال این‌که پرسش واژه به کارت مرور تبدیل شود. پیش‌فرض ۰.۵ = ۵۰٪.

### `--session-cap`

How many review sessions per day. Each session is a batch of cards.
تعداد جلسات مرور در روز.

### `--session-size`

Cards per session. Default 5 (product standard).
تعداد کارت در هر جلسه. پیش‌فرض ۵ (استاندارد محصول).

### `--backlog-ceiling`

Maximum cards waiting for their FIRST review. When full, new cards are rejected.
Default 50 (current product setting).
حداکثر کارت در صف انتظار برای اولین مرور. وقتی پر شود، کارت جدید رد می‌شود.

### `--fail-review-prob`

How often the user clicks "Again" (forgot) vs "Remembered".
چقدر کاربر "دوباره مرور" می‌زند در مقابل "یادم بود".

- 0.15 = 15% fail (typical learner)
- 0.3+ = struggling, leads to more early-interval resets

### `--overflow-session-threshold`

If backlog exceeds this number, an automatic extra session runs using only
backlog cards. Disabled by default.
اگر صف از این عدد بگذرد، یک جلسه اضافی فقط از کارت‌های صف اجرا می‌شود.

### `--seed`

Random seed for repeatable results. Same seed = same output every time.
عدد ثابت برای تکرارپذیری. هر بار با یک seed خروجی یکسان می‌گیرید.

### `--csv`

Save full results as a CSV file for Excel/Google Sheets.
ذخیره نتایج کامل در CSV برای بررسی در اکسل.

---

## Understanding the Output / توضیح خروجی

### Table columns / ستون‌های جدول

| Column | Meaning / معنی |
|--------|---------------|
| **Day** | Simulation day (روز شبیه‌سازی) |
| **Backlog** | Cards waiting for first review (کارت‌های منتظر اولین مرور) |
| **DueProc** | Due cards that WERE reviewed today (کارت‌های سررسیدشده که مرور شدند) |
| **DueCarry** | Due cards NOT reviewed (carried to next day) (به فردا موکول شد) |
| **Grad** | Total cards that graduated past first review (فارغ‌التحصیل‌شده) |
| **Rej** | New cards rejected because backlog was full (ردشده به علت پر بودن صف) |
| **Ovrflw** | Overflow session triggered today? (جلسه جبرانی فعال شد؟) |

### Summary metrics / شاخص‌های نهایی

- **Average backlog (last 7 days)** — میانگین صف در ۷ روز آخر
- **Max carry streak** — بیشترین روزهای پیاپی با کارت‌های موکول‌شده
- **Days with rejection (%)** — چند درصد روزها کارت جدید رد شد
- **Overflow sessions triggered** — تعداد جلسات جبرانی

### What to look for / به چه نکاتی توجه کنید

| If you see... | It means... |
|--------------|------------|
| Backlog constantly at ceiling | The review capacity is too low for the input rate |
| High carry streak | Users fall behind and can't catch up |
| High rejection % | New cards are wasted — backlog limit is too tight |
| Low graduated count | The system isn't producing enough learned words |

| اگر دیدید... | یعنی... |
|-------------|---------|
| صف مدام روی سقف است | ظرفیت مرور کمتر از ورودی است |
| DueCarry زیاد | کاربر عقب می‌افتد و نمی‌تواند جبران کند |
| ردشدگی بالا | کارت‌های جدید هدر می‌روند |
| فارغ‌التحصیلی کم | سیستم به‌اندازه کافی واژه نمی‌آموزاند |

---

## Examples / مثال‌ها

```bash
# Compare all plans with same seed / مقایسه هر سه پلن
python -m tools.srs_simulation --plan free   --days 30 --seed 42
python -m tools.srs_simulation --plan silver --days 30 --seed 42
python -m tools.srs_simulation --plan gold   --days 30 --seed 42

# What if users save more words? / اگر کاربران بیشتر ذخیره کنند؟
python -m tools.srs_simulation --plan free --word-query-save-prob 0.8 --days 60

# Test the overflow relief valve / تست شیر اطمینان
python -m tools.srs_simulation --plan free --days 60 --overflow-session-threshold 30

# 90-day gold simulation to CSV / ۹۰ روز طلایی در CSV
python -m tools.srs_simulation --plan gold --days 90 --seed 7 --csv gold_90d.csv
```

---

## How It Works / نحوه عملکرد

Each day (هر روز):

1. **New cards / کارت جدید** → added to backlog (up to ceiling)
2. **Word queries / پرسش واژه** → may add more to backlog (based on save probability)
3. **Review sessions / جلسات مرور** → process up to `session_cap × session_size` cards:
   - Priority 1 / اولویت ۱: overdue graduated cards (most overdue first)
   - Priority 2 / اولویت ۲: fill from backlog (FIFO)
4. **Overflow session / جلسه جبرانی** (optional): extra session from backlog only

### Review outcomes / نتیجه مرور

| Card type | Outcome | Result |
|-----------|---------|--------|
| Backlog (idx=-1) | First interaction | Graduates to `idx=0, next_review=today+1` |
| Graduated + Remembered | Advance | Next interval `[1, 3, 7, 16, 30]` days |
| Graduated + Again | Reset | Back to `idx=0, next_review=today+1` |

---

## Why This Tool Exists / چرا این ابزار ساخته شده

Before locking the SRS v2.8 product numbers (plan caps, backlog limits,
session sizes), the product owner can test various scenarios to find
balanced settings. This avoids deploying bad numbers that cause user
frustration (rejected cards) or wasted AI budget.

این ابزار به مالک محصول اجازه می‌دهد پیش از نهایی‌سازی اعداد SRS v2.8،
سناریوهای مختلف را تست کند تا از انتخاب اعداد نامتعادل جلوگیری شود.
