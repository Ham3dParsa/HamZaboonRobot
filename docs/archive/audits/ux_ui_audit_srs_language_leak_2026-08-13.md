# UX/UI Audit — SRS Study Flow & "Ask a Word" Card

**Date:** 2026-08-13
**Scope:** Static analysis of the SRS session/review flow and the manual "Ask a Word" flow. Read-only analysis; the language-leak root cause was subsequently fixed (see §4 + Reconciliation).
**Modules traced:** `services/db/words.py` → `services/db/__init__.py` → `services/session/assembly.py` → `handlers/study_handler.py` → `services/utils/formatting.py` → `config/keyboards.py`; and `services/word_query.py` → `bot.py` (ask-word block).

---

## 0. Contract concept → current code mapping

The contract brief refers to **New (`interval_idx == -1`)** vs **Review (`interval_idx >= 0`)**. The `interval_idx` column was **dropped** from `saved_words` (schema.py:504). The current state machine is encoded instead by two columns:

| Contract term | Current code signal | Meaning |
| :--- | :--- | :--- |
| New (`interval_idx == -1`) | `first_exposure_done = 0` | First-Exposure card — learner rates *familiarity* |
| Review (`interval_idx >= 0`) | `first_exposure_done = 1` AND `last_review_at IS NOT NULL` | SRS Review card — learner rates *recall* |

All audit text below uses the **current** semantics (`first_exposure_done`).

---

## 1. Data Flow — DB tuple → Telegram message string

### 1.1 Session (study) card path

```
saved_words row  (services/db/words.py: SELECT * …)
   │  (lang, card_data JSON, word, first_exposure_done, review_status, …)
   ▼
build_session_list(user_id, lang, goal, level, plan)   services/session/assembly.py
   │  Tier 1: due_words_for_user(user_id, lang)        → activity_type="srs_review"
   │  Tier 2: get_pre_first_exposure_words(user_id, lang) → activity_type="first_exposure"
   │  returns list[SessionNode]  (card_data={"word":…}, source_id=row["id"])
   ▼
handle_study_start → _render_and_send_first_card → _build_card_text_and_keyboard
   handlers/study_handler.py:243
   │  db.get_saved_word(word_id, user_id)  → row
   │  _saved_word_card(row)                 → card dict  (services/utils/formatting.py:150)
   │      parses row["card_data"] JSON (word, phonetic, fa_meaning, examples, …)
   │  _phonetic_lines(card_data["phonetic"]) → e.g. ["`/ipa/`"]
   ▼
format_card(card_data, footer=progress, phonetic_lines=…)   formatting.py:76
   │  escape_mdv2() applied to EVERY dynamic field
   │  default presentation="detailed"  (brief/detailed NOT read from user pref here)
   │  builds MarkdownV2 string:
   │    *WORD*
   │    `/ipa/`
   │    ✤ *fa_meaning*
   │    fa_explanation
   │    🟢 مترادف: …
   │    🔴 متضاد: …
   │    📝 مثال‌ها + ترجمه: …    (translations only if translations_prepared)
   │    ✍️ نکته‌ی گرامری: …
   │    نشست N | کارت n از m      (footer = progress, ALWAYS shown)
   ▼
bot.send_message(text, parse_mode=MARKDOWN_V2, reply_markup=KEYBOARD)
```

**Keyboard selection (state-based):**
- `first_exposure` → `get_first_exposure_keyboard(user_id, word_id)` (formatting.py:380) — familiarity labels.
- else → `get_review_keyboard(user_id, word_id, show_pronounce=db.should_show_pronounce(user_id))` (formatting.py:335) — recall labels + optional 🔊 tts row.

### 1.2 "Ask a Word" (manual) card path

```
bot.py ask-word block (text == BTN_ASK_WORD) → ask_for_ask_word
   │  word_query.ask(user_id, text, generate_card=…)   services/word_query.py:207
   │     validate → reserve quota → AI 2-step pipeline → db.create_query_result(…)
   │     returns AskResult(kind="ok", token, card_data, show_pronounce, usage_text)
   ▼
format_card(result.card_data,
            footer=f"{usage_text}\n\nبرای افزودن این واژه به مرور، از دکمه‌ی زیر استفاده کن.",
            presentation=_user_presentation(row),     # <-- respects user brief/detailed pref
            phonetic_lines=phon_lines)                 formatting.py:76
   ▼
query_result_keyboard(token, row["target_lang"],
                      show_translations=True, show_pronounce=…)   keyboards.py:300
   ▼
bot.send_message(…, reply_markup=query_result_keyboard)
```

