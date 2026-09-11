---
name: plan-dim3-ab-calibration-locked
description: Locked A/B calibration params for dimension 3 (window, threshold, rotation)
created: 2026-09-07
base_commit: ab8163d
branch: docs/dim1-lock
status: in-progress
---
STATE: dim 3/7 — status: LOCKED — focus: params frozen; implementation follows dims 1,5,6 pattern when ordered

## Contract Lock — Dimension 3 (owner locked 2026-09-07, issue #467)

GATE STATUS: LOCKED for dimension 3.

- Attribution window: 3 hours (push_sent_at <= session_started_at <= +3h). Rationale: instant effect; longer windows credit organic habit returns (false attribution).
- Decision threshold: 40 successful session starts per variant (80 conversions total). Rationale: distinguishes 10-15 point response gaps at 90% confidence; 30 is jittery.
- Rotation: fixed per user per ISO calendar week, hash(user_id + ISO_week) mod variants. Rationale: kills message fatigue (weekly change) and spillover (no daily switch).
- Assignment is deterministic with zero storage; outcome joins reuse existing session-start rows.

## Evidence
- Gemini proposal + owner plain-language confirmation 2026-09-07.
- dims 1,5,6 LOCKED; dim 2 HALF-LOCKED; dim 4 SEMI-LOCKED; dim 7 PENDING.

## Blocked Questions
- None on dim 3 params. Implementation needs push scheduler scope (dim 11 flag) before any A/B code runs.
