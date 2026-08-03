# Plan — Migrate Daily Cards to Session Engine (Tier 2 First-Exposure)

**Status:** `> STATUS: active`
**Related:** `docs/plans/plan_fsrs_session_cleanup.md` (Phase 3), `docs/plans/plan_fsrs_migration_v2.md`
**Target:** Solve "empty session for existing users" by converting `daily_cards` → `saved_words` as first-exposure cards.

---

## 1. Problem Statement

Current state after Phase 1 merge:
- Session engine reads ONLY `saved_words` via Tier 1 (`due_words_for_user`) + Tier 2 (`get_pre_first_exposure_words`)
- `daily_cards` table contains 29–50+ cards per active user (auto-delivered, never saved)
- Users who never pressed "Add to review" have 0 `saved_words` → empty session
- `get_pre_first_exposure_words()` is a stub returning `[]` (Phase 3 deferral)

**Goal:** Migrate all historical `daily_cards` into `saved_words` with `first_exposure_done=0` so they appear in Tier 2 of the session engine.

---

## 2. Schema Changes (Phase 3a - Before Phase 2)

### 2.1 Add Columns to `saved_words`

```sql
-- In services/db/schema.py migration
ALTER TABLE saved_words ADD COLUMN first_exposure_done INTEGER DEFAULT 0;
ALTER TABLE saved_words ADD COLUMN stability REAL DEFAULT 0.0;
ALTER TABLE saved_words ADD COLUMN difficulty REAL DEFAULT 5.0;
```

These columns are required for FSRS scheduling (Phase 3b).

### 2.2 Reset Existing `saved_words` to First-Exposure

```sql
UPDATE saved_words
SET interval_idx = 0,
    next_review = date('now'),
    review_status = 'idle',
    first_exposure_done = 0,
    stability = 0.0,
    difficulty = 5.0;
```

Per Q3 locked decision: "Reset scheduling fields, keep cards + review history."

---

## 3. Daily Cards Migration (Phase 3a)

### 3.1 Migration Logic

```sql
-- Run once at startup via migrate_saved_words_to_fsrs()
-- Idempotent: uses INSERT OR REPLACE on (user_id, lang, normalized_word)

INSERT INTO saved_words (
    user_id, word, lang, normalized_word, card_data,
    interval_idx, next_review, review_status,
    first_exposure_done, stability, difficulty, added_at
)
SELECT
    dc.user_id,
    json_extract(dc.card_data, '$.word'),
    u.target_lang,                    -- language from users table
    lower(json_extract(dc.card_data, '$.word')),
    dc.card_data,
    0,                                -- interval_idx
    date('now'),                      -- next_review = today
    'idle',                           -- review_status
    0,                                -- first_exposure_done = 0 (Tier 2)
    0.0,                              -- stability
    5.0,                              -- difficulty
    datetime(dc.card_date || ' ' || printf('%02d:00:00', dc.card_index))  -- approximate added_at
FROM daily_cards dc
JOIN users u ON u.user_id = dc.user_id
WHERE u.onboarded = 1
ON CONFLICT(user_id, lang, normalized_word) DO UPDATE SET
    card_data = excluded.card_data,
    first_exposure_done = 0,
    stability = 0.0,
    difficulty = 5.0,
    next_review = date('now');
```

### 3.2 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Tier** | Tier 2 (first_exposure_done=0) | Never reviewed → first exposure |
| **Language** | `users.target_lang` | User's current language; daily_cards has no lang column |
| **Dedupe key** | `(user_id, lang, normalized_word)` | Matches `saved_words` unique constraint |
| **Conflict resolution** | Update card_data, force first_exposure | Fresh start for all |
| **Scope** | ALL historical daily_cards | User expects their full history |
| **Ordering in Tier 2** | `added_at` ASC (from card_date + card_index) | Oldest first = natural review order |

### 3.3 Idempotency Guard

```python
# services/db/words.py - migrate_saved_words_to_fsrs()
def migrate_saved_words_to_fsrs() -> bool:
    """One-time startup migration. Returns True if migration ran, False if already done."""
    with get_conn() as conn:
        # Check if already migrated
        already = conn.execute(
            "SELECT 1 FROM settings WHERE key = 'fsrs_migration_done'"
        ).fetchone()
        if already:
            return False

        # Run migration SQL (schema changes + data migration)
        _run_schema_migration(conn)
        _run_data_migration(conn)

        # Mark complete
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('fsrs_migration_done', '1')"
        )
        conn.commit()
        return True
```

