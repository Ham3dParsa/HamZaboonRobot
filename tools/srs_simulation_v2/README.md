# SRS Session Engine v3 — Pull-Based Simulation

A pure-Python offline simulator for the **pull-based** SRS review engine.
Unlike v1 (push-based), v3 only generates AI cards when review sessions
have room AFTER due cards and query backlog are handled. This eliminates
backlog choking and reduces AI costs.

---

## English

### Philosophy

| v1 (Push) | v3 (Pull) |
|-----------|-----------|
| Forces new cards into backlog daily | Only generates AI cards when slots are empty |
| Backlog ceiling (50) blocks entries | No ceiling — backlog grows but doesn't block |
| Overflow session as relief valve | No overflow needed — pull design prevents choking |
| AI budget is fully consumed | AI budget used only on demand (cost savings) |

### Quick Start

```bash
# Interactive mode
python -m tools.srs_simulation_v2

# Direct mode
python -m tools.srs_simulation_v2 --plan free --days 30 --seed 42
python -m tools.srs_simulation_v2 --plan gold --days 90 --seed 7 --csv gold_v2.csv
```

### CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--plan` | free | `free`, `silver`, or `gold` |
| `--days` | 30 | Simulation duration |
| `--ai-daily-cap` | *plan default* | Max AI-generated cards/day (free=3, silver=8, gold=12) |
| `--query-daily-cap` | *plan default* | Max queries/day (each day rolls 0..cap randomly) |
| `--query-save-prob` | 0.5 | Chance each query saves to backlog |
| `--sessions` | *plan default* | Review sessions/day (free=1, silver=3, gold=5) |
| `--session-size` | *plan default* | Cards/session (free=4, silver=6, gold=6) |
| `--fail-prob` | 0.15 | Chance user clicks "Again" |
| `--seed` | None | Random seed for repeatability |
| `--report-every` | 5 | Print table every N days |
| `--csv` | None | Export to CSV |

### Plan Defaults

| Plan | Sessions | Slot/ session | Total slots | AI cap | Query cap |
|------|----------|--------------|-------------|--------|-----------|
| Free | 1 | 4 | 4 | 3 | 3 |
| Silver | 3 | 6 | 18 | 8 | 10 |
| Gold | 5 | 6 | 30 | 12 | 14 |

### How It Works

Each day:

1. **Queries** (randomized): User makes a random number of queries between 0 and
   the daily cap (`randint(0, cap)`). Each query independently rolls for save
   chance. Saved words enter the query backlog for review.

2. **Slot filling** (bulk, `sessions x session_size` total):
   - **Priority 1 (Due cards)**: Overdue graduated cards first
   - **Priority 2 (Query backlog)**: FIFO from saved queries
   - **Priority 3 (AI generation)**: New AI cards, up to daily cap
   - Remaining slots (if all sources empty) = session runs smaller

3. **AI Cost Tracking** (AICalls column): Every query and every AI-generated
   card consumes one API call. This is the true financial pressure on the AI
   provider (`AICalls = queries_made + ai_generated`).

### Output Metrics

| Column | Description |
|--------|-------------|
| `Day` | Simulation day |
| `DueProc` | Due cards successfully processed in sessions |
| `DueRem` | Due cards that couldn't fit (should stay near zero) |
| `QSaved` | Query backlog size at day's end (cards waiting for a slot) |
| `AIGen` | AI cards actually generated today |
| `AICalls` | **Total AI API calls today** = queries + AI gen (true cost) |
| `AICap` | Daily AI generation cap |
| `Active` | Total active cards in the SRS loop |

### Examples

```bash
# Compare all three
python -m tools.srs_simulation_v2 --plan free   --days 90 --seed 42
python -m tools.srs_simulation_v2 --plan silver --days 90 --seed 42
python -m tools.srs_simulation_v2 --plan gold   --days 90 --seed 42

# What if user does more sessions?
python -m tools.srs_simulation_v2 --plan free --sessions 2 --days 90

# Higher fail rate impact
python -m tools.srs_simulation_v2 --plan silver --fail-prob 0.3 --days 90 --seed 42
```

---

## فارسی

### شبیه‌سازی موتور مرور SRS نسخه ۳ (کششی - Pull-Based)

