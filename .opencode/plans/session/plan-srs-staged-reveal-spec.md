---
name: srs-staged-reveal-spec
description: Locked spec — randomized staged-reveal review prompts, granular display-toggle system replacing brief/detailed, with admin-global defaults.
created: 2026-08-13
base_commit: pending (implementation deferred)
branch: pending
status: locked-spec
---

STATE: phase 0/0 — status: LOCKED SPEC — focus: implemented only after AI-preset releases Persistence/Admin seams + FSRS T09 closes

# Technical Spec — SRS Study Session UX/UI & Staged Reveal Architecture

> **Status:** LOCKED. This is the authoritative spec. Coding is deferred until the
> AI-preset branch releases the Persistence and Telegram UI->Admin seams, and the
> FSRS phase-06 release gate (T09) closes. Tracking issue: see below.

## 0. Contract Lock Summary (GATE STATUS: LOCKED)

All rules were chosen independently by the owner during the grill (2026-08-13).
Dependency & Wiring Map is in §6.

| Rule | Decision | Option |
|---|---|---|
| R1 | `direct_translate`/`meaning` language name is **dynamic** via `language_label(target_lang)` | A |
| R2 | synonym/antonym prompt draws **2–3 items randomly from combined synonyms+antonyms**; prompt sentence built by whether drawn set is only-antonyms / only-synonyms / both | owner custom |
| R3 | fill_blank: **search both examples, pick one containing the exact word**; if neither has it verbatim, **fall back** to standard/meaning/direct_translate | owner custom |
| R4 | sub-instruction (`👇 ...`) + progress footer shown on **all** front stages and the back stage (match mock) | A |
| R5 | FE badge: `کارت جدید ✨` in badge slot + footer. Review badge: `⏰ آخرین مرور: X روز پیش` (no «مرور فاصله‌دار» prefix) | owner custom |
| R6 | Delete card = **permanent remove-from-review with a confirm step** | B |
| R7 | **Full granular display-toggle system** (per-user + admin-global) **replaces** brief/detailed. Warning for high-value toggles; prompt pool follows toggles | A |
| R8 | Record `prompt_type` + `revealed` flag in `review_events.raw_signal` | A |
| R9 | Warning UX: confirm popup «خاموش کردن نمایش این مورد کیفیت و غنای تجربه آموزشی را کاهش می‌دهد. باز هم خاموشش می‌کنید؟ بله / انصراف»; user may proceed after warning | owner custom |
| R10 | Precedence: user override wins; admin-global sets defaults; admin has an optional override (with confirmation + warn) | A + admin override |
| R11 | Prompt pool never empty: always ≥1 eligible prompt (standard w/ word, or meaning/direct_translate w/ fa_meaning). Toggleable features designed so the session engine always can render a simple prompt | owner custom |
| R12 | Response-time telemetry: record recall-response time (front-stage prompt shown → grade) in `response_time_ms` | owner custom |

## 1. Core Philosophy

To maximize **Active Recall** and avoid the illusion of competence:
- **Review (due) cards** use a randomized **Staged Reveal**: a front (hidden) prompt,
  then a `👁 نمایش پاسخ` reveal to the full back-stage card, then grading.
- **First-Exposure (new) cards** bypass recall (no memory trace yet) — show the full
  card directly with familiarity-grading buttons.

## 2. Session Flow

### A. First-Exposure (New cards)
- Full card disclosure (word, IPA, meaning, explanation, synonyms/antonyms, examples +
  translations, grammar tip).
- Badge: `کارت جدید ✨` in the badge slot + progress footer.
- Keyboard: familiarity grid (`srs:fe:...`), unchanged labels.

### B. Review (Due cards) — Staged Reveal with randomized prompts

#### Front stage (hidden) — one of these prompt types
1. **`standard`** — shows `WORD` (bold, LTR) + `IPA` + badge + `🧠 از حافظه‌ات استفاده کن...` + sub-instruction.
2. **`fill_blank`** — `? ? ?` + badge + `🧠 واژه جا افتاده در این جمله را به یاد بیاور:` + a blanked example (from the example containing the exact word) + local-DB hint (synonym → antonym → meaning priority). No AI call.
3. **`meaning`** — `? ? ?` + badge + `🧠 چه واژه‌ای به معنای «[fa_meaning]» است؟` + hint `راهنما: [fa_explanation]`.
4. **`synonym`** — `? ? ?` + badge + prompt built from a random 2–3-item draw of the combined synonyms+antonyms set.
5. **`direct_translate`** — `? ? ?` + badge + `🧠 معادل [language_name] «[fa_meaning]» را به یاد بیاور.`

- **Front keyboard:** Row1 `👁 نمایش پاسخ`; Row2 `🗑 حذف کارت از جعبه مرور`.

#### Back stage (revealed)
- Full card: word+IPA (LTR), `✤ fa_meaning` + fa_explanation, `🟢 مترادف / 🔴 متضاد`, `📝 مثال‌ها + ترجمه` (paired), `✍️ نکته گرامری`, post-reveal prompt `🧠 با دکمه‌های توصیفی زیر یادآوری خود را ثبت کنید.`, footer.
- **Keyboard:** Row1 `⭕ یادم نیامد | 🟡 سخت بود`; Row2 `🟢 خوب بود | 🟣 خیلی راحت`; Row3 `🔊 تلفظ`.

## 3. UI String Registry (Persian)

