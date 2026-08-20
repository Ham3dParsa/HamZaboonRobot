# Canonical Remaining-Work Plan — Architecture Deepening (ACTIVE tracker)

STATE: ACTIVE — this is the SINGLE SOURCE OF TRUTH for the 3 coordinated sessions (A=DB, B=AI, C=Routing).
THEME: architecture-deepening
DATE: 2026-08-19
VERIFIED GROUND TRUTH: `git` HEAD = `3ece608`; `gh pr list --state open` = empty → all prior architecture-deepening PRs are MERGED; every item below marked REMAINING is NOT yet in a PR.
SOURCE REPORTS (locked designs live here):
- docs/audit/Deepening/2026-08-16-db-domain-consolidated.md
- docs/audit/Deepening/2026-08-16-ai-config-consolidated.md
- docs/audit/Deepening/2026-08-16-handlers-routing-consolidated.md
- Reconciliation evidence: docs/audit/Deepening/2026-08-19-remaining-work.md
This file supersedes the audit snapshot and the stale rows in plan-2026-08-16-architecture-deepening.md.

## Execution model (3 coordinated sessions)
- Session A = DB track · Session B = AI-config track · Session C = Routing track.
- Each item: own git worktree + PR; per-item CONTRACT-LOCK gate (owner `proceed`/`locked`); do NOT merge.
- parallel-work-guard: canonical seam names ONLY from SEAMS.md (`Persistence`, `AI/LLM Provider`, `Telegram UI -> AI Config`, `Telegram UI -> Plans`, `TTS Provider`, `Telegram UI -> Admin/Stats/Cost/User Domain`, `Telegram Callback Notifications`, `Custom-word query orchestration`). Shared registries (catalog identifiers, callback prefixes, settings keys) are NOT claimable — coordinate by manual waits.
- Before every acquire: `git rev-parse --git-common-dir`; read `<common-dir>/parallel-work-claims.json`; verify zero unresolved claim by a DIFFERENT branch on the same seam; STOP+report on overlap. Release claim after merge.
- SHARED-DOC RULE (cross-session sync): after EVERY commit AND every PR open/merge, the owning session updates the STATUS + PR/Branch columns in THIS file, and rebases its worktree onto `origin/main` after each merge. This file is the only sync artifact between the 3 sessions.