یک شبیه‌ساز کاملاً آفلاین و خالص با پایتون برای موتور مرور **کششی** SRS.
برخلاف نسخه ۱ (فشاری - Push-Based)، نسخه ۳ تنها زمانی کارت‌های AI تولید
می‌کند که پس از کارت‌های رسیده و صف پرس‌وجو، جای خالی در جلسات مرور باقی
بماند. این کار از انباشتگی صف و هزینه‌های بی‌مورد AI جلوگیری می‌کند.

### شروع سریع

```bash
# حالت تعاملی
python -m tools.srs_simulation_v2

# حالت مستقیم
python -m tools.srs_simulation_v2 --plan free --days 30 --seed 42
python -m tools.srs_simulation_v2 --plan gold --days 90 --seed 7 --csv gold_v2.csv
```

### گزینه‌های خط فرمان

| پرچم | پیش‌فرض | توضیح |
|------|---------|-------|
| `--plan` | free | رایگان، نقره‌ای یا طلایی |
| `--days` | 30 | مدت شبیه‌سازی |
| `--ai-daily-cap` | پیش‌فرض پلن | سقف کارت‌های AI در روز |
| `--query-daily-cap` | پیش‌فرض پلن | سقف پرس‌وجوی روزانه (هر روز ۰..سقف تصادفی) |
| `--query-save-prob` | 0.5 | احتمال ذخیره شدن هر پرس‌وجو در صف مرور |
| `--sessions` | پیش‌فرض پلن | تعداد جلسات مرور در روز |
| `--session-size` | پیش‌فرض پلن | کارت در هر جلسه |
| `--fail-prob` | 0.15 | احتمال کلیک کاربر روی "فراموش کردم" |
| `--seed` | ندارد | دانه تصادفی برای تکرارپذیری |
| `--report-every` | 5 | چاپ جدول هر N روز |
| `--csv` | ندارد | خروجی CSV |

### نحوه عملکرد

هر روز:

1. **پرس‌وجوی تصادفی**: کاربر بین ۰ تا سقف روزانه پرس‌وجو انجام می‌دهد
   (`randint(0, cap)`). هر پرس‌وجو به طور مستقل برای ذخیره‌شدن شانس دارد.
   کلمات ذخیره‌شده وارد صف مرور می‌شوند.

2. **پر کردن اسلات‌ها** (یکجا، مجموع `جلسات × کارت در جلسه`):
   - **اولویت ۱ (کارت‌های رسیده)**: کارت‌های قدیمی که نوبت مرورشان رسیده
   - **اولویت ۲ (صف پرس‌وجو)**: کلمات ذخیره‌شده به ترتیب FIFO
   - **اولویت ۳ (تولید AI)**: کارت‌های جدید AI، تا سقف روزانه

3. **رهگیری هزینه AI**: هر پرس‌وجو و هر کارت AI تولیدشده، یک تماس API محسوب
   می‌شود. ستون `AICalls` فشار مالی واقعی را نشان می‌دهد.

### ستون‌های خروجی

| ستون | توضیح |
|------|-------|
| `Day` | روز شبیه‌سازی |
| `DueProc` | کارت‌های رسیده‌ای که پردازش شدند |
| `DueRem` | کارت‌های رسیده‌ای که جا نشدند (باید نزدیک صفر باشد) |
| `QSaved` | اندازه صف پرس‌وجو در پایان روز |
| `AIGen` | کارت‌های AI تولیدشده امروز |
| `AICalls` | **مجموع تماس‌های API امروز** = پرس‌وجو + تولید AI |
| `AICap` | سقف تولید روزانه AI |
| `Active` | کل کارت‌های فعال در چرخه SRS |

### مثال‌ها

```bash
# مقایسه هر سه پلن
python -m tools.srs_simulation_v2 --plan free   --days 90 --seed 42
python -m tools.srs_simulation_v2 --plan silver --days 90 --seed 42
python -m tools.srs_simulation_v2 --plan gold   --days 90 --seed 42

# اگر کاربر جلسات بیشتری داشته باشد؟
python -m tools.srs_simulation_v2 --plan free --sessions 2 --days 90

# تأثیر نرخ فراموشی بالاتر
python -m tools.srs_simulation_v2 --plan silver --fail-prob 0.3 --days 90 --seed 42
```
