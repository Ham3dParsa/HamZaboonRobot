---
name: plan-screening-cabin-c-locked
description: Scenario C lock doc — layout zones, D rejection, UX-1..32 traceability, open-items-none
created: 2026-09-27
base_commit: 03c6af6f30696b176d04c53fbaca70a2a8e92840
branch: refactor/webui-static-phase1
status: locked
---

STATE: LOCKED — Scenario C approved, Scenario D rejected, 12 tickets in 7 phases across 3 waves, zero open items.

## 1. Locked layout — Scenario C

Sticky right control column (never covered, never scrolled away) + left workspace with TWO co-equal tabs + slide-over data dialog + tablet smart accordion.

- **Control column (right, sticky):** A1 bulk intake (textarea LTR + file-pick + upload + live count preview) · A2 output name + destination (visible defaults, sanitized preview) · A3 ledger preview (`X تازه، Y تکراری` + fresh-only default + explicit reprocess toggle) · A4 run/abort (busy-state buttons, `withBusy`).
- **Workspace (left), tab 1 — live run + results:** status badge + human duration + live log `<pre>` (3 states: idle / live tail / final tail) + metric cards (input/kept/dropped + twins-R3 + proper-R2) + per-lemma table with `FilterableListController` + row-click detail pane + `N نمایان از M سطر` counter + handoff banner.
- **Workspace (left), tab 2 — history/lineage:** per-cabin run table on W (search/filter live, no server round-trip) + per-record `تحویل به کابین بعدی` button.
- **Data dialog (slide-over):** global console dialog for file-input / output-dest picking; tree browse from `<DATA_ROOT>`; docks to the side, NEVER covers the control column.
- **Tablet smart accordion:** control column collapses to accordion sections above workspace; order A1→A2→A3→A4 preserved; dialog becomes full-sheet.

## 2. Scenario D — REJECTED (rationale on record)

D placed intake + naming + destination for ALL cabins in one shared top strip (domain-boundary violation: one form owning every cabin's output contract), crowded the strip with 4-option collision + ledger preview on small widths (input crowding), and squeezed the per-lemma table + detail pane into leftover space (review-space squeeze — the operator's primary surface). C keeps each cabin owning its own A1–A4 column, gives the review table the full workspace width, and isolates the dialog from controls. Decision final; D not to be revived without a new owner lock.

## 3. Requirement traceability (UX-1..UX-32 + locked decisions → tickets)