## Track assignment & seam reality (collision-proof)
- **A (DB):** every item claims `Persistence` (#1) → strictly SERIAL (one active worktree at a time). No intra-track parallelism.
- **B (AI):** items claim `AI/LLM Provider` (#2) and/or `Telegram UI -> Plans` (#10) and/or utils (non-numbered). BOT-* (#2) can run parallel to F8/RT-B3 (#10); both differ from DB/Routing seams → B may run 2 items concurrently if seams differ.
- **C (Routing):** items claim handler seams (#5/#6/#8/#15) + callback codec → strictly SERIAL (all touch bot.py/handlers).

## Per-item execution table

### DB track — Session A (serial, Persistence #1)
| Item | Report ID | Seams | Depends-on | Exec | Status | PR / Branch |
|---|---|---|---|---|---|---|
| R1 transaction() | R1 | Persistence | — | done | MERGED #371 | refactor/transaction-seam |
| R3 DisplayToggleService | R3 | Persistence | — | done | MERGED #377 | refactor/display-toggle-store |
| R5 plan-semantics | R5 | Persistence | — | done | MERGED #372 | refactor/plan-semantics |
| BUG-B2 hourly_usage growth | BUG-B2 | — | — | done | ADDRESSED elsewhere | excluded |
| A2-1 BN1 RLock to WAL (HIGH-RISK) | BN1 | Persistence | — | serial | MERGED #415 | refactor/db-concurrency |
| A2-2 BUG-B3 + BN4 due_words | BUG-B3/BN4 | Persistence | A2-1 | serial | MERGED #425 | refactor/due-words-read-split |
| A2-3 R2 normalize_word NFC | R2 | Persistence | A2-1/2 | serial | MERGED #434 | refactor/db-normalize |
| A2-4 BUG-B1 $ENV resolve | BUG-B1 | Persistence | A2-1/2 | serial | PLANNED (contract next) | (tbd) |
| A2-5 R6 preset upsert registry | R6 | Persistence | — | serial | PARTIAL/PLANNED | refactor/db-presets |
| A2-6 R7 quota helper | R7 | Persistence | — | serial | PARTIAL/OTHER | refactor/db-presets |
| A2-7 R8 settings upsert seam | R8 | Persistence | — | serial | PLANNED | refactor/db-presets |
| A2-8 R9 CardModeService | R9 | Persistence | — | serial | PLANNED (build on #361) | refactor/db-cardmode |
| A2-9 R10 __init__ facade split | R10 | Persistence | — | serial | PLANNED (Speculative) | refactor/db-cardmode |
| A2-10 R11 app_today/key-resolver | R11 | Persistence | — | serial | PLANNED | refactor/db-integration |
| A2-11 BN2 composite SRS index | BN2 | Persistence | — | serial | PLANNED | refactor/db-integration |
| A2-12 BN3 get_presets no api_key | BN3 | Persistence | — | serial | PARTIAL/PLANNED | refactor/db-integration |
| A2-13 BUG-B4 to_thread word_query | BUG-B4 | Persistence + #17 | — | serial (after A2-12) | PLANNED (serialize vs word-query branches) | refactor/db-integration |
| G1 DB-offload in handlers | RT-BN2/BN3+RT-B2 | Persistence + #5/#6 | A2-13 | serial | PLANNED (after A2-13; coordinate word-query branches) | refactor/db-handler-offload |

### AI-config track — Session B
| Item | Report ID | Seams | Depends-on | Exec | Status | PR / Branch |
|---|---|---|---|---|---|---|
| F1 preset-field registry | F1/R1 | AI Config (#12) | — | done | MERGED #383 | refactor/preset-field-registry |
| F2 create_client seam | F2/R2 | AI/LLM Provider (#2) | — | done | MERGED #373 | fix/ai-provider-hardening |
| F3 TTS voice to catalog | F3/R3 | TTS Provider (#13) | — | done | MERGED #384 | refactor/tts-voice-catalog |
| F4 prompt prelude | F4/R4 | AI/LLM Provider (#2) | — | done | MERGED (in main) | — |
| F5 plan-identity | F5/R5 | AI Config (#12) | — | done | MERGED #387 | refactor/plan-identity |
| F7 LimiterStore | F7/R7 | AI/LLM Provider (#2) | — | done | MERGED #373 | fix/ai-provider-hardening |
| BUG-1..3,5,6,7 | — | AI/LLM Provider (#2)/TTS (#13) | — | done | MERGED #373/#384 | — |
| F6/R6 + BUG-4 MDV2 choke | F6/R6,BUG-4 | utils (formatting) + bot.py/study/srs imports | — | done | MERGED #423 | refactor/mdv2-render-choke |
| F8/R8 + RT-B3 FieldRegistry to plans | F8/R8,RT-B3 | Telegram UI -> Plans (#10) + admin.py (#8) | — | done | MERGED #429 | refactor/field-registry-plans |
| BOT-1/2/3 AI cache/amplification | BOT-1/2/3 | AI/LLM Provider (#2) | — | done | MERGED #432 | refactor/ai-cache-amplification |
| BOT-4 log overflow | BOT-4 | AI/LLM Provider (#2) | — | done | MERGED #432 | (folded into BOT-1/2/3) |

### Routing track — Session C (serial)
| Item | Report ID | Seams | Depends-on | Exec | Status | PR / Branch |
|---|---|---|---|---|---|---|
| RT-R1 routing registry | RT-R1 | Admin/Stats/Plans/Cost/AI Config (#8-#12) | — | done | MERGED #375 | refactor/callback-router |
| RT-B1 double-notify | RT-B1 | callback (#15) | — | done | MERGED #375 | refactor/callback-router |
| RT-R2 awaiting namespace | RT-R2 | User/Admin/Stats/Plans/Cost/AI Config (#7-#12) | — | done | MERGED #382 | refactor/flows |
| RT-R3 reply() seam | RT-R3 | Callback Notifications (#15) | — | done | MERGED #385 | refactor/send-pretty |
| RT-B4 effective_message None | RT-B4 | Callback Notifications (#15) | — | done | MERGED #385 | refactor/send-pretty |
| RT-B2 finish send_pretty transfer | RT-B2 | Callback Notifications (#15) + handlers | — | serial | MERGED #414 | refactor/send-pretty-finish |
| RT-R4 USER_ACTIVITY log | RT-R4 | handlers (user/srs) | — | serial | MERGED #428 | refactor/activity-log-consolidate |
| RT-R5 keyboard ownership + codec | RT-R5 | callback codec / keyboards | — | serial | MERGED #431 | refactor/keyboard-ownership |
| RT-B3 double HTML-escape | RT-B3 | Plans (#10) + admin.py (#8) | — | serial | done (with F8/R8) | MERGED #429 |
| RT-B5 early awaiting reset | RT-B5 | bot.py | — | serial | MERGED #433 | refactor/early-awaiting-reset |
| RT-BN1 broadcast semaphore | RT-BN1 | Admin (#8) | — | serial | MERGED #437 | refactor/broadcast-semaphore |
| RT-BN2/BN3 handler DB-offload | RT-BN2/BN3 | Persistence + #5/#6 | — | — | REMAINING to G1 (Session A) | refactor/db-handler-offload |

## Gaps (must be planned — no current owner)
- **G1 (critical):** synchronous SQLite on event-loop in `srs_handler.py`/`study_handler.py` (RT-BN2/BN3 + RT-B2 remainder). Assigned to Session A after A2-13; claims `Persistence` (#1) + handler seams, serialize vs word-query branches.
- **G2:** F6/R6 + BUG-4 (`_phonetic_lines` private import, MDV2 render choke) — Session B.
- **G3:** F8/R8 + RT-B3 (FieldRegistry generalize to plans; double HTML-escape) — Session B (shares RT-B3 with C; coordinate). **DONE via #429 (2026-08-20).**
- **G4:** BOT-1/2/3 (AI read-amplification, cost/usage caching) — Session B. **DONE via #432 (2026-08-20).**
- **G5:** RT-R4, RT-R5, RT-B5, RT-BN1 done (#428/#431/#433/#437) — Session C complete.

## Overlaps (avoid duplication)
- **OVL-2:** A2-8 (R9 CardModeService) MUST build on CARD-MODES #361 resolver (already shipped in `users.py`+`catalog.py`) — do NOT re-create the resolver (violates AGENTS.md §3 single-source).
- **OVL-3:** A2-13 (BUG-B4) claims `Custom-word query orchestration` (#17); serialize against active word-query branches (`feat/word-query-card-consistency`, `refactor/word-query-deep-module`, `fix/ask-word-ai-timeout`).
- **OVL-4:** RT-R1 ↔ `callback-wiring` skill — every registry change locked by `tests/test_wiring.py`.
- **OVL-5:** RT-R3 ↔ CB-NOTIFY-01 (#310) + HELP-01 (#342) — outbound + notify share seam #15.

## Cross-track blockers (the only real ones)
1. **A2-13 ↔ word-query branches** (seam #17) — A2-13 must not touch `word_query.py` until those branches merge/release.
2. **A2-8 ↔ CARD-MODES #361** — build-on, not duplicate.

## RT-B2 follow-up (remaining outbound bypasses)
Kilo review of PR #414 flagged 44 outbound sites that still bypass the `send_pretty` seam (43× `update.message.reply_text` + 1× `update.effective_message.edit_reply_markup`), out of RT-B2 scope. Tracked under umbrella **#416**:
- #417 RT-ADMINAI (admin_ai.py, 21)
- #418 RT-ADMIN (admin.py, 11) — serialize vs Session A G1 / Session B RT-B3
- #419 RT-PLANS (admin_plans.py, 6) — serialize vs Session B RT-B3
- #420 RT-COST (admin_cost.py, 4)
- #421 RT-LEARNER (study_handler.py + srs_handler.py, 2) — unblocked (#414 merged)

## Status counts (synced to 3ece608)
- DB: 4 addressed / 3 partial / 11 remaining (+ G1 gap).
- AI: 12 addressed / 0 partial / 7 remaining.
- Routing: 7 addressed / 1 partial / 5 remaining (RT-BN2/BN3 folded into G1).
- Total: 21 addressed, 4 partial, 25 remaining of 50 enumerated items.
