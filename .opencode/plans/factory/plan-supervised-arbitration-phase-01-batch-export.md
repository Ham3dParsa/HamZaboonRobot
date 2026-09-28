# Phase 01 — Batch export builder (P01)

Gates: R1 (batch shape carries what review needs), R2 (md+json carriers), R4 (lifecycle start, oldest-first, 10–50/default 25).
Blocking: none (W1). Feeds: P04, P05 (frozen contracts in main plan).

## Scope (new files only — never edit existing modules)

- `factory/webui/batches.py`: `build_batch(screened_path, size) -> BatchRecord`; `render_markdown(batch)`; `render_json(batch)`; `save_batch(batch)` under `<data_root>/webui/batches/<id>/`; `list_batches()`; status transitions `exported/cancelled` only in this phase.
- `factory/webui/supervised_prompt_v1.txt`: versioned system prompt (v1); sha256 over this file = `prompt_hash`.
- Item sourcing: read screened JSONL (tolerant parse, skip bad lines like `parse_run_events`); candidates via mechanical path (`factory/linking` build_link_index/lookup_link — read-only calls, no engine change); oldest-unjudged-first = screened order minus `sense_id`s already in `labels.jsonl` and in non-cancelled batches.
- Size clamp 10–50 (default 25); `ValueError` with `VALIDATION-*` message on bad size/empty queue.

## Tests

- `tests/factory/test_webui_batches.py`: oldest-first + dedup vs labels/batches; size clamp; md contains system block + version + hash + template; json round-trips items; bad lines skipped.

## Wiring rows

| Type | Item | Disposition |
|---|---|---|
| New module | `factory/webui/batches.py` | create |
| New data | `supervised_prompt_v1.txt` | create |
| Read-only callers | screened JSONL, mechanical linker, `labels.py::load_labels` | keep (no change) |
| Routes | `POST/GET /api/batches*` | mount by coordinator after W1 (server.py, additive) |

## Acceptance

`pytest tests/factory/test_webui_batches.py` green; `python -m compileall` clean on new files; ruff F821/F811 clean; no existing file modified (`git status` shows only the 3 new paths).
