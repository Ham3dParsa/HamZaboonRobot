# DESIGN B — Lexicon factory manifest registry (file-based, JSONL + content hashes)

Status: DESIGN ONLY. No code, no behavior change. Competing proposal (designer B).
Scope: 500-lemma pilot → 5000 pre-cards → batched final cards (1000–2000/day).
Bias: file-based manifest registry, JSONL + content hashes, zero new dependencies.
This doc argues honestly for that bias, including its costs.

## 0. What is broken today (read from pipeline)

- `factory/run_v14_phase1.py` rebuilds everything every run: `uniq_senses-v14a.json`
  and `ranked_senses-v14a.json` are wholesale rewrites. No per-lemma checkpoint.
  (LLM stages — phase-2 merge, phase-3 judge — already resume via progress JSON;
  phase-1 does not.)
- Sense IDs are **unstable across reruns**: `sense_id = f"{w}#{lab}"` where `lab`
  is an `AgglomerativeClustering` label (`run_v14_phase1.py:166`). Cluster labels
  are arbitrary per-fit (label permutation, different cluster counts after any
  data/code change). `Miss#21` in v14c means nothing stable. Any registry must
  replace these, keeping the old IDs only as aliases.
- No record of pre-card → final-card conversion (`picks` in v14c are candidate
  selections, not conversion receipts).
- Rerun can silently duplicate: same lemma re-ingested under different case
  (`April` vs `april` — raw lookup already lowercases, but `lemmas.csv` keys do
  not) gets a fresh row; nothing dedups on input.

## 1. Registry layout

```
factory/registry/
  schema_version.txt            # single integer, e.g. "1"; fail-closed on mismatch
  lemma_index.jsonl             # 1 line / lemma_key — the ONLY lemma registry
  cards.jsonl                   # 1 line / pre-card — the ONLY card registry
  runs.jsonl                    # 1 line / pipeline run (fingerprint + counts)
  input_receipts.jsonl          # 1 line / ingested lemmas.csv batch (hash + verdict)
  checkpoints/phase1.json       # per-lemma phase-1 checkpoint (atomic rewrite)
  batches/<yyyy-mm-dd>-<seq>.json   # final-card batch tickets (§3)
  batches/_progress.jsonl       # append-only card-done log (§3)
  aliases/old_ids.jsonl         # old unstable sense_id → stable card_id (§4)
```

### 1.1 lemma_index.jsonl (one line per lemma)

```json
{"schema":1,"lemma_key":"miss|noun","lemma_raw":"Miss","pos_raw":"noun",
 "pos_norm":"noun","lemma_cefr":"A1",
 "norm_hash":"sha1:…","raw_hash":"sha1:…",
 "phase1":{"status":"done","run_id":"…","n_raw":41,"n_uniq":9,"card_ids":[…],"fp":"…"},
 "merge":{"status":"done","merged_away":["…"],"run_id":"…"},
 "judge":{"status":"judged","pick_source":"judge","run_id":"…"},
 "first_seen_run":"…","updated_run":"…"}
```

- **Lemma key** = `norm_lemma + "|" + norm_pos`. Norm rules (§1.4). Key is the
  dedup identity. `lemma_raw`/`pos_raw` preserved for audit.
- `raw_hash` = sha1 of the exact Kaikki lines + WordNet synset id list consumed
  for this lemma (per-lemma invalidation, §2). `norm_hash` = sha1 of normalized
  identity (for dup detection across batches).
- Per-stage status lives here, not in filenames. `converted-to-final` lives on
  the **card** row, not the lemma row (one lemma → many cards, converted
  independently).

### 1.2 cards.jsonl (one line per pre-card, append-only)

