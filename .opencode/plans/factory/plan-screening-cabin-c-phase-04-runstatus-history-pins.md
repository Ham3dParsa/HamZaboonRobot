---
name: plan-screening-cabin-c-phase-04-runstatus-history-pins
description: T04 run-status disk file + T05 history endpoint + T06 pinned_paths.json
created: 2026-09-27
base_commit: 03c6af6f30696b176d04c53fbaca70a2a8e92840
branch: refactor/webui-static-phase1
status: locked
---

STATE: phase 4/7 — status: partial (T06 implemented-uncommitted; T04+T05 untouched, per Wave-1 order) — focus: T06 pins in worktree feat/screening-cabin-c (no commit)

## Ticket T04 — run-status disk file, reconnect (UX-20, OQ-8) [Wave 1 · SERIAL before T05]

- **Blocking edges:** none. Downstream: T05 (history reads the same store), T07 (reconnect banner + resume poll).
- **Scope (files):** `factory/webui/server.py` (`_SCREENING` lifecycle `:4976-5178` + new CABIN-PARAMETRIC `factory/webui/run_status.py` store owner: `write(cabin, ...)/status_path(cabin)/read(cabin)`); run-status file `<DATA_ROOT>/webui/<cabin>_run_status.json` (this ticket: `cabin="screening"` → `screening_run_status.json`: `{run_id, pid, started_iso, out_dir, out_name, words_hash, status}`); `tests/factory/test_screening_runstatus.py` (new, incl. a second-cabin key test proving no cross-talk).
- **Rule (locked):** status written on spawn, updated on settle (completed/failed/aborted), fsync per write, atomic tmp+replace. `GET /api/screening/status` merges disk state when no in-memory proc (refresh/restart → same run_id, log tail + progress recovered from out_dir). PID valid only for liveness probe — never kill-by-guess (existing abort path unchanged).
- **Tests:** spawn → file exists with running; kill -9 server proc in test → fresh snapshot reads disk state; completed run → status + manifest summary recovered.
- **Wiring rows:** `api_screening_run → run_status.write`; `_screening_snapshot → run_status.read (fallback)`; `status → T07 reconnect banner`.

### Acceptance criteria

- **Interaction tests (named):** IT-T04-01 start run → refresh page mid-run → live status + log tail resume on SAME run (no empty state); IT-T04-02 restart console process mid-run → status shows run with `started_iso` + recovered progress; IT-T04-03 completed run → refresh shows final metrics, not idle.
- **Screenshots:** `shot-t04-reconnect-desktop.png` (resumed live view) + `shot-t04-reconnect-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_screening_runstatus.py -n 8`

## Ticket T05 — history endpoint on W (ADD-11 backend) [Wave 1 · SERIAL after T04]

- **Blocking edges:** T04 (same store/format). Downstream: T08 (history tab).
- **Scope (files):** `factory/webui/server.py` (new CABIN-PARAMETRIC `GET /api/runs/history?cabin=` → per-run records `{run_id, out_name, out_dir, started_iso, status, kept_total, dropped_total}` scanned from `<DATA_ROOT>/webui/<cabin>_runs/` + T04 status file for that cabin; newest last; this ticket wires `cabin="screening"`); `tests/factory/test_screening_history.py` (new, incl. unknown-cabin 400 + cross-cabin isolation).
- **Rule (locked):** history is a READ view over run dirs + registry — no new write path. Missing/corrupt record → skipped with count in `skipped` field (never 500). Cap 500 records, `truncated:true` beyond.
- **Tests:** 3 seeded runs → ordered list; corrupt dir → skipped + counted; empty → `runs:[]`.
- **Wiring rows:** `<cabin>_runs/ + run_status(cabin) → /api/runs/history?cabin= → T08 table`.

### Acceptance criteria

- **Interaction tests (named):** IT-T05-01 history endpoint with 3 runs → tab lists 3 newest-last with kept/dropped; IT-T05-02 per-record «تحویل به کابین بعدی» arms linking cabin with that run's path; IT-T05-03 corrupt run dir → row skipped, `skipped:1` shown honestly.
- **Screenshots:** `shot-t05-history-desktop.png` + `shot-t05-history-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_screening_history.py -n 8`

## Ticket T06 — `pinned_paths.json` shared pins (UX-15, OQ-4) [Wave 1 · PARALLEL-safe vs T04/T05]

- **Blocking edges:** none (disjoint module). Downstream: T09 (dialog pins UI).
- **Scope (files):** new `factory/webui/pinned_paths.py` (owner: load/save/add/remove under `<DATA_ROOT>/webui/pinned_paths.json`); `server.py` (`GET/POST/DELETE /api/files/pins`); `tests/factory/test_webui_pins.py` (new).
- **Rule (locked):** shared factory file per OQ-4 (all consoles/worktrees see same pins). Entries `{name, path, kind: dir|file}`; paths validated under data root OR existing browse roots; atomic tmp+replace writes; DELETE needs exact name (no destructive cascade).
- **Tests:** add → persists across two store instances (simulated restart); invalid path → 400; remove → gone.
- **Wiring rows:** `pinned_paths.* ↔ /api/files/pins ↔ T09 dialog pins section`.

### Acceptance criteria

- **Interaction tests (named):** IT-T06-01 pin a folder → close + reopen console → still pinned; IT-T06-02 pin from dialog row → appears in pins section with given name; IT-T06-03 unpin → removed, no other pins touched.
- **Screenshots:** `shot-t06-pins-desktop.png` (dialog pins section) + `shot-t06-pins-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_webui_pins.py -n 8`
