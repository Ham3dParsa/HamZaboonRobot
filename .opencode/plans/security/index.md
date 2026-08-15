---
name: security
scope: Encryption-at-rest and master-key operations (AI_MASTER_KEY rotation/re-wrap, key lifecycle).
---
## Plans & Dependency Edges
| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-ai-master-key-rotation.md` | 1 | `feat/srs-staged-reveal` (must release Seam 1 first) | `deferred` |