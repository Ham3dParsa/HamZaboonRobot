# AUDIT: SRS Reminder Message Lacks Complete Card Data

**Audit Date:** 2026-07-12  
**Scope:** `db.py` (saved_words table), `bot.py` (srs_job, ask_for_add_word), `keyboards.py` (missing SRS interaction buttons)

---

## Executive Summary

Users receive SRS (spaced repetition) reminders that display **only word names**, without any accompanying flashcard data:

```
⏰ Time to review 1 word:

• Singularity

Try to remember the meaning, then check.
```

### Critical Gaps

1. **No complete flashcard displayed** – Definition, synonyms, antonyms, examples, pronunciation are absent.
2. **No interactive buttons** – User cannot click to view or interact with the word.
3. **Notification without utility** – Message asks user to recall but offers no learning aid.
4. **Architecture mismatch** – Contradicts the design pattern used successfully in `daily_cards`.

---

## Detailed Analysis

### 1. Database Schema for `saved_words`

**File:** [db.py](db.py#L80-L90)

```sql
CREATE TABLE IF NOT EXISTS saved_words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    word TEXT,
    lang TEXT,
    normalized_word TEXT,
    interval_idx INTEGER DEFAULT 0,
    next_review TEXT,
    added_at TEXT
);
```

**Current Storage:**
- Word name only
- Language code
- SRS metadata (interval_idx, next_review)

**Missing Data:**
- ❌ Definition / meaning (Persian translation)
- ❌ Pronunciation / phonetic guide
- ❌ Synonyms
- ❌ Antonyms
- ❌ Example sentences
- ❌ Grammar tips
- ❌ Example translations

### Comparison with `daily_cards` Schema

```sql
CREATE TABLE IF NOT EXISTS daily_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    card_date TEXT,
    card_index INTEGER,
    card_data TEXT,  -- ✅ Stores complete flashcard as JSON
    UNIQUE(user_id, card_date, card_index)
);
```

**Key Difference:**
- `daily_cards` stores **complete flashcard data as JSON**
- `saved_words` stores **only the word name**

---

### 2. Word Addition Flow

**File:** [bot.py](bot.py#L383-L387), [bot.py](bot.py#L475-L478)

#### Step 1: Request word from user

```python
async def ask_for_add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting"] = "add_word"
    await update.message.reply_text("Send a word you want to remember:")
```

#### Step 2: Save word (insufficient)

```python
if awaiting == "add_word":
    row = db.get_user(user_id)
    db.add_saved_word(user_id, text, row["target_lang"] if row else "en")
    await update.message.reply_text(f"Word '{text}' saved; I'll remind you later. ✅")
    return
```

**Problems:**
- User provides only **word name**, not full context
- **No AI-generated flashcard** is created and stored
- System has no reference data to display later

---

### 3. Incomplete SRS Job Implementation

**File:** [bot.py](bot.py#L613-L632)

```python
async def srs_job(context: ContextTypes.DEFAULT_TYPE):
    """Send reminders for words due for spaced repetition review."""
    for row in db.all_active_users():
        user_id = row["user_id"]
        try:
            due = db.due_words_for_user(user_id)
            if not due:
                continue
            words = "\n".join(f"• {escape_mdv2(w['word'])}" for w in due)
            text = (
                f"⏰ *Time to review {len(due)} word(s):*\n\n{words}\n\n"
                "Try to remember the meaning, then check\\."
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            for w in due:
                db.advance_word_review(w["id"])
        except Exception:
            log.exception(f"srs_job failed for user {user_id}")
```

**Critical Issues:**

1. ❌ **Word names only** – No complete flashcard rendering
2. ❌ **No reply markup** – No inline buttons for interaction
3. ❌ **No AI card generation** – System doesn't fetch/create flashcard details
4. ❌ **Poor learning utility** – User cannot see definitions, examples, or context
5. ❌ **Premature advance** – `advance_word_review` is called immediately after sending, regardless of user engagement

---

### 4. Missing SRS Interaction Buttons

**File:** [keyboards.py](keyboards.py#L1-L60)

Available buttons:
```python
BTN_TODAY_CARD = "🃏 Daily Flashcard"
BTN_ASK_WORD = "❓ Ask a Word"
BTN_STATUS = "📊 My Status"
BTN_GRAMMAR = "✍️ Grammar Tip"
```

**Gap:** After receiving an SRS reminder, the user has **no button** to:
- View the complete word card
- Mark as understood
- Request more details
- Defer the review

---

### 5. Architecture Inconsistency

**Design Pattern Mismatch:**

| Feature | daily_cards | saved_words | Alignment |
|---------|-------------|-------------|-----------|
| Store word name | ✅ (in JSON) | ✅ | ✓ Consistent |
| Store complete flashcard | ✅ (JSON) | ❌ | **✗ Inconsistent** |
| Generate via AI before storage | ✅ (required) | ❌ | **✗ Inconsistent** |
| Display complete card to user | ✅ (format_card) | ❌ | **✗ Inconsistent** |
| Provide interactive buttons | ✅ | ❌ | **✗ Inconsistent** |
| Use format_card utility | ✅ | ❌ | **✗ Inconsistent** |

---

## User Experience Impact

### Problems for the Learner

| Issue | Consequence |
|-------|-------------|
| Word name only | No context; impossible to understand what "Singularity" means |
| No buttons | No way to request help or view details |
| No definitions | Defeats the purpose of a reminder system |
| No examples | Word remains abstract and disconnected |
| No pronunciation guide | Cannot verify correct pronunciation |

### Result
The SRS system becomes a **notification service, not a learning tool**.

---

## Technical Impact

### Architecture Problems

| Problem | Risk |
|---------|------|
| Two different storage patterns for similar data | Confusion during maintenance and feature extensions |
| Duplication of word storage across `saved_words` and potential manual entries | Potential data consistency issues |
| Inability to reuse `format_card` for SRS | Code duplication; missed opportunity for consistency |
| No card data means queries need re-generation or external calls | Unnecessary API calls and latency |

### Operational Costs

- **Scenario 1 (Current):** User forgets word → sends "Tell me about this word" → AI called (cost)
- **Scenario 2 (Proposed):** Flashcard pre-generated and stored during word addition → Immediate display with no extra cost

---

## Root Cause

The `saved_words` feature was implemented as a **simple persistence layer** (just store the word name and SRS metadata), without considering that users would eventually need to **review the full card content**. 

The design pattern established in `daily_cards` (AI generation + complete JSON storage) was not applied to `saved_words`.

---

## Evidence from Code

### `add_saved_word` function

[db.py](db.py#L706-L719)

```python
def add_saved_word(user_id: int, word: str, lang: str = "en") -> bool:
    normalized_word = _normalize_word(word)
    word = " ".join(word.split())
    next_review = (_today() + datetime.timedelta(days=INTERVALS_DAYS[0])).isoformat()
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO saved_words("
            "user_id, word, lang, normalized_word, interval_idx, next_review, added_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (user_id, word, lang, normalized_word, next_review, _utc_now().isoformat()),
        )
        conn.commit()
        return cursor.rowcount == 1
```

**Analysis:** Only inserts word metadata. No card data. No AI call.

---

### `due_words_for_user` function

[db.py](db.py#L723-L728)

```python
def due_words_for_user(user_id: int):
    today = _today().isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM saved_words WHERE user_id=? AND next_review<=?", (user_id, today)
        ).fetchall()
```

**Analysis:** Retrieves all columns, including `word`, `id`, but lacks the `card_data` column entirely.

---

### `format_card` utility function exists

[bot.py](bot.py#L73-L99)

```python
def format_card(data: dict, footer: str = "") -> str:
    """Formats a complete flashcard using MarkdownV2 for Telegram."""
    word = escape_mdv2(data.get("word", ""))
    phon = escape_mdv2(data.get("phonetic", ""))
    fa_meaning = escape_mdv2(data.get("fa_meaning", ""))
    # ... renders definition, synonyms, antonyms, examples, grammar tips
    return "\n".join(lines)
```

**Observation:** This utility is **not used for SRS** because card data is unavailable.

---

## Proposed Two-Phase Solution

### Phase 1: Extend Database Schema

**Add column to `saved_words`:**

```python
# In db.init_db():
ALTER TABLE saved_words ADD COLUMN card_data TEXT;
```

**Rationale:** Store complete flashcard as JSON, matching `daily_cards` pattern.

---

### Phase 2A: Modify Word Addition

**New function in `db.py`:**

```python
def add_saved_word_with_card(user_id: int, word: str, lang: str, card_data: dict) -> bool:
    """Add a saved word along with its complete flashcard data."""
    normalized_word = _normalize_word(word)
    word = " ".join(word.split())
    next_review = (_today() + datetime.timedelta(days=INTERVALS_DAYS[0])).isoformat()
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO saved_words("
            "user_id, word, lang, normalized_word, interval_idx, next_review, added_at, card_data) "
            "VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
            (user_id, word, lang, normalized_word, next_review, _utc_now().isoformat(), json.dumps(card_data)),
        )
        conn.commit()
        return cursor.rowcount == 1
```

**Updated flow in `bot.py`:**

```python
if awaiting == "add_word":
    row = db.get_user(user_id)
    await update.message.chat.send_action("typing")
    
    try:
        card_data = ai.ask_card(
            prompts.custom_word_system_prompt(row["target_lang"], row["level"]),
            user_prompt=text,
        )
    except Exception:
        log.exception("AI error during word addition")
        await update.message.reply_text("Error generating flashcard. Try again.")
        return
    
    db.add_saved_word_with_card(user_id, text, row["target_lang"], card_data)
    await update.message.reply_text(
        f"Word '{text}' saved with complete details. I'll remind you at the right time. ✅"
    )
```

---

### Phase 2B: Enhance SRS Job

**Updated `srs_job` in `bot.py`:**

```python
async def srs_job(context: ContextTypes.DEFAULT_TYPE):
    """Send complete flashcards for words due for spaced repetition review."""
    for row in db.all_active_users():
        user_id = row["user_id"]
        try:
            due = db.due_words_for_user(user_id)
            if not due:
                continue
            
            for word_row in due:
                card_data = {}
                if word_row["card_data"]:
                    try:
                        card_data = json.loads(word_row["card_data"])
                    except json.JSONDecodeError:
                        log.warning(f"Invalid card_data for word {word_row['id']}")
                
                # Send complete flashcard
                await context.bot.send_message(
                    chat_id=user_id,
                    text=format_card(card_data),
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=srs_word_keyboard(word_row["id"]),
                )
                
                # Small delay between messages
                await asyncio.sleep(0.5)
        
        except Exception:
            log.exception(f"srs_job failed for user {user_id}")
```

---

### Phase 2C: Add SRS Interaction Buttons

**New function in `keyboards.py`:**

```python
def srs_word_keyboard(word_id: int) -> InlineKeyboardMarkup:
    """Buttons for SRS word review interaction."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Got it", callback_data=f"srs:advance:{word_id}"),
            InlineKeyboardButton("🔄 Review later", callback_data=f"srs:defer:{word_id}"),
        ]
    ])
```

**New callback handlers in `bot.py`:**

```python
async def srs_advance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, word_id: str):
    """User confirms understanding; advance to next interval."""
    user_id = update.effective_user.id
    db.advance_word_review(int(word_id))
    await update.callback_query.answer("Great! Next review is scheduled.")

async def srs_defer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, word_id: str):
    """User defers review; push to tomorrow."""
    user_id = update.effective_user.id
    db.defer_word_review(int(word_id))  # New function to set next_review to tomorrow
    await update.callback_query.answer("Deferred. You'll see it tomorrow.")
```

---

## Roadmap Alignment

### ROADMAP.md References

The ROADMAP section on custom-word query improvements states:

> "Custom-word query improvements: daily quota visibility, persistent short-lived query identity, inline Add to review, and removal of the separate manual-save action from the primary menu."

**Observation:** This phase focused on **query-based word discovery**, not **saved-word review**. The SRS system for saved words was treated as a separate, simpler feature and lacks the same level of polish.

---

## Risk Classification

| Issue | Severity | Confidence | Category |
|-------|----------|------------|----------|
| No card data in SRS reminder | **High** | **High** | UX / Learning effectiveness |
| No buttons for user interaction | **High** | **High** | UX / Usability |
| Architecture inconsistency | **Medium** | **High** | Technical debt / Maintainability |
| Wasted AI card generation | **Low** | **Medium** | Operational cost |

---

## Status Summary

| Aspect | Status |
|--------|--------|
| Problem identification | ✅ Confirmed |
| Root cause | ✅ Clear (schema gap + missing AI call) |
| Solution design | ✅ Defined (two-phase approach) |
| Implementation | ⏳ Pending |
| Testing | ⏳ Pending |
| Deployment | ⏳ Pending |

---

## References

- **saved_words schema:** [db.py](db.py#L80-L90)
- **add_saved_word function:** [db.py](db.py#L706-L719)
- **due_words_for_user function:** [db.py](db.py#L723-L728)
- **advance_word_review function:** [db.py](db.py#L731-L740)
- **Word addition flow:** [bot.py](bot.py#L383-L387), [bot.py](bot.py#L475-L478)
- **SRS job:** [bot.py](bot.py#L613-L632)
- **format_card utility:** [bot.py](bot.py#L73-L99)
- **daily_cards schema (reference):** [db.py](db.py#L100-L110)
- **ROADMAP custom-word section:** [ROADMAP.md](ROADMAP.md) (Custom-word query improvements)

---

## Conclusion

**Finding:** The SRS reminder system for saved words is **incomplete**. It notifies the user but provides no learning context or interaction options. This violates the architecture pattern established in the daily-cards feature.

**Recommendation:** Implement the two-phase solution to align `saved_words` with the `daily_cards` design pattern, enabling complete flashcard display and user interaction in SRS reminders.

**Impact:** This change will transform SRS from a bare notification system into a functional learning tool that matches the quality and utility of on-demand flashcard requests.
