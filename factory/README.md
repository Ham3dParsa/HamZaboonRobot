# Factory (lexicon) — map + backup policy

## Where things live (three homes, one truth per kind)
- **Code + small data (PR-bound):** this `factory/` dir — runners (`run_v14_*`, `run_v15*`, `run_v16*`),
  `registry.py`, `env_loader.py`, `test_registry_proof.py`, `packs/en/` (minus the Tatoeba pool),
  designs + evidence md. All committable, all small.
- **Big data (W: only):** `W:\hamzaban_data_factory\fixtures\` (ranked/uniq/topic/vectors JSONs, zips),
  `raw\` (Kaikki/Tatoeba dumps), `reports\`, `logs\`, `notebooks\`. Never committed; referenced by path.
- **Live state (worktree-local, NEVER committed):** `factory/registry.db` (the ledger),
  `factory/.env` (keys), `*_progress.json` (resume state). Gitignored by design.

## Backup policy (locked 2026-09-03)
- Before any cleanup/migration/scale-up: copy `registry.db` + `.env` + builders into
  `W:\hamzaban_data_factory\backups\<timestamp>\` (see W: README §Backups).
- The live DB is never opened from W: (SQLite locking) — W: copies are backup only.
- Restore = copy back + `python factory/test_registry_proof.py` green.
- `.env` backup is RESTRICTED: same disk only, never commit, never paste into chat/issues.

## Regeneration (no backup needed)
- Fixtures: `python factory/run_v14_phase1.py` (~7 min local GPU) → phases 2/3 scripts (need keys).
- Registry: `python factory/registry.py` (migration import, zero reprocessing).
- Big JSONs/zips/progress files are scratch: safe to delete once backed-up-or-regenerable.
