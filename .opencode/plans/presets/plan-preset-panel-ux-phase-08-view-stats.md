---
name: plan-preset-panel-ux-phase-08-view-stats
phase: 8
gates: [U3]
blocking: [phase-07]
status: complete
---
STATE: phase 8 — status: complete — evidence: handlers/admin_ai.py::_show_ai_preset_view appends 📊 «مصرف ۲۴ ساعته» block via single db.get_hourly_usage read (Persian digits, span-escaped); tests test_preset_view_shows_24h_usage_stats + test_preset_view_zero_usage_renders_graceful_empty in test_admin_ai_render_flow.py green; full suite 1778 passed + 324 subtests, compile_all clean, ruff F821/F811 clean, diff --check clean; NOT committed (per instruction). Deviation: no total/last-used — no cheap existing getter (see Uncertainties).

## Scope

`handlers/admin_ai.py::_show_ai_preset_view` — append a compact usage-stats block
(requests today / total + last-used timestamp if cheap) from EXISTING registry
getters only (grep preset_hourly_usage / llm_requests counters in
services/db/preset_registry.py + cost_tracking.py; one cheap read per render, no
new tables, no new callback routes, no new buttons). Masking/escaping via spans.

## Tests

- Integration test pins stats block presence + values from seeded usage;
zero-usage preset renders graceful empty (no crash on missing rows).

## Acceptance

- [ ] stats visible on preset view; no new buttons/routes/queries-per-render
- [ ] full suite green; `hamzaban-reviewer` 0 confirmed findings
