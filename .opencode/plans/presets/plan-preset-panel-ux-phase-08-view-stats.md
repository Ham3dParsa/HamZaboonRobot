---
name: plan-preset-panel-ux-phase-08-view-stats
phase: 8
gates: [U3]
blocking: [phase-07]
status: pending
---
STATE: phase 8 — status: pending — focus: view usage stats

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
