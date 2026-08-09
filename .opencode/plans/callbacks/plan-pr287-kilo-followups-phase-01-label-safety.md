---
name: pr287-kilo-followups-phase-01-label-safety
description: Make group-label callback selections safe and repair non-HTML confirmation rendering.
created: 2026-08-09
base_commit: a871300
branch: fix/admin-ai-presets-audit
status: ready
---

STATE: phase 1/3 - status: ready - focus: group-label callback and escaping safety

## Parent

Parent specification issue: #288.
Ticket issue: #289.

## Blocked By

None - can start immediately.

## What To Build

An admin sees exact label text in a successful group-rename confirmation. If a group-label picker button is stale because its label no longer resolves, it gives a safe not-found response and cannot alter the full-edit wizard or create a garbage group label. Existing URL-encoded plain-label callbacks remain usable.

## Rules

- Contract Rules 1, 2, 5, and 6.
- No new callback prefix is added in this phase.
- No database schema or AI behavior changes.

## Testing

- Prove a stale hash is rejected without modifying staged wizard values or persistence.
- Prove the rename confirmation shows a literal dynamic label without HTML entities.
- Retain legacy plain-label resolution coverage.
- Cover `html_escape(None)` and falsy values.
- Remove the dead mock from the cap-validation test.

## Acceptance Criteria

- [ ] Dynamic group-label rename confirmations do not show literal HTML entities.
- [ ] An unresolved hash cannot become a `group_label` value.
- [ ] Existing non-hash label callback payloads still resolve.
- [ ] Focused handler, codec, formatting, and awaiting tests pass.
- [ ] Full validation and wiring/dead-reference guards pass before commit.

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | Existing `full_edit_pick_group` / group-manager label payloads | update |
| Router branches | AI preset sub-router label resolution | update |
| Keyboard builders / constants | None | keep |
| DB tables / columns / functions | Existing preset Save path | keep |
| Handler functions | Label resolver, full-edit picker, rename confirmation | update |
| Imports / re-exports | Formatting / test imports | update / remove |
| Prompts / formatting helpers | Plain-text Persian confirmation; `html_escape` | update |
| Tests | Codec, admin awaiting, formatting, integration | update |
| Docs / issues | Parent / ticket status | update |
