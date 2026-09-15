---
name: TICKETS-network-home
description: تیکت‌های فازی خانه شبکه — هر فاز با لبه مسدودکننده، دامنه، تست، گیت و ردیف سیم‌کشی (قفل‌شده 2026-09-15: هر هشت R همان گزینه پیشنهادی)
created: 2026-09-15
status: locked
---
STATE: no phase started — status:locked-2026-09-15 — focus: R1..R8 = پیشنهادی؛ اجرا به ترتیب P0→P1→P2 بعد از مرج 697.

> قفل 2026-09-15: هر هشت R همان گزینه پیشنهادی جدول پلن. بدون تغییر.

## P0 — خانه + چیدمان .env (پیش‌نیاز همه)

- **Blocked on:** مرج 697 (انجام شد 2026-09-15) — R1..R3 پیش‌تر قفل شده‌اند.
- **Scope:** `factory/precard/net.py` جدید (`NetConfig`، `lease_for`، `call_leg`، `report_lease`، `TARGETS` از سوپروایزر به اینجا)؛ `run_with_lease.py` پوسته نازک روی خانه (فلگ/چاپ عیناً)؛ `KeyRing` تک‌مالک (حذف کپی دوم)؛ `load_factory_env` تک‌مالک (حذف کپی vendored در pipeline.py، همان رفتار)؛ جابه‌جایی یک‌باره ۲ کلید یدکی از `tools/egress/.env`؛ بازنویسی جدول `.env` در `factory/README.md` (مالک + خواننده هر متغیر)؛ probeها: فلگ صریح یا خواندن از `factory/.env` (حذف `ZEN_API_KEY` جدا یا نگاشت صریح).
- **Tests:** hermetic برای `lease_for` (سرور/ساعت فیک)، `call_leg` (transport فیک: چرخش 429، STOP روی 401/403، اعمال proxy در-process)، ترتیب env→file، توقف بلند کلید غایب؛ `test_no_archive_imports` سبز می‌ماند؛ `tests/test_single_source_of_truth.py`: کلیدواژه‌های `KeyRing`/`TARGETS` → مالک جدید.
- **Gates:** R1، R2، R3، R6 (رفتار ABORT همین‌جا قفل می‌شود).
- **Wiring rows:** Imports/re-exports: `supervisor.TARGETS` → `net.TARGETS` (update)؛ `pipeline.load_factory_env` → حذف (update)؛ `transport.KeyRing` → حذف (update)؛ `client.lease` → `net.lease_for` (keep-as-shell)؛ DB/callback/keyboard: none؛ Docs: `factory/README.md` جدول env (update)، `tools/egress/README.md` (update).
- **Acceptance:** هیچ `KeyRing`/`TARGETS`/`load_factory_env` دومی در `grep` نیست؛ هر ۵ کلید دقیقاً یک خواننده دارند (تست who-reads-what)؛ فول‌سوئیت سبز.

## P1 — وایت‌لیست کدشده (بعد از P0)

- **Blocked on:** P0 green + R4 pick (کد در برابر prose).
- **Scope:** چهار تابع probe/choose/retire/never-overwrite-empty در خانه؛ سوپروایزر CLI صدایشان می‌زند (بدون بازنویسی منطق)؛ `egress_pool.json` فقط از همین توابع نوشته می‌شود؛ per-provider cooldown (429 یک provider دیگری را نمی‌بندد).
- **Tests:** hermetic با ساعت/سرور فیک (top-N، ping گوگل‌اول، cooldown جداگانه، خالی‌نویسی‌نکردن)؛ probe واقعی بدون شبکه اجرا نمی‌شود (تست ندارد، دستی).
- **Gates:** R4.
- **Wiring rows:** supervisor `--probe-zen/--probe-google` → همان توابع (update)؛ `egress_pool.json` writer واحد (update)؛ Docs: سیاست ۴بندی در README (update).
- **Acceptance:** حذف منطق تکراری از سوپروایزر؛ تست خالی‌نویسی سبز؛ رفتار probe روی همان SUBهای امروز عین دیروز (مقایسه دستی یک‌بار).

## P2 — فالبک مدل هر leg (بعد از P1، با تأیید هزینه)

- **Blocked on:** P1 green + R5/R7 picks + تأیید صریح مدل‌های پولی (قانون هزینه AI).
- **Scope:** `LEG_FALLBACKS[(provider, leg)]` در خانه + یادداشت هزینه هر ورودی؛ سیم‌کشی legs (`pipeline.py` هر ۴ leg، بعد `card_pilot.py`) به `call_leg` (بدون لیست محلی)؛ حرکت فقط روی `classify()==ROTATE`؛ رکورد تله‌متری + خط run.log + ورودی provider_map برای هر step-down؛ فالبک‌های قطعی همان نام `*-fallback`.
- **Tests:** hermetic هر leg: 429 → مدل بعدی همان leg؛ 401/403 → STOP بلند بدون تلاش بعدی (تست قفل R6)؛ provider_map هر مدل امتحان‌شده را ثبت می‌کند؛ بدون شبکه/کلید واقعی.
- **Gates:** R5، R6، R7 (مدل‌به‌مدل)، R8 (ترتیب).
- **Wiring rows:** Imports: legs → `net.call_leg` (update)؛ `JUDGE_MODELS`/لیست‌های محلی → حذف به نفع جدول (remove)؛ Telemetry: `model tried` per step (update)؛ Docs: جدول فالبک + هزینه در README (update).
- **Acceptance:** ران hermetic با 429 تزریقی دقیقاً به مدل دوم می‌رسد؛ ران 401 تزریقی هیچ تماسی به مدل دوم نمی‌گیرد و progress را flush می‌کند؛ فول‌سوئیت سبز؛ `provider_map.json` هر مدل امتحان‌شده را دارد.
