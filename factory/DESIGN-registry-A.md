# DESIGN-A: SQLite-backed lemma registry + checkpoints (lexicon factory)

Status: DESIGN ONLY — no code, no migration run, no schema created.
Scope: 500-lemma pilot → 5000 pre-cards → batched final cards (1000–2000/day).
Bias: SQLite registry. Argued honestly below (§0), including costs.

## 0. Core choice: SQLite registry file (`factory/registry.db`, WAL mode)

Why SQLite and not JSON-progress-files or Postgres:
- Today phase-1 has NO checkpoint (reprocesses all 500 lemmas, ~7 min GPU);
  phases 2/3 resume only via ad-hoc progress JSON (fragile, no dedup guarantee).
- The problem is relational (lemma → senses → pre-cards → batches → final cards)
  with exactly the queries JSON can't answer cheaply: "how many UNIQUE pre-cards?",
  "which pre-cards already converted?", "what's left in today's batch?".
- Postgres/server DB is overkill for a single-operator factory run on one RTX
  machine; adds ops, secrets, and network failure modes for zero benefit at
  5000-row scale.
- SQLite gives: single file (backs up with fixtures zips), ACID transactions
  (crash-safe checkpoint per lemma), UNIQUE constraints (dup prevention at the
  storage layer, not discipline layer), SQL counting queries.

Honest costs:
- C1 Single-writer bottleneck: SQLite serializes writers. Fine at our rate
  (per-lemma commits, batch claims), but parallel LLM workers MUST claim work
  via short transactions, never hold a transaction across an API call.
- C2 Network-drive locking: raw data lives on `W:/`; the registry file MUST live
  on local disk (`factory/registry.db`), synced/copied to W: after runs. SQLite
  over SMB/NFS locks unreliably → corruption risk.
- C3 Schema discipline: needs a `schema_version` table row + forward-only
  migrations; harder to "just edit JSON". Small price, standard practice.
- C4 GPU nondeterminism is NOT solved by SQLite: embeddings vary slightly
  run-to-run on CUDA; registry must store similarity-thresholded outcomes, never
  raw float vectors, for stability checks (§2).

## 1. Schema (5 tables max)

### Normalization (input dedup, applied once at ingest)
- `norm_lemma = NFKC(lower(strip(lemma)))`, collapse inner whitespace, strip
  surrounding `'".-` punctuation. English-only for `en` pack (no Persian
  normalization here; document if pack adds `fa` later).
