STATE: deferred — do NOT implement without a locked contract (architecture seam move).

# Ticket: centralize keyboard `api_key` masking below the `config/` layer

Source: PR #551 reviews — opencode-agent[bot] issues/551/comments/5533384799
`[warning]` (nested `_mask_api_key` duplicated canonical `mask_key()` owned
by `services/db/key_crypto.py:133`, diverging on empty input).

## What PR #551 already did
`config/keyboards/admin.py::ai_preset_edit_keyboard` now imports and reuses
canonical `mask_key()` (deferred import, matching the existing
`callback_codec` pattern) for both stored-value and draft-value rendering,
and the local `_mask_api_key` duplicate was deleted in the same PR
(route-delete). Single-source test (`tests/test_single_source_of_truth.py`)
passes — imports are consumers, not definitions.

## Remaining work (this ticket)
Move masking *out* of `config/` entirely, per AGENTS.md §3: "NO business
logic in `config/`" — `config/` is static metadata + env bindings.
Options for the locked contract:
1. Keyboard takes pre-rendered display strings (caller in `handlers/`
   masks via `mask_key` before calling) — preferred: keeps `config/`
   pure data, thinnest diff.
2. A `services/`-owned keyboard-text helper (e.g. `services/ai/preset_display.py`)
   that `config/keyboards` delegates to — new module needs §4 table +
   `tests/test_wiring.py` scan-target + `SEAMS.md` updates (module change guard).
3. Keep the deferred `mask_key` import (status quo) — cheapest, but leaves a
   `services.db` import inside `config/keyboards`, against the layering rule.

## Why deferred (NOT trivially safe)
- Architecture decision with module-guard fallout (§4 table, wiring scan
  targets, `parallel-work-guard/SEAMS.md`); needs owner choice per §2
  numbered-rules gate, not a silent refactor.
- Stack conflict: PR #551 (`fix/preset-draft-indicator`, unmerged at ticket
  time) owns the exact hunks this move would rewrite — landing this first
  would rebase-conflict 551. Sequence AFTER #551 merges.
- Behavior surface: empty-key rendering (`mask_key("") == "—"`) vs the
  keyboard's current empty-means-no-suffix convention must be pinned by
  contract + snapshot tests before moving.

## Acceptance criteria for the future PR
1. No `services.*` import inside `config/keyboards/*` (grep clean).
2. Masked/unmasked rendering byte-identical to post-551 snapshots
   (`tests/test_integration/test_admin_ai_render_flow.py` masking tests green
   unmodified, or updated in the same PR per test-sync with obsolete-classified
   diffs).
3. `tests/test_single_source_of_truth.py` + `tests/test_wiring.py` green;
   §4 module table + `SEAMS.md` updated if a new module is added.
