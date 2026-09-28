# Phase 02 — Gallery build module (P02)

Gates: R6 (gallery for current + old runs via existing viewer).
Blocking: none (W1). Feeds: P05 (gallery button), P07 (path wiring).

## Scope (new files only — `viewer.py` core untouched)

- `factory/webui/gallery.py`: `gallery_sources(run_ref)` → locate stored link-table TSV + verdicts/labels for a run id or explicit paths (current `runs/` + history registry); `build_gallery(run_ref)` → call `viewer.build_linker_gallery(rows, verdicts, out_html)` with output next to sources (`gallery.html`, cached; rebuild only when sources newer); honest `FileNotFoundError` (farsi message) when TSV absent — never fake rows.
- Old runs: same function over any run dir in history (this is the «history-native» requirement).

## Tests

- `tests/factory/test_webui_gallery.py`: build from fixture TSV+verdicts (small, synthetic); cache-hit no rebuild; missing TSV raises honest error; old-run-shaped dir works.

## Wiring rows

| Type | Item | Disposition |
|---|---|---|
| New module | `factory/webui/gallery.py` | create |
| Read-only caller | `factory/linking/viewer.py::build_linker_gallery` | keep (no change) |
| Routes | `GET /api/gallery?run=` | mount by coordinator after W1 (server.py, additive) |

## Acceptance

Own tests green; gallery HTML opens standalone in browser from fixture; `git status` shows only the 2 new paths.
