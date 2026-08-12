# Phase 01 — Cosmetic / low-risk UI (R6, R8, R9, R15-plan-escape)

STATE: phase 1/1 — status: complete (impl + tests; awaiting reviewer + full suite) — focus: R6 shared render, R8 emoji dictionary, R9 usage relabel, R15 plan escape

- **Blocking edges:** none (first executable phase).
- **Scope (files):**
  - `handlers/admin_ai.py` — R6 shared render fix (both list sites → clean `🟢 name [tags]`); R8 apply emoji dictionary to templates A–D + list/chain views; R9 relabel usage to «مصرف ۲۴ ساعته».
  - `handlers/admin_cost.py` — R8 legend on cost dashboard.
  - `handlers/admin_plans.py` — R15 `html.escape` on `display_name`/`name`/`old_val`/`new_val`.
  - `config/keyboards.py` — R8 emoji in buttons per dictionary (🛡️/🎯/🟢⚪).
- **Tests:** `tests/test_formatting.py` (escape); `tests/test_integration/test_admin_*.py` (render snapshots); `tests/test_wiring.py` only if callbacks change (none here).
- **Gates:** R6, R8, R9, R15.
- **Wiring rows:** AI Config (render) update; Cost (legend) update; Plans (escape) update.
- **Acceptance:** no stray space in lists; 🟢/⚪ toggle + 🛡️ emergency + 🔋/🪫 quota + ✅/❌ health applied per dictionary; usage label «مصرف ۲۴ ساعته»; plan texts escaped.
