---
name: plan-preset-save-preview-phase-01-helper
phase: 1
gates: [R4, R5]
blocking: []
status: pending
---
STATE: phase 1 — status: pending — focus: shared helper + unit tests

## Scope

New file `services/utils/confirm_summary.py` (domain-agnostic formatting helper,
prepared-strings-in — same standing as `services/utils/formatting.py`):

```python
@dataclass FieldDiff: label, old, new, secret=False
def build_confirm_message(title, subject, diffs: list[FieldDiff], *, notes=()) -> Message
```

- Builds `heading(3, title+subject)` + per-field vertical 2-row Rich `table((وضعیت, مقدار), (قبلی, old), (جدید, new))` + dirty-count line + notes block, via `services/send_pretty.py` spans only.
- Helper NEVER sees plaintext secrets: callers pre-mask via `mask_key` and pass display strings. Helper never truncates.
- Persian digits for counts via existing digit helper.

## Tests

- New `tests/test_confirm_summary.py`: 2-field diff renders both tables with old+new; count line uses Persian digits; notes appended; empty diffs → "تغییری برای ذخیره وجود ندارد" path (or empty Message — match chosen, pin it).
- Full suite green: `pytest`, `compile_all.py`, `ruff F821/F811`, `git diff --check`.

## Acceptance

- [ ] helper builds Rich Message matching demo C (vertical, mobile-safe, no wide table)
- [ ] no Telegram imports outside send_pretty spans; no DB access
- [ ] unit tests pass; full validation passes
- [ ] `hamzaban-reviewer`: 0 confirmed findings
