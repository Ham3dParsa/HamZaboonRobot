# CONTEXT v13 final — 2026-09-03 — همه واقعی

## اعداد نهایی (از فایل، نه حدس)
- v13a: 500 لم، 1797 کارت، Other 58.9% — وزن 0.50/0.12/0.30، بدون LLM
- v13b: 500 لم، 2072 کارت، Other 59.9% (831 keyword + 1241 none) — keep-more Kmax 4/5/7، بدون LLM (ادعای تقلبی پاک شد، بکاپ *.bak-fake)
- v13c: 500 لم، 2072 کارت، Other 10.5% (218) — 1023 تماس واقعی: 865 spark-1.3 (responses/minimal) + 158 ling
- Topic v13c: Daily 258, Health 223, Other 218, Emotions 186, Society 186, Law 176, Work 165, SciTech 147, Food 139, Nature 127, Travel 92, Sports 83, Business 72

## مدل‌ها (واقعی تست‌شده)
- spark-1.3 فقط via /responses (chat/completions میده 500). reasoning minimal = نصف توکن (594 vs 1170) با همان parse 15/15. بچ 18 تایی ~12-15 ثانیه، صفر rate limit در 100+ تماس.
- spark-1.2 با پرامپت ضعیف schema را رعایت نمی‌کند (strong prompt لازم دارد). ling اول خوب بود بعد rate limit خورد. Groq qwen با این کلیدها 403. Gemini مستقیم PermissionDenied.
- Progress: tqdm زنده (بدون pipe!) + logs/v13c_refine_progress.json بعد هر بچ + resume خودکار.

## مقایسه صادقانه tops
- v6: rock=موسیقی، light=تشعشع، pass=کشیده‌شدن، flat=دکور تئاتر — بدون CEFR، موضوع تصادفی (Food/Sports)
- v9: rock=سنگ A1، light=سبک A1، pass=امتحان تزریقی B1، flat=آپارتمان B1 — بهترین tops ولی با +0.4/tزریق (تقلب)
- v10: rock=the Rock، light=تشعشع، pass=مردن، flat=آپارتمان — حذف تقلب = برگشت غلط‌ها
- v12C: rock=یخ، light=شعر 1590، pass=قانون، flat=آپارتمان با مثال Tatoeba — موضوع 50% Other
- v13c: rock=یخ، light=To lighten، pass=تغییر وضعیت/Work، flat=آبجو/Food — موضوع 10.5% ولی رتبه rock/flat بدتر از v9

## مشکل بعدی (وزن، نه موضوع)
- Zipf 0.50 بر همه می‌چربد: یخ (B2) در برابر سنگ (A1) برای لم B2 — هر دو factor 1.0 می‌گیرند، بسامد یخ می‌برد.
- Duplicate واقعی: rock#50 و rock#24 هر دو «To move gently back and forth» نگه داشته شدند — dedup 0.82 آن‌ها را جدا دید.
- proper noun («the Rock») و slang جریمه نمی‌شوند.

## تخمین 4000 کارت (از throughput واقعی)
- LLM refine: ~1 ثانیه/کارت all-in (18 تایی ~13 ثانیه)؛ ~60% کارت‌ها Other می‌شوند → برای ~16000 حس ≈ 9600 کارت ≈ 534 تماس ≈ 2 ساعت + sleep ≈ 3 ساعت.
- Dedup MiniLM + ranking: با GPU کولب ~1-2 ساعت برای 4000 لم.
- جمع: حدود نصف روز برای 4000 (با spark-1.3/minimal/bچ 18). بدون LLM: فقط CPU چند ساعت.

## طرح v14 (پیشنهاد، نه قفل)
1. وزن: جریمه اسم خاص (gloss تک‌کلمه‌ای با حرف بزرگ) + slang؛ CEFR نامتقارن قوی‌تر (sense==level بوست)؛ بسامد per-sense (NGSL rank via synonyms) به‌جای Zipf لم.
2. LLM merge: muse 1.3 بچ 20 تایی حس‌های نزدیک را ادغام + نماینده انتخاب کند (rock#50/#24 → یکی)؛ بعد pick نهایی per-level با judge.
3. استاندارد زبان‌آگنوستیک: normalize → full-text embed (MiniLM چندزبانه) → POS dedup → freq/CEFR → topic (keyword+LLM) → merge/pick — برای DE/TR/HE فقط pack عوض می‌شود.