**Key data-flow differences:**

| Aspect | Session card | Ask-a-Word card |
| :--- | :--- | :--- |
| Card source | `saved_words.card_data` via `_saved_word_card` | `query_results.result_json` (fresh AI) |
| `presentation` | hardcoded `detailed` | `_user_presentation(row)` (user choice) |
| Footer | progress `نشست N \| کارت n از m` | usage `📊 استفاده امروز…` + save hint |
| Translations toggle | only if `translations_prepared` (never set in session) | rendered by default, toggle re-runs prep |
| Escaping | `escape_mdv2` (centralized ✓) | `escape_mdv2` (centralized ✓) |

Both paths correctly route **all** dynamic values through `escape_mdv2`/`escape_mdv2_code` before MarkdownV2 interpolation — no raw concatenation detected.

---

## 2. State Machine — First-Exposure vs Review (visual + functional)

| Dimension | First-Exposure (New) | Review |
| :--- | :--- | :--- |
| DB signal | `first_exposure_done = 0` | `first_exposure_done = 1` + `last_review_at` set |
| `SessionNode.activity_type` | `"first_exposure"` | `"srs_review"` |
| Rendered by | `get_first_exposure_keyboard` | `get_review_keyboard` |
| Button semantics | **familiarity** (no recall attempt) | **recall** (self-test then rate) |
| Buttons (2×2) | 🟥 کاملاً ناآشناام · 🟨 کمی آشناام · 🟩 آشنایی خوب · 🟪 کاملاً بلدمش | ⭕ یادم نیامد · 🟡 به سختی یادم اومد · 🟢 خوب بود · 🟣 خیلی راحت بود |
| `callback_data` | `srs:fe:{grade}:{user_id}:{word_id}` | `srs:{grade}:{user_id}:{word_id}` |
| Grade resolver | `resolve_grade("first_exposure", grade)` | `resolve_grade("srs_review", grade)` |
| Handler | `_handle_first_exposure_grade` (srs_handler.py:149) | `_handle_srs_review` (srs_handler.py:91) |
| Scheduling seed | `initial_stability_first_exposure` / `initial_difficulty` | `update_stability` / `update_difficulty` (FSRS-6) |
| `response_time_ms` | **omitted** (no recall signal) | recorded |
| Post-grade toast | `format_next_review_text(interval_seconds)` | same |
| Advance | `await advance_session(...)` | `await advance_session(...)` |

Both handlers share an identical ownership guard (`user_id == target_user_id`), an identical "expected failure" branch (`not_found` / `wrong_state` → no telemetry, no streak, no advance), and identical streak + toast + `advance_session` tail. The **only** behavioral divergence is the scheduling seed and the response-time telemetry.

**Functional gap (orphaned staged-reveal):** `format_srs_prompt`, `SRS_HIDDEN_INSTRUCTION`, and `SRS_REVEAL_QUESTION` (formatting.py:7-14,136) implement a "hidden → reveal" prompt design, but they are **not referenced by any production handler** (`grep` shows only a plan doc, a network-resilience plan, and a test). In production, session cards render the **full** card immediately via `format_card` — there is no hidden/recall gate in the live UX. This is dead/aspirational UI text that contradicts the real flow.

---

## 3. UI Comparison — Session Card vs Ask-a-Word Card

### 3.1 Text structure