```json
{"schema":1,"card_id":"miss.noun.3f9a2c1e","lemma_key":"miss|noun",
 "gloss_norm_hash":"sha1:…","gloss_raw":"An act of avoidance …",
 "synset_sig":"sha1:… (sorted synonym set)","p_rank":4,"score":0.093,
 "sense_cefr":"A1","topic":"Other / Abstract",
 "status":"active | superseded | withdrawn",
 "merged_into":"<card_id> | null","merged_from_aliases":["Miss#36"],
 "old_sense_ids":["Miss#36"],
 "judge_pick":{"beginner":false,"intermediate":false,"advanced":true},
 "converted_to_final":false,"final_card_id":null,"converted_run":null,
 "created_run":"…","superseded_run":null}
```

- **Stable card ID**: `<norm_lemma>.<norm_pos>.<hash10>` where `hash10` =
  first 10 hex of `sha1(gloss_norm + "\x00" + synset_sig)`. Rationale:
  - `gloss_norm` = NFKC → casefold → collapse whitespace → strip trailing
    periods. This is what exact-dup merging already keys on
    (`run_v14_phase1.py:313`), so the registry reuses the pipeline's own
    notion of "same meaning".
  - `synset_sig` = sha1 of sorted lowercased synonym word list. Distinguishes
    same-gloss senses with genuinely different synonym sets; keeps IDs stable
    when only *examples* change (examples come from the Tatoeba pool, which
    churns independently — examples are deliberately EXCLUDED from identity).
  - Rank/score/p_rank/topic are NOT part of identity (they change every
    weight tweak; identity must survive R1-style retunes).
- **Unique pre-card count** = `count(cards where status == "active")`, computed
  by scanning `cards.jsonl` (or a cached count in `runs.jsonl`, recomputed on
  demand — cache is advisory, scan is canonical). Merged-away senses become
  `superseded` with `merged_into` set; they stop counting but stay auditable.
  This directly encodes the v14a→v14b story (2101 → 1676, 367 merged) as data.

### 1.3 Append path for new lemmas (no reprocessing of old ones)

1. New `lemmas.csv` batch → normalize each row → `lemma_key`.
2. Look up `lemma_index.jsonl` (loaded once into a dict at startup; 5000 rows
   is trivially small). Hit + fingerprint match (§2) → **skip entirely**
   (no embedding, no LLM, no raw re-read). Hit + fingerprint mismatch →
   reprocess that lemma only. Miss → process and **append** one index line +
   N card lines. Never rewrite old lines; corrections are new lines with
   `superseded`/`withdrawn` status (append-only history).
3. Write an `input_receipts.jsonl` line per batch: input file hash, row count,
   accepted / skipped-unchanged / rejected-duplicate counts.

### 1.4 Duplicate prevention — normalization rules (locked here, not inferred later)

