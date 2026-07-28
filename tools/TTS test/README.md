# Edge TTS Test Module

تست pronunciation با Edge TTS برای زبان‌های پشتیبانی شده در catalog.

## وابستگی

```bash
pip install edge-tts
```

## نحوه استفاده

```bash
# نمایش زبان‌های پشتیبانی شده
python tts_test.py --list-languages

# نمایش همه صداهای موجود (اختیاری با فیلتر زبان)
python tts_test.py --list-voices
python tts_test.py --list-voices en

# تلفظ یک کلمه
python tts_test.py "hello" -l en
python tts_test.py "hello" -l en -o output.mp3
python tts_test.py "hello" -l en --gender Male
python tts_test.py "hello" -l en --rate "-20%"
python tts_test.py "سلام" -l fa
python tts_test.py "שלום" -l he --gender Male
```

## کنترل‌ها

| پارامتر | توضیح | پیش‌فرض |
|---------|-------|---------|
| `-l, --lang` | کد زبان (`en`, `es`, `ar`, `fr`, `de`, `tr`, `he`, `fa`) | `en` |
| `-o, --output` | مسیر فایل MP3 خروجی | `<lang>_<word>.mp3` |
| `--gender` | `Male` یا `Female` | خودکار |
| `--rate` | سرعت گفتار (`+0%`, `-20%`, `+30%`) | `+0%` |

## زبان‌های پشتیبانی شده

| کد | زبان | تعداد صدا |
|----|------|-----------|
| en | انگلیسی | 47 |
| es | اسپانیایی | 45 |
| ar | عربی | 32 |
| fr | فرانسوی | 13 |
| de | آلمانی | 10 |
| tr | ترکی استانبولی | 2 |
| he | عبری | 2 |
| fa | فارسی | 2 |

تمامی ۸ زبان دارای هر دو جنسیت **Male** و **Female** هستند.

## فایل‌های تست

۲۴ فایل MP3 نمونه در همین پوشه با الگوی `test_<lang>_<word>.mp3` تولید شده‌اند.