```
┌─────────────────────────────────────────┐   ┌─────────────────────────────────────────┐
│ SESSION CARD (study_handler)             │   │ ASK-A-WORD CARD (bot.py ask-word)       │
├─────────────────────────────────────────┤   ├─────────────────────────────────────────┤
│ *WORD*                                   │   │ *WORD*                                   │
│ `/ipa/`                                  │   │ `/ipa/`                                  │
│ ✤ *fa_meaning*                           │   │ ✤ *fa_meaning*                           │
│ fa_explanation                           │   │ fa_explanation                           │
│ 🟢 مترادف: …                             │   │ 🟢 مترادف: …                             │
│ 🔴 متضاد: …                              │   │ 🔴 متضاد: …                              │
│ 📝 مثال‌ها + ترجمه: …            │   │ 📝 مثال‌ها + ترجمه: …            │
│ ✍️ نکته‌ی گرامری: …               │   │ ✍️ نکته‌ی گرامری: …               │
│ ─────────────────────────────────────── │   │ ─────────────────────────────────────── │
│ نشست N | کارت n از m        (footer)     │   │ 📊 استفاده امروز: x/limit · باقی‌مانده: y│
│                                         │   │ برای افزودن این واژه به مرور، …         │
└─────────────────────────────────────────┘   └─────────────────────────────────────────┘
   Same body renderer: format_card()              Same body renderer: format_card()
   presentation = detailed (forced)               presentation = _user_presentation(row)
```

### 3.2 Inline keyboards

```
SESSION — First-Exposure:                 SESSION — Review:
[🟥 کاملاً ناآشناام][🟨 کمی آشناام]      [⭕ یادم نیامد][🟡 به سختی یادم اومد]
[🟩 آشنایی خوب][🟪 کاملاً بلدمش]          [🟢 خوب بود][🟣 خیلی راحت بود]
([🔊 تلفظ]  optional, show_pronounce)     ([🔊 تلفظ]  optional, show_pronounce)

ASK-A-WORD:
[ ذخیره در جعبه مرور (Lang) ]   ← toggle save / remove
([✦ ترجمه مثال‌ها]  if show_translations)
([🔊 تلفظ]  if show_pronounce)
```

### 3.3 Inconsistencies & redundancies found

1. **Presentation preference ignored in session cards.** Ask-a-Word honors `_user_presentation(row)` (brief/detailed user choice); session cards **always** render `detailed` (study_handler.py:270, `format_card(..., presentation defaults to "detailed")`). A user who chose "خلاصه" sees a long card in study but a short card when asking — inconsistent.

2. **No shared "save to review" affordance, by design — but asymmetric.** Session cards are saved words already, so no save button. Ask-a-Word cards need the toggle. This is *correct* asymmetry, but the **footer** is the only place the two diverge in tone (progress vs usage hint) — acceptable, though the progress footer re-states info already implied by the card sequence.

3. **Translations toggle parity.** Ask-a-Word exposes `✦ ترجمه مثال‌ها` (re-run prep). Session cards never set `translations_prepared`, so example translations (if present in `card_data`) are **always inline** with no toggle. Mixed model: one flow has a toggle, the other has none. Minor redundancy/confusion risk.

4. **Orphaned staged-reveal UI** (`format_srs_prompt`, `SRS_HIDDEN_INSTRUCTION`, `SRS_REVEAL_QUESTION`) is dead in production (see §2). It implies a "hide meaning → self-test → reveal" loop that does not exist in the live session UX. Either implement it or remove it to avoid misleading future work.

5. **Pronounce row parity is good** — both flows use `db.should_show_pronounce` and `IBTN_PRONOUNCE` with the same `tts:pronounce:…` prefix; consistent.

6. **Card body identical** — both use `format_card` with the same field order, escaping, and icons. Good consistency on the content layer; the divergence is purely in *presentation mode*, *footer*, and *action buttons*.

---

## 4. The Language Leakage Bug (Rule 2) — root cause location

**Symptom:** A learner studying language **A** can receive session cards for words saved in language **B** (and vice-versa). The study session is not scoped to the user's active `target_language`.

**Where the queue is built — `services/session/assembly.py:46,61`:**
```python
due = due_words_for_user(user_id)              # no lang passed
fe   = get_pre_first_exposure_words(user_id)   # no lang passed
```
The `target_lang` parameter is received by `build_session_list` (assembly.py:25) and even copied into `activity_meta`, but it is **never used to filter the DB query**.