| # | Rule | Example |
|---|------|---------|
| N1 | Lemma: NFKC normalize → strip → casefold (`str.casefold`, not `lower`) | `Miss`→`miss` |
| N2 | Strip surrounding quotes/punctuation artifacts; collapse internal whitespace | `  give up ` → `give up` |
| N3 | POS: map to closed set via table `{n,noun→noun; v,verb→verb; a,s,adj,adjective→adj; r,adv,adverb→adv; name,propn→name}`. Unknown POS → `other`, logged, never silently folded into noun | phase-1 drops `name` lines (`:137`); registry keeps the lemma row but marks `pos_norm` honestly |
| N4 | Key collision across batches (same `lemma_key`, different raw, e.g. `Miss`/`MISS`) → second occurrence **rejected**, logged in receipt with reason `dup-key`, first row wins | — |
| N5 | Same lemma, different POS → different keys (`light|noun` vs `light|verb`); same lemma+POS, different CEFR → SAME key (CEFR is an attribute, not identity; tier changes update the row, don't fork it) | `light` probes |
| N6 | Gloss identity for cards = §1.2 hash; two raw senses hashing equal → one card, loser recorded in `merged_from_aliases` | the 15 exact-dup merges of v14a |

### Why file-based (honest argument)

For: zero new dependencies (factory already leans stdlib-only — cf.
`env_loader.py` fail-closed stdlib style); human-auditable and `W:`-drive
syncable (the project already syncs fixtures/zips/reports to `W:`); greppable;
diffable; survives the "keys live in gitignored `.env`, everything else is
plain files" operating model; at 5000 lemmas / ~20k cards, JSONL scans are
milliseconds — no query engine needed. Append-only JSONL gives crash safety
almost for free (a torn last line is detectable and droppable; a torn SQLite
page is not, without WAL expertise).

Costs (stated plainly): no transactions — concurrent writers WILL interleave;
mitigation is a lockfile + single-writer rule, which is a convention, not a
guarantee. No indexes — every lookup is a full scan into memory (fine at
20k lines, wouldtii not be fine at 2M). Schema drift is a real risk —
mitigation is the per-line `schema` field + a tiny validator, but nothing
forces anyone to run it. If the factory ever needs concurrent LLM workers
writing results, this design must be revisited (SQLite with WAL, or one
writer process). For the stated scale (500 → 5000, batched daily finals),
files win on simplicity; beyond ~100k cards they lose.

## 2. Phase-1 checkpoint (deterministic)

### Granularity: per-lemma, two sub-stages

Phase-1 as written has a hidden global coupling: per-lemma dedup/uniq
(loop `:132`, checkpointable) feeds a **global** embedding pass for ranking
(`all_embs` `:222`, needs all `full_text`s at once). The checkpoint respects
that split:

- **Stage A (dedup → uniq_senses)**: checkpointable per lemma. Entry =
  `{lemma_key, n_raw, n_uniq, uniq_full_texts_hash, card_ids}`.
- **Stage B (ranking → ranked_senses)**: needs the global matrix. On resume,
  Stage-B-done lemmas are skipped; the global matrix is rebuilt only from
  lemmas needing (re)ranking (their Stage-A outputs are on disk in the
  checkpoint + `uniq` artifact). The full `all_embs` matrix is NOT persisted
  (large, device-specific); recompute is ~seconds, versus LLM minutes.

Checkpoint file `checkpoints/phase1.json`:
`{"run_id":…, "global_fp": <§2.2 global part>, "lemmas": {lemma_key: {"stage": "A-done|B-done|failed", "fp": <per-lemma fp>, "card_ids": […], "error": …}}}`.
Written atomically (tmp file + `os.replace`) after each lemma. A crash loses
at most the in-flight lemma.

### Resume rule

Skip a lemma iff `checkpoint.lemmas[key].stage == "B-done"` **and**
`checkpoint.lemmas[key].fp == current_fp(key)` **and**
`checkpoint.global_fp == current_global_fp()`. Anything else → reprocess that
lemma only. `--force` reprocesses all (and records a new `run_id`).

### Invalidation — what kills a checkpoint

Two-tier fingerprint, recorded per lemma and globally:

- **Global (any change → all lemmas reprocess; requires explicit run, never
  silent)**: `pack.json` content hash (covers weights, thresholds, tier C/Tau/
  Kmax — i.e. every R1/R5 knob), `run_v14_phase1.py` code hash (sha1 of file),
  embedding `model_id` string, WordNet data version (if queryable, else the
  NLTK corpus checksum).
- **Per-lemma (only that lemma reprocesses)**: `raw_hash` = sha1 of the
  lemma's Kaikki lines (as read) + its WordNet synset ID list. Raw-data edits,
  new Kaikki dumps, or lemma.csv CEFR changes invalidate exactly the affected
  lemmas.

`fp(key) = sha1(global_fp + raw_hash(key))`. Deliberately conservative: an
unknown `schema_version` or unreadable checkpoint → fail-closed to full
reprocess, never to silent skip.

## 3. Stop/resume for daily final-card batches (1000–2000/day)

### Batch ticket

`batches/<yyyy-mm-dd>-<seq>.json`, written when the day's batch is planned
(ticket is the plan; `_progress.jsonl` is the truth):

```json
{"batch_id":"2026-09-04-01","date":"2026-09-04","quota":1000,
 "card_ids":[…ordered…],"cursor":0,"status":"open|done|aborted",
 "llm_calls_budgeted":125,"model":"muse-spark-1.3 (zen)"}
```

Planner fills `card_ids` from `cards.jsonl` where `status==active AND
converted_to_final==false`, in a deterministic order (lemma_key sort, then
card_id sort — no sampling randomness), capped at quota. Leftover cards roll
to the next day's ticket; tickets never overlap (planner asserts every
`card_id` is in no other `open` ticket).

