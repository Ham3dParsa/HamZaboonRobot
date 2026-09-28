---
name: plan-screening-cabin-c-phase-03-ledger-preview
description: T03 — screened_registry.jsonl ledger + fresh/duplicate preview endpoint (ADD-10)
created: 2026-09-27
base_commit: 03c6af6f30696b176d04c53fbaca70a2a8e92840
branch: refactor/webui-static-phase1
status: locked
---

STATE: phase 3/7 — status: implemented-uncommitted — focus: T03 ledger + preview, code+tests+screenshots in worktree feat/screening-cabin-c (no commit)

## Ticket T03 — ledger `screened_registry.jsonl` + preview (ADD-10, UX-5) [Wave 1 · PARALLEL-safe vs T01/T02/T04]

- **Blocking edges:** none. Downstream: T07 (A3 preview pane + run payload flag).
- **Scope (files):** `factory/linking/export_screened.py` (append `{lemma, out_dir, created_at, run_id}` lines on success — atomic `open("a")` per run); `factory/webui/server.py` (new `GET /api/screening/ledger_preview?words=` → `{fresh:[...], duplicate:[...], fresh_count, dup_count}` read from `<DATA_ROOT>/screened_registry.jsonl` on W; `POST /api/screening/run` accepts `reprocess_duplicates: bool`, default false → filters words to fresh-only); `tests/factory/test_screening_ledger.py` (new).
- **Rule (locked):** registry path = `<DATA_ROOT>/screened_registry.jsonl` (W root, via `data_root()` single source — no second resolver). Preview is read-only, never mutates. Default run processes fresh-only; duplicates need explicit `reprocess_duplicates:true` from A3 toggle. Registry write best-effort (never fails a successful export).
- **Tests:** export twice → second preview shows `X تازه، Y تکراری`; run without flag skips dups; run with flag includes them; missing registry → all fresh.
- **Wiring rows:** `export_words → screened_registry.jsonl (append)`; `/api/screening/ledger_preview → A3 pane`; `run{reprocess_duplicates} → export argv words (filtered)`.
- **Changed / not changed / uncertain:** adds ledger + endpoint + run flag. NOT changed: JSONL output format, manifest. Uncertain: none — lemma identity is exact lowercase match (documented, not fuzzy).

### Acceptance criteria

- **Interaction tests (named):** IT-T03-01 paste 5 words incl. 2 previously screened → A3 shows `۳ تازه، ۲ تکراری`; IT-T03-02 start with default → only 3 fresh processed, manifest words == 3; IT-T03-03 enable «پردازش مجدد تکراری‌ها» → all 5 processed.
- **Screenshots:** `shot-t03-ledger-desktop.png` (A3 preview states) + `shot-t03-ledger-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_screening_ledger.py -n 8`
