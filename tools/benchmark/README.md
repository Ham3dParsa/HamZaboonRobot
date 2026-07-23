# ابزار بنچمارک مدل‌های AI

مقایسه مدل‌های مختلف AI برای تولید کارت واژه، با تحلیل هزینه، latency، نرخ خطا و کیفیت خروجی.

## ساختار

| فایل | وظیفه |
|------|--------|
| `__init__.py` | ورودی CLI — argparse + انتخاب تعاملی پریست |
| `runner.py` | موتور اجرا — non-batched (هم‌زمان با retry) + batched |
| `report.py` | تولید گزارش Markdown با جزئیات هزینه/توکن |
| `README.md` | این فایل — مستندات |
| `benchmark_full.bat` | بنچمارک کامل: همه پریست‌ها، هر دو حالت |
| `benchmark_fast.bat` | بنچمارک سریع: فقط flash-lite، هر دو حالت |
| `benchmark_single_preset.bat` | بنچمارک یک پریست خاص در حالت single |
| `benchmark_both_modes.bat` | مقایسه single vs batch روی یک پریست |

## نحوه استفاده

### خط فرمان

```powershell
# یک پریست خاص
python -m tools.benchmark --presets google_36_flash_eliapi

# دو پریست
python -m tools.benchmark --presets google_36_flash_eliapi google_flash_lite_latest_eliapi

# انتخاب تعاملی پریست (بدون --presets)
python -m tools.benchmark

# واژه‌های دلخواه
python -m tools.benchmark --presets google_36_flash_eliapi --words run,book,cozy

# فقط حالت non-batched با فرمت full
python -m tools.benchmark --presets google_36_flash_eliapi --mode single --no-compact
```

### فایل‌های bat

روی فایل‌های `*.bat` دابل کلیک کنید یا از خط فرمان اجرا کنید:

```powershell
.\tools\benchmark\benchmark_fast.bat
.\tools\benchmark\benchmark_full.bat
.\tools\benchmark\benchmark_single_preset.bat
.\tools\benchmark\benchmark_both_modes.bat
```

## نحوه کار

### Non-batched (single)
- هر واژه یک تماس API مجزا
- تماس‌ها هم‌زمان با `ThreadPoolExecutor(max_workers=max_concurrency)` اجرا می‌شوند
- در صورت خطای RateLimit (429): تا ۳ بار با backoff هوشمند بر اساس `max_rpm` پریست تلاش مجدد می‌کند
- خطاهای غیر RateLimit: بدون retry ثبت می‌شوند

### Batched (batch)
- همه واژه‌ها در یک تماس با `ask_batch()` ارسال می‌شوند
- پریسمپت شامل لیست دقیق واژه‌هاست تا مدل مجبور به تولید کارت برای همان واژه‌ها شود
- در صورت عدم تطابق واژه‌های خروجی با ورودی، به‌عنوان خطا ثبت می‌شود

### هزینه‌ها
- هزینه‌ها با `MODEL_COST_MAP` در `runner.py` بازمحاسبه می‌شوند (نه از DB settings)
- نرخ دلار: ۲,۰۰۰,۰۰۰ IRR = 1 USD
- پشتیبانی از مدل‌های: gemini-3.6-flash، gemini-3.5-flash، gemini-flash-lite-latest، gemma-4, ...

### گزارش
- خروجی: stdout + فایل Markdown در `docs/reports/`
- شامل: جدول خلاصه، جزئیات هر پریست، تحلیل خطاها، خروجی خام کارت‌ها

## افزودن مدل جدید

۱. مدل و preset را در `services/ai/ai_presets.py` تعریف کنید
۲. قیمت را به `MODEL_COST_MAP` در `runner.py` اضافه کنید
۳. بنچمارک را اجرا کنید