- `norm_pos`: map via existing VN table (`n→noun, v→verb, a/s→adj, r→adv`);
  lowercase, strip; `name` → rejected at ingest (matches R-design rule: proper
  nouns don't consume slots; logged to `rejects`, not silent).
- `lemma_key = norm_lemma + "|" + norm_pos` — PRIMARY KEY of `lemmas`.
  Case-collision (e.g. `April` vs `april`) intentionally collapses; `lemma_raw`
  preserved for display (`April` keeps capital in card, key is `april|noun`).
- `norm_gloss = " ".join(lower(gloss).split()).rstrip(".")` — same rule as the
  R9 exact-dup merge key in `run_v14_phase1.py:315`, promoted to registry-wide.

### Table 1: `lemmas` — one row per lemma_key (append-only; never UPDATE key)
| col | type | notes |
|---|---|---|
| lemma_key | TEXT PK | `april\|noun` |
| lemma_raw | TEXT | display form |
| pos / cefr / tier | TEXT | from `lemmas.csv` |
| raw_hash | TEXT | sha1 of contributing raw lines (Kaikki entries + WN synset ids for this lemma only — per-lemma, NOT whole-file, so appending lemma 501 doesn't invalidate 1–500) |
| st_deduped / st_ranked / st_merged / st_judged / st_topics / st_vectors | INT 0/1 + `*_at` UTC | per-stage flags |
| fingerprint | TEXT | `pack_version:code_hash` that produced current row (see §2) |
| created_at / updated_at | TEXT UTC | |

### Table 2: `precards` — one row per stable pre-card (the countable unit)
| col | type | notes |
|---|---|---|
| pre_card_id | TEXT PK | STABLE content-addressed: `{lemma_key}::g{sha1(norm_gloss)[:10]}`. Replaces unstable `{w}#{lab}` cluster ids (cluster label shifts with ordering). Legacy `April#0` kept in `legacy_sense_id` for migration only. |
| lemma_key | TEXT FK→lemmas | indexed |
| legacy_sense_id | TEXT NULL | v14a/b/c id (`Miss#21`); UNIQUE where not null, for traceability |
| gloss_norm / full_text_hash | TEXT | dedup + stability |
| score / p_rank / sense_cefr / topic_id / topic_label / topic_source | as in ranked fixtures | |
| merged_from | JSON TEXT | array of legacy ids, matches R3b `merged_from` |
| vectors_json | TEXT NULL | v15/v16b weight vector (`≤3 labels, sum 1.0`) |
| converted_final_id | TEXT NULL | set once (see Table 4); NULL = unconverted |
| created_at | TEXT UTC | |

**Unique pre-card counting query (canonical — replaces "count rows in JSON"):**
```sql
SELECT COUNT(*) FROM precards;                                  -- unique pre-cards
SELECT COUNT(*) FROM precards WHERE converted_final_id IS NULL; -- not yet final
SELECT topic_label, COUNT(*) FROM precards GROUP BY 1;          -- Other% etc.
```

### Table 3: `runs` — provenance + invalidation source
| col | type | notes |
|---|---|---|
| run_id | TEXT PK | `p1-20260903-a3f9` (phase + date + short hash) |
| phase | TEXT | `phase1\|merge\|judge\|vectors\|finalbatch` |
| pack_version / code_hash / embed_model | TEXT | `v14a`, sha1 of pipeline script(s), `all-MiniLM-L6-v2` |
| raw_snapshot | TEXT | sha1 of `filtered_500_kaikki.jsonl` header+count (whole-file tripwire) |
| started_at / finished_at / note | TEXT | |

### Table 4: `batches` — daily final-card batch ticket
| col | type | notes |
|---|---|---|
| batch_id | TEXT PK | `FINAL-20260904-01` (date + seq; §3) |
| day | TEXT | `YYYY-MM-DD` (APP_TIMEZONE day) |
| quota / claimed / done_count / failed_count | INT | quota ∈ {1000, 2000} |
| fingerprint | TEXT | same `pack_version:code_hash` — batch is bound to it |
| status | TEXT | `open\|sealed\|done` (sealed = quota frozen, no new claims) |
| manifest_json | TEXT | lemma_key ranges + filter (e.g. `{"tiers":["beginner"]}`) |

### Table 5: `batch_items` — one row per pre-card claimed into a batch
| col | type | notes |
|---|---|---|
| batch_id | TEXT FK | indexed |
| pre_card_id | TEXT UNIQUE | **once-only conversion enforced here**: UNIQUE prevents the same pre-card entering two batches |
| final_card_id | TEXT NULL | set on success |
| status | TEXT | `queued\|claimed\|done\|failed\|skipped` + `lease_at` UTC for crash recovery |
| attempts | INT | bounded (max 3), then `failed` |

Append path for new lemmas: ingest computes `lemma_key`; `INSERT OR IGNORE
INTO lemmas`; only keys with `st_deduped=0` (or fingerprint mismatch, §2) enter
the pipeline. Old rows are never re-scored, re-embedded, or re-judged.

## 2. Phase-1 checkpoint (deterministic, per-lemma)

- Granularity: ONE transaction per lemma AFTER all its senses are built
  (dedup → cap → EVP guard → rank → exact-merge). Commit row in `lemmas`
  (`st_deduped=1, st_ranked=1`) + its `precards` rows atomically. Crash between
  lemmas loses at most 1 lemma (~1 s), never corrupts.
- Resume rule: on start, `SELECT lemma_key FROM lemmas WHERE st_ranked=1 AND
  fingerprint = :current_fp`; skip those entirely (no embedding, no file reads
  beyond ingest). Everything else is work.
- Fingerprint: `pack_version (pack.json "version") + ":" + sha1(run_v14_phase1.py)
  + ":" + sha1(weights+thresholds subset of pack.json)`. Stored per lemma row.
- What INVALIDATES a checkpoint (forces reprocess of that lemma only):
  1. `pack_version` change (e.g. `v14a→v14b` weights/thresholds) → ALL rows stale.
  2. `code_hash` change (pipeline script edited) → ALL rows stale (conservative;
     future: per-function hashes for surgical invalidation — explicitly NOT v1).
  3. `raw_hash` change for THAT lemma (new Kaikki lines / WN version drift) →
     only that lemma stale. Whole-file growth does NOT invalidate old lemmas
     (this is the key append-only property).
- What does NOT invalidate: embedding float noise (we store ranked outcomes,
  not vectors), fixture renames, report edits, `.env` changes.
- Determinism guardrails (already mostly true in current script; lock them):
  sort `raw_by_lemma` inputs, `np.argsort(-p, kind="stable")` (already used),
  seed `AgglomerativeClustering` path has no RNG but keep `try/except` fallback
  order stable; record `embed_model` in `runs` so a model swap is visible.

## 3. Daily final-card batches (1000/2000 per day)

- Batch ticket format: `FINAL-{YYYYMMDD}-{NN}` + `manifest_json`, e.g.
```json
{"batch_id":"FINAL-20260904-01","day":"2026-09-04","quota":1000,
 "filter":{"unconverted_only":true,"order":"lemma_key ASC"},
 "fingerprint":"v14c:a3f9…","created_by":"factory/run_final_batch.py"}
```
- Progress record: `batches` row (`claimed/done_count/failed_count` updated in
  the same transaction that flips each `batch_items` row — counters never drift).
- Claiming (crash-safe): worker does `UPDATE batch_items SET status='claimed',
  lease_at=NOW WHERE batch_id=? AND status='queued' LIMIT N` in one short
  transaction; then does the expensive LLM/render work OUTSIDE any transaction;
  then `UPDATE … SET status='done', final_card_id=?` + `precards.converted_final_id`
  in one transaction. Never hold a transaction across an API call (per AGENTS.md §5).
- Crash recovery rule: on startup, `UPDATE batch_items SET status='queued' WHERE
  status='claimed' AND lease_at < NOW - 30min` (stale leases re-queue); rows
  `done` are NEVER re-queued (UNIQUE + `converted_final_id` non-null = terminal).
  A second overlapping batch for the same pre-card fails on UNIQUE — that error
  is the correctness signal, not a bug.
- Stop rule: operator seals batch (`status='sealed'`) at quota or end-of-day;
  leftover `queued` items roll into next day's ticket explicitly (new `batch_id`,
  re-`INSERT … SELECT` of still-unconverted ids — `OR IGNORE` makes this safe).

## 4. Migration (import 500-lemma outputs WITHOUT reprocessing)

One-shot read-only importer (`scripts/` future, not this design):
1. `uniq_senses-v14a.json` → `lemmas` rows (key, raw) + `st_deduped=1`; per-sense
   rows → `precards` with `pre_card_id` freshly computed from `norm_gloss`
   (content-addressed from day one) and `legacy_sense_id = "w#lab"`.
2. `ranked_senses-v14a.json` → UPDATE score/p_rank/sense_cefr/topic_*,
   `st_ranked=1`, `merged_from` preserved.
3. `ranked_senses-v14b.json` → UPDATE merged rows (matched by `legacy_sense_id`),
   `st_merged=1`; pre-cards absorbed by a merge are NOT deleted — flagged
   (`status` via `merged_from` membership) so history survives.
4. `ranked_senses-v14c.json` + `topic_labels-v14c.json` → `st_judged=1`,
   `st_topics=1` (+ `picks` JSON into a run-note or manifest sidecar — no new table).
5. `topic_vectors-v15.json` / `-v16.json` / `-v16b.json` → `vectors_json`,
   `st_vectors=1`. v16 13→16 label migration map (`topic_migration_13_to_16.json`)
   applied as data (old `topic_id` kept in `legacy_*`, new label primary).
- Cost: ~500 lemmas / ~4093 uniq rows / 1676 pre-cards / ~500 vector rows —
  single script, minutes, zero LLM calls, zero embeddings. Fingerprint for all
  migrated rows: `v14a:legacy-import` (+ per-stage run rows in `runs` noting the
  original fixture filenames + sha1s, so provenance is auditable).
- Validation post-import: row counts match fixture counts exactly
  (4093 uniq / 2101 v14a / 1676 v14b-c); every `pre_card_id` recomputable from
  `gloss_norm`; spot-check probes (rock/flat/light/pass) present.

## 5. Failure modes + proof of append-only correctness

Failure modes:
- F1 Re-ingest with different case/POS (`Miss` noun vs verb) → two keys
  (`miss|noun`, `miss|verb`) — CORRECT (different cards), not a dupe. True dupes
  (same key) collapse via PK.
- F2 Legacy cluster-id collision (`w#3` meaning different glosses in v14a vs
  rerun) → neutralized: PK is content hash, legacy id is alias only.
- F3 Concurrent writers (two terminals) → SQLite `database is locked` → writer
  retries with backoff; no torn rows (WAL + per-lemma transactions). Never run
  two phase-1 writers on the same registry file.
- F4 Registry on `W:/` network share → lock failure/corruption → rule: registry
  lives local, `rsync`/copy to W: after each phase; W: copy is backup, never live.
- F5 Fingerprint storm (accidental script edit reformats file → new sha1 →
  full reprocess) → mitigate: hash normalized script bytes (strip comments/
  whitespace) OR accept conservative full reprocess; log `runs.note` when it happens.
- F6 Final-batch double-claim after crash → prevented by UNIQUE(pre_card_id) +
  lease re-queue; `failed` after 3 attempts needs operator triage, never auto-retry forever.

Proof measures (the "3 overlapping runs" test):
- M1 `SELECT COUNT(*) FROM precards` identical after run 2 and run 3 with
  overlapping inputs (e.g. lemmas 1–500, then 400–900, then 1–900) → expect
  exactly the union count, zero growth on pure overlap.
- M2 `SELECT gloss_norm, COUNT(*) c FROM precards GROUP BY lemma_key, gloss_norm
  HAVING c>1` → zero rows (no dupes), after all 3 runs.
- M3 `SELECT COUNT(*) FROM batch_items GROUP BY pre_card_id HAVING COUNT(*)>1`
  → zero rows (converted at most once); `SELECT COUNT(*) FROM precards WHERE
  converted_final_id IS NOT NULL` == `SELECT COUNT(*) FROM batch_items WHERE
  status='done'`.
- M4 Fingerprint audit: `SELECT fingerprint, COUNT(*) FROM lemmas GROUP BY 1` →
  at most 2 distinct values during the test (original + newly appended), proving
  old rows were untouched.
- M5 Recompute check: recompute every `pre_card_id` from stored `gloss_norm` →
  100% match (ID stability proven, rerun-safe joins).
