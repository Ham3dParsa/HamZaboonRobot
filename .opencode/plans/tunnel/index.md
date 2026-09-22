---
name: tunnel
scope: Permanent provider-aware tunnel-selection module (select/prove/remember) and ordered caller migration
---

## Plans & Dependency Edges

| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-tunnel-selection.md` | 01-foundation (T1–T3) | — (root) | `draft` |
| `plan-tunnel-selection-phase-02-probes.md` | 02-probes (T4) | `tunnel/plan-tunnel-selection-phase-01-foundation.md` | `draft` |
| `plan-tunnel-selection-phase-03-linker.md` | 03-linker (T5) | `tunnel/plan-tunnel-selection-phase-02-probes.md` | `draft` |
| `plan-tunnel-selection-phase-04-precard.md` | 04-precard (T6) | `tunnel/plan-tunnel-selection-phase-03-linker.md` | `draft` |
| `plan-tunnel-selection-phase-05-pilot.md` | 05-pilot (T7) | `tunnel/plan-tunnel-selection-phase-04-precard.md` | `draft` |
| `plan-tunnel-selection-phase-06-web.md` | 06-web (T8) | `tunnel/plan-tunnel-selection-phase-05-pilot.md` | `complete` |

Chain is serial across phases by locked rule R6 (probes → linker → precard → pilot → web last).
Parallelism exists only inside Phase 01 (T2 ∥ T3 after T1). Registry untouched throughout.
