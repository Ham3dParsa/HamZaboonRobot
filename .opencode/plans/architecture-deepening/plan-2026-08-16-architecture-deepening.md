# Plan: Architecture Deepening + Bug/Bottleneck Audit (11 jobs, 3 tracks)

STATE: IN_PROGRESS (DB track A J-A1/A2/A3 MERGED; DB **continuation pipeline** of 13 tickets A2-1..A2-13 tracked in plan-2026-08-17-db-remaining.md; AI track B + Routing track C owned by other sessions)
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

## DB Track Continuation (serial pipeline, 13 tickets)

The 11-job roadmap's DB track ended at J-A3 (R3). The source audit `2026-08-16-db-domain-consolidated.md` contained a broader backlog; a `hamzaboon-db` subagent verified (origin/main @ `c6bd1de`) that **13 items remain open/partial** (BUG-B2 already fixed elsewhere). These are tracked as a **serial pipeline** in `plan-2026-08-17-db-remaining.md` — NOT parallel sessions (all claim Persistence #1; many overlap on schema.py/words.py/users.py). Order: A2-1 → A2-2 → (A2-3,A2-4) → (A2-5,6,7) → (A2-8,9) → (A2-10,11,12,13). A2-13 additionally claims #17 and serializes against the two active word-query worktrees.

| Ticket | Item | Seam | Status |
|---|---|---|---|
| A2-1 | BN1 global RLock→WAL (HIGH-RISK) | Persistence #1 | planned (gate pending; #372 merged) |
| A2-2 | BUG-B3/BN4 due_words read-only | Persistence #1 | planned |
| A2-3 | R2 normalize_word NFC | Persistence #1 | planned |
| A2-4 | BUG-B1 $ENV runtime resolve | Persistence #1 | planned |
| A2-5 | R6 preset upsert registry | Persistence #1 | planned |
| A2-6 | R7 quota helper | Persistence #1 | planned |
| A2-7 | R8 settings upsert seam | Persistence #1 | planned |
| A2-8 | R9 CardModeService | Persistence #1 | planned |
| A2-9 | R10 __init__ facade split | Persistence #1 | planned |
| A2-10 | R11 app_today/key-resolver | Persistence #1 | planned |
| A2-11 | BN2 composite SRS index | Persistence #1 | planned |
| A2-12 | BN3 get_presets no api_key | Persistence #1 | planned |
| A2-13 | BUG-B4 to_thread in word_query | Persistence #1 + #17 | planned |

## Critical path
J-C1 (routing) has MERGED (#375) and its claim released, so **J-B2 is now unblocked**. J0.2 has also merged (#376 + safety follow-up #378), unblocking J-A3. Remaining AI-track work: J-B2 (`refactor/preset-field-registry`) and J-B3 (`fix/tts-voice-align`). J0.2's safety follow-up addressed two Kilo findings (by-reference return, dead else-branch).

## Source reports (locked designs live here)
- docs/audit/Deepening/2026-08-16-db-domain-consolidated.md
- docs/audit/Deepening/2026-08-16-ai-config-consolidated.md
- docs/audit/Deepening/2026-08-16-handlers-routing-consolidated.md
- Matching .html files in same folder.
