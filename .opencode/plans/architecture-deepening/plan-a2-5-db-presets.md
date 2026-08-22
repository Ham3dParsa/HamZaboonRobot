STATE: phase 1/4 — status: locked — focus: R6 preset upsert registry + R8 settings seam

## CONTRACT LOCK TEMPLATE

Rule #1
Decision: 19-column list single source in schema.py
Option Chosen: A — _AI_PRESETS_COLUMNS in schema.py only
Alternatives Rejected: B keep 4 copies — drift risk
Trade-offs: A one file change for new column; B 4 files
Owner Confirmation: "Proceed with As" (2026-08-21)
GATE STATUS: LOCKED

Rule #2
Decision: Build upsert via helper
Option Chosen: A — build_preset_upsert() from single list
Alternatives Rejected: B manual strings — typo risk
Owner Confirmation: "Proceed with As"
GATE STATUS: LOCKED

Rule #3
Decision: Settings writes via set_setting
Option Chosen: A — route 16 preset_registry upserts through settings.set_setting
Alternatives Rejected: B keep direct — bypasses seam
Owner Confirmation: "Proceed with As"
GATE STATUS: LOCKED

Rule #4
Decision: Scope R6+R8 together
Option Chosen: A — one PR
Alternatives Rejected: B two PRs — overhead
Owner Confirmation: "Proceed with As"
GATE STATUS: LOCKED

## Dependency & Wiring Map
| Dependency | Items | Disposition |
|---|---|---|
| DB tables | ai_presets, settings | keep |
| Functions | _AI_PRESETS_COLUMNS, set_preset, clone_preset, _init_ai_presets_table, 16× settings upserts | update to use helpers |
| Imports | services/db/settings.set_setting | add |
| Tests | test_single_source_of_truth, preset tests | update/add |

## Plan
- RED: tests for helper builds same SQL, settings writes call set_setting
- GREEN: implement helper + replace upserts
- Validation + Kilo
- PR # -> MERGED, update tracker A2-5/A2-7
