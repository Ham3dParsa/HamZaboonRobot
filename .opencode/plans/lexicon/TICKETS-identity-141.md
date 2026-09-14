---
name: TICKETS-identity-141
description: تیکت‌های دقیق فاز هویت (خانه مستقل factory/precard) — هر تیکت با لبه مسدودکننده، دامنه فایل، تست و معیار قبول
created: 2026-09-14
status: in-progress
---
STATE: tickets drafted from audit 2026-09-14, FOLDER locked 2026-09-14 — status:LOCKED — focus: execute T0..T5 in order on owner go

## موجودی ممیزی (سند هر تیکت — ۲۰۲۶-۰۹-۱۴)

- ورودی‌های مستقیم `precard_pipeline.py`: ماژول card_pilot + دو نام (item_key و
  append_telemetry_history) + ‏RunLogger،‏ cefr_bridge، سه‌تایی llm_json،
  سه‌تایی phrase_judge، هفت نام stage_glossary، سه‌تایی telemetry، و wordfreq
  تنبل. جمعاً ۳۹ کاربرد `card_pilot.*` متمایز.
- ورودی‌های تنبل از آرشیو: داور (deterministic_picks و validate_picks و MODELS
  و call_responses)، وکتور (MODELS و USER_TMPL و fallback_vectors و lemma_block
  و validate_vectors و call_responses)، برچسب (USER_TMPL و lemma_block و MODELS
  و validate_senses و call_responses) و evp_fallback_label. همه transportها
  تزریقی‌اند و شبکه نمی‌خواهند.
- مصرف‌کننده دوم: `blind50.py` پنج نماد می‌برد (RETRY_PREFIX و _judge_validate
  و _judge_prompt و anchor_rank_item و item_key). در همان PR باید repoint شود.
- stage_glossary را جز precard و تست‌هایش هیچ ماژول production دیگری نمی‌خواند
  (card_pilot جدول نام خودش را دارد). پس تغییرنام فایل‌های progress محصور است.
- مصرف‌کنندگان تست: test_precard_pipeline (پوشش سنگین stageها و resume) و
  test_precard_v141 و enrich در test_cefr_bridge و test_cloze_gates و
  test_blind50 و test_stage_glossary و test_formof_anchor. همه با کدشان
  می‌آیند و همان‌جا سبز می‌مانند.

## تیکت‌ها (به ترتیب اجرا — هر تیکت فقط وقتی شروع می‌شود که لبه‌اش سبز باشد)

### T0 — امضای ممیزی (بدون کد)
- دامنه: همین فایل. لبه: هیچی.
- قبول: مالک موجودی بالا را تأیید می‌کند یا اصلاح می‌دهد.

### T1 — اسکلت و نام‌ها (مسیر قفل‌شده: `factory/precard/`)
- دامنه (پیشنهاد مسیر: `factory/precard/` — نسخه در کد نه در مسیر):
  `__init__.py` با VERSION و run، ‏progress.py (نام‌های جدید جدول Q-names +
  read-shim فایل‌های قدیمی)، ‏accounting.py (انتقال audit_sample_accounting)،
  ‏prompts.py (متن‌ها و سازنده‌های prompt داور و inflection و افزوده topic).
- تست: تست عضویت نام‌ها و shim خواندن progress قدیمی.
- لبه: T0. گیت‌های قراردادی: Q-ver و Q-names. قبول: import آرشیو صفر در
  فایل‌های جدید (grep) و تست‌ها سبز.

### T2 — judge.py (استقلال داور)
- دامنه: انتقال _judge_prompt و judge_validate_multi و _judge_validate و
  fanout_picks و MAX_FANOUT و fallback و veto و judge_batch. از آرشیو فقط بخش
  خالص vendored می‌شود با سربرگ provenance (deterministic_picks و
  validate_picks و فهرست MODELS) و transportها تزریقی می‌مانند.
- تست: تست‌های S2 موجود می‌آیند؛ تست parity تک‌حس حفظ می‌شود.
- لبه: T1. قبول: هیچ ارجاعی به factory/archive در این ماژول نیست و رفتار
  داور بایت‌به‌بایت همان است (تست‌های منتقل‌شده بدون تغییر سبزند).

### T3 — topics.py (استقلال موضوع، بستن باگ ۱۳/۱۶)
- دامنه: توابع vectors و label بچ + TOPIC_TIEBREAK + guard + کپی فریز
  موجودی ۱۶تایی زنده با سربرگ provenance. از آرشیو فقط بلوک‌های prompt و
  اعتبارسنج خالص vendored می‌شوند. guard با نام‌های ۱۶تایی بازنویسی می‌شود
  (فیکس باگ زنده) و تست عضویت در رجیستری (همان تستی که باگ را می‌گرفت) همین‌جا
  می‌آید.
- لبه: T1. قبول: خروجی guard همیشه عضو موجودی زنده است (تست) و وکتورهای
  ران v141 برای آیتم‌های تک‌حس عیناً بازتولید می‌شوند.

### T4 — enrich.py و pipeline.py و CLI (استقلال غنی‌سازی و اجرا)
- دامنه: enrich_item و fallback لم و لینک CEFR و شناسه کارت به enrich.py.
  ماژول cefr_bridge با همان فایل‌های pack vendored می‌شود (دیتا جابه‌جا
  نمی‌شود). pipeline.py مونتاژ و assembly و CLI با نام‌های جدید stageها
  (--stages نام جدید می‌گیرد و id قدیم فقط از shim خوانده می‌شود).
  blind50 به خانه جدید repoint می‌شود (پنج نماد) — حذف مسیر قدیمی و جابه‌جایی
  فراخوان در همان PR (قانون route-delete).
- تست: تست‌های S5 و assembly و CLI می‌آیند؛ resume روی progress واقعی v141
  چک می‌شود.
- لبه: T2 و T3. قبول: precard.jsonl بازتولیدشده روی نمونه ۲۸۴تایی با خروجی
  v141 برای آیتم‌های تک‌حس موبه‌مو یکی است.

### T5 — cutover (حذف و قفل)
- دامنه: حذف factory/pipeline/precard_pipeline.py، به‌روزرسانی جدول ماژول
  AGENTS.md و اهداف اسکن test_wiring، نگهبان‌های CI (ممنوعیت import آرشیو و
  id قدیمی)، جدول تطبیق 0.x در docs، graphify update بعد از جابه‌جایی،
  مارکر read-only روی آرشیو.
- لبه: T4. قبول: grepها خالی‌اند، فول سوت سبز است، docs با کد یکی است.

### T6 — موکول (ثبت‌شده، اجرا نه)
- نسخه‌بندی خط پایلوت با همین الگو + رشد بسته EVP. فقط ثبت، بدون اقدام.

## تصمیم قفل‌شده (یکی بود — ۲۰۲۶-۰۹-۱۴)

- FOLDER: `factory/precard/`. رد شده: `factory/precard141/` (با اولین نسخه
  بعدی منسوخ می‌شود) و `factory/lexicon/precard/` (lexicon جای pool و pack
  است نه خط اجرا). استدلال: طبق Q-ver نسخه در کد زندگی می‌کند نه در مسیر.
  GATE STATUS = LOCKED.
