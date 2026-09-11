# Factory (lexicon) — map + backup policy + PishCard v13 line

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

## PishCard Pipeline v13 — precard line

Builds learner-ready EN precards (sense-picked + topic-tagged rows) from a
word sample. Deterministic stages first, one cheap AI judge (GLM), no
per-card reasoning burn.

## The 7 stages (ids are stable — files/progress keys never change)

| id | console label | does what | in | out |
|---|---|---|---|---|
| `s0` | preprocess (pishpardazesh) | drops names/junk, level-aware frequency floor | sample json | `progress/s0.json` |
| `s0b` | inflection (sarf) | flags inflection stubs for LLM review | s0 kept | `progress/s0b.json` |
| `s1` | anchor (langar) | deterministic sense ranking per lemma | s0b kept | `progress/s1.json` |
| `s2` | judge (davari) | GLM picks one sense per item (same prompt for all) | s1 window | `progress/s2.json` |
| `s3` | vectors (bordar) | topic vectors per picked sense | s2 picks | `progress/s3.json` |
| `s4` | label (barchasb) | CEFR/topic labels | s3 | `progress/s4.json` |
| `s5` | enrich (ghanasazi) | examples, IPA, Persian gloss | s4 | `progress/s5.json` → `precard.jsonl` |

Reading a run: the console speaks labels (`[STAGE judge (davari)]`);
`run.log` speaks ids (`stage s2 start`) — grep-friendly and stable.
Persian drop details go to `dropped.log`, never the console.

## Run

```powershell
# dry run, no keys, no network (first 20 items of your sample file)
python factory\precard_pipeline.py --sample W:\hamzaban_data_factory\pilot\sample200b.json `
  --out out\precard.jsonl --progress-dir out\prog --limit 20 --dry-run

# blind judge comparison on the frozen 50 (needs keys)
python factory\blind50.py --accept W:\hamzaban_data_factory\pilot\accept50.json `
  --s1 W:\hamzaban_data_factory\pilot200glm\progress\s1.json --glm-s2 W:\hamzaban_data_factory\pilot200glm\progress\s2.json `
  --out W:\hamzaban_data_factory\blind50\blind50.json --progress W:\hamzaban_data_factory\blind50\progress.json --dry-run
```

Keys: env vars win, then `factory\.env`, then `tools\egress\.env` (owner layout).
Three consecutive 429s stop the run — rotate key/server, re-run, resume
continues from `progress/*.json` (per-stage files named by stable id).

## Runbook — which script does what (all commands from repo root)

| I want to... | Script | Keys needed | Command |
|---|---|---|---|
| Dry-run the line (no cost) | precard_pipeline.py | none | `python factory\precard_pipeline.py --sample W:\hamzaban_data_factory\pilot\sample200b.json --out out\precard.jsonl --progress-dir out\prog --limit 20 --dry-run` |
| Full precard run (GLM judge via AvalAI) | precard_pipeline.py | AVALAI in factory/.env | same minus `--dry-run` (and `--limit` for full sample) plus `--llm-provider avalai` (covers all LLM legs; GLM is the AvalAI default, bare defaults run Zen) |
| Blind-compare 4 judges on the frozen 50 | blind50.py | GOOGLE + OPENROUTER (factory/.env or tools/egress/.env) | `python factory\blind50.py --accept W:\hamzaban_data_factory\pilot\accept50.json --s1 W:\hamzaban_data_factory\pilot200glm\progress\s1.json --glm-s2 W:\hamzaban_data_factory\pilot200glm\progress\s2.json --out W:\hamzaban_data_factory\blind50\blind50.json --progress W:\hamzaban_data_factory\blind50\progress.json` |
| Check key + egress health (no secrets printed) | probe_keys.py | factory/.env; ZEN keys + egress IP only (no SUB ranking, no GOOGLE/OPENROUTER/AVALAI check) | `python factory\probe_keys.py` |
| Rank SUB servers by latency | supervisor --probe | SUBs in tools/egress/.env | `python tools\egress\supervisor.py --probe --top-n 30` |
| Find Google-friendly servers | supervisor --probe-google | + GOOGLE key | `python tools\egress\supervisor.py --probe --top-n 30 --probe-google 15` |
| Serve leases to scripts | supervisor (serve) | + EGRESS_SUP_TOKEN | `python tools\egress\supervisor.py` (then `run_with_lease.py zen -- <cmd>`) |

## The 3 .env files — which serves what

| File | Read by | Holds | Never holds |
|---|---|---|---|
| `.env` (root) | bot runtime (`config/__init__.py`) | BOT_TOKEN, runtime AI key, DB_PATH, quotas | factory research keys |
| `factory/.env` | factory scripts (`env_loader.py`, `blind50.load_keys`) | ZEN x2, OPENROUTER, GOOGLE, AVALAI (`blind50` also falls back to `tools/egress/.env` for GOOGLE/OPENROUTER) | bot token |
| `tools/egress/.env` | supervisor only | EGRESS_SUB_URL(S), EGRESS_SUP_TOKEN (+ owner's spare LLM keys as fallback) | anything committed |

Rule of thumb: running the bot → root; running the line → factory; touching VPN/SUBs → egress. If a script says "missing key", this table tells you which file to open.

## Files

- `precard_pipeline.py` — the line (stages, gates G1–G6, resume).
- `card_pilot.py` — anchor scorer, kaikki readers, run logger.
- `probe_keys.py` — egress + key health check (no secrets in output).
- `blind50.py` — 4-way judge comparison (on main; needs keys, see runbook).
- `run_v14_phase*.py`, `run_v15_topics.py` — vendored scorer owners
  (rank logic lives here; do not re-implement elsewhere).
