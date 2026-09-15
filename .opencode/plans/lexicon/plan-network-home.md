---
name: plan-network-home
description: یک خانه شبکه برای خط پیش‌کارت و کارت کامل — API قابل import، چیدمان یکتای .env، وایت‌لیست صریح، فالبک مدل هر leg فقط روی 429
created: 2026-09-15
base_commit: efae2b2
branch: TBD (after identity plan lands)
status: locked
---
STATE: phase none — status:locked-2026-09-15 — focus: R1..R8 = پیشنهادی (مالک: قفل شد)؛ اجرا P0→P1→P2 بعد از مرج 697.

## چرا (سند: گزارش تحقیق ۲۰۲۶-۰۹-۱۵)

- یک کلید سه‌جور مختلف resolve می‌شود (precard: factory→egress؛ blind50: env→factory→egress؛ probe: flag→env، بی‌خبر از factory). رفع فایل اشتباه هیچ اثری ندارد.
- fallback نامتقارن: google در ۲ از ۴ جا، OpenRouter در ۱ از ۴، بقیه صفر.
- probe اسم دیگری می‌خواهد (`ZEN_API_KEY` در برابر `OPENCODE_ZEN_API_KEY`).
- مالک تکراری: `KeyRing` ×۲، `load_factory_env` ×۲، `AuthError/extract_json` ×۲، کلاینت سوپروایزر ×۲؛ شاخه‌های 429 در `transport.py` جدول `classify()` را دور می‌زنند.
- فالبک مدل وجود ندارد: هر leg تک‌مدل است؛ 429 روی همان مدل می‌سوزد و STOP می‌دهد.
- مسیر شبکه قابل import وجود ندارد: تنها ابزار مشترک `run_with_lease.py` (process wrapper) است؛ نه precard نه card_pilot نمی‌توانند از داخل کد lease بگیرند یا `HTTPS_PROXY` را در-process اعمال کنند.

## نام‌گذاری و جای درز (زبان codebase-design)

- **ماژول عمیق** `factory/precard/net.py`: اینترفیس کوچک (`NetConfig`، `lease_for(provider)`، `call_leg(leg, prompt)`، `report_lease(outcome)`، جدول `TARGETS`) پشت رفتار زیاد (چرخش کلید، step-down مدل، lease/proxy در-process، تله‌متری بدون مقدار کلید، cooldown). درزهای داخلی (rotation، probe، ساعت، کش) خصوصی و فقط برای تست‌های خودش‌اند.
- **جای درز:** داخل `precard` چون تست هویت (`test_no_archive_imports`) import از `precard` به `pipeline/lexicon/archive` را ممنوع می‌کند ولی برعکسش را نه — پس card_pilot و blind50 بدون هیچ تغییر قانونی از همین خانه استفاده می‌کنند. `run_with_lease.py` پوسته نازک CLI روی همین خانه می‌شود (فلگ‌ها و چاپ‌ها عیناً).
- **آزمون حذف:** با پاک شدن `net.py` پیچیدگی در N فراخوان برمی‌گردد (هر leg دوباره چرخش/lease/proxy خودش را می‌خواهد) — پس بار خودش را می‌کشد، گذرگاه نیست.

## چیدمان .env (تک‌مالک، بدون منبع دوم پنهان)

- ریشه `.env`: فقط ران‌تایم بات. factory و egress هرگز نمی‌خوانندش.
- `factory/.env`: تنها مالک هر ۵ کلید LLM. ترتیب: process env، بعد `factory/.env`. کلید لازمِ غایب = توقف بلند با نام متغیر + فایل.
- `tools/egress/.env`: فقط `EGRESS_SUB_URL(S)` + `EGRESS_SUP_TOKEN`. دو کلید یدکی LLM یک‌بار جابه‌جا می‌شوند؛ بعدش این فایل هیچ کلید LLM ندارد. probeها کلید را فقط با فلگ صریح یا از `factory/.env` می‌گیرند.

## قوانین وایت‌لیست (صریح، بعداً تابع‌وار)

1. Probe: رنک TCP همه سرورها (هم‌روند، سقف ۵ ثانیه)؛ مرده = رنک نمی‌شود؛ top-N کاندید.
2. Choose: تونل تک‌تک کاندیدها + یک ping واقعی (Zen: responses کوچک؛ Google: models-list)؛ قبول‌شده‌های گوگل اول صف.
3. Retire: 429 فقط همان سرور برای همان provider را ۳۰۰ ثانیه می‌خواباند؛ `auth_err` lease را بازنشست می‌کند؛ `unknown` نه lease را می‌گیرد نه cooldown می‌دهد.
4. Never-overwrite-empty: probe با صفر سرور زنده هرگز `egress_pool.json` را بازنویسی نمی‌کند.

