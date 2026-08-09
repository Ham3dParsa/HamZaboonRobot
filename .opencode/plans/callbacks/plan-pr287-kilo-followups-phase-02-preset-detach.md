---
name: pr287-kilo-followups-phase-02-preset-detach
description: Add pending-save detachment of one custom AI preset from its group.
created: 2026-08-09
base_commit: a871300
branch: fix/admin-ai-presets-audit
status: ready
---

STATE: phase 2/3 - status: ready - focus: implemented, validation passed, pending commit

## Parent

Parent specification issue: #288.
Ticket issue: #290.

## Blocked By

None - can start immediately. This ticket is implemented second only to keep commits small and easy to review.

## What To Build

An admin editing a custom preset with a group label can press a Persian “remove from group” button. The action affects only that preset, stages an empty group label in the existing pending-edit state, and takes effect only after the existing Save confirmation. Discard leaves the stored label unchanged. Group-wide clear behavior does not change.

## Rules

- Contract Rule 3 and the unused keyboard-import portion of Rule 5.
- New callback: `admin:ai_preset:detach_group:<preset-ref>`.
- The primary field-by-field edit keyboard is the only detach entry point in this scope.
- The detach callback accepts only a currently resolvable preset hash; stale tokens are rejected without falling back to a raw preset name.
- The preset Save transaction persists the empty staged label, supports an optional rename, and removes the old shared key if the preset was that group's final member. No schema change is needed.
- Starting Full Edit with pending direct edits is rejected until the admin saves or discards them.
- A rename Save verifies its destination name remains free inside the transaction; conflicts are rejected without overwriting another preset.
- Full Edit and detach are session-wide exclusive: any pending direct edit blocks Full Edit, and any active Full Edit blocks detach.
- Batch label operations and the separate preset-manager tool are deliberately out of scope for orphan-key cleanup.

## Testing

- Verify the keyboard emits the detach action for a grouped custom preset.
- Route an owner callback through the admin AI callback seam and assert feedback and staged state.
- Save the staged detach and assert only the chosen preset loses its label.
- Verify Discard leaves the stored label unchanged.
- Verify a stale detach token cannot target a hash-named preset.
- Verify detaching the final member deletes its shared key while detaching one of several members retains it.
- Verify rename-plus-detach is atomic from the persistence seam and cannot leave a stale old row or shared key.
- Verify Full Edit cannot start while direct edits are pending.
- Verify a late rename collision leaves both presets and the pending detach unchanged.
- Verify a detach cannot stage while Full Edit is active for the same preset.
- Verify the same guards apply when the pending edit or active wizard belongs to another preset.
- Update the wiring guard for the new action and run its reverse-wiring check.

## Acceptance Criteria

- [ ] A grouped custom preset has a per-preset detach button.
- [ ] Clicking it stages, rather than immediately persists, an empty group label.
- [ ] Saving detaches only that preset; its peers retain their group labels.
- [ ] Discarding does not mutate stored data.
- [ ] A stale detach token cannot act on another preset.
- [ ] No orphaned shared key remains after the final member is detached.
- [ ] Rename-plus-detach does not have a partial persistence path.
- [ ] Full Edit cannot bypass or retain a staged detach.
- [ ] A late rename collision cannot overwrite another preset.
- [ ] A detach callback cannot create pending edits during Full Edit.
- [ ] Cross-preset direct edits and Full Edit cannot create competing staging state.
- [ ] Callback wiring and handler-level integration coverage pass.
- [ ] Full validation and wiring/dead-reference guards pass before commit.

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | New `admin:ai_preset:detach_group:` action | update |
| Router branches | Owner-gated admin dispatcher; AI preset sub-router | keep / update |
| Keyboard builders / constants | Custom-preset edit keyboard; detach label | update |
| DB tables / columns / functions | Existing `group_label` field through Save; orphaned shared-key cleanup | update |
| Handler functions | Per-preset detach action | update |
| Imports / re-exports | Keyboard codec import | remove unused symbol |
| Prompts / formatting helpers | Static Persian callback feedback | keep |
| Tests | Keyboard, routing, integration, wiring | update |
| Docs / issues | Parent / ticket status | update |