### Progress record

`batches/_progress.jsonl`, one line per event, append-only:
`{"batch_id":…,"card_id":…,"event":"card-done|card-failed|batch-done",
"final_card_id":"f_…","llm_calls":1,"ts":"…"}`.
Final card artifacts land per-card (`batches/<batch_id>/<card_id>.json`,
tmp+rename) and the registry `cards.jsonl` gets the conversion receipt as a
**new status line** (same `card_id`, `converted_to_final:true`,
`final_card_id`, `converted_run:batch_id`) — pre-card history preserved.

### Crash recovery rule

On restart: load ticket + replay `_progress.jsonl` for that `batch_id`.
Any `card_id` with a `card-done` event is skipped — **its LLM call is never
retried** (this mirrors the existing phase-2/3 progress-JSON resume and is
the cost-control property: at ~8 lemmas/call, re-running a 1000-card day
would burn ~125 calls). Cursor = first card without a terminal event.
`card-failed` cards retry up to a fixed budget (2), then the batch completes
with them listed as `failed` (carried to the next ticket, never silently
dropped). Double-conversion guard: planner + writer both assert
`converted_to_final==false` before writing; the writer re-checks the live
`cards.jsonl` tail (covers the crash-between-LLM-and-write window: LLM output
exists on disk but receipt not appended → resume rewrites only the receipt,
no second LLM call).

## 4. Migration — importing existing outputs without reprocessing

One-shot, deterministic, zero LLM calls, zero embeddings. For each of
`ranked_senses-v14a.json` (2101 cards), `-v14b.json` (1676),
`-v14c.json` (+picks/judge), `topic_vectors-v15.json`, `topic_vectors-v16b.json`
+ `topic_labels-v16b.json`:

1. For each lemma: compute `lemma_key` via §1.4 rules, append `lemma_index`
   row with `first_seen_run: "import-v14x"` and per-stage status backfilled
   from evidence: phase1 done (present in v14a); merge done iff card counts
   match v14b lineage; judge `judged|deterministic-fallback` from v14c
   `pick_source` (the 6 deterministic lemmas —
   light/chairman/cycling/exchange/stool/drive — recorded honestly as
   `deterministic-fallback`, not laundered into `judged`).
2. For each ranked sense: compute the §1.2 stable `card_id` from stored gloss
   + synonyms; append `cards.jsonl` row; record the old unstable ID
   (`April#0`, `Miss#21`) in `old_sense_ids` + `aliases/old_ids.jsonl`
   (`{old:"Miss#21", new:"miss.noun.…", source:"ranked_senses-v14c.json"}`).