---

## 4. Phase Ordering

```
Phase 1: Merge session engine shell (current PR, after B1 fix)
    ↓
Phase 3a: Schema + migration (add columns, reset saved_words, migrate daily_cards)
    ↓   [uses daily_cards table while it still exists]
Phase 2: Remove stale flows (daily, review menu, old SRS) + DROP daily_cards table
    ↓
Phase 3b: Wire FSRS scheduling (grade_word_review, due_words_for_user,
         get_pre_first_exposure_words consume fsrs_core.py)
```

**Why 3a before 2:** Migration needs `daily_cards` table. Phase 2 drops it. Doing migration first avoids backup/restore complexity.

---

## 5. Tier 3 (AI Generation) — Future Work

`daily_card_system_prompt` in `services/ai/prompts.py:88` is the correct template for Tier 3 cards:
- Single card generation (per slot)
- Takes `lang`, `goal`, `level`, `avoid_words`
- Returns exact card schema matching `saved_words.card_data`

When implementing `generate_tier3_node()` (Phase 3b+):
- Use `daily_card_system_prompt` with `compact=True` for token efficiency
- Pass `avoid_words` from session's already-seen words (Tier 1+2 + Tier 3 generated so far)
- Respect AI daily quota per user/plan

---

## 6. Validation

### 6.1 Migration Test (Phase 3a)
```python
def test_migrate_daily_cards_to_first_exposure():
    # Setup: user with daily_cards, no saved_words
    # Run: migrate_saved_words_to_fsrs()
    # Assert: saved_words count = daily_cards count (deduped)
    # Assert: all have first_exposure_done=0, stability=0.0, difficulty=5.0
    # Assert: next_review = today
    # Assert: idempotent (second run changes nothing)
```

### 6.2 Session Test (Phase 3a)
```python
def test_session_shows_migrated_cards_as_tier2():
    # After migration, user presses "Start Session"
    # build_session_list() returns Tier 2 nodes for all migrated words
    # Grading first card → grade_first_exposure() → first_exposure_done=1
    # Next session → word appears in Tier 1
```

### 6.3 Dedupe Test
```python
def test_migration_dedupes_by_user_lang_word():
    # Same word in daily_cards multiple days + already in saved_words
    # Migration runs → only ONE row in saved_words, card_data from latest daily_card
    # first_exposure_done=0 enforced
```

---

## 7. Files to Modify

| File | Change |
|------|--------|
| `services/db/schema.py` | Add `first_exposure_done`, `stability`, `difficulty` columns in migration |
| `services/db/words.py` | Implement `migrate_saved_words_to_fsrs()` with idempotency guard |
| `services/db/words.py` | Implement `get_pre_first_exposure_words()` → `SELECT * FROM saved_words WHERE user_id=? AND first_exposure_done=0 ORDER BY added_at` |
| `services/db/words.py` | Implement `grade_first_exposure()` using `fsrs_core.initial_stability_first_exposure()` |
| `services/db/words.py` | Implement `due_words_for_user()` → filter `first_exposure_done=1 AND next_review<=today` |
| `services/db/words.py` | Implement `grade_word_review()` using `fsrs_core.compute_interval()` etc. |
| `services/session/assembly.py` | `generate_tier3_node()` → call AI with `daily_card_system_prompt` |
| `docs/plans/plan_fsrs_migration_v2.md` | Update Phase 1a items 1a.6–1a.11 status (partial) |

---

## 8. Open Questions (Need Owner Decision)

1. **Language for daily_cards**: Use `users.target_lang` at migration time? What if user changed language since card was generated?
2. **Scope**: Migrate ALL historical daily_cards (29 for Iceguy, 50+ for others) or only last 30 days?
3. **Conflict card_data**: When same word exists in both tables, which `card_data` wins? (Plan: latest daily_card wins)
4. **Phase 3a timing**: Run migration in `init_db()` at startup? Or as a separate admin command first?

---

## 9. Rollback

- Settings flag `fsrs_migration_done` allows re-run if needed
- Before migration: snapshot `saved_words` to backup table (per Rollback Appendix in `plan_fsrs_session_cleanup.md`)
- `daily_cards` table preserved until Phase 2 confirms migration success