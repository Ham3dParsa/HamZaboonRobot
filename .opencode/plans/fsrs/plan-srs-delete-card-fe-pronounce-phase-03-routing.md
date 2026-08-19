---
name: srs-delete-card-fe-pronounce-phase-03-routing
description: Phase 3 — register srs:delete:* callback prefixes (Rule 6)
created: 2026-08-19
base_commit: 6305c18
branch: feat/srs-delete-card
status: in-progress
---
STATE: phase 3/5 — status: in-progress — focus: register srs:delete: / :yes: / :no: in services/routing.py

## Blocking edges
- Phase 2 (keyboards emit the exact prefix strings `srs:delete:`, `srs:delete:yes:`, `srs:delete:no:`).

## Scope
- `services/routing.py` (R1 central registry): register the three prefixes → handlers in `handlers/srs_handler.py` (`_handle_srs_delete`, `_handle_srs_delete_yes`, `_handle_srs_delete_no`). Longest-prefix match, owner-gate, single-answer guarantee per AGENTS §4.
- Verify the actual dispatch path (services/routing.py vs bot.py callback_router) for existing `srs:` routes and register consistently.

## Tests
- `tests/test_wiring.py`: assert `srs:delete:`, `srs:delete:yes:`, `srs:delete:no:` are registered and resolve to the handlers; reverse-wiring guard (every keyboard prefix has a router match) passes.

## Gates
- Satisfies Rule 6 (callbacks + routing).

## Wiring rows
| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | `srs:delete:`, `srs:delete:yes:`, `srs:delete:no:` | add |
| Router branches | `services/routing.py` (R1) | add |

## Acceptance criteria
- The three prefixes resolve to their handlers and are covered by `tests/test_wiring.py`.