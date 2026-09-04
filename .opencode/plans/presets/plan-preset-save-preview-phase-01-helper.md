---
name: plan-preset-save-preview-phase-01-helper
phase: 1
gates: [R4, R5]
blocking: []
status: complete
---
STATE: phase 1 — status: complete — helper + unit tests done, validated 2026-09-04 in worktree .worktrees/feat-preset-save-preview (branch feat/preset-save-preview). Evidence: tests/test_confirm_summary.py 4 passed (two_field_diff_renders_both_tables, dirty_count_persian_digits, notes_appended, empty_diffs_pins_no_change_line); tests/test_single_source_of_truth.py 16 passed (no duplicate to_persian_digits); python scripts/compile_all.py clean; ruff --select F821,F811 clean on both new files; git diff --check clean. NOT committed (per instruction).

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

- [x] helper builds Rich Message matching demo C (vertical, mobile-safe, no wide table)
- [x] no Telegram imports outside send_pretty spans; no DB access
- [x] unit tests pass; full validation passes
- [ ] `hamzaban-reviewer`: 0 confirmed findings
