# Plan: Architecture Deepening + Bug/Bottleneck Audit (11 jobs, 3 tracks)

STATE: IN_PROGRESS (DB track A COMPLETE as of 2026-08-17 — J-A1/A2/A3 merged; AI track B + Routing track C owned by other sessions)
THEME: architecture-deepening
TICKET: arch-deepening

## Operating rules (survives compaction)
- Each job runs in its OWN git worktree + PR; lightweight contract lock taken from the consolidated report (no re-grill). Owner says `proceed`/`locked` per job. Do NOT merge.
- parallel-work-guard: canonical seam names ONLY from SEAMS.md. Shared registries (catalog identifiers, callback prefixes, settings keys) are NOT claimable — coordinate via the manual waits below, never invent a seam name.
- Before every acquire: resolve `git rev-parse --git-common-dir`, read `<common-dir>/parallel-work-claims.json`, verify zero unresolved claim by a different branch on the same seam; STOP+report on overlap. Release claim after merge.
- Update THIS plan's STATUS column + theme index STATE after each step. Rebase worktree onto origin/main after each merged PR.

## Roadmap

| Job | Track | Canonical seam(s) claimed | Manual-wait depends on | Exec | Status | Branch / PR |
|---|---|---|---|---|---|---|
| J-A1 | A (DB) | Persistence | — | done | MERGED | refactor/transaction-seam |
| J0.1 | B (AI) | none (catalog = non-claimable registry) | — | done | MERGED (PR #370) | refactor/catalog-registry |
| J0.2 | B (AI) | none (settings keys non-claimable) | J0.1 merged | serial | MERGED (PR #376 + safety follow-up #378) | refactor/settings-inventory |
| J-A2 | A (DB) | Persistence (only; NOT "Telegram UI -> Plans") | J-A1 merged | parallel | MERGED | refactor/plan-semantics |
| J-B1 | B (AI) | AI/LLM Provider | J0.1 merged | parallel | MERGED (PR #373, squash a964770) | fix/ai-provider-hardening |
| J-A3 | A (DB) | Telegram UI -> User Domain (only) | J0.2 + J0.1 merged | parallel | MERGED (PR #377, squash `436ffd2`) | refactor/display-toggle-store |
| J-B2 | B (AI) | Telegram UI -> AI Config | J0.1 merged + J-C1 merged (#375) & released | serial (after B1) | UNBLOCKED (awaiting gate) | refactor/preset-field-registry |
| J-B3 | B (AI) | TTS Provider | J0.1 merged + J-B2 merged | serial | PENDING | fix/tts-voice-align |
| J-C1 | C (Routing) | Telegram UI -> Admin, Stats, Plans, Cost, AI Config | — | STARTED | IN_PROGRESS (holds AI Config until merged+released) | refactor/callback-router |
| J-C2 | C (Routing) | Telegram UI -> User Domain, Admin, Stats, Plans, Cost, AI Config | J-C1 merged & released | serial | PENDING | refactor/awaiting-namespace |
| J-C3 | C (Routing) | Telegram Callback Notifications | J-C1 merged & released | serial (after C2) | PENDING | refactor/reply-escape-seam |

## Critical path
J-C1 (routing) has MERGED (#375) and its claim released, so **J-B2 is now unblocked**. J0.2 has also merged (#376 + safety follow-up #378), unblocking J-A3. Remaining AI-track work: J-B2 (`refactor/preset-field-registry`) and J-B3 (`fix/tts-voice-align`). J0.2's safety follow-up addressed two Kilo findings (by-reference return, dead else-branch).

## Source reports (locked designs live here)
- docs/audit/Deepening/2026-08-16-db-domain-consolidated.md
- docs/audit/Deepening/2026-08-16-ai-config-consolidated.md
- docs/audit/Deepening/2026-08-16-handlers-routing-consolidated.md
- Matching .html files in same folder.
