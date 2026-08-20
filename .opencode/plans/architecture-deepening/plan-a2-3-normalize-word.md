---
name: plan-a2-3-normalize-word
description: A2-3 R2 — single NFC normalize_word + full backfill migration (Persistence)
created: 2026-08-20
base_commit: 264b095
branch: refactor/db-normalize
status: in-progress
---
# Plan: A2-3 — R2 `normalize_word` single-source (NFC) + backfill

STATE: phase 3/4 — status: in-progress — focus: independent review then commit/PR

THEME: architecture-deepening
BRANCH: refactor/db-normalize
SEAMS: Persistence
RULES: A2-3-R2
CLAIM: acquired 2026-08-20 (Persistence)

## Locked contract (owner: "option a. proceed." on R3-collision; prior A on R1/R2/R4/R5)
- **Rule 1 (A):** Single owner = `services/db/schema.py` `normalize_word(text)`.
- **Rule 2 (A):** NFC recipe everywhere: `" ".join(unicodedata.normalize("NFC", text).split()).casefold()`.
- **Rule 3 (B):** Full migration backfill of existing `saved_words.normalized_word` (idempotent).
- **Rule 3-collision (A):** On NFC merge within (user_id, lang), keep the most-recently-active row, delete the older duplicate.
- **Rule 4 (A):** Public `normalize_word`; delete private `_normalize_word` copies (words.py) + dead `schema._normalize_word`; `_normalize_query_text` delegates; keep `db.normalize_word` re-export.
- **Rule 5 (A):** A2-3 ships as its own PR; A2-4 (BUG-B1) is a separate contract+PR later.

## Scope boundaries
- NOT in scope: search-already-saved-word re-spends AI quota gap (separate issue; flag only).
- NOT in scope: A2-4 BUG-B1 `$ENV` resolver.
- Owner module per AGENTS.md §3: `services/db/schema.py`. Add `normalize_word` to `tests/test_single_source_of_truth.py`.

## Implementation steps
1. RED: tests — (a) normalize_word NFC folding (decomposed→precomposed same key); (b) saved_words dedup catches the accented duplicate across search-save; (c) migration backfill re-normalizes existing rows + collision keep-recent/delete-older.
2. GREEN: `normalize_word` in schema.py; words.py imports it (delete local); `_normalize_query_text` delegates; re-export; migration backfill in schema migration block.
3. REFACTOR + validate (full suite), independent review.
4. PR (# per workflow), Kilo loop, merge on owner approval, cleanup, release claim, update tracker.

## Evidence (updated per step)
- RED: `pytest tests/test_word_normalize.py` — 3 failed (normalize_word missing, dedup missing, backfill missing); idempotency passed trivially.
- GREEN: `pytest tests/test_word_normalize.py` — 4 passed.
- Full suite: `pytest tests/ -n 14` — 1347 passed, 270 subtests; `compile_all.py` clean; `ruff F821/F811` clean; `git diff --check` clean.
- Files: `services/db/schema.py` (normalize_word + _backfill_saved_word_normalization), `services/db/words.py` (delegates), `services/db/__init__.py` (re-export normalize_word; _normalize_query_text delegates; dropped unicodedata), `tests/test_word_normalize.py` (new), `tests/test_single_source_of_truth.py` (normalize_word -> schema.py).
- (pending) reviewer result, commit hash, PR number.