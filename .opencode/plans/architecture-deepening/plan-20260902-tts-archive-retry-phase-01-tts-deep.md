---
name: plan-20260902-tts-archive-retry-phase-01-tts-deep
description: Deep TTS service — single seam for lock+cache+channel+fallback
created: 2026-09-02
base_commit: e477a02
branch: feat/tts-deep
status: in-review
---

STATE: phase 1/3 — status: in-review (2026-09-03) — rebased onto origin/main af7adae (#533); full suite 1643 passed + 324 subtests, compile_all + ruff F821/F811 + diff-check clean; PR pending owner merge

## Blocking Edges
- Depends on: none (root)
- Blocks: phase-03 (retry consolidation needs stable TTS seam)

## Scope
- New module `services/tts_service.py` (or deepen `services/tts.py` to `services/tts/service.py`): `async speak(word, lang, *, bot, chat_id, reply_to)` + `async handle_callback(update, context, data)` + `resolve_word(source, parts, user_id)`
- Move `config/__init__.py:219-260` resolve_tts_cache_chat_id + `services/tts_cache.py` async wrappers + `helpers._send_voice_with_retry` channel branch inside service
- `bot.py:1056-1296` _handle_tts_pronounce collapses to 3 lines delegation; remove `to_thread(get_cached)` duplication, remove outer lock (already 7887e6a), remove `is_owner` duplicate check
- `tts_cache.db` init moved from bot.py:1349 into service init (or services/db/schema)
- `_ensure_voices` warmup outside per-key lock (asyncio.Event)

## Contract Rules
- R1: Single owner for per-key lock + cache + channel — services/tts_service.py owns, bot.py delegates
- R2: No business logic in config/ — resolve_tts_cache_chat_id leaves config, stays in service
- R3: tts_cache get/put become async-native (hide to_thread inside service)

## Tests
- tests/test_integration/test_tts_deep.py: concurrent pronounce same key from different users -> one channel upload, one file_id hit; Forbidden on channel falls back to direct send
- Update tests/test_voice_p0_fix.py to target service seam, tighten channel snippet check
- tests/test_wiring.py: tts:pronounce prefix still via bot.py BUILTIN but delegation verified

## Wiring Rows
| Prefix | Registry | Handler |
|--------|----------|---------|
| tts:pronounce: | services/routing BUILTIN (bot.py:144) | services/tts_service.handle_callback |

## Acceptance
- pytest 1598+ pass, no deadlock on concurrent cache miss, log shows `speak kind=file_id_hit|generated`
- Grep `tts_cache` outside services/tts* returns 0 outside owner
- Handler no longer imports `tts._get_tts_lock`

## Gates
- ruff F821/F811 clean, compile_all pass, wiring guard pass

## Evidence (2026-09-03)
- Rebased feat/tts-deep onto origin/main af7adae clean (no conflicts).
- bot.py _handle_tts_pronounce = 3-line delegation; `_send_voice_with_retry` import removed; tts_cache db init via `ensure_tts_cache_db()`.
- Service owns `_SPEAK_LOCKS` per-key lock (only upload-dedup lock) + `_speak_locked`; sends via phase-03 `_send_media_with_retry` (no `idempotent=`, no duplicate loops).
- config/__init__.py keeps thin delegates (admin callers intact); to_thread get/put only in service.
- tests/test_integration/test_tts_deep.py (6 tests) + retargeted test_voice_p0_fix + service-seam test_tts_daily_action_removed.
- Full suite: 1643 passed, 324 subtests; compile_all, ruff F821/F811, diff-check clean.
- Review: Task tool unavailable in this env; reviewer checklist self-applied — 0 confirmed bugs (1 trivial observation: _SPEAK_LOCKS unbounded per-word, restart-safe).
