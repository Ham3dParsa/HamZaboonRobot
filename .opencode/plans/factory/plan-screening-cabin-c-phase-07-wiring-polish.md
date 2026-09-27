---
name: plan-screening-cabin-c-phase-07-wiring-polish
description: T10 paths+T3 wiring+format + T11 validation+collision + T12 cross-cabin inheritance
created: 2026-09-27
base_commit: 03c6af6f30696b176d04c53fbaca70a2a8e92840
branch: refactor/webui-static-phase1
status: locked
---

STATE: phase 7/7 — status: locked — focus: T10+T11+T12, no code yet

## Ticket T10 — paths T3 wiring + formatting sweep (UX-22/23/24, UX-25/26/27-consume, OQ-9-consume) [Wave 3 · SERIAL after T07 · PARALLEL-safe vs T11]

- **Blocking edges:** T07 (metrics/log DOM), T02 (formatters). Downstream: T12.
- **Scope (files):** `factory/webui/static/js/telemetry/telemetry_dashboard_controller.js` (`renderPaths :48-72` — consume `files.{kaikki_raw,screened}` facts: exists/size/lines/mtime or titled `—`); `screening_cabin_controller.js` (`renderMetrics/splitDropReasons` — prefer `drop_reasons`, keep sidecar fallback until proven; elapsed via `elapsed_human`); `server.py` `_list_dir`/`_file_facts` already extended in T09; `tests/factory/test_webui_data_root.py` + live-browser extend.
- **Rule (locked):** every `—` carries a `title` cause (unrecorded / missing-file / over-cap), zero bare dashes in paths + metrics; dead roots drop with count message; log box never bare «نرسید» (idle/live/final + cause). Route-delete: remove old fallback readers ONLY with proof in same PR.
- **Tests:** roots response with facts → 4 values/row; missing file → titled empty; over-cap lines → `۵۰۰۰۰+`.
- **Wiring rows:** `/api/files/roots.files → paths table cols 3-4`; `manifest.drop_reasons → twins/proper cards`; `elapsed_human → badge`.

### Acceptance criteria

- **Interaction tests (named):** IT-T10-01 paths table shows exists/size/`۵۰۰۰۰+`/mtime per row from live response; IT-T10-02 remove a root dir → row gone, badge count matches; IT-T10-03 every `—` on page has a title cause (DOM audit); IT-T10-04 log box states idle→live→final each with correct text.
- **Screenshots:** `shot-t10-paths-desktop.png` + `shot-t10-paths-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_webui_data_root.py tests/factory/test_webui_live_browser.py -n 8`

## Ticket T11 — intake validation + collision dialog + upload (UX-3/4/5/10, OQ-2/5/6, UX-17-consume) [Wave 3 · SERIAL after T07/T09 · PARALLEL-safe vs T10]

- **Blocking edges:** T07 (A1/A2), T09 (dialog host for collision + upload entry). Downstream: T12.
- **Scope (files):** `server.py` (`_screening_parse_words` `:5010-5016` — multiline+comma split, 2500 fail-fast with excess count; name sanitize fa+lat+digits+`-`+`_` → `-`; new `POST /api/files/upload` allowlisted-dirs-only into data root); new `collision_dialog` in `data_dialog_controller.js` (4 options: auto-`name_v2` / forced-overwrite-with-confirm / fresh-name-inline / full-cancel); `tests/factory/test_screening_intake.py` (new).
- **Rules (locked):** OQ-2 2500 cap = fail-fast 3-part fa error with excess count, NO silent trim. Collision NEVER silent overwrite — dialog BEFORE spawn, choice explicit, second same-name run without dialog impossible. Upload lands under data root only, re-selectable (UX-3/6). Invalid name chars → `-` with live sanitized preview (OQ-6).
- **Tests:** 2501 words → 400 + excess count, zero spawn; each of 4 collision options → correct outcome, first output intact; upload outside allowlist → 400.
- **Wiring rows:** `A1 text → parse(2500 cap) → run | 3-part error`; `run name check → collision dialog → spawn/overwrite/rename/cancel`; `upload → data root → dialog re-pick`.

### Acceptance criteria

- **Interaction tests (named):** IT-T11-01 paste 2501 words → fa error with excess `۱`, no run spawned; IT-T11-02 bad row → error cites row number; IT-T11-03 run `demo` twice → dialog with 4 options → each option verified (v2 created / overwrite confirmed / inline rename / cancel, first output intact); IT-T11-04 upload file → lands under data root → re-pickable from dialog.
- **Screenshots:** `shot-t11-collision-desktop.png` (4-option dialog) + `shot-t11-collision-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_screening_intake.py -n 8`

## Ticket T12 — cross-cabin inheritance + final polish (UX-11/28/29/30/31/32, OQ-10) [Wave 3 · SERIAL after T10+T11]

- **Blocking edges:** T10 + T11 (final DOM/contracts to conform). Downstream: none (program end).
- **Scope (files):** linking/precard/pilot views (name+dest+collision field names, busy, handoff, error-box, honest-empty titles — same strings, no synonyms); `cabins.css` (shared tokens only); `tests/factory/test_webui_live_browser.py` (cross-cabin assertions).
- **Rule (locked, OQ-10):** unconditional inheritance — field names `واژه‌ها/نام خروجی/مقصد/شروع/توقف/تحویل` byte-identical; every server button `withBusy`; every success a handoff banner with path + next-cabin button; every form error in the 3-part box; every `—` titled from the shared list. Polish only — no new endpoints, no behavior change beyond conformance.
- **Tests:** cross-cabin sweep: field-name equality, busy on all server buttons, handoff per completed output, zero bare `—`, zero off-box errors.
- **Wiring rows:** `T07/T08/T09/T10/T11 contracts → linking/precrad/pilot views (same names/shapes)`.
- **Changed / not changed / uncertain:** conformance edits only. NOT changed: cabin logic, schemas, endpoints. Uncertain: none — deviations found become follow-up tickets, never silent fixes.

### Acceptance criteria

- **Interaction tests (named):** IT-T12-01 open each cabin → field names byte-identical; IT-T12-02 click every server button → busy `در حال…`, no double-click; IT-T12-03 complete each cabin output → handoff banner with path + next button; IT-T12-04 trigger each error → inside 3-part box with retry + copy-report.
- **Screenshots:** `shot-t12-cabins-desktop.png` (all cabins) + `shot-t12-cabins-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_webui_live_browser.py -n 8`