**Where the queries run — `services/db/words.py`:**
```python
def due_words_for_user(user_id):                 # words.py:219
    rows = conn.execute(
        "SELECT * FROM saved_words WHERE user_id=? "
        "AND COALESCE(first_exposure_done,0)=1 "
        "AND COALESCE(review_status,'idle')!='pending' "
        "AND retry_at IS NULL ", (user_id,)).fetchall()
    # ← no "AND lang=?" clause

def get_pre_first_exposure_words(user_id):       # words.py:261
    return conn.execute(
        "SELECT * FROM saved_words WHERE user_id=? AND first_exposure_done=0 "
        "ORDER BY ...", (user_id,)).fetchall()
    # ← no "AND lang=?" clause
```
The `saved_words` table **does** carry a `lang` column (schema.py:162), and `add_saved_word`/`toggle_review_word` populate it. The unique key is `(user_id, lang, normalized_word)` (schema.py:380). So a multilingual user has rows in several `lang` values, and the session queue pulls **all of them**.

**Why it's a real leak (not just cosmetic):** the rendered card's `word`/`fa_meaning` come from `card_data`, which is language-agnostic storage. A French learner who also dabbles in Spanish would get a Spanish card mid-French-session, breaking the study context and polluting FSRS scheduling per language.

**Fixed (2026-08-13, commit `a3c541d`, direct to `main`):** threaded `target_lang` into both queue builders and both DB functions:
- `due_words_for_user(user_id, lang=None)` — appends `AND lang=?` when a language is given; `None` keeps legacy all-language behavior for existing callers/tests.
- `get_pre_first_exposure_words(user_id, lang=None)` — same optional filter.
- `build_session_list` (assembly.py:46,61) now passes its already-received `target_lang` into both calls.
- `handlers/user.py` status "due count" scoped to `row["target_lang"]` for consistency.
- Added `tests/test_reliability.py::test_session_queue_filters_by_language` covering Tier 1 + Tier 2 filtering and the legacy no-lang path.

**Behavior decision (chosen):** a missing `target_lang`/`lang` keeps the **legacy all-language** behavior rather than returning no rows. This preserves existing callers (status, tests, any internal use) and avoids a silent empty-session regression; the session entry point (`build_session_list`) always supplies the active `target_lang`, so live sessions are correctly scoped.

---

## 5. Audit verdict

- **Data flow & escaping:** sound; both cards route dynamic text through the centralized `escape_mdv2` chokepoint. No MarkdownV2 injection risk found.
- **State machine:** clear and consistent between First-Exposure and Review at the handler/scheduling layer; only divergence is scheduling seed + response-time telemetry (intentional).
- **UI consistency:** one real inconsistency (session cards ignore the user's brief/detailed preference) plus one dead/orphaned UI module (staged reveal). Buttons are otherwise well-differentiated and consistent.
- **Language leakage:** confirmed root cause in `services/session/assembly.py` (call sites) + `services/db/words.py` (queries) — both SRS queue builders omitted the `lang` filter. **Fixed in commit `a3c541d`** (see §4).

*No production files were modified during the audit phase itself; the fix was implemented afterwards (commit `a3c541d`).*

---

## Reconciliation (2026-08-13)

- **Language leakage (Rule 2)** — **Resolved.** The audit's proposed fix direction was implemented and verified: both queue builders now pass `target_lang`, both DB functions accept an optional `lang` filter, and a focused test proves Tier 1 + Tier 2 are scoped to the active language while the legacy no-arg path is preserved. Full suite green (848 passed + 153 subtests); ruff `F821/F811` clean; `git diff --check` clean. Committed directly to `main` as `a3c541d` (no PR, per owner instruction).
- **UI inconsistencies (Rule 1)** — **Open / not in this scope.** Two findings remain unaddressed and are recorded here for a future, separately-scoped UX change: (a) session cards ignore the user's brief/detailed `presentation` preference (always render `detailed`), and (b) the orphaned staged-reveal UI (`format_srs_prompt`/`SRS_HIDDEN_INSTRUCTION`/`SRS_REVEAL_QUESTION`) is dead in production. Neither is a correctness bug and neither relates to the language leak, so they are deliberately deferred rather than bundled into this fix.
- **No MarkdownV2 injection risk** — confirmed; both paths route all dynamic values through the centralized `escape_mdv2`/`escape_mdv2_code`. No action required.
