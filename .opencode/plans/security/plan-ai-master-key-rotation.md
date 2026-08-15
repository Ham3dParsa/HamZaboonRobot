---
name: ai-master-key-rotation
description: Rotate AI_MASTER_KEY without an outage via a re-wrap-on-startup sweep (single previous key, fail-closed)
created: 2026-08-15
base_commit: 2b1315f
branch: pending (deferred)
status: deferred
---

STATE: DEFERRED — blocked on `feat/srs-staged-reveal` releasing its Seam 1 (Persistence) claim. Design locked 2026-08-15; do not implement until Seam 1 is free.

## Problem

Changing or revoking `AI_MASTER_KEY` today makes every stored (Fernet `v1:`) API key
undecryptable at once (fail-closed) -> full AI provider outage, and no way to
recover without re-entering every provider key. Goal (owner): change the master
key **without an outage**, recoverable, no manual re-entry.

## Locked Contract (owner decisions 2026-08-15)

| Rule | Decision | Option | Detail |
|---|---|---|---|
| R1 | Old key supplied via one env var | A (owner deferred choice; selected as simplest+safe) | `AI_MASTER_KEY_PREVIOUS` holds the immediately-previous master key. Document in `.env.example`. |
| R2 | Re-wrap runs at startup | A | Before serving, an idempotent sweep decrypts each stored key with current or previous key and re-encrypts under current. Skips tokens already decryptable under current key. |
| R3 | Scope = all three stores | fixed | Re-wrap covers `ai_presets.api_key`, `preset_groups.api_key`, and `settings.ai_api_key`. |
| R4 | Unrecoverable tokens | A | Preserve token untouched (fail-closed, no destruction), log a warning, and report a count of keys still needing re-entry at startup. |

Dependency & Wiring Map: no callback prefixes / keyboards / router changes. Touches
`services/db/key_crypto.py` (new re-wrap helpers), a sweep routine over
`ai_presets`/`preset_groups`/`settings` (persistence), `config/__init__.py`
(load `AI_MASTER_KEY_PREVIOUS`), a startup hook, `.env.example`, and tests.
Data transformation only — no schema change.

## Why deferred

- Parallel-work guard: this writes to **Seam 1 (Persistence)**, already claimed by
  `feat/srs-staged-reveal`. Owner chose **wait** for that branch to release the claim.
- Same blocking relationship as Phase 6/7 preset work.

## Steps (once unblocked)

- [ ] Load contract-lock-gate + parallel-work-guard; re-confirm Seam 1 free; acquire claim.
- [ ] Add `AI_MASTER_KEY_PREVIOUS` to config + `.env.example`.
- [ ] Implement re-wrap helpers in `services/db/key_crypto.py` (idempotent, fail-closed).
- [ ] Implement startup sweep across the three stores (immediate/exclusive transaction).
- [ ] Startup report of unrecoverable-key count (R4).
- [ ] Tests: rotation happy path, no-old-key fail-closed, idempotency, fresh + upgraded DB, multi-key stores.
- [ ] Independent review + validation + commit + PR.

## Blocked Questions

- Whether to also add an admin-panel manual "Run re-wrap" action later (out of current scope).