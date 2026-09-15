---
name: TICKETS-identity-141
description: تیکت‌های دقیق فاز هویت (خانه مستقل factory/precard) — هر تیکت با لبه مسدودکننده، دامنه فایل، تست و معیار قبول
created: 2026-09-14
status: in-progress
---
STATE: T5 IN PROGRESS — status:locked-executing — focus: contract 2026-09-15 (R0-R5, path 1 shim-then-delete).

## T5 resume notes (2026-09-15, exact)

- Done: W2 fixture fixed; blind50 repointed (committed); 6 test files
  mechanically repointed (proper_route, v7, v10, cloze, v141, cefr_bridge);
  graphify blast radius clean (only tests reference old module).
- Open bug: `gen_t5.py` drop patterns miss multi-line/`# noqa` from-imports
  (test_proper_route.py got mangled once — restored; do NOT rerun blindly).
  Verify drop on one file before batch.
- Hand rewrites pending: display-string tests in
  tests/test_precard_pipeline.py (Finglish assertions -> progress.display),
  tests/test_stage_glossary.py:92 (glossary-vs-live parity -> normalize
  based), STAGE_FINGLESH/STAGE_NAMES refs.
- Then: delete factory/pipeline/precard_pipeline.py; docs + AGENTS table;
  CI guards already exist (test_no_archive_imports); commit; push.
- CI state at pause: PR #697 red (tests + ram-gate + Kilo review failed).
  Root cause found+fixed after the red run: hermetic equivalence test left
  s0b leg uninjected so CI (keyless) hit the GOOGLE key gate (commit
  683b069, pushed, rerun in flight). Kilo failure unevaluated.
- Known live quirk: throwaway scripts under TEMP/opencode must be
  idempotent-guarded (append sections re-ran and duplicated blocks twice
  this session — always restore-then-run-once or guard appends).

## T5 locked contract (2026-09-15, GATE STATUS = LOCKED)

Premise (owner-decided): path 1 — shim as temporary step in this PR,
deletion at end of same PR. T5 scope ("delete in same PR") intact.
Owner confirmation: "locked — برو" (rules) + "باشه... انجامش بده" (path 1).
- Rule R0 / Option A: full explicit re-export of old public names +
  DEPRECATED header + T5 pointer. (B minimal rejected: brittle, no benefit.)
- Rule R1 / repair: drop old import lines in 4 half-repointed files
  (diff was insertions-only, no mangling). (Revert rejected: same speed,
  defers work pointlessly.)
- Rule R2 / Option A: hand repoint test_precard_pipeline.py, no script,
  chunked pytest; ~140 stage/resume/CLI tests preserved. (B delete-with-
  coverage-map rejected: loses end-to-end coverage, strains test-sync.)
- Rule R3 / hand now: test_stage_glossary.py:92 to new normalize.
- Rule R4 / "Society": R6 fixture live label. ("Arts & Culture" rejected:
  less close semantically; asserts only check ids/css so both safe.)
- Rule R5 / defer: card_pilot-side copies untouched (pilot line out of
  plan §19); T6 pointer + recorded reason; bots accept defer-with-reason.
  (Repoint-now rejected: widens scope, breaks §6.6 single-PR rule.)
- Blast-radius: structural trigger fired (module delete + cross-module
  repoint). Graph stale (built 10b06de != HEAD 769e6bd) so read-first:
  git-grep ground truth = 6 test files consume old module, 0 production
  importers (card_pilot refs are comments), blind50 already repointed.
  graphify update runs at delete step per T5.
- Parallel-work: claims registry empty ({"claims":[]}); no canonical
  SEAMS.md seam touched (factory/ + tests/ only) → zero overlap, no claim.
- Design note (codebase-design): shim is a deliberately shallow temporary
  adapter at the seam; deletion test passes trivially (no logic inside) —
  that is the point; it dies at end of PR.

## T5 execution record (2026-09-15)

- R0 AMENDED (owner, evidence: ~60-name inventory incl. renamed privates
  `_normalize_stage`, dead `STAGES`, stdlib passthroughs → faithful shim =
  adapter layer with legacy semantics, double work with R2): shim dropped,
  direct R3 → R2 → delete. T5 "delete in same PR" intact.
- R4: `Society & Culture` → `Society` (test-only). R1: 4 files repaired
  (old import lines dropped; diff was insertions-only). R3: glossary parity
  → live `progress` pin (11 passed).
- R2: test_precard_pipeline.py cut over by hand (no script), 140/140 green:
  per-name homes, USE-site transport patching (pipeline binding for judge
  leg, transport-module attrs for remap legs), display/normalize/stage-map/
  provider-map rewritten to Q-names, F7 identity test → vendoring-
  provenance test (plan line 42 supersedes no-second-copy).
- PRODUCTION GAP (T4c miss, found by R2 tests): pipeline.py:690 referenced
  `transport.zen_judge_transport` which did not exist (default Zen judge
  path crashed). Fix: vendored archive `call_responses` verbatim as
  `zen_judge_transport` + `JUDGE_SYS` in prompts.py (provenance headers).
  No archive imports; no behavior invented.
- Parity→baseline: 3 old-vs-new tests converted to new-only baselines with
  probed evidence values (anchor set-based: ranking rides live wordfreq).
- Reviewer gate: 2 confirmed findings, both fixed+verified — (1) slug scan
  repointed to factory/precard/* (+`review-error` registry gap closed in
  stage_glossary.py), (2) cefr test seam repointed to vendored copy.
- OC follow-up (5680202937): 1 warning answered with deprecation pointers
  in both copies (card_pilot.py:1359/2659, topics.py:73, accounting.py:12)
  + qualified "single owner" docstrings per R5-defer-to-T6; 6 infos
  evaluated — all deferred with the bot's own reasons (cosmetic/offline/
  contained/controlled/documented/clarity-only).
- Delete: factory/pipeline/precard_pipeline.py removed; zero code refs
  (READMEs → `python -m factory.precard`); graphify updated (12915 nodes).
- Evidence: pytest tests/ -n 14 → 2797 passed (after v7 dry-run rewrite);
  compile_all clean post-stage; ruff F821/F811 clean; diff --check clean.

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

**تصمیم قفل‌شده ۲۰۲۶-۰۹-۱۴: scorer لنگر vendored می‌شود** (حدود ۴۰۰ خط +
جدول‌ها، با سربرگ provenance). استدلال ثبت‌شده: تابع قطعی خالص است و همین
حالا عملاً فریز است؛ import یعنی نشت تغییر پایلوت به خط زنده (تکرار کلاس
باگ ۱۳/۱۶)؛ تست parity هر واگرایی را بلند قرمز می‌کند؛ هزینه‌اش فیکس
دوباره در صورت باگ فرمولی است. پس خانه جدید ماژول `anchor.py` هم می‌گیرد.
اجرا در سه زیرگام: T4a لنگر و preprocess، T4b لوله مشترک شبکه
(transport.py: keyring و rotation و JSON و telemetry)، T4c غنی‌سازی و
مونتاژ و CLI و repoint کردن blind50.
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
