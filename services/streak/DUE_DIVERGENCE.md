# Due-Stats TEXT-Compare Divergence (REF6-T3)

> **Status: intentional divergence — do not unify.** This document is the single
> design note for the "due" count disagreement between the stats aggregation and
> the session engine. Any change that would make the two paths return identical
> counts needs a separate contract lock and owner approval.

## Call sites

| Site | File | Lines | What it does |
|------|------|-------|--------------|
| **Stats (day-granular)** | `services/db/users.py` → `get_user_learning_stats()` | ~646–653 | `SELECT ... SUM(CASE WHEN next_review_at <= ?)` with `today_iso = _today().isoformat()` |
| **FSRS eligibility (exact UTC)** | `services/db/words.py` → `_row_effective_due()` | 161–188 | Parses `next_review_at` as exact UTC; falls back to legacy `next_review` date via `APP_TIMEZONE` |
| **FSRS pre-filter (widened)** | `services/db/words.py` → `due_words_for_user()` | 237–272 | Best-effort SQL prefilter `next_review_at <= now+1d` + `NOT LIKE`/`datetime()` guards; Python `_row_effective_due` is source of truth |

## Why they may disagree — by design

1. **Granularity mismatch.** The stats query compares `next_review_at` (TEXT ISO-8601)
   lexicographically against `today_iso` (`YYYY-MM-DD`, app-timezone day). Any card
   whose `next_review_at` is today after 00:00 app-time but before `now` UTC is
   counted as `due` in stats, while a card due later today (e.g. `2026-09-13T18:00:00+00:00`
   when `now` is `09:00Z`) is **not yet due** per `_row_effective_due`'s `ts <= now` check.
   The stats view is intentionally day-granular (cheap aggregated dashboard count);
   the session engine is instant-granular (correct FSRS scheduling).

2. **Legacy fallback is Python-only.** `_row_effective_due` falls back to
   `next_review` (legacy `YYYY-MM-DD`) → `_today()` → start-of-day local → UTC
   when `next_review_at` is absent or unparseable. The stats query does **not**
   apply this fallback — it only checks `next_review_at <= today_iso`. Cards that
   are legacy-only due will be eligible in `due_words_for_user` but invisible in
   `get_user_learning_stats().due`.

3. **TEXT vs `_parse_utc` divergence.** SQLite TEXT comparison is lexicographic.
   Strings with `Z` suffix, non-UTC offsets, or unparseable-but-ISO-looking values
   sort differently from true UTC instants. `due_words_for_user` compensates with
   a widened window (`now + 1 day`) plus `NOT LIKE '____-__-__T%'` and
   `datetime(next_review_at) IS NULL` guards so unparseable rows are still fetched
   and decided by Python. The stats path deliberately does **not** widen — it is a
   cheap single-query aggregation, not an eligibility oracle.

4. **Prefilter is intentionally lossy.** `due_words_for_user` fetches a superset
   (prefilter is an index hint) and then filters/sorts via `_row_effective_due`
   + `_row_priority_key` in Python. Different superset ≠ different result — the
   final list after Python filtering is authoritative regardless of prefilter width.

## Design decision: do not unify

- **Stats = dashboard hint.** `get_user_learning_stats` is called for profile stats
  and `due_words_for_user` drives the actual review queue. A fast, day-granular
  count that is occasionally ±N from the queue length is acceptable; making stats
  pay the FSRS parse + fallback + R-sort cost on every profile view is not.

- **Unifying would regress one side.** Making stats exact-UTC would require per-row
  Python parsing (loses the single aggregated SQL), plus legacy fallback handling.
  Making the engine day-granular would break FSRS timing.

- **No SQL/PY behavioral change in this ticket (REF6-T3).** This file and the
  alongside comments in `services/db/users.py:646-653` and `services/db/words.py:161-188,237-265`
  are docs-only. If counts are ever required to agree, open a new ticket with an
  explicit contract and re-evaluate cost.

## Where the comments live

- `services/db/users.py` — block comment above the `br = conn.execute(...)` due subquery
  cross-references this file.
- `services/db/words.py` — docstring/call-site comments in `_row_effective_due` and
  `due_words_for_user` cross-reference this file.

## Verification

```powershell
Select-String -Pattern "DUE_DIVERGENCE" services/db/users.py services/db/words.py services/streak/DUE_DIVERGENCE.md
Select-String -Pattern "get_user_learning_stats|due_words_for_user|_row_effective_due" services/streak/DUE_DIVERGENCE.md
```

Zero SQL/PY behavioral change — `git diff` should show only comments and this markdown file.
