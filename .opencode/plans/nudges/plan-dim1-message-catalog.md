---
name: plan-dim1-message-catalog
description: Locked message catalog for dimension 1 (11 triggers + post-session tips, #467)
created: 2026-09-07
base_commit: ab8163d
branch: docs/dim1-lock
status: in-progress
---
STATE: dim 1/7 — status: LOCKED — focus: message catalog M01-M10 frozen; dims 2-7 pending

## Contract Lock — Dimension 1 (owner locked 2026-09-07, issue #467)

GATE STATUS: LOCKED (dimension 1 only). Dimensions 2-7 remain PENDING.

### Locked changes 1-5
1. `{content_type}` slot (word, phrase, street idiom...) instead of hardcoded word — forward compatible.
2. No hardcoded windows like «evening»; dynamic `{hours}` slot from smallest `effective_due` same calendar day (`target_window == 'today'`).
3. Full silence when hard-card dues fall tomorrow/late-night (`target_window == 'tomorrow'`).
4. Drop false streak-save-at-night claim; replaced by midnight-crossing event (angel/shield consume or streak-break warning via theme).
5. Premium extra quota for same-day returns (x4 multiplier). NOTE: quota-affecting; implementation needs its own atomicity + test detail under the same lock.

### Message spec M01-M10 (verbatim, Persian)
- M01 short-interval same-day (hard cards): after session iff `target_window == 'today'`. «اون {count} {content_type} سخت این نشست، حدود {hours} ساعت دیگه برمی‌گردن؛ یه نشستت رو برای اون موقع نگه دار تا بهشون به موقع رسیدگی کنیم.» Silence on `tomorrow`. Premium without normal quota gets optional extra-quota offer at x4.
- M02 midnight crossing (0 study days): after 00:00 next day. `{shield_emoji} «دیروز فرصت نشد سر بزنی؛ {theme_shield_event}. حواست باشه، برای حفظ پیوستگی باید امروز حتماً یه نشست بری!»` — `{theme_shield_event}` injected from `config/themes.py`. No shield: streak-to-zero warning.
- M03 streak at risk: evening, iff `last_active_date < today` and no session today. «امروز هنوز به هم‌زبان سر نزدی؛ حیف پیوستگی {streak} روزه‌ت نیست؟ با یه نشست ۳ دقیقه‌ای {next_streak} روزش کن! 🔥»
- M04 fresh words (teasing): noon. «چند تا {content_type} تازه برات آماده کردم؛ میای چند دقیقه درس بخونیم؟»
- M05 due cards: morning iff `due_words_for_user` non-empty. «نوبت مرور چندتا {content_type} رسیده؛ بیا با یه نشست کوتاه سبک و مرتبشون کنیم.»
- M06 unfinished session: noon/evening iff open `study_sessions` row same user calendar day. «یه نشست نصفه‌کاره داری که چندتا کارتش مونده؛ وقت داری سریع با هم ببندیمش؟»
- M07 quota remaining: evening. «هنوز {remaining} نشست از سهمیه امروزت مونده؛ سرت خلوت شد یکیش رو بریم؟» (`remaining` = plan quota minus daily `settings` key).
- M08 one step to heat jump: evening iff next session hits 40% line. «فقط یه نشست تا {target_heat_theme} مونده؛ همینو بری وضعیت امروزت می‌درخشه!» (`{target_heat_theme}` from `config/themes.py`).
- M09 evening dues ready: evening. «چند تا {content_type} برای امشب آماده مرور شدن؛ وقت داری یه دور سریع بزنیم؟» (sub-day intervals reviewed hours ago, due now).
- M10 weak session (<50% recall): right after session, fixed. Two study tips (two-sided pause + honest grading), no blame.

### Dimensions 2-7 (PENDING, not locked)
- Dim 2: cheap algorithmic monitoring + metrics (read path, cost, refresh).
- Dim 3: A/B evaluation + calibration (hash assignment, return-rate).
- Dim 4: free vs premium boundary.
- Dim 5: Rich vs Plain per surface.
- Dim 6: frequency caps, quiet hours, notification priority.
- Dim 7: behavioral risks + FSRS authenticity (grade gaming, streak anxiety).

## Evidence
- Owner lock: chat 2026-09-07 («این را قفل میکنم. ثبت کن و پرسیست شود.»), spec table M01-M10 verbatim.
- Prior grill: issue #467 comments (tiers, heat, shield, pre-reveal, Rich v2, S/D, punctuation, events, garden, nudges).

## Blocked Questions
- None open on dim 1. Implementation detail for change 5 (premium x4 atomicity + tests) to be settled in implementation ticket under this lock.
