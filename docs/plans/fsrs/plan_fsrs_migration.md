# FSRS-6 Session Engine Migration Plan

**Status:** Phase 1 — Core Engine Ready (v5.4 validated, bot ready for implementation)
**Target bot version:** After this plan, the bot uses FSRS-6 for all scheduling
**References:**
- `docs/FSRS_v6.md` — Complete FSRS-6 algorithm reference
- `tools/Fsrs_simulation_v5/v5.4_FSRS_full.py` — Validated FSRS-6 simulation (566 lines)
- `tools/Fsrs_simulation_v5/archive/fsrs_simulator_v1.1.html` — Standalone HTML/JS FSRS-6 simulator dashboard (1755 lines, interactive Chart.js UI, potential foundation for future Telegram Mini App or WebApp)
- `config/keyboards.py` — Current Telegram keyboard definitions
- `handlers/srs_handler.py` — Current SRS review handler
- `services/db/__init__.py` — Database functions
- `services/srs_engine.py` — Existing scaffold (to be rewritten)
- `handlers/study_handler.py` — Existing scaffold (to be rewritten)
- `services/scheduling.py` — Does not exist yet (to be created)

---

## Table of Contents

- [Implementation Tracking State](#implementation-tracking-state)
0. [Architecture Overview](#0-architecture-overview)
   - [1.4 Grade Policy Framework](#14-grade-policy-framework)
1. [Phase 1a — Core FSRS Engine (`services/fsrs_core.py`)](#1-phase-1a--core-fsrs-engine)
2. [Phase 1b — Database Migration (`services/db/__init__.py`)](#2-phase-1b--database-migration)
3. [Phase 1c — 4-Button UI (`config/keyboards.py` + `handlers/srs_handler.py`)](#3-phase-1c--4-button-ui)
4. [Phase 1d — Study Session Engine (`services/srs_engine.py` + `handlers/study_handler.py`)](#4-phase-1d--study-session-engine)
5. [Phase 1e — Session Scheduling (`services/scheduling.py`)](#5-phase-1e--session-scheduling)
6. [Phase 1f — bot.py callback updates](#6-phase-1f--botpy-callback-updates)
7. [Phase 2 — Data Collection & Monitoring](#7-phase-2--data-collection--monitoring)
8. [Phase 3 — Parameter Optimization](#8-phase-3--parameter-optimization)
9. [Phase 4 — AI-Enhanced Session Types](#9-phase-4--ai-enhanced-session-types)
10. [Simulation vs Bot: Gaps & Confidence](#10-simulation-vs-bot-gaps--confidence)
11. [Rollback Plan](#11-rollback-plan)

---

## Implementation Tracking State

| # | Phase | Status | Started | Completed | Notes |
|---|---|---|---|---|---|
| 1a | Core FSRS Engine (`services/fsrs_core.py`) | ✅ DONE | 2026-07-28 | 2026-07-28 | 80 lines, 31 unit tests |
| 1b | DB Schema Migration + Functions (`services/db/__init__.py`) | ⏳ PENDING | — | — | |
| 1c | 4-Button UI (`config/keyboards.py` + `handlers/srs_handler.py`) | ⏳ PENDING | — | — | |
| 1d | Study Session Engine (`services/srs_engine.py` + `handlers/study_handler.py`) | ⏳ PENDING | — | — | |
| 1e | Session Scheduling (`services/scheduling.py`) | ⏳ PENDING | — | — | |
| 1f | bot.py Integration (`bot.py`) | ⏳ PENDING | — | — | |
| 2 | Data Collection & Monitoring | 🔮 FUTURE | — | — | Needs 1000+ review events |
| 3 | Parameter Optimization (w₀-w₂₀ fitting) | 🔮 FUTURE | — | — | Needs Phase 2 data |
| 4 | AI-Enhanced Session Types (quiz, sentence, etc.) | 🔮 FUTURE | — | — | Design finalized in §10 |

**Legend:** ✅ Done / ⏳ Pending / 🔮 Future Phase

---

## 0. Architecture Overview

### 0.1 Target State

```
User presses "📚 شروع مطالعه امروز"
  → handle_study_start()
    → generate_v3_session() [srs_engine.py]
      → Tier 1: due SRS words (ordered by lowest retrievability)
      → Tier 2: pre-first-exposure saved_words
      → Tier 3: new AI cards (if slots remain)
    → Present first node to user
    → User grades → FSRS updates stability/difficulty → next node

User opens SRS review directly
  → start_srs_review()
    → due_words_for_user() (same tier-1 subset)
    → FSRS 4-button grading (Again/Hard/Good/Easy)

User saves a word from query
  → add_saved_word() with stability=0, first_exposure_done=0
  → Word appears in Tier 2 of next session
  → First exposure grading sets initial stability/difficulty
```

### 0.2 Data Flow

```
Query word saved
  → saved_words: stability=0, difficulty=null, first_exposure_done=0, next_review=null
  
First session/encounter
  → User presses grade (1/2/3/4)
  → fsrs_core.initial_stability(grade) → stability
  → fsrs_core.initial_difficulty(grade) → difficulty
  → fsrs_core.compute_interval(stability, DR) → next_review
  → first_exposure_done=1

Subsequent reviews
  → User presses grade (1/2/3/4)
  → r = fsrs_core.compute_retrievability(elapsed, stability)
  → new_d = fsrs_core.update_difficulty(difficulty, grade)
  → new_s = fsrs_core.update_stability(difficulty, stability, r, grade)
  → next_review = fsrs_core.compute_interval(new_s, DR)
  
Every review event → review_events table (for future parameter fitting)
```

### 0.3 Key Decisions (Locked)

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Short-term formula | Included in `fsrs_core.py`, gated `enable_short_term=False` | Ready for future same-day reviews, no behavioral change today |
| 2 | Desired retention default | 0.9 (FSRS-6 standard) | Matches algorithm design: interval=S when r=0.9 |
| 3 | Grade labels | 4-button: Again(1), Hard(2), Good(3), Easy(4) | Full FSRS-6 compatibility, enables w16 bonus and complete failure modeling |
| 4 | First exposure | Separate labels + separate stability weights | Familiarity question != recall question; see Decisions 11, 12 |
| 5 | Easy grade | Included in UI as "Easy" button | Unlocks w16 easy bonus (1.87× stability growth); better data for future fitting |
| 6 | Session priority | Tier 1 (due) → Tier 2 (pre-first-exposure) → Tier 3 (new AI) | Matches simulation, user confirmed |
| 7 | Plan defaults | Keep existing bot plan quotas; simulation PLAN_DEFAULTS for reference | Bot config is source of truth |
| 8 | Quiz fail → FSRS grade | Quiz incorrect → grade 1 (Again) | Same failure formula as direct "یادم نیامد" |
| 9 | AI judgment → FSRS grade | AI maps directly to 1-4 | No intermediate score conversion layer |
| 10 | Interactive flow persistence | `context.user_data['current_flow']` during flow, cleaned after `resolve_grade()` | Intermediate state survives Telegram API roundtrips |
| 11 | First-exposure button labels | Familiarity-based: کاملاً ناآشنا / کمی آشنا / آشنایی خوب / کاملاً بلدمش | Different from review labels (یادم نیامد / سخت بود / خوب بود / خیلی راحت بود); user evaluates pre-existing knowledge, not recall success |
| 12 | First-exposure stability weights | `FIRST_EXPOSURE_STABILITY = {1: 0.212, 2: 1.5, 3: 3.0, 4: 12.0}` | Mild adjustment of standard w0-w3 — familiarity-based grading gives more credit for partial/complete knowledge; agreed via simulation |

### 0.4 Grade Policy Framework

All user interactions in the bot eventually produce an **FSRS grade (1-4)**, but the *way* a grade is determined differs by activity type. This framework ensures future interactive flows (quiz, sentence writing, etc.) can feed into FSRS without changing the core engine.

```python
# services/srs_engine.py — GradePolicy registry
from dataclasses import dataclass
from typing import Literal

@dataclass
class GradePolicy:
    activity_type: str
    grade_source: Literal["direct_button", "right_wrong", "ai_judgment"]
    grade_mapping: dict      # {source_value: fsrs_grade}
    description: str

GRADE_POLICIES: dict[str, GradePolicy] = {
    "srs_review": GradePolicy(
        "srs_review", "direct_button",
        {1: 1, 2: 2, 3: 3, 4: 4},
        "User presses grade directly from keyboard"
    ),
    "first_exposure": GradePolicy(
        "first_exposure", "direct_button",
        {1: 1, 2: 2, 3: 3, 4: 4},
        "User presses grade on first encounter with word"
    ),
    "new_ai_card": GradePolicy(
        "new_ai_card", "direct_button",
        {1: 1, 2: 2, 3: 3, 4: 4},
        "User presses grade on first encounter with AI card"
    ),
    "ai_quiz": GradePolicy(
        "ai_quiz", "right_wrong",
        {"correct": 3, "incorrect": 1},
        "MC quiz: correct→Good, incorrect→Again"
    ),
    "sentence_write": GradePolicy(
        "sentence_write", "ai_judgment",
        {"again": 1, "hard": 2, "good": 3, "easy": 4},
        "AI evaluates sentence quality, assigns grade directly"
    ),
}

def resolve_grade(activity_type: str, source_value) -> int:
    """Convert any activity's interaction result to an FSRS grade (1-4)."""
    policy = GRADE_POLICIES[activity_type]
    return policy.grade_mapping[source_value]
```

**Key principle:** Every activity type must have:
1. A `GradePolicy` entry in `GRADE_POLICIES`
2. An entry in `ACTIVITY_REGISTRY` (how to render it)
3. A test verifying both registries are in sync

This makes it safe to add new interactive flows (quizzes, sentence writing, etc.) in Phase 4 without changing the FSRS engine, the DB schema, or existing handlers.

#### 1.4.1 Interaction flow model

```
Simple (Phase 1):          Interactive (Phase 4):
  Card → buttons              Card → interactive flow → resolve_grade()
  grade = button value        grade = GRADE_POLICIES[type][source]
  ↓                           ↓
  grade_word_review(grade)    grade_word_review(grade)
  ↓                           ↓
  next_node                   next_node
```

Interactive flows can span multiple messages (e.g., quiz: question → user answer → AI judgment → grade → next). The intermediate state lives in `context.user_data['current_flow']` during the flow, and is cleaned up after `resolve_grade()`.

---

## 1. Phase 1a — Core FSRS Engine

**New file:** `services/fsrs_core.py`
**Size estimate:** ~110 lines
**Dependency:** None (pure math + constants)

### 1.1 Constants (from FSRS_v6.md)

```python
# Full FSRS-6 parameters (w0-w20)
DSR_W = {
    "w0": 0.212, "w1": 1.2931, "w2": 2.3065, "w3": 8.2956,
    "w4": 6.4133, "w5": 0.8334, "w6": 3.0194, "w7": 0.001,
    "w8": 1.8722, "w9": 0.1666, "w10": 0.796, "w11": 1.4835,
    "w12": 0.0614, "w13": 0.2629, "w14": 1.6483, "w15": 0.6014,
    "w16": 1.8729, "w17": 0.5425, "w18": 0.0912, "w19": 0.0658,
    "w20": 0.1542,
}

# Derived
DSR_FACTOR = 0.9 ** (-1.0 / DSR_W["w20"]) - 1.0
DESIRED_RETENTION_DEFAULT = 0.9

# First-exposure constants (familiarity-based grading, not recall)
# G=1,2,3,4 map to: کاملاً ناآشنا, کمی آشنا, آشنایی خوب, کاملاً بلدمش
FIRST_EXPOSURE_STABILITY = {1: 0.212, 2: 1.5, 3: 3.0, 4: 12.0}
```

### 1.2 Function Signatures

```python
def compute_retrievability(elapsed_days: float, stability: float) -> float
    """R = (1 + DSR_FACTOR * t/S) ^ (-w20)  — §2.1"""

def compute_interval(stability: float, desired_retention: float = 0.9) -> float
    """I = S/DSR_FACTOR * (r^(-1/w20) - 1)  — §2.8"""

def initial_stability(grade: int, *, first_exposure: bool = False) -> float
    """S0(G) — §2.2; grade in {1,2,3,4}
    If first_exposure=True, uses FIRST_EXPOSURE_STABILITY[grade]
    (familiarity-based: کاملاً ناآشنا→0.212, کمی آشنا→1.5, آشنایی خوب→3.0, کاملاً بلدمش→12.0)
    Otherwise uses standard DSR_W[w_{G-1}] (recall-based).
    """

def initial_difficulty(grade: int) -> float
    """D0(G) = w4 - exp(w5 * (G-1)) + 1  — §2.3"""

def update_difficulty(d: float, grade: int) -> float
    """Mean reversion toward D0(4) (Easy) — §2.7"""

def update_stability(d: float, s: float, r: float, grade: int) -> float
    """Success (§2.4) if grade>=2, failure (§2.5) if grade=1"""

def short_term_stability(s: float, grade: int) -> float
    """Same-day review stability — §2.6 (gated)"""
```

### 1.3 Implementation Notes

- All functions are **pure** (no DB, no async, no side effects)
- `initial_stability(grade)` accepts `{1: w0, 2: w1, 3: w2, 4: w3}` (full 4-grade FSRS-6)
- `initial_stability(grade, first_exposure=True)` uses `FIRST_EXPOSURE_STABILITY` dict instead (familiarity-based: 0.212/1.5/3.0/12.0)
- `initial_difficulty(grade)` uses same D0 formula with `G-1` offset (same for both first-exposure and review)
- `update_difficulty`: mean reverts toward `D0(4)` (Easy) per FSRS-6 §2.7
- `update_stability`: for grade=1 uses failure formula with `min(s_new, s)` guard; for grade>=2 uses success formula with hard_penalty (w15) for grade=2, easy_bonus (w16) for grade=4

### 1.4 Validation

```python
# Test: same as v5.4 simulation seed=42
cfg = SimConfig(plan="silver", persona="average", days=180, seed=42)
rows, s = simulate(cfg)
```

---

## 2. Phase 1b — Database Migration

**File:** `services/db/__init__.py`
**Changes:** Schema + 3 DB functions

### 2.1 Schema Change

```sql
-- Current:
--   interval_idx INTEGER DEFAULT 0
--   next_review TEXT

-- New columns added:
ALTER TABLE saved_words ADD COLUMN stability REAL DEFAULT 1.0;
ALTER TABLE saved_words ADD COLUMN difficulty REAL DEFAULT 5.0;
ALTER TABLE saved_words ADD COLUMN first_exposure_done INTEGER DEFAULT 0;
-- interval_idx kept for rollback safety, then dropped after migration verified
```

### 2.2 Migration Function

```python
def migrate_saved_words_to_fsrs():
    """One-time migration: map interval_idx → approximate stability."""
    STABILITY_MAP = {0: 1.0, 1: 3.0, 2: 7.0, 3: 16.0, 4: 30.0}
    # Set stability = STABILITY_MAP.get(interval_idx, 1.0)
    # Set difficulty = 5.0 (neutral)
    # Set first_exposure_done = 1 (existing words have been reviewed)
    # Run in init_db() if column 'stability' doesn't exist yet
```

Called in `init_db()` after `CREATE TABLE IF NOT EXISTS`.

### 2.3 Changed Functions

#### `add_saved_word()` — Rewrite

```python
def add_saved_word(user_id, word, lang, card_data=None) -> bool:
    """Save word with FSRS initial state (ungraded)."""
    # Same INSERT logic but:
    # - stability = 0.0 (sentinel: not yet graded)
    # - difficulty = 5.0 (neutral default)
    # - first_exposure_done = 0
    # - next_review = NULL (no review until first exposure graded)
    # - review_status = 'idle'
```

#### NEW: `grade_word_review()` — Replaces `advance_word_review` + `defer_word_review`

```python
def grade_word_review(word_id: int, user_id: int, grade: int) -> bool:
    """Apply FSRS grade (1=Again, 2=Hard, 3=Good, 4=Easy) and update scheduling.
    
    If word.first_exposure_done == 0:
        # Uses familiarity-based weights (FIRST_EXPOSURE_STABILITY)
        stability = fsrs_core.initial_stability(grade, first_exposure=True)
        difficulty = fsrs_core.initial_difficulty(grade)
        if grade == 1:
            next_review = today + 1          # Again: force 1-day revisit
        else:
            next_review = today + fsrs_core.compute_interval(stability)
        first_exposure_done = 1
    Else:
        row = get_saved_word(word_id)
        elapsed = today - row.last_review_date
        r = fsrs_core.compute_retrievability(elapsed, row.stability)
        difficulty = fsrs_core.update_difficulty(row.difficulty, grade)
        stability = fsrs_core.update_stability(row.difficulty, row.stability, r, grade)
        next_review = today + fsrs_core.compute_interval(stability)
    
    UPDATE saved_words SET stability=?, difficulty=?, next_review=?, 
           first_exposure_done=1, review_status='idle'
    WHERE id=? AND review_status='pending'
    """
```

```python
def grade_first_exposure(word_id: int, user_id: int, grade: int) -> bool:
    """Convenience wrapper: set initial stability/difficulty from grade.
    
    Called when user grades a word for the first time.
    Uses FIRST_EXPOSURE_STABILITY weights via initial_stability(grade, first_exposure=True).
    Sets first_exposure_done=1, computes next_review from initial stability.
    """
```

#### `due_words_for_user()` — Modified

```python
def due_words_for_user(user_id: int):
    """Return due words ordered by retrievability ascending (lowest first)."""
    # Same grace deadline logic
    # Add ORDER BY retrievability:
    #   Compute R from (today - last_review) / stability
    #   R closest to 0 (most forgotten) first
    # This requires a SQL expression or in-Python sorting
    # Option: fetch all due, sort in Python by compute_retrievability()
```

#### `record_review_event()` — Add `grade` column

```sql
ALTER TABLE review_events ADD COLUMN grade INTEGER;
```

Update function signature:
```python
def record_review_event(
    word_id, user_id, *,
    revealed_before_answer,
    outcome,
    grade=None,
    activity_type='srs_review',   # NEW: identifies interactive flow type
    grade_source='direct_button',  # NEW: how grade was produced
):
```

### 2.4 Destroyed Functions

| Old Function | Status | Replacement |
|---|---|---|
| `INTERVALS_DAYS` | Delete | FSRS formulas |
| `advance_word_review()` | Delete | `grade_word_review(word_id, grade=3)` |
| `defer_word_review()` | Delete | `grade_word_review(word_id, grade=1)` |

---

## 3. Phase 1c — 4-Button UI

### 3.1 New Button Labels (`config/keyboards.py`)

```python
# Replace old SRS labels
IBTN_SRS_AGAIN = "🔴 یادم نیامد"      # Grade 1 — failure formula (w11-w14)
IBTN_SRS_HARD = "🟡 سخت بود"          # Grade 2 — success + w15 hard penalty
IBTN_SRS_GOOD = "🟢 خوب بود"          # Grade 3 — success, normal growth
IBTN_SRS_EASY = "🔵 خیلی راحت بود"    # Grade 4 — success + w16 easy bonus (1.87×)
IBTN_SRS_REVEAL = "👁 افشای کارت"     # Keep
IBTN_SRS_TRANSLATIONS = "✦ ترجمه مثال‌ها"  # Keep

# Delete:
# IBTN_REMEMBERED = "✅ یادم بود"
# IBTN_CONFIRM_CORRECT = "✅ یادم بود"
# IBTN_REMIND_AGAIN = "🔁 بازم یادم بیار"

# --- First-Exposure (familiarity-based, different from review) ---
# Question: "چقدر با محتوای این فلش کارت آشنایی داری؟"
IBTN_FE_AGAIN = "🔴 کاملا ناآشنا اَم"     # Grade 1 — initial_stability(1, first_exposure=True)=0.212
IBTN_FE_HARD = "🟡 کمی آشنا اَم"            # Grade 2 — initial_stability(2, first_exposure=True)=1.5
IBTN_FE_GOOD = "🟢 آشنایی خوب"            # Grade 3 — initial_stability(3, first_exposure=True)=3.0
IBTN_FE_EASY = "🔵 کاملا بلدمش"           # Grade 4 — initial_stability(4, first_exposure=True)=12.0
```

### 3.2 New Keyboard Templates

4 buttons per row: Again/Hard/Good/Easy. Two rows: grade row + action row (reveal/pronounce).

```python
def srs_hidden_keyboard(user_id, word_id, *, show_pronounce=False):
    """Word-only state: 4 grade buttons + reveal + pronounce."""
    rows = [
        [
            InlineKeyboardButton(IBTN_SRS_AGAIN, callback_data=f"srs:1:{user_id}:{word_id}"),
            InlineKeyboardButton(IBTN_SRS_HARD, callback_data=f"srs:2:{user_id}:{word_id}"),
            InlineKeyboardButton(IBTN_SRS_GOOD, callback_data=f"srs:3:{user_id}:{word_id}"),
            InlineKeyboardButton(IBTN_SRS_EASY, callback_data=f"srs:4:{user_id}:{word_id}"),
        ],
        [
            InlineKeyboardButton(IBTN_SRS_REVEAL, callback_data=f"srs:reveal:{user_id}:{word_id}"),
        ],
    ]
    if show_pronounce:
        rows.append([InlineKeyboardButton(IBTN_PRONOUNCE, callback_data=f"tts:pronounce:s:{user_id}:{word_id}")])
    return InlineKeyboardMarkup(rows)

def srs_revealed_keyboard(user_id, word_id, *, show_pronounce=False):
    """Full card revealed: translations + 4 grade buttons."""
    rows = []
    top_buttons = []
    top_buttons.append(InlineKeyboardButton(IBTN_TRANSLATIONS, callback_data=f"srs:prepare:{user_id}:{word_id}"))
    if show_pronounce:
        top_buttons.append(InlineKeyboardButton(IBTN_PRONOUNCE, callback_data=f"tts:pronounce:s:{user_id}:{word_id}"))
    rows.append(top_buttons)
    rows.append([
        InlineKeyboardButton(IBTN_SRS_AGAIN, callback_data=f"srs:1:{user_id}:{word_id}"),
        InlineKeyboardButton(IBTN_SRS_HARD, callback_data=f"srs:2:{user_id}:{word_id}"),
        InlineKeyboardButton(IBTN_SRS_GOOD, callback_data=f"srs:3:{user_id}:{word_id}"),
        InlineKeyboardButton(IBTN_SRS_EASY, callback_data=f"srs:4:{user_id}:{word_id}"),
    ])
    return InlineKeyboardMarkup(rows)

def srs_first_exposure_keyboard(user_id, word_id, *, show_pronounce=False):
    """First encounter: familiarity-based grading (card content already shown).
    Question: 'چقدر با محتوای این فلش کارت آشنایی داری؟'
    Uses FIRST_EXPOSURE_STABILITY weights via initial_stability(grade, first_exposure=True)."""
    rows = []
    if show_pronounce:
        rows.append([InlineKeyboardButton(IBTN_PRONOUNCE, callback_data=f"tts:pronounce:s:{user_id}:{word_id}")])
    rows.append([
        InlineKeyboardButton(IBTN_FE_AGAIN, callback_data=f"srs:fe:1:{user_id}:{word_id}"),
        InlineKeyboardButton(IBTN_FE_HARD, callback_data=f"srs:fe:2:{user_id}:{word_id}"),
        InlineKeyboardButton(IBTN_FE_GOOD, callback_data=f"srs:fe:3:{user_id}:{word_id}"),
        InlineKeyboardButton(IBTN_FE_EASY, callback_data=f"srs:fe:4:{user_id}:{word_id}"),
    ])
    return InlineKeyboardMarkup(rows)
```

### 3.3 Callback Pattern Changes

| Old callback | New callback | Handler |
|---|---|---|
| `srs:remember:{uid}:{wid}` | `srs:3:{uid}:{wid}` | `_handle_srs_review(update, 3, uid, wid)` |
| `srs:confirm:{uid}:{wid}` | `srs:3:{uid}:{wid}` | Same (revealed_before_answer flag differentiates) |
| `srs:again:{uid}:{wid}` | `srs:1:{uid}:{wid}` | `_handle_srs_review(update, 1, uid, wid)` |
| — (new) | `srs:2:{uid}:{wid}` | `_handle_srs_review(update, 2, uid, wid)` |
| — (new) | `srs:4:{uid}:{wid}` | `_handle_srs_review(update, 4, uid, wid)` |
| — (new) | `srs:fe:{grade}:{uid}:{wid}` | `_handle_first_exposure_grade(update, grade, uid, wid)` |
| `srs:reveal:{uid}:{wid}` | `srs:reveal:{uid}:{wid}` | Keep (same handler) |
| `srs:prepare:{uid}:{wid}` | `srs:prepare:{uid}:{wid}` | Keep (same handler) |

### 3.4 Handler Changes (`handlers/srs_handler.py`)

#### `_handle_srs_review()` — Rewrite

```python
async def _handle_srs_review(update: Update, grade: int, target_user_id_text: str, word_id_text: str):
    """Handle a 4-grade SRS review (1=Again, 2=Hard, 3=Good, 4=Easy)."""
    # Validate user_id, word_id, review_status='pending'
    # outcome = "recalled" if grade >= 2 else "again"
    # db.grade_word_review(word_id, user_id, grade)
    # db.record_review_event(..., grade=grade, activity_type='srs_review',
    #                        grade_source='direct_button')
    # db.touch_streak(user_id) if grade >= 2
    # Answer: "ثبت شد. مرور بعدی: [date]" showing next_review date from DB
```

#### NEW: `_handle_first_exposure_grade()`

```python
async def _handle_first_exposure_grade(update: Update, grade: int, ...):
    """Grade a word on first encounter. Sets initial S0/D0."""
    # db.grade_first_exposure(word_id, user_id, grade)
    # db.record_review_event(..., grade=grade, outcome="first_exposure",
    #                        activity_type='first_exposure',
    #                        grade_source='direct_button')
    # db.touch_streak(user_id) if grade >= 2
```

#### `_handle_srs_reveal()` — Modified

After revealing, show `srs_revealed_keyboard` with 4 grade buttons instead of 2.

---

## 4. Phase 1d — Study Session Engine

**Rewrite file:** `services/srs_engine.py` (was scaffold)
**Rewrite file:** `handlers/study_handler.py` (was stub)

### 4.1 `srs_engine.generate_v3_session()` — Full Implementation

```python
async def generate_v3_session(
    user_id: int,
    target_lang: str,
    goal: str,
    level: str,
    plan: str,
) -> dict:
    """Generate a pull-based study session using 3-Tier Priority.
    
    Tier 1: Due saved_words (next_review <= today, ordered by retrievability ascending)
    Tier 2: Pre-first-exposure saved_words (first_exposure_done=0, added_at ASC)
    Tier 3: New AI-generated cards (fresh content, subject to AI quota)
    
    Session size determined by plan (sessions × session_size).
    """
    # 1. Get plan config (from config.__init__ or PLAN_DEFAULTS)
    # 2. Tier 1: due_words_for_user(user_id) — limit to plan daily cap
    # 3. Tier 2: db.get_pre_first_exposure_words(user_id) — ungraded saved words
    # 4. Tier 3: if slots remain, call AI generation (respect AI daily cap)
    # 5. Assemble SessionNode list
    # 6. Persist session to smart_study_sessions table (new)
    # 7. Return session dict with nodes and metadata
```

#### 5.1.1 Session Sizing (matches PLAN_DEFAULTS from simulation)

```python
PLAN_SESSION_CONFIG = {
    "free":     {"sessions": 1, "session_size": 4},
    "silver":   {"sessions": 3, "session_size": 5},
    "gold":     {"sessions": 4, "session_size": 7},
    "platinum": {"sessions": 5, "session_size": 10},
}
daily_slots = sessions * session_size
```

#### 5.1.2 SessionNode Dataclass

```python
@dataclass
class SessionNode:
    activity_type: str      # "srs_review" | "first_exposure" | "new_ai_card" | "quiz" | ...
    source_tier: int        # 1, 2, or 3
    card_data: dict
    source_id: int | None   # word_id for SRS, None for AI cards
    activity_meta: dict
    grade_policy_ref: str = ""           # NEW: key into GRADE_POLICIES
    interaction_schema: dict | None = None  # NEW: multi-step flow definition
```

Where `interaction_schema` describes a multi-step user interaction:
```python
# Quiz example:
interaction_schema = {
    "type": "multiple_choice",
    "prompt": "کدام ترجمه برای 'apple' درست است؟",
    "options": ["سیب", "موز", "پرتقال", "انگور"],
    "correct_index": 0,
    "max_attempts": 1,
}

# Sentence writing example:
interaction_schema = {
    "type": "sentence_write",
    "instruction": "یک جمله با کلمهٔ 'apple' بنویس",
    "max_length": 200,
    "user_response_key": "awaiting:sentence:123",
}
```

### 4.2 `handle_study_start()` — Full Implementation

```python
async def handle_study_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and present a study session.
    
    1. Check user exists, check session quota (daily sessions used)
    2. Call generate_v3_session()
    3. If no nodes: "همه کارت‌های امروز تموم شده!"
    4. Store session in context.user_data['session']
    5. Present first node via send_session_node()
    """
```

### 4.3 `send_session_node()` — Helper

```python
async def send_session_node(update, context, node: SessionNode, is_first: bool = False):
    """Render a SessionNode to the user.
    
    Dispatching:
      - If node.interaction_schema is set:
          → Start multi-step interactive flow
          → Set context.user_data['current_flow'] = node
          → Await user response → resolve_grade(activity_type, response) → grade_word_review
      - Else (simple card + buttons):
          → srs_review: show word with 4-grade keyboard
          → first_exposure: show full card with 4-grade keyboard
          → new_ai_card: show full card + "افزودن به مرور" button
    """
    grade_policy = GRADE_POLICIES.get(node.activity_type, GRADE_POLICIES["srs_review"])
    if node.interaction_schema:
        await _start_interactive_flow(update, context, node, grade_policy)
    else:
        _render_single_card(update, context, node, grade_policy)
```

Interactive flows span multiple user messages. The flow resolver waits for user input,
validates it, and (for AI-judged activities) calls the AI to assign a grade.
Once `resolve_grade(activity_type, source_value)` returns an FSRS grade, the flow
is treated identically to a button press: `grade_word_review()` + `record_review_event()`
with the appropriate `activity_type` and `grade_source`.

### 4.4 New DB Tables

```sql
CREATE TABLE IF NOT EXISTS study_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    session_date TEXT NOT NULL,
    slot_count INTEGER NOT NULL DEFAULT 0,
    slots_consumed INTEGER NOT NULL DEFAULT 0,
    activity_types TEXT  -- JSON list of types in this session
);

CREATE TABLE IF NOT EXISTS session_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    activity_type TEXT NOT NULL,
    source_tier INTEGER NOT NULL,
    source_id INTEGER,
    card_data TEXT,
    activity_meta TEXT,
    status TEXT DEFAULT 'pending',  -- pending | completed | skipped
    completed_at TEXT,
    grade INTEGER,
    FOREIGN KEY (session_id) REFERENCES study_sessions(id)
);
```

---

## 5. Phase 1e — Session Scheduling

**New file:** `services/scheduling.py`
**Size estimate:** ~80 lines

### 5.1 Responsibilities

- Timezone-aware daily slot budget
- Per-plan session config management
- Quota enforcement (sessions per day per user)

```python
def daily_session_budget(user_id: int, plan: str) -> dict:
    """Return today's session config for a user.
    
    Returns: {
        "max_sessions": int,
        "session_size": int,
        "daily_slots": int,
        "sessions_used_today": int,
        "sessions_remaining": int,
    }
    """

def consume_session_slot(user_id: int) -> bool:
    """Atomically consume one session slot for today."""

def release_session_slot(user_id: int) -> None:
    """Release a session slot (rollback on error)."""
```

### 5.2 DB Schema

```sql
-- Add to users table:
ALTER TABLE users ADD COLUMN sessions_used_today INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN sessions_used_date TEXT;
```

---

## 6. Phase 1f — bot.py Callback Updates

### 6.1 callback_router Changes

In the `callback_router` function, update the SRS callback handling section (currently lines 1086-1103):

```python
# Replace this block (old 2-button routing):
if data.startswith("srs:prepare:"): ...
elif data.startswith("srs:reveal:"): ...
elif data.startswith("srs:"): ...

# With:
if data.startswith("srs:prepare:"):
    ...
elif data.startswith("srs:reveal:"):
    ...
elif data.startswith("srs:fe:"):
    # First-exposure grade: srs:fe:{grade}:{uid}:{wid}
    parts = data.split(":")
    await _handle_first_exposure_grade(update, int(parts[2]), parts[3], parts[4])
elif data.startswith("srs:"):
    # Review grade: srs:{grade}:{uid}:{wid} where grade is 1, 2, 3, or 4
    parts = data.split(":")
    await _handle_srs_review(update, int(parts[1]), parts[2], parts[3])
```

### 6.2 Remove Old SRS Keyboard References

The `srs_review_keyboard()` function in `keyboards.py` can be kept as `srs_revealed_keyboard()` or deleted if unused.

---

## 7. Phase 2 — Data Collection & Monitoring

### 7.1 What to Track

| Data point | Source | Purpose |
|---|---|---|
| Grade distribution per user | `review_events.grade` | Validate grade threshold calibration |
| Stability growth per review | `saved_words.stability` history | Check if w-parameters produce expected growth |
| Difficulty drift | `saved_words.difficulty` history | Check mean reversion effectiveness |
| Session completion rate | `session_nodes.status` | Measure user engagement |
| Average retrievability at review | Computed from `last_review` + `stability` | Check if reviews happen at optimal R |

### 7.2 Review Events Table Schema (Final)

```sql
CREATE TABLE IF NOT EXISTS review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    grade INTEGER,                          -- 1, 2, 3, or 4
    revealed_before_answer INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL,                  -- 'again' (G=1) | 'recalled' (G=2,3,4) | 'recalled_after_peek' (G=2,3,4 after reveal) | 'first_exposure'
    activity_type TEXT DEFAULT 'srs_review',-- NEW: which interactive flow produced this review
    grade_source TEXT DEFAULT 'direct_button', -- NEW: how grade was determined
    stability_before REAL,                  -- stability before this review
    stability_after REAL,                   -- stability after this review
    difficulty_before REAL,                 -- difficulty before this review
    difficulty_after REAL,                  -- difficulty after this review
    elapsed_days REAL,                      -- days since last review
    retrievability_at_review REAL,          -- R at the time of review
    created_at TEXT NOT NULL
);
```

The `activity_type` and `grade_source` columns enable:
- Per-activity-type grade distribution analysis (e.g., do quizzes produce more Again grades than SRS reviews?)
- Future parameter fitting that accounts for different grade sources
- Auditing: verify that interactive flows produce grades consistent with button presses

This enriched schema allows full FSRS parameter fitting in Phase 3.

### 7.3 Dashboard / Admin View

Add an admin command to show per-user FSRS stats:
- Total reviews
- Grade distribution (Again/Hard/Good/Easy %)
- Average stability
- Average difficulty
- Average retrievability at review time

---

## 8. Phase 3 — Parameter Optimization

### 8.1 When

After collecting **1000+ review events** with the enriched schema (Phase 2). With 10 test users doing ~3 reviews/day each, this is ~33 days.

### 8.2 How

```bash
# Export review_events as CSV
python -c "
from services.db import get_conn
import csv
with get_conn() as conn:
    rows = conn.execute('SELECT * FROM review_events ORDER BY created_at').fetchall()
    with open('review_export.csv', 'w') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(dict(r) for r in rows)
"

# Run fsrs-optimizer against review_export.csv
# pip install fsrs-optimizer
# Follow optimizer README to fit w0-w20
```

### 8.3 Outcome

New w0-w20 values specific to HamZaboon's user population. Update `services/fsrs_core.py` constants.

---

## 9. Phase 4 — AI-Enhanced Session Types

### 9.1 Planned Activity Types

| Activity | Description | Grade Policy ref | Grade mapping | When |
|---|---|---|---|---|
| `srs_review` | Standard word review (4-grade) | `srs_review` | button 1→1 ... 4→4 | Phase 1 |
| `first_exposure` | First encounter with saved word | `first_exposure` | button 1→1 ... 4→4 | Phase 1 |
| `new_ai_card` | First encounter with AI card | `new_ai_card` | button 1→1 ... 4→4 | Phase 1 |
| `ai_quiz` | AI-generated multiple-choice quiz | `ai_quiz` | correct→3, incorrect→1 | Phase 4 (Q3 2026) |
| `sentence_write` | "یک جمله با کلمه X بنویس" → AI judges | `sentence_write` | again→1, hard→2, good→3, easy→4 | Phase 4 (Q3 2026) |
| `grammar_tip` | AI grammar explanation (no review) | — | No grade, informational only | Phase 4 |

**Key decisions applied:**
- Quiz incorrect → grade 1 (Again) — same failure formula as "یادم نیامد"
- AI judgment maps directly to 1-4 — no intermediate score conversion

### 9.2 Activity Registry + Grade Policy Integration

```python
# In srs_engine.py — combined registry and policies
from dataclasses import dataclass
from typing import Literal, Callable, Coroutine

@dataclass
class ActivityHandler:
    """Pairs a GradePolicy with a render function."""
    grade_policy: GradePolicy
    render: Callable[..., Coroutine]

ACTIVITY_REGISTRY: dict[str, ActivityHandler] = {
    "srs_review": ActivityHandler(
        grade_policy=GRADE_POLICIES["srs_review"],
        render=render_srs_review,
    ),
    "first_exposure": ActivityHandler(
        grade_policy=GRADE_POLICIES["first_exposure"],
        render=render_first_exposure,
    ),
    "new_ai_card": ActivityHandler(
        grade_policy=GRADE_POLICIES["new_ai_card"],
        render=render_new_ai_card,
    ),
    # Phase 4 additions:
    "ai_quiz": ActivityHandler(
        grade_policy=GRADE_POLICIES["ai_quiz"],
        render=render_ai_quiz,
    ),
    "sentence_write": ActivityHandler(
        grade_policy=GRADE_POLICIES["sentence_write"],
        render=render_sentence_write,
    ),
    "grammar_tip": ActivityHandler(
        grade_policy=None,  # informational only, no FSRS grade
        render=render_grammar_tip,
    ),
}
```

Each render function takes `(update, context, node, grade_policy)` and:
- For simple (Phase 1) activities: renders the card + keyboard, awaits button callback
- For interactive (Phase 4) activities: starts a multi-step flow, stores `context.user_data['current_flow']`, and calls `resolve_grade()` on completion

The session engine dispatches via `ACTIVITY_REGISTRY[node.activity_type].render()`.

### 9.3 Session Balance (FSRS-6 Determines the Mix)

The balance between review content and new content is set by:
- **Tier 3 allocation**: remaining slots after Tier 1 + Tier 2 are filled
- **AI daily cap**: limits how many new AI cards per day
- **Desired retention**: Higher DR = more frequent reviews = fewer slots for new content

This naturally creates the "تعادل بین درس/کارت جدید و یادآوری" the user described, without hand-tuned ratios.

---

## 10. Simulation vs Bot: Gaps & Confidence

### 10.1 What the Simulation Gets Right

| Aspect | Simulation (v5.4) | Bot Equivalent | Confidence |
|---|---|---|---|
| FSRS formulas | Same w0-w20, same DSR math | Same formulas in `fsrs_core.py` | High |
| 3-tier priority | due → backlog → new AI | Same order in session engine | High |
| Plan-based quotas | PLAN_DEFAULTS map | Same values in bot config | High |
| 4-grade system | Grades 1,2,3,4 (full FSRS-6) | Same button mapping | High |
| AI cost model | Cost per call | Same cost tracking | High |
| Session sizing | sessions × session_size | Same config | High |

### 10.2 What the Simulation Cannot Predict

| Aspect | Simulation | Bot Reality | Impact on Plan |
|---|---|---|---|
| Grade distribution | Derived from `f(R, noise)` formula | User consciously presses button | Parameter refitting needed in Phase 3 |
| User attendance | Fixed persona probabilities | Real-world variability | Session quotas are the safety net |
| AI reliability | Probabilistic rejection | Real API failures, timeouts | Tier 3 may underfill; session adapts |
| Review timing | Daily at simulation tick | User chooses when | No impact — next_review is date-based |

### 10.3 Overall Readiness

**Phase 1 is safe to implement now.** The simulation validates:
- The math is correct (FSRS-6 formulas verified against `docs/FSRS_v6.md`)
- The priority scheme matches requirements
- The session sizing produces reasonable learning rates
- The grade system maps to user expectations

The simulation's grade distribution (how many 1s vs 2s vs 3s vs 4s) will differ from real users, but this only affects the optimality of w-parameters, not the correctness of the algorithm. Default FSRS-6 parameters work well across populations and will be a massive improvement over the current 5-step interval ladder regardless.

---

## 11. Rollback Plan

### 11.1 Per-File Rollback

| File | Rollback Action |
|---|---|
| `services/fsrs_core.py` | Delete file |
| `services/db/__init__.py` | Revert 3 functions + schema migration via `git checkout` |
| `config/keyboards.py` | Revert SRS keyboard functions via `git checkout` |
| `handlers/srs_handler.py` | Revert via `git checkout` |
| `services/srs_engine.py` | Revert to scaffold via `git checkout` |
| `handlers/study_handler.py` | Revert to stub via `git checkout` |
| `services/scheduling.py` | Delete file |
| `bot.py` | Revert callback patterns via `git checkout` |

### 11.2 Data Rollback

If FSRS scheduling produces worse results than the interval ladder:

```python
# Reverse migration in init_db():
# UPDATE saved_words SET interval_idx = CASE
#   WHEN stability <= 2 THEN 0
#   WHEN stability <= 5 THEN 1
#   WHEN stability <= 12 THEN 2
#   WHEN stability <= 24 THEN 3
#   ELSE 4 END
# Revert to old advance/defer functions
```

### 11.3 Testing Before Production

```
1. Run with 10 test users (already in place)
2. Monitor review_events for anomalies:
   - stability < 0? (clamp error)
   - next_review in the past? (interval=0 bug)
   - difficulty outside [1, 10]? (clamp missing)
3. Compare lateness metrics against simulation:
   - Simulation predicts avg_lateness ≈ 0.6 days
   - Bot should be similar (real users may differ)
4. Collect grade distribution:
   - If 70%+ of grades are Good/Easy (3/4), intervals may be too short
   - If 40%+ are Again (1), intervals are too long
   - Easy (4) should be 5-15% of reviews; if >25%, the w16 bonus may be too aggressive
   - Hard (2) should be 15-30% of reviews; if <5%, users may not be distinguishing difficulty
```

---

## Appendix: File-by-File Change Summary

| File | Action | Lines Change | Complexity |
|---|---|---|---|
| `services/fsrs_core.py` | **CREATE** | +110 | Low (pure math) |
| `services/scheduling.py` | **CREATE** | +80 | Low |
| `services/srs_engine.py` | **REWRITE** | ~150 replaces 91 | Medium |
| `handlers/study_handler.py` | **REWRITE** | ~120 replaces 44 | Medium |
| `services/db/__init__.py` | **MODIFY** | ~50 changed +100 new | High (schema migration) |
| `config/keyboards.py` | **MODIFY** | ~30 changed +50 new | Low |
| `handlers/srs_handler.py` | **MODIFY** | ~80 changed | Medium |
| `bot.py` | **MODIFY** | ~15 changed | Low |

**Total new code:** ~290 lines
**Total modified code:** ~275 lines
**Total removed code:** ~50 lines (INTERVALS_DAYS, old advance/defer, old callbacks)
**Net increase:** ~515 lines

---

## Appendix: Owner Decision Log

| # | Decision | Choice | Date |
|---|---|---|---|
| 1 | Short-term formula | Include + gated `enable_short_term=False` | 2026-07-28 |
| 2 | Desired retention default | 0.9 (FSRS-6 standard) | 2026-07-28 |
| 3 | Grade labels | 4-button: Again(1)/Hard(2)/Good(3)/Easy(4) | 2026-07-28 |
| 4 | Easy threshold | Included in UI as Easy button — full FSRS-6 4-grade system | 2026-07-28 |
| 5 | Session priority | Tier 1 (due) → Tier 2 (pre-first-exposure) → Tier 3 (new AI) | 2026-07-28 |
| 6 | Migration scope | All three unified (daily cards + SRS + study sessions) | 2026-07-28 |
| 7 | Quiz fail → FSRS grade | Quiz incorrect → grade 1 (Again) — same as button press | 2026-07-28 |
| 8 | AI judgment → FSRS grade | AI maps directly to grades 1-4 | 2026-07-28 |
| 9 | Grade policy framework | Every activity type has GradePolicy + ACTIVITY_REGISTRY entry + test | 2026-07-28 |
| 10 | First-exposure grade=1 | 1-day forced interval (not FSRS-computed) | 2026-07-28 |
| 11 | First-exposure button labels | Familiarity-based labels (کاملاً ناآشنا / کمی آشنا / آشنایی خوب / کاملاً بلدمش) | 2026-07-29 |
| 12 | First-exposure stability weights | `FIRST_EXPOSURE_STABILITY = {1: 0.212, 2: 1.5, 3: 3.0, 4: 12.0}` — mild adjustment of w0-w3 | 2026-07-29 |
