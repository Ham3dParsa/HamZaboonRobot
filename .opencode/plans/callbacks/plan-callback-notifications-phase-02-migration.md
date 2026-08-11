---
name: callback-notifications-phase-02-migration
description: Replace every production callback-answer call with the shared interface.
created: 2026-08-11
base_commit: a62bb1204610c3f587e23937526cef5a936c14d1
branch: refactor/callback-notifications
status: pending
---

STATE: phase 2/3 - status: complete - focus: all current production callback answers use the shared module

## Steps

| Step | Status | Evidence |
|---|---|---|
| Classify current call sites using the locked presentation-preserving map. | complete | Existing modal/toast presentation retained; owner selected INFO for ambiguous toasts |
| Migrate bot and handler call sites; preserve Persian copy and callback flow. | complete | `bot.py`, all affected handlers, and `helpers.py` |
| Remove `_answer_callback_safely` after zero-reference grep. | complete | Production grep has no remaining reference |
