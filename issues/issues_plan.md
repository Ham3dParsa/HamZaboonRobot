# Project Status Tooling Plan

## Overview

The project-status model keeps `issues/issues.json` canonical for engineering
records and adds `project_status.json` as the machine-readable phase and
decision index. `issues/project_status.html` is a lightweight, read-only
joined dashboard generated from those sources.

Structured changes go through `issues/status_editor.py`. It accepts a
reviewable JSON patch, validates the complete resulting model, shows a diff,
and updates only canonical JSON plus explicitly marked generated views. The
human-written narrative sections of `ROADMAP.md` remain protected.

## Current strengths

- Phase, category, status, priority, and decision-lock views
- Canonical JSON ownership is explicit
- `issues/validate.py check` detects invalid records and stale generated views
- `status_editor.py` supports reviewable preview/apply changes
- Generated roadmap status is confined to marked boundaries
- No browser-local status or editing workflow can become a competing source

## Current boundaries

- The editor is intentionally patch-file based; there is no browser form
  editor.
- Markdown narrative and machine-readable references still require deliberate
  review.
- The dashboard is an embedded generated view rather than a live JSON server.
- A browser editor should be added only if the patch workflow proves
  insufficient.

## Supported workflow

1. Prepare a `changes.json` patch containing `issues`, `phases`, and/or
   `decisions` arrays.
2. Run:

   ```bash
   .venv/bin/python issues/status_editor.py preview changes.json
   ```

3. Review the complete diff.
4. Apply only after review:

   ```bash
   .venv/bin/python issues/status_editor.py apply changes.json --confirm
   ```

5. Run the repository test suite and:

   ```bash
   .venv/bin/python issues/validate.py check
   ```

The editor updates `issues/issues.json`, `project_status.json`, the optional
Markdown issue export, the dashboard’s embedded data, and the marked generated
status block in `ROADMAP.md` together. It never rewrites the roadmap’s
narrative sections.

## Example patch

```json
{
  "issues": [
    {
      "id": 54,
      "status": "partial",
      "evidence": "Mitigation landed; richer validation remains."
    }
  ],
  "phases": [
    {
      "id": "phase-4",
      "status": "in-progress"
    }
  ],
  "decisions": []
}
```

## Future consideration

A local browser editor may be useful later for non-technical project
management. If added, it must use the same patch/preview/validation boundary;
it must not write arbitrary Markdown or maintain browser-persisted status.