| Key | Text |
|---|---|
| Show Answer | `👁 نمایش پاسخ` |
| Delete Card | `🗑 حذف کارت از جعبه مرور` |
| New Card Badge | `کارت جدید ✨` |
| Review Badge | `⏰ آخرین مرور: [X] روز پیش` |
| Instruct standard | `🧠 از حافظه‌ات استفاده کن تا معنا، مترادف‌ها و متضادهای این واژه را یادآوری کنی.` |
| Instruct fill_blank | `🧠 واژه جا افتاده در این جمله را به یاد بیاور:` |
| Instruct meaning | `🧠 چه واژه‌ای به معنای «[Meaning]» است؟` |
| Instruct synonym | built from drawn set |
| Instruct translate | `🧠 معادل [lang] «[Meaning]» را به یاد بیاور.` |
| Hint synonym | `💡 راهنما: مترادف [Syn]` |
| Hint antonym | `💡 راهنما: متضاد [Ant]` |
| Hint meaning | `💡 راهنما: به معنای «[Meaning]»` |
| Sub-instruction | `👇 دکمه‌ی «نمایش پاسخ» را بزن؛ سپس صادقانه با دکمه‌ها به یادآوری‌ات نمره بده.` |
| Post-reveal | `🧠 با دکمه‌های توصیفی زیر یادآوری خود را ثبت کنید.` |
| Warning text | `خاموش کردن نمایش این مورد کیفیت و غنای تجربه آموزشی را کاهش می‌دهد. باز هم خاموشش می‌کنید؟ بله / انصراف` |

All dynamic values pass through `escape_mdv2`/`escape_mdv2_code` (centralized, per AGENTS.md §Localization).

## 4. Prompt Selection & Guardrails

### Data-availability pre-filter (Rule 11)
- `synonym`: eligible only if combined synonyms+antonyms yields a draw (≥1); **2–3 items** drawn randomly.
- `fill_blank`: eligible only if an example contains the exact word (Rule 3).
- Cards missing fields fall back to `standard`, `meaning`, or `direct_translate`.
- **The pool is never empty**: `standard` needs only `word`; `meaning`/`direct_translate` need only `fa_meaning`. Guard rails ensure a bare card still yields a prompt.

### Randomization
- **Injectable seeded RNG** for deterministic tests (system RNG in production).
- Synonyms/antonyms draw: random 2–3 items from the combined set (Rule 2).
- Example index: random among eligible examples, but only those containing the exact word (Rule 3).

## 5. Display-Toggle System (R7/R9/R10/R11)

- **Replaces** the existing `presentation_preference` (brief/detailed) via migration.
- Per-user toggleable fields; admin-global defaults; user override wins; optional admin override (confirm + warn).
- Toggleable: explanation, synonyms, antonyms, examples, example translations, grammar tip, IPA/phonetic.
- High-value toggles (examples, synonyms/antonyms) → confirm popup (R9).
- Low-value (phonetic, grammar tip, example translations) → no warning.
- Prompt pool follows toggles (e.g., synonyms off ⇒ no `synonym` prompt; examples off ⇒ no `fill_blank`).
- Toggleable fields must be designed so the session engine can always render a minimal prompt (R11).

## 6. Dependency & Wiring Map

| Surface | Current | Disposition | Notes |
|---|---|---|---|
| `services/session/assembly.py` | builds nodes | **update** | nodes carry `activity_type`; prompt selection happens at render |
| `handlers/study_handler.py` | full-card render via `format_card` | **update** | front/back staging, reveal action |
| `handlers/srs_handler.py` | grade handlers | **update** | record response_time (prompt→grade), prompt_type + revealed in raw_signal |
| `services/utils/formatting.py` | `format_card`, orphaned `format_srs_prompt` | **update** | new prompt engine replaces orphaned code; back-stage renderer |
| `config/keyboards.py` | review/FE keyboards | **update** | add reveal + delete (confirm) callbacks; keep `srs:`/`srs:fe:` prefixes |
| `bot.py` `callback_router` | routes `srs:`, `srs:fe:` | **update** | add new prefixes (reveal, delete, delete-confirm) |
| `services/db/schema.py` + `settings.py` | `presentation_preference` | **update** | display-toggle storage (migration); **Persistence seam** |
| `handlers/user.py` | settings panel | **update** | per-user toggle editing + warning |
| `handlers/admin.py` (+ sub-router) | admin panel | **update** | admin-global defaults + optional override; **Admin seam** |
| `services/ai/ai.py` `card_data` | has all fields | **keep** | no AI-call change; data already sufficient |
| `tests/test_srs_staged_reveal.py` | orphaned-reveal tests | **update** | repurpose to new engine (deterministic via seeded RNG) |

**Verification guards:** `tests/test_wiring.py` (new callbacks), `tests/test_dead_code_guard.py` (orphaned `format_srs_prompt` removed), `tests/test_formatting.py`.

## 7. Tracking

- **GitHub Issue:** [#338](https://github.com/Ham3dParsa/HamZaboonRobot/issues/338) tracks this spec (recorded in TICKETS.md).
- **Plan register:** `.opencode/plans/TICKETS.md`.
- **Blocked Questions:** none outstanding — spec fully locked.

## 8. Blocked / Deferred

- **Implementation** deferred until AI-preset releases Persistence + Admin seams (parallel-work-guard) and FSRS T09 closes.
- **Back-stage always full detail** (R7 chose the toggle system, not brief/detailed respect for back stage).