3. Merge lineage: v14b's removed 367 → mark corresponding cards `superseded`
   with `merged_into` where recoverable (exact-dup `merged_from` arrays give
   this for free); LLM-merged ones best-effort with `superseded_run:
   "import-v14b-unresolved"` where the mapping is ambiguous — flagged, not
   guessed (§logic-lock: report uncertainty, don't invent mappings).
4. v14c `picks` → `judge_pick` flags only. `converted_to_final` stays
   **false** everywhere: v14c picks are selections, not final cards; the first
   real conversion happens in a §3 batch. v15/v16b vectors attach as
   provenance fields (`topic_vectors` refs), not new cards.
5. Verify: assert imported active-card counts equal the locked numbers
   (v14a 2101; v14b/v14c 1676; per-CEFR 265/258/298/296/309/250; Other 453).
   Any mismatch aborts the import (fail-closed), it never "adjusts" history.

**Migration cost**: ~half a day of careful scripting + verification, no GPU,
no API spend. Dominant cost is step 3 ambiguity review (LLM-merge lineage for
367 cards) — bounded, one-time, and explicitly allowed to leave
`import-v14b-unresolved` flags rather than force false precision.

## 5. Failure modes + proof of append-only correctness

### Failure modes

| # | Mode | Effect | Mitigation |
|---|------|--------|------------|
| F1 | Truncated-hash collision (10 hex ≈ 40 bits) | Two meanings share a card_id | At ~20k cards, P(collision) ≈ 10⁻⁷ (birthday bound); on append, assert full `gloss_norm_hash` differs → on the astronomically unlikely hit, extend to 14 hex and log. Full hash always stored, short ID is display |
| F2 | Over-normalization (N1/N5 fold truly distinct lemmas) | Lost lemma | Rejected-dup log is reviewable; N5 keeps CEFR out of identity; English lemma space has negligible casefold collisions |
| F3 | Torn JSONL tail on crash/kill | Half-line at EOF | Writer appends + flushes + fsyncs per batch of lines; reader drops a trailing malformed line and logs it; checkpoint uses tmp+rename so it never tears |
| F4 | Stale checkpoint skip (code changed, fp not bumped) | Wrong results kept | fp includes code hash + pack hash; unknown schema → full reprocess (fail-closed). The dangerous direction (skip-when-shouldn't) requires defeating two hashes |
| F5 | Concurrent writers | Interleaved JSONL | Lockfile (`registry/.lock`, exclusive create); second writer exits with message, never waits silently. Documented limit: single writer (§1 costs) |
| F6 | Merge-chain supersede (A→B→C across runs) | `merged_into` points at a superseded card | Writer follows the chain to the live head at write time; reader resolves transitively. Chain length logged; depth >2 flags a review |
| F7 | Double conversion (same pre-card in two batches) | Two final cards, one pre-card | Planner excludes `converted_to_final` + open-ticket members; writer re-asserts pre-write (§3). Violation aborts the batch, never overwrites |
| F8 | Raw-data mutation mid-run | Half-old/half-new corpus | `raw_hash` captured at run start per lemma; a run records its input receipt; mid-run changes affect only the next run |

### What to measure (acceptance experiment, no API spend — phase-1 only)

Three runs, overlapping inputs:
- R1: lemmas 1–500 (the pilot). R2: same 500 + 50 new (shuffled order).
  R3: same 550 shuffled + 10 exact dupes + 10 case/whitespace variants
  injected into `lemmas.csv`.
- Assert: (a) active-card set after R1 ⊆ after R2, with exactly the 50 new
  lemmas' cards added (`diff` of card_id sets — **zero** new card_ids for old
  lemmas); (b) R3 adds zero cards, receipt shows 20 `rejected-dup-key`;
  (c) no-op rerun (R2 inputs, R2 registry) is byte-identical on card_id sets
  and touches zero embeddings for old lemmas (wall-clock ≈ startup only);
  (d) `input_receipts` accepted/skipped/rejected counters match the plan
  (500/0/0, 50/500/0, 0/550/20); (e) checkpoint resume: kill a run mid-Stage-A
  (e.g. after ~100 lemmas), restart, assert skipped==100 and final card set
  equals an uninterrupted run's.
- Report: card_id-set diffs (empty, shown not claimed), per-run LLM call
  counts (0 for phase-1 proof; budgeted 1-per-8-lemmas when extended to final
  batches), registry line-count deltas, and the kill-restart equality check.
  PASS = all five asserts green; anything else names the failing assert and
  keeps the registry untouched (import/append never deletes).
