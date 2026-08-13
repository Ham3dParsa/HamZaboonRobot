---
name: session
scope: SRS study-session UX — staged reveal, randomized prompts, and the granular display-toggle system.
---

## Plans & Dependency Edges

| Plan | Phase | Depends On | Status |
|---|---|---|---|
| `plan-srs-staged-reveal-spec.md` | spec | FSRS phase-06 release (T09 live smoke) + AI-preset branch releasing Persistence/Admin seams | `locked-spec` |

## Release Boundaries

This theme's implementation must NOT begin until:
1. The AI-preset branch (`feat/ai-preset-phase4-builtin-removal`) releases the **Persistence** and **Telegram UI -> Admin** seams (parallel-work-guard claim), AND
2. The FSRS phase-06 release gate (T09) is closed (live session flow verified).

The spec itself is locked and tracked as an issue; only coding is deferred.
