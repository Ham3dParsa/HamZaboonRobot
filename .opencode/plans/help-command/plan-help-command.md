# Plan: User Help Module (`/help` + راهنما panel)

STATE: complete — implemented on `feat/help-command`; full suite green (636 passed); owner locked Rules 1–5; Rule 6 left OPEN.

## Locked contract (grill-to-spec)

| # | Decision | Option | Status |
|---|---|---|---|
| 1 | Module location | `handlers/help_command.py` (deep module: 2-fn interface hides data-driven `HELP_SECTIONS`) | LOCKED |
| 2 | Triggers | `/help` command + `راهنما` text | LOCKED |
| 3 | راهنما scope | opens help only when NOT mid-input (post-await routing) | LOCKED |
| 4 | UX | inline PANEL; each section button shows a detail message | LOCKED |
| 5 | Format | escaped MarkdownV2 + main-menu keyboard | LOCKED |
| 6 | Admin section | owner-only button (default; owner undecided) | OPEN |

## Callback prefixes (new seam: Telegram UI -> Help)

- `help:section:<id>` -> detail for section id
- `help:back` -> re-show panel

## Phase steps

- [x] Create `handlers/help_command.py` (interface: `send_help_panel`, `handle_help_callback`; registry `HELP_SECTIONS`).
- [x] Wire `bot.py`: import, `CommandHandler("help", send_help_panel)`, `راهنما` branch in `text_router`, `help:` prefix + `help:` branch in `callback_router`.
- [x] Update `AGENTS.md` §3 table + `SEAMS.md` (new seam #16) + callback-wiring skill map.
- [x] Tests: `tests/test_help_command.py` (unit), `tests/test_integration/test_help_flow.py` (flow), wiring guard auto-covers new prefixes.
- [x] Validation: compile, ruff F821/F811, dashboard regen, `git diff --check`, full suite (636 passed) all green.

## Residual / uncertain

- Rule 6 (admin help section) is OPEN — implemented as owner-only button; owner may revise.
- Grammar tips (`send_grammar_tip`) remain unwired and are intentionally NOT documented in help (per Rule 4 = wired features only).

## Follow-up — feat/help-hide-review (LOCKED)

Owner asked to deactivate the "review" (مرور واژه‌های ذخیره‌شده) section from help for now, and confirmed the "no technical details" principle applies only to this removal (other sections unchanged).

- Rule 1: KEEP-BUT-HIDDEN — added `"hidden": True` to the review entry; `_visible_sections` now filters `hidden` (and `owner_only`). Section is excluded from the panel AND rejected at the callback layer (`help:section:review` -> "unknown" error) for everyone, including owner. Reversible by removing the flag.
- Rule 2: ONLY REMOVE REVIEW — no other help text rewritten.
- Seam re-claimed: "Telegram UI -> Help" under branch feat/help-hide-review.
- Tests: unit `test_hidden_section_excluded_from_panel_for_all` + integration `test_hidden_review_section_not_openable`.
