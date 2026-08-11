# Callback Notifications Rebase Report

## Foundation

- Foundation branch: `refactor/callback-notifications`
- Tracking issue: #310
- PR URL: https://github.com/Ham3dParsa/HamZaboonRobot/pull/311
- Base commit: `a62bb1204610c3f587e23937526cef5a936c14d1` (`origin/main` at worktree creation)
- Final implementation commit: `c3553b4`
- Merge status: not merged; awaiting PR CI and owner approval.
- Foundation claim: `Telegram Callback Notifications`, registered for `refactor/callback-notifications` in the shared claims file. It remains registered until post-merge cleanup.

## Public Interface

```python
await notify_callback(query, text, intent=CallbackNoticeIntent.SUCCESS)
await notify_callback(query, text, intent=CallbackNoticeIntent.INFO)
await notify_callback(query, text, intent=CallbackNoticeIntent.IMPORTANT_ERROR)
await notify_callback(query)
```

| Intent | Telegram presentation |
|---|---|
| `SUCCESS` | Non-blocking toast (`show_alert=False`) |
| `INFO` | Non-blocking toast (`show_alert=False`) |
| `IMPORTANT_ERROR` | Blocking modal (`show_alert=True`) |
| Empty text | Callback acknowledgement with no visible text |

The module owns stale callback-query handling, `BadRequest` classification,
`TimedOut` / `NetworkError` handling, and callback-answer logging. Unexpected
Telegram errors still propagate.

## Migration Scope

- Migrated: `bot.py`, `handlers/admin.py`, `handlers/admin_ai.py`,
  `handlers/admin_cost.py`, `handlers/admin_plans.py`, `handlers/admin_stats.py`,
  `handlers/srs_handler.py`, `handlers/study_handler.py`, `handlers/user.py`,
  and callback acknowledgement paths in `services/utils/helpers.py`.
- Removed symbol: `services.utils.helpers._answer_callback_safely`.
- Guard tests: `tests/test_wiring.py` rejects low-level production `.answer()`
  calls outside `services/utils/callback_notifications.py`; `tests/test_dead_code_guard.py`
  bans `_answer_callback_safely` from returning.
- Callback prefixes, keyboard construction, DB/schema, quotas, scheduling, and
  AI calls/cost are unchanged. The foundation adds no AI calls or token cost.

## Evidence

- Focused evidence before final suite: `tests/test_callback_notifications.py`,
  `tests/test_reliability.py`, `tests/test_wiring.py`, and
  `tests/test_integration/test_callback_notification_flow.py` passed.
- Full validation evidence: `python -m pytest tests/ -n 14` -> 623 passed;
  `compile_all.py`, ruff F821/F811, dashboard generation, and both whitespace
  checks passed.
- Independent reviewer result: final `hamzaboon-reviewer` pass reported no
  confirmed findings.
- Remaining uncertainty: PR URL, final commit, CI result, and merge commit are
  pending the normal review and owner-approval sequence.

## Paused Worktrees

| Branch | Current status | Required post-merge claim |
|---|---|---|
| `feat/grade-feedback-toast` | Paused; do not modify until this foundation is merged. | `Telegram UI -> Study` |
| `feat/custom-word-query` | Paused; do not modify until this foundation is merged. | `Persistence`, `Telegram UI -> SRS Grading`, `Telegram UI -> User Domain` |

## Safe Rebase: Grade Feedback (#308)

1. Do **not** rebase a dirty worktree. First preserve its changes through its
   owning session's approved workflow.
2. Fetch the merged main branch: `git fetch origin`.
3. From a clean `feat/grade-feedback-toast` worktree, run
   `git rebase origin/main`.
4. Expected conflict surface: `handlers/study_handler.py` now imports
   `CallbackNoticeIntent` / `notify_callback` and `_reply_or_answer` accepts
   semantic `intent`, not `show_alert`.
5. The #308 grade-feedback callback path in
   `handlers/srs_handler.py::_handle_srs_review` and
   `handlers/srs_handler.py::_handle_first_exposure_grade` must use
   `notify_callback(...)`; it must not introduce `.answer()` or `show_alert`.
6. Re-run the feature's contract gate, then atomically re-register exactly
   `Telegram UI -> Study` under `feat/grade-feedback-toast`.

## Safe Rebase: Custom Word Query

1. Do **not** rebase a dirty worktree. First preserve its changes through its
   owning session's approved workflow.
2. Fetch the merged main branch: `git fetch origin`.
3. From a clean `feat/custom-word-query` worktree, run
   `git rebase origin/main`.
4. Expected conflict surfaces: `handlers/srs_handler.py` and
   `handlers/user.py`, whose callback notices now import and use the shared
   module; `services/utils/helpers.py` no longer exports
   `_answer_callback_safely`.
5. The custom-word query callback/UI phase that changes
   `handlers/srs_handler.py::_handle_query_add` or
   `handlers/user.py::_handle_query_prepare` must use `notify_callback(...)`.
6. Re-run the feature's contract gate, then atomically re-register exactly
   `Persistence`, `Telegram UI -> SRS Grading`, and
   `Telegram UI -> User Domain` under `feat/custom-word-query`.