## جدول فالبک هر leg (فقط ROTATE، هرگز ABORT)

- شکل: `LEG_FALLBACKS[(provider, leg)] → [model, …]` با یادداشت هزینه هر ورودی، مالک: خانه شبکه. legها هیچ لیستی ندارند.
- حرکت فقط روی `classify() == ROTATE` (429/quota شامل RESOURCE_EXHAUSTED گوگل). روی `ABORT` (401/403/کلید نامعتبر): توقف فوری با نام متغیر + فایل، flush پیشرفت + تله‌متری، بدون تلاش مدل بعدی.
- هزینه: فقط مدل هم‌قیمت یا ارزان‌تر؛ هر مدل پولیِ جدید تأیید صریح هزینه می‌خواهد. هر قدم (چرخش کلید، step-down، سوییچ) رکورد تله‌متری + خط run.log + ورودی provider_map. فالبک‌های قطعی همان نام‌های `*-fallback` را نگه می‌دارند.

## خارج از دامنه

- ران‌تایم بات (`services/`، `handlers/`، `config/`، ریشه `.env`) دست نمی‌خورد.
- بازنشستگی Zen (تصمیم جدا، موکول‌شده) — این پلن با هر provider کار می‌کند.
- تغییر رفتار legها (prompt، گیت، assembly) — فقط سیم‌کشی شبکه عوض می‌شود.

## معیار قبول (کل پلن)

- `classify()` تنها جدول معنای خطا؛ `KeyRing`/`TARGETS`/هر لیست فالبک/هر متغیر `.env` دقیقاً یک مالک.
- همه تست‌ها hermetic (ساعت/سرور/فایل‌کلید تزریقی)؛ هیچ کلیدی در لاگ/تله‌متری (فقط key_idx عددی).
- هیچ fallback بی‌صدا: هر قدم خودکار برچسب `*-fallback`/`rotating`/`cooldown_switch` دارد.
- `pytest tests/ -n 14` سبز، `compile_all.py`، `ruff F821/F811`، `git diff --check`.

## تصمیم‌های باز (R1..R8 — هر کدام جدا، پیش‌فرض پیشنهادی)

| # | موضوع | پیشنهاد | بدیل‌ها |
|---|---|---|---|
| R1 | خانه کجاست؟ | `factory/precard/net.py` | A: `factory/core/net.py` + کپی vendored (تکرار)؛ B: پکیج `factory/net/` (درز جدید + sync) |
| R2 | API قابل import یا wrapper؟ | `call_leg`/`lease_for` + پوسته CLI | wrapper تنها (نیاز ۱ و ۴ بی‌پاسخ می‌ماند) |
| R3 | چیدمان .env؟ | factory مالک ۵ کلید؛ egress فقط SUB/token؛ بدون fallback پنهان | A: fallback با فلگ + هشدار؛ B: ادغام در ریشه (شکست جدایی بات/factory) |
| R4 | وایت‌لیست کد یا prose؟ | چهار تابع + تست hermetic | فقط README (دریفت برمی‌گردد) |
| R5 | جدول فالبک کجاست؟ | `LEG_FALLBACKS` در خانه | ثابت پر-leg در هر فایل (۴+ مالک، دریفت) |
| R6 | رفتار 401/403؟ | STOP فوری + flush، بدون تلاش بعدی | یک تلاش مدل بعدی (ریسک پنهان‌کردن مشکل اعتبار با هزینه) |
| R7 | سقف هزینه فالبک؟ | فقط هم‌قیمت/ارزان‌تر؛ مدل پولی = تأیید صریح | گران‌تر مجاز (هزینه غیرقابل پیش‌بینی) |
| R8 | ترتیب مهاجرت؟ | خانه+.env، بعد وایت‌لیست، بعد فالبک | فالبک اول (سریع ولی یک لیست یک‌بارمصرف دیگر) |

## Blocked Questions
- [2026-09-15] R1..R8: هر هشت مورد همان گزینه پیشنهادی جدول؟ Decision: بله، هر هشت = پیشنهادی (مالک: «با پیشنهاد‌هات قفل کردیم»). اجرا بعد از مرج 697.
