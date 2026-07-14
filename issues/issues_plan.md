# Issue Explorer Improvement Plan

## Overview
The project-status model keeps `issues/issues.json` canonical for engineering
records and adds `project_status.json` as the machine-readable phase and
decision index. `issues/project_status.html` is a lightweight, read-only
joined dashboard generated from those sources; it is not an editor.

## Audit Summary
### Current strengths
- Basic search over issue title, module, func, problem, and solution
- Priority-based filtering for high/medium/low and resolved issues
- LocalStorage persistence for edited issue state
- Import/export support for JSON and Markdown
- Fallback data loading from embedded `ISSUES_DATA` when `issues.json` is unavailable
- Canonical records already carry `roadmap_refs`, `status`, `priority`, and review metadata that can be reused for roadmap-aware organization

### Current gaps
- Search ignores useful fields: `note`, `status`, `id`, `roadmap_refs`, `evidence`, `last_reviewed`
- Search syntax is only plain substring matching with no multi-term or ID-specific search
- Filters are limited to priority/resolved and do not support open/partial, module, roadmap reference, or issue status filters
- No sort controls or explicit current-result count for the active filter/search
- No match highlighting for search terms inside issue cards
- Embedded dashboard data is only a generated fallback for opening the HTML
  file locally; it must never become a second status source
- Export operations do not support exporting only the current filtered set
- No quick “jump to issue ID” or issue navigation helper
- No explicit `phase` field in the issue schema, so roadmap-stage groupings are only inferred from `roadmap_refs`

## Improvement Goals
- Expand search scope and add issue ID matching
- Add richer filtering options: status, module, roadmap refs, and priority/resolved state
- Improve exploration UX with active result counts, sort control, and navigation shortcuts
- Align data loading so `issues.json` is the authoritative source and the HTML UI remains a thin viewer/editor
- Add filtered export support and minimize stale data risk
- Add explicit phase-aware organization without replacing `roadmap_refs`

## Proposed Feature List
1. Search improvements
   - Include `note`, `status`, `id`, `roadmap_refs`, `evidence`, and `last_reviewed`
   - Support numeric ID search like `id:12`
   - Support multi-term match and phrase search if feasible
   - Add search term highlighting inside issue cards
2. Filter improvements
   - Add status filters: `open`, `partial`, `resolved` plus existing priority filters
   - Add module/file filter dropdown or quick chip buttons
   - Add roadmap-ref filter capability
   - Preserve active filter state visibly in the UI
3. Sorting / navigation
   - Add sort-by controls for `id`, `priority`, `status`, and `module`
   - Show the count of matching issues and count of currently visible results
   - Add an “Go to issue ID” quick input or button
4. Data consistency and export
   - Make `issues.json` the single source of truth wherever possible
   - If embedded `ISSUES_DATA` remains, generate it from `issues.json` during build or export only when needed
   - Add export buttons for filtered results and optionally for current view only
5. Local UX polish
   - Add a small “clear search” button inside the search box
   - Add a tooltip or help text explaining filter/search behavior
   - Add a visual badge for `status` and `roadmap_refs` on each card
6. Phase-aware organization
   - Add an optional `phase` field to `issues.json` entries with values that map to roadmap stages or release phases
   - Surface `phase` as a badge/filter in the explorer UI
   - Validate that `phase` values and `roadmap_refs` stay aligned with `ROADMAP.md`

## Implementation Plan
1. Create or update `issues_plan.md` (this file) and document the feature scope.
2. Keep phase, category, status, priority, roadmap-reference, and decision-lock
   filters in `issues/project_status.html`.
3. Add UI controls in the `controls` bar for status and module filters, sort order, and ID search helper.
4. Extend the `render()` search logic to include all searchable fields and parse `id:` queries.
5. Add filtered export support to `exportAllMD()` and `exportAllJSON()`.
6. Change the data-loading flow so `fetch('./issues.json')` is the authoritative source and embedded fallback is explicitly secondary.
7. Add result-count text and visible filter state summary within the controls or header.
8. Test the dashboard locally by opening `issues/project_status.html` and
   verifying read-only filtering and phase/decision rendering.
9. If phase support is added, validate the explorer badge/filter behavior and ensure phase values remain backward compatible for older issue entries.

## Notes and Next Steps
- This plan is intentionally limited to issue explorer improvements and does not alter production bot logic.
- `issues/validate.py check` must reject unknown categories, phases, decision
  references, unassigned issues, and duplicate phase assignments.
- After implementation, a small acceptance checklist should be added to verify: search scope, filters, filtered export, and data-loading fallback.
