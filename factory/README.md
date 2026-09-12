# Factory (lexicon) — map + backup policy + PishCard v13 line

## Where things live (three homes, one truth per kind)
- **Code + small data (PR-bound):** this `factory/` dir — `pipeline/` (precard line:
  `precard_pipeline.py`, `card_pilot.py`, `blind50.py`), `lexicon/` (sample/index/pool/judge/AWL),
  `core/` (`registry.py`, `env_loader.py`, `llm_json.py`, `telemetry.py`, `probe_keys.py`,
  `stage_glossary.py`), `archive/v14_v16/` (frozen `run_v14_*`, `run_v15*`, `run_v16*` runners +
  designs + evidence md), `packs/en/` (minus the Tatoeba pool). Tests live in `tests/factory/`.
  All committable, all small. Per-dir maps: `pipeline/README.md`, `lexicon/README.md`,
  `core/README.md`, `archive/README.md`.
- **Big data (W: only):** `W:\hamzaban_data_factory\fixtures\` (ranked/uniq/topic/vectors JSONs, zips),
  `raw\` (Kaikki/Tatoeba dumps), `reports\`, `logs\`, `notebooks\`. Never committed; referenced by path.
- **Live state (worktree-local, NEVER committed):** `factory/registry.db` (the ledger),
  `factory/.env` (keys), `*_progress.json` (resume state). Gitignored by design.

## Backup policy (locked 2026-09-03)

- Before any cleanup/migration/scale-up: copy `registry.db` + `.env` + builders into
  `W:\hamzaban_data_factory\backups\<timestamp>\` (see W: README §Backups).
- The live DB is never opened from W: (SQLite locking) — W: copies are backup only.
- Restore = copy back + `python -m pytest tests/factory/test_registry_proof.py` green.
- `.env` backup is RESTRICTED: same disk only, never commit, never paste into chat/issues.

## Regeneration (no backup needed)
- Fixtures: `python -m factory.archive.v14_v16.run_v14_phase1` (~7 min local GPU) → phases 2/3 scripts (need keys).
- Registry: `python -m factory.core.registry` (migration import, zero reprocessing).
- Big JSONs/zips/progress files are scratch: safe to delete once backed-up-or-regenerable.

## Namespace rule (locked 2026-09-11) — two counters, never one

Research snapshots keep their v-numbers frozen (`ranked_senses-v13a.json`,
`card-pilot-v12-*.html`, `run_v14_*`): never rename, never delete the
pinned live set below. Living outputs never take v-numbers — they take
kind prefixes (`precard-*`, `pilot-final*`). "PishCard v13" names the
13th line generation, unrelated to snapshot v13a.

Pinned live files (load-bearing defaults — do not delete/rename):
`fixtures/tatoeba_pool_v13a.json` (examples; missing file now warns
LOUD instead of silently disabling), `fixtures/topic_vectors-v16b.json`,
`fixtures/phrase_type_log.jsonl`. A missing default pool prints
`WARNING: default Tatoeba pool missing` — if you see it, restore from
`W:\hamzaban_data_factory\backups\`, do not silence it.

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
python -m factory.pipeline.precard_pipeline --sample W:\hamzaban_data_factory\pilot\sample200b.json `
  --out out\precard.jsonl --progress-dir out\prog --limit 20 --dry-run

# blind judge comparison on the frozen 50 (needs keys)
python -m factory.pipeline.blind50 --accept W:\hamzaban_data_factory\pilot\accept50.json `
  --s1 W:\hamzaban_data_factory\pilot200glm\progress\s1.json --glm-s2 W:\hamzaban_data_factory\pilot200glm\progress\s2.json `
  --out W:\hamzaban_data_factory\blind50\blind50.json --progress W:\hamzaban_data_factory\blind50\progress.json --dry-run
```

Keys: env vars win, then `factory\.env`, then `tools\egress\.env` (owner layout).
Three consecutive 429s stop the run — rotate key/server, re-run, resume
continues from `progress/*.json` (per-stage files named by stable id).

## Runbook — which script does what (all commands from repo root)

| I want to... | Script | Keys needed | Command |
|---|---|---|---|
| Dry-run the line (no cost) | pipeline/precard_pipeline.py | none | `python -m factory.pipeline.precard_pipeline --sample W:\hamzaban_data_factory\pilot\sample200b.json --out out\precard.jsonl --progress-dir out\prog --limit 20 --dry-run` |
| Full precard run (GLM judge via AvalAI) | pipeline/precard_pipeline.py | AVALAI in factory/.env | same minus `--dry-run` (and `--limit` for full sample) plus `--llm-provider avalai` (covers all LLM legs; GLM is the AvalAI default, bare defaults run Zen) |
| Blind-compare 4 judges on the frozen 50 | pipeline/blind50.py | GOOGLE + OPENROUTER (factory/.env or tools/egress/.env) | `python -m factory.pipeline.blind50 --accept W:\hamzaban_data_factory\pilot\accept50.json --s1 W:\hamzaban_data_factory\pilot200glm\progress\s1.json --glm-s2 W:\hamzaban_data_factory\pilot200glm\progress\s2.json --out W:\hamzaban_data_factory\blind50\blind50.json --progress W:\hamzaban_data_factory\blind50\progress.json` |
| Check key + egress health (no secrets printed) | core/probe_keys.py | factory/.env; ZEN keys + egress IP only (no SUB ranking, no GOOGLE/OPENROUTER/AVALAI check) | `python -m factory.core.probe_keys` |
| Rank SUB servers by latency | supervisor --probe | SUBs in tools/egress/.env | `python tools\egress\supervisor.py --probe --top-n 30` |
| Find Google-friendly servers | supervisor --probe-google | + GOOGLE key | `python tools\egress\supervisor.py --probe --top-n 30 --probe-google 15` |
| Serve leases to scripts | supervisor (serve) | + EGRESS_SUP_TOKEN | `python tools\egress\supervisor.py` (then `run_with_lease.py zen -- <cmd>`) |

## The 3 .env files — which serves what

| File | Read by | Holds | Never holds |
|---|---|---|---|
| `.env` (root) | bot runtime (`config/__init__.py`) | BOT_TOKEN, runtime AI key, DB_PATH, quotas | factory research keys |
| `factory/.env` | factory scripts (`core/env_loader.py`, `blind50.load_keys`) | ZEN x2, OPENROUTER, GOOGLE, AVALAI (`blind50` also falls back to `tools/egress/.env` for GOOGLE/OPENROUTER) | bot token |
| `tools/egress/.env` | supervisor only | EGRESS_SUB_URL(S), EGRESS_SUP_TOKEN (+ owner's spare LLM keys as fallback) | anything committed |

Rule of thumb: running the bot → root; running the line → factory; touching VPN/SUBs → egress. If a script says "missing key", this table tells you which file to open.

## Files

- `pipeline/precard_pipeline.py` — the line (stages, gates G1–G6, resume).
- `pipeline/card_pilot.py` — anchor scorer, kaikki readers, run logger.
- `core/probe_keys.py` — egress + key health check (no secrets in output).
- `pipeline/blind50.py` — 4-way judge comparison (on main; needs keys, see runbook).
- `archive/v14_v16/run_v14_phase*.py`, `archive/v14_v16/run_v15_topics.py` — vendored scorer owners
  (rank logic lives here; do not re-implement elsewhere).
- `lexicon/` — sample/index/pool/judge/AWL builders; `core/` — registry/transport/telemetry/env/glossary.
  Tests: `tests/factory/`.
