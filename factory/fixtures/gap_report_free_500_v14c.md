# v14c — داور + موضوع نهایی (126 تماس واقعی spark-1.3، بدون fallback)

زنجیره: v14a قطعی (2101 کارت) ← merge مدل (v14b: 1676 کارت، 367 ادغام، خرابی ۰) ← داور per-level + موضوع (v14c).
فایل: `ranked_senses-v14c.json` (picks + pick_source هر لم) + `topic_labels-v14c.json`.

## اعداد (از فایل)

- 500 لم، **1676 کارت**؛ picks: judge 494 لم، deterministic ۶ لم (light، chairman، cycling، exchange، stool، drive — بدون placeholder)
- Per-CEFR (ردیف‌های موضوع): A1 265 / A2 258 / B1 298 / B2 296 / C1 309 / C2 250
- موضوع: Other 453 (**27.0٪**) — بالای تارگت ۱۵٪؛ داور Other را برای حس‌های واقعاً انتزاعی نگه داشت (about/always/anything)
- توزیع غیر-Other: Society 187 / Emotions 148 / SciTech 135 / Work 131 / Nature 104 / Daily 100 / Food 87 / Health 79 / Travel 73 / Law 72 / Sports 60 / Business 47
- تماس‌ها: ۶۳ merge + ۶۳ judge = ۱۲۶، همه spark-1.3 (Zen responses/minimal)؛ مدل‌های fallback لازم نشدن

## پروب‌ها (picks واقعی داور)

- rock: مبتدی [#23 تکان، #4] / متوسط [#23، #1 موسیقی، #4] / پیشرفته [#1، #23، #39، #4] — موسیقی فقط برای پیشرفته اول است؛ سنگ (#12) با recall به uniq برگشته ولی top-4 نشد و داور بین نگه‌داشته‌شده‌ها انتخاب کرد (محدودیت واقعی: recall بدون بوست رتبه کافی نیست)
- flat: مبتدی [#40 سطح صاف، #14 آپارتمان] — هر دو معنی اصلی جلو هستند
- light (fallback قطعی): [#62 لامپ، #7 سبک] — تمیز، بدون داور هم درست است
- pass: مبتدی [#8 گذراندن، #25 بلیط] — «امتحان» وجود خارجی نداشت (فقط v9 تزریقی داشت)

## transport (فیکس‌های واقعی، در اسکریپت‌های ورک‌تری)

- مدل‌ها بدون پیشوند `opencode/` (با پیشوند 401 می‌داد)
- هدر User-Agent مرورگر (وگرنه Cloudflare 403)
- باگ double-POST در اسکریپت فاز ۲ (هر تماس دوبار می‌رفت) — فیکس شد
