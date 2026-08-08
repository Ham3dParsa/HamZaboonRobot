# Plan: Network Resilience V2 (feat/network-resilience-v2)

**Status:** Locked — ready for implementation
**Owner locked:** 2026-07-20
**Target branch:** `feat/network-resilience-v2`
**Base branch:** `main`

---

## Problem

The bot runs on a Windows machine with frequent internet/VPN drops. After reconnection, the circuit breaker (`_telegram_offline`) stays `True` for up to 60s, rejecting all incoming user requests with an "offline" message. Background jobs (`_dispatch_queue`, `srs_job`) waste retry attempts during disconnection. SRS failed sends have no retry queue — words are missed for 24h.

---

## Owner's Chosen Rules (locked 2026-07-20)

| # | Decision | Scope |
|---|----------|-------|
| 1 | Proactive CB reset on retry success | `helpers.py` + `bot.py` |
| 2 | Background jobs skip when offline | `bot.py` (`_dispatch_queue`, `srs_job`, `daily_job`) |
| 3 | Faster health check (30s interval, 1 failure threshold) | `bot.py` (globals + schedule) |
| 4 | Replace all raw `reply_text` with `_send_with_retry` | `bot.py` (text_router) |
| 5 | Add SRS retry queue (persistent) | `db/__init__.py` + `bot.py` |
| 6 | Startup catch-up checks connection | `bot.py` (`startup_catch_up_job`) |

---

## Implementation Phases

### Phase 1: `helpers.py` — Proactive CB reset

**Add `_reset_telegram_cb()`:**
```python
def _reset_telegram_cb():
    import bot
    bot._telegram_offline = False
    bot._consecutive_health_failures = 0
```

**Modify `_send_with_retry`** (end of success path, after semaphore release):
- Call `_reset_telegram_cb()`

**Modify `_edit_with_retry`** (same):
- Call `_reset_telegram_cb()`

**Modify `_delete_with_retry`** (same):
- Call `_reset_telegram_cb()`

**Modify `_send_voice_with_retry`** (same):
- Call `_reset_telegram_cb()`

---

### Phase 2: `bot.py` — Faster health check + BG jobs + Startup

**Change globals (line 178-179):**
```python
_consecutive_health_failures: int = 0
_OFFLINE_THRESHOLD: int = 1
```

**Change schedule (line 1380-1384):**
```python
app.job_queue.run_repeating(
    connection_health_job,
    interval=30,
    first=30,
)
```

**Modify `_dispatch_queue`:**
- At top: `if _telegram_offline: log.warning("..."); return`

**Modify `srs_job`:**
- At top: `if _telegram_offline: log.warning("..."); return`

**Modify `daily_job`:**
- At top: `if _telegram_offline: log.warning("..."); return`

**Modify `startup_catch_up_job`:**
- Before running jobs: try `await _send_with_retry(context.bot, OWNER_ID, "test")` or use `context.bot.get_me()` directly; if fails, log and skip all jobs

**Modify `text_router` — replace raw `update.message.reply_text()` calls:**
- Line ~587: `await _send_with_retry(...)`
- Line ~597: `await _send_with_retry(...)`
- Line ~625: `await _send_with_retry(...)`
- Line ~643: `await _send_with_retry(...)`
- Line ~662: `await _send_with_retry(...)`
- Line ~680: `await _send_with_retry(...)`
- Line ~703: `await _send_with_retry(...)`
- Line ~710: `await _send_with_retry(...)`
- Line ~722: `await _send_with_retry(...)`
- Line ~736: `await _send_with_retry(...)`

Each replacement: `_send_with_retry(context.bot, update.effective_chat.id, text, ...)` instead of `update.message.reply_text(text, ...)`

---

### Phase 3: `db/__init__.py` — SRS retry queue

