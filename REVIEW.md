# REVIEW.md

Repo-specific guidance for automated code review, read by Kilo from the base
branch. Add value only where it changes this reviewer's defaults — the
repo-specific traps a generic reviewer would get wrong. Keep in sync with
AGENTS.md §3.

## Read this before reviewing

- Telegram send is non-idempotent. `_send_with_retry` / `_send_voice_with_retry`
  must raise on `TimedOut`/`NetworkError` and retry ONLY on `RetryAfter` — a
  timeout may mean the message already shipped, so retrying produces a
  duplicate. Do NOT flag the missing timeout-retry as a bug.
  (`_edit_with_retry` / `_delete_with_retry` may retry — those are idempotent.)
- Every dynamic value in a learner-facing MarkdownV2 message (AI, DB, user
  input) must go through `escape_mdv2()` in `services/utils/formatting.py`
  before interpolation. A raw value in `bot.py` is the "can't parse entities"
  bug.
- Callback routes are wired end-to-end: each `callback_data` prefix needs a
  matching handler, and new/removed routes must be covered by
  `tests/test_wiring.py`. Flag a prefix with no router as a wiring break.
- API keys are stored as `$UPPERCASE` env-name references, resolved at runtime
  by `resolve_api_key()`. Flag any raw key in code, tests, logs, commits, or DB.
- Application-day math uses `APP_TIMEZONE`; UTC for processing metadata. Flag a
  quota/date boundary computed in the wrong zone.

## Verify before flagging

- Escaping / wiring / quota claims: point to the function or
  `tests/test_wiring.py` line that demonstrates the breach.
- Behavior changes: look for handler-level coverage in `tests/test_integration/`
  before flagging missing tests.
- Schema changes: require fresh-DB AND prior-schema migration coverage.

## Severity

- Critical: data loss, privilege escalation, raw-key exposure, plan/quota
  billing errors, duplicate delivery.
- Warning: escaping misses, wiring gaps, quota/date-boundary bugs, untested
  behavior.
- Do not flag: formatting/whitespace (ruff + `git diff --check` gate these),
  LLM token/cost choices, or product/education policy outside this PR's scope.

## Comment style

- Cite `file_path:line_number`.
- State the positive fix, not just the problem.
- One confirmed issue per comment, ordered by severity.
