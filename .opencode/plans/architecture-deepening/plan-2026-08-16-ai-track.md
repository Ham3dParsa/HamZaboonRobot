# Plan: AI Track — Provider Hardening + Limiter (J-B1)

STATE: phase 1/1 — status: complete — focus: impl+review+commit+merge done; PR #373 MERGED (squash a964770); claim released

---
name: j-b1-ai-provider-hardening
description: J-B1 AI provider hardening — fail-closed client seam, real-token TPM, lazy LimiterStore, prompt compact unification.
created: 2026-08-16
base_commit: 6f375d7
branch: fix/ai-provider-hardening
status: in-progress
---

## Locked Contract (owner chose Option A on all four rules, "locked")

Source report: `docs/audit/Deepening/2026-08-16-ai-config-consolidated.md` (§F2/§F4/§F7 + BUG-1/BUG-2/BUG-3/BUG-5).

| Rule | Decision | Status | Notes |
|---|---|---|---|
| J-B1.1 | `create_client(preset=None, *, api_key_override=None)` single seam; key resolves ONLY via `db.resolve_preset_key` (fail-closed `""`); `_client` thin alias; `test_connection` routes through seam; removed `DEFAULT_AI_API_KEY` plaintext fallback (BUG-2/BUG-3). | complete | verified by reviewer; `test_ai_preset_api_key.py` rewritten to assert fail-closed. |
| J-B1.2 | Tracked AI calls return `TrackedResult(value, telemetry)`; `_log_preset_usage` reads real token usage (BUG-1 TPM); `_call_ai_limited` unwraps `.value`; direct callers (tools/tests) use `.value`. | complete | verified; annotations updated to `TrackedResult`. |
| J-B1.3 | `LimiterStore` replaces hidden `_get_limiter_for_preset._states`; lazy RPM/TPM/concurrency from live preset; semaphore rebuilt on `max_concurrency` change; `get_limiter_store()` + `reset()` for tests (BUG-5). | complete | verified; race fixed (capture slot ref in finally). |
| J-B1.4 | `prompts.card_output_is_compact()` single compact decision; `build_prompt_prelude` used by `daily_card_system_prompt` (byte-identical output); removed `_language_guidance`/`_level_guidance` wrappers; word_query + admin_ai custom-test route through helper (F4). | complete | verified byte-identical. |

## Review findings (hamzaboon-reviewer) → fixed
- [x] Type annotations on `repair_card`/`ask_json`/`ask_card`/`ask_batch` updated `-> TrackedResult` (was `-> dict`/`-> list[dict]`).
- [x] Semaphore rebuild race: capture `slot = limiter["slots"]`, release `slot` in `finally` (was re-reading dict entry).
- [x] `build_prompt_prelude` unused `lang_fa` removed (dead code).
- [x] `test_custom_word_query_uses_compact_helper` made hermetic via `mock.patch` on `AI_CARD_OUTPUT_FORMAT`.
- [note] `schema.py` still seeds `ai_api_key` setting with `DEFAULT_AI_API_KEY` (pre-existing, not a regression — runtime no longer reads it).
- [note] "injectable" claim is overstated: store is a module singleton with `reset()`; acceptable for tests.

## Evidence
- Tests: `tests/test_ai_limiter_hardening.py` (9 new), `tests/test_ai_preset_api_key.py`, `tests/test_fallback_flow.py`, `tests/test_fallback_backoff.py`, `tests/test_reliability.py`, `tools/benchmark/runner.py`, `tools/generate_cards.py` updated.
- Full suite: `python -m pytest tests/ -n 14` → 1045 passed.
- Daily-card prompt header byte-identical (verified programmatically).

## Blocked / waiting (downstream jobs, NOT part of this PR)
- J0.1 merged (PR #370) is prerequisite — already satisfied (branch fast-forwarded to origin/main).
- J-B2 waits on J-C1 merged+released; J-B3 waits on J-B2. Out of scope here.

## Final Verdict
- Done: J-B1.1 fail-closed create_client seam (BUG-2/BUG-3); J-B1.2 TrackedResult + real-token TPM (BUG-1); J-B1.3 LimiterStore with lazy limits + race-safe release (BUG-5); J-B1.4 card_output_is_compact() single source + build_prompt_prelude (F4), byte-identical daily-card output. All four rules verified by independent reviewer; low findings fixed.
- Deliberately Not Done: schema.py still seeds ai_api_key with DEFAULT_AI_API_KEY (pre-existing; runtime no longer reads it) — left untouched (scope: client seam only). LimiterStore not made fully injectable (reset() suffices for tests).
- Deferred: J-B2 (preset field registry, waits J-C1), J-B3 (TTS voice-map, waits J-B2). Not part of this PR.
- Uncertain: none.