**Approach:** Add `retry_at` column to `saved_words` table (similar to delivery_queue's retry_at). When SRS send fails, set `retry_at = now + backoff`. New function `get_due_srs_failed()` fetches words with `retry_at <= now`.

**Add migration** (in `init_db`):
```python
saved_word_columns = {row["name"] for row in conn.execute("PRAGMA table_info(saved_words)").fetchall()}
if "retry_at" not in saved_word_columns:
    conn.execute("ALTER TABLE saved_words ADD COLUMN retry_at TEXT")
```

**Add functions:**

```python
def mark_srs_send_failed(word_id: int, attempts: int):
    """Set retry_at with exponential backoff (5min, 10min, 20min, max 1h)."""
    delay = min(300 * (2 ** attempts), 3600)
    retry_at = (_utc_now() + datetime.timedelta(seconds=delay)).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE saved_words SET retry_at=?, review_status='idle' WHERE id=?",
            (retry_at, word_id),
        )
        conn.commit()

def get_due_srs_failed(max_words: int = 50):
    """Fetch words with retry_at <= now and review_status='idle'."""
    now = _utc_now().isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM saved_words WHERE retry_at IS NOT NULL AND retry_at<=? "
            "AND review_status='idle' ORDER BY retry_at LIMIT ?",
            (now, max_words),
        ).fetchall()
```

**Modify `due_words_for_user`**: exclude words with non-null `retry_at` (they're already pending retry).

---

### Phase 4: `bot.py` — SRS retry job

**Add `srs_retry_job`:**
```python
async def srs_retry_job(context: ContextTypes.DEFAULT_TYPE):
    if _telegram_offline:
        return
    for word in db.get_due_srs_failed():
        # same send logic as srs_job but uses db.get_saved_word(word["id"])
        # if send succeeds, clear retry_at
        # if fails, call mark_srs_send_failed with incremented attempt count
        # need to track attempts — could use a simple counter stored in retry_at format or add attempts column
```

**Design choice for attempt tracking:**
- Simplest approach: store `attempts` count in the `retry_at` column? No, that's messy.
- Better: Since SRS retry attempts are bounded (e.g., 3 retries max), just check if `retry_at` has been set before. If the word has been retried 3 times, give up.
- Actually, the simplest: just don't track attempts. If a word fails to send, set `retry_at = now + 5min`. On the next retry_job cycle, if it still fails, set `retry_at = now + 10min`. If it keeps failing, the backoff increases exponentially. After ~5-6 failures (max 1h delay), retries mostly stop. This is self-limiting without needing an attempt counter.

Wait, but `mark_srs_send_failed` takes `attempts` parameter. We need to track how many times a word has been retried. Let me think of the simplest approach:
- Add `srs_retry_attempts` column with default 0
- Increment on each failed send
- Max 5 attempts, then give up (set retry_at = NULL)

**Add column:**
```python
if "srs_retry_attempts" not in saved_word_columns:
    conn.execute("ALTER TABLE saved_words ADD COLUMN srs_retry_attempts INTEGER NOT NULL DEFAULT 0")
```

**Update `mark_srs_send_failed`:**
```python
def mark_srs_send_failed(word_id: int, current_attempts: int, max_attempts: int = 5):
    if current_attempts >= max_attempts:
        with get_conn() as conn:
            conn.execute(
                "UPDATE saved_words SET retry_at=NULL, srs_retry_attempts=? WHERE id=?",
                (current_attempts, word_id),
            )
            conn.commit()
        return
    delay = min(300 * (2 ** current_attempts), 3600)
    retry_at = (_utc_now() + datetime.timedelta(seconds=delay)).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE saved_words SET retry_at=?, srs_retry_attempts=? WHERE id=?",
            (retry_at, current_attempts, word_id),
        )
        conn.commit()
```

**Add `clear_srs_retry`:**
```python
def clear_srs_retry(word_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE saved_words SET retry_at=NULL, srs_retry_attempts=0 WHERE id=?",
            (word_id,),
        )
        conn.commit()
```

**Modify `srs_job` error path:**
When `_send_with_retry` fails in `srs_job`, call `mark_srs_send_failed(word_id, row.get("srs_retry_attempts", 0))` instead of just `release_srs_claim`.

**Add `srs_retry_job`:** (runs every 15 minutes)
```python
async def srs_retry_job(context: ContextTypes.DEFAULT_TYPE):
    if _telegram_offline:
        return
    for word in db.get_due_srs_failed():
        word_id = word["id"]
        user_id = word["user_id"]
        user_row = db.get_user(user_id)
        if not user_row or not user_row["onboarded"]:
            continue
        try:
            card = await asyncio.to_thread(
                _prepare_cached_card,
                _saved_word_card(word),
                lang=word["lang"],
                user_id=user_id,
                plan=user_row["plan"] or "free",
                source="srs",
                persist_patch=lambda patch, word_id_=word_id: db.update_saved_word_fields(
                    word_id_, user_id, patch,
                ),
            )
            phon_lines = _phonetic_lines(card.get("phonetic", ""))
            show_pronounce = (user_row["plan"] or "free") in PREMIUM_PLANS
            await _send_with_retry(
                context.bot, user_id,
                format_srs_prompt(card, phonetic_lines=phon_lines),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=srs_hidden_keyboard(user_id, word_id, show_pronounce=show_pronounce),
            )
            db.clear_srs_retry(word_id)
            if db.mark_word_review_pending(word_id):
                log.info("srs retry succeeded word_id=%s user_id=%s", word_id, user_id)
        except CardPreparationError:
            db.mark_srs_send_failed(word_id, word["srs_retry_attempts"] + 1)
            log.warning("srs retry card prep failed word_id=%s user_id=%s", word_id, user_id)
        except Exception:
            db.mark_srs_send_failed(word_id, word["srs_retry_attempts"] + 1)
            log.exception("srs retry failed word_id=%s user_id=%s", word_id, user_id)
```

---

## Files changed

| File | Changes |
|---|---|
| `helpers.py` | +`_reset_telegram_cb()` function; called at end of all 4 retry wrappers |
| `bot.py` | Threshold: 2→1; Interval: 60→30; `_dispatch_queue` + `srs_job` + `daily_job` CB check; `startup_catch_up_job` connection check; 10x raw reply_text → retry; +`srs_retry_job` + schedule |
| `db/__init__.py` | Migration: add `retry_at`, `srs_retry_attempts` columns; +`mark_srs_send_failed` +`get_due_srs_failed` +`clear_srs_retry` |

---

## Test Plan

1. **`_reset_telegram_cb` resets globals** — mock globals, call function, assert reset
2. **`_send_with_retry` calls `_reset_telegram_cb` on success** — mock both, assert call
3. **`_dispatch_queue` skips when offline** — set `_telegram_offline=True`, call, assert no DB interactions
4. **`get_due_srs_failed` returns only words with retry_at ≤ now** — insert test rows, query, assert
5. **`mark_srs_send_failed` exceeds max** — call with attempts=5, assert retry_at=NULL

---

## Verification

```powershell
python -m unittest discover -s tests -v
python -m ruff check --select F821,F811
python scripts/compile_all.py
git diff --check
```
