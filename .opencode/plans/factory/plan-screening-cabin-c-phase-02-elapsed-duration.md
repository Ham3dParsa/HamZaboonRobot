---
name: plan-screening-cabin-c-phase-02-elapsed-duration
description: T02 — human duration helper (smart-relative + dual calendar, fa digits)
created: 2026-09-27
base_commit: 03c6af6f30696b176d04c53fbaca70a2a8e92840
branch: refactor/webui-static-phase1
status: locked
---

STATE: phase 2/7 — status: implemented-uncommitted — focus: T02 duration helper, code+tests+screenshots in worktree feat/screening-cabin-c (no commit)

## Ticket T02 — elapsed/duration helper (UX-25, OQ-9) [Wave 1 · PARALLEL-safe vs T01]

- **Blocking edges:** none. Downstream: T07 (badge), T10 (history/paths timestamps).
- **Scope (files):** new pure helper `factory/webui/duration_fmt.py` (single owner — no logic in `config/` or `services/utils/`); `factory/webui/server.py` `_screening_public_locked` (`:5049-5087` — ADD `elapsed_human` + `started_iso`, keep raw `elapsed` for compat); `tests/factory/test_webui_duration_fmt.py` (new).
- **Rule (locked):** pure function `format_duration(seconds) → fa-digit string` (≤90s: `N ثانیه`; <90min: `M دقیقه و S ثانیه`; else `H ساعت و M دقیقه`); never >3 decimals, never raw float to UI. OQ-9: `format_moment(iso)` → smart-relative primary (`۵ دقیقه پیش`) + detail `شمسی + میلادی + Asia/Tehran/UTC labels`. Timezone via stdlib `zoneinfo`, Jalali via existing repo helper only (grep before duplicating).
- **Tests:** unit table (0.4s, 75s, 3700s, None) + fa-digit assertion + moment dual-calendar assertion; snapshot test keeps raw `elapsed` key present.
- **Wiring rows:** `duration_fmt.format_duration → _screening_public_locked.elapsed_human → badge#screening-elapsed`; `format_moment → history/dialog timestamps (T05/T09 consumers)`.
- **Changed / not changed / uncertain:** adds helper + 2 snapshot keys. NOT changed: monotonic clock source, poll cadence, status shape otherwise. Uncertain: none.

### Acceptance criteria

- **Interaction tests (named):** IT-T02-01 start run → badge shows `۱۲ ثانیه`-style fa text, never `12.438291`; IT-T02-02 run past 90s → `۱ دقیقه و N ثانیه`; IT-T02-03 history/dialog timestamp shows relative + شمسی/میلادی dual detail on hover/title.
- **Screenshots:** `shot-t02-duration-desktop.png` (live badge + log header) + `shot-t02-duration-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_webui_duration_fmt.py -n 8`