| ID | Requirement (short) | Ticket |
|---|---|---|
| UX-1, UX-5 | bulk textarea, comma-or-line split, live count = sent count | T07 (+T11 cap) |
| UX-2, UX-6 | file pick from dialog, wordlists under data root | T07+T09 |
| UX-3 | upload into data root, re-selectable | T11 |
| UX-4 | Persian 3-part validation, row numbers, no run on invalid | T11 |
| UX-7, UX-9 | output name, auto time-stamped default, visible defaults | T07 |
| UX-8 | dest pick from dialog, default under data root, final path announced | T07+T09 |
| UX-10 | collision 4-option dialog (`name_v2` / forced overwrite / fresh name / cancel), never silent | T11 |
| UX-11 | same name+dest+collision pattern in later cabins | T12 |
| UX-12, UX-13 | global dialog, data-root start, missing roots drop out | T09 (+T06 pins) |
| UX-14 | per-file size/lines-cap/`۵۰۰۰۰+`/mtime, no aggregate folder sizes | T09 |
| UX-15 | pinned paths persist across sessions | T06+T09 |
| UX-16 | per-row pick-as-input / pick-as-dest returns to caller form | T09 |
| UX-17 | no destructive ops in web; mkdir+rename only, allowlisted upload dirs | T09+T11 |
| UX-18, UX-21 | per-lemma live filter (no server call) + visible-of-total counter | T07 |
| UX-19 | row click → detail (counts + dropped sense_ids + reason, no gloss text per OQ-7) | T01+T07 |
| UX-20 | reconnect after refresh/restart via disk run-status | T04+T07 |
| UX-22, UX-23, UX-24 | paths table from live `files` facts, titled honest empties, dead roots drop | T10 |
| UX-25 | human duration (fa digits), never raw float | T02 (+T10 render) |
| UX-26 | manifest `drop_reasons` (twin-R3 / proper-R2 / other), sum == dropped_total | T01 (+T10 render) |
| UX-27 | log box 3 states, never bare «نرسید» | T07 (+T10) |
| UX-28..UX-32 | identical names/empties/busy/handoff/error-box across cabins | T12 |
| OQ-2 | 2500-word cap, fail-fast with excess count, no silent trim | T11 |
| OQ-4 | pins shared at `<DATA_ROOT>/webui/pinned_paths.json` | T06 |
| OQ-5 | collision default = instant 4-option dialog | T11 |
| OQ-6 | name charset fa+lat+digits+`-`+`_`, invalids → `-` with preview | T11 |
| OQ-8 | disk run-status (pid/start/dest), reconnect + log/progress recovery | T04 |
| OQ-9 | smart relative time + dual calendar (Jalali+Gregorian, Asia/Tehran + UTC labels) | T02+T10 |
| OQ-1/OQ-3 | mkdir+rename allowed, delete blocked, upload from allowlisted dirs only | T09 |
| OQ-7 | lemma detail = counts + dropped sense_ids + reason | T01 |
| OQ-10 | unconditional inheritance for linking/precard/pilot cabins | T12 |
| ADD-10 | `screened_registry.jsonl` on W + `X تازه، Y تکراری` preview, fresh-only default | T03 |
| ADD-11 | per-cabin history table on W, live search, per-record handoff | T05+T08 |

## 4. Verified code facts (read, not assumed)

- Manifest writer `factory/linking/export_screened.py:113-121` emits only `kept_total/dropped_total/per_lemma` — no `drop_reasons`. Drops sidecar (`screened.drops.jsonl:101-106`) already carries per-sense `reason` — T01 aggregates, never re-derives.
- `server.py:5075-5082` `elapsed` is raw monotonic float; shape is `{screening:{status,elapsed,out_dir,...}}` (`server.py:5183-5192`).
- `/api/files/roots` returns `{roots, files}` with `files.{kaikki_raw,screened}` facts (`server.py:4459-4462,1721-1737`); UI consumes only `roots` (`telemetry_dashboard_controller.js:92-96`), last two columns hard-coded `—` (`:67-68`).
- Intake is single-line `input#screening-words`, sender posts only `{words}` (`index.html:405`, `screening_cabin_controller.js:247`); `out_dir` shown read-only though backend accepts it (`index.html:410`, `server.py:5135-5151`).
- `_SCREENING` is in-memory only (`server.py:4976-4978`) — refresh/restart loses runs (OQ-8 gap → T04).
- Static assets live flat in `factory/webui/static/` (`cabins.css` + `js/screening|shell|sense_linking|telemetry`) — no `static/css/` subdir.
- Reusable patterns: `FilterableListController` (`shell/filterable_list_controller.js:6`), `withBusy` + 3-part error box (`shell/api_client.js`), `queue-remaining` counter + handoff banner (`human_review_controller.js:40-50`, `screening_cabin_controller.js:274-280`).

## 5. Open items: NONE

All 10 OQ + ADD-10/ADD-11 decided (spec §6). No rule left to owner choice. What changes / deliberately not changed / uncertain is recorded per phase file (§6 of each).

## 6. Claim state (parallel-work-guard)

Shared registry `<git-common-dir>/parallel-work-claims.json` read 2026-09-27. Branch `refactor/webui-static-phase1` ALREADY HOLDS seam `factory/webui` (R1–R4, locked 2026-09-27). This program stays on the SAME branch — NO new claim acquired, none needed. Other claims (`feat/linker-viewer`, `feat/viewer-survival`, `refactor/provider-registry`) touch disjoint seams — zero overlap. SEAMS.md lists no finer factory/webui sub-seam; all 12 tickets share the held seam, ordered by waves/serial marks instead of claims.
