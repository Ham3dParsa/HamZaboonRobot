# v16 EVIDENCE — full 16-label relabel + weight vectors (2026-09-03)

Locked scope (plan-v14.md v16 + owner order). Script: `factory/run_v16_topics.py`
(v15 transport/batch/resume/validation pattern reused). No pack changes (13-label
pack frozen; 16 labels live in script header only). No commit, no PR.

## Run numbers

- Input: `factory/fixtures/ranked_senses-v14c.json` (500 lemmas, 1676 cards).
- Calls: **64, ALL `muse-spark-1.3-contributor-free`** (chain fallbacks never needed).
- Failed lemmas: **0** (no deterministic fallback used; all sources `llm-v16`).
- Batch 8 lemmas, sleep 2.5s, resume `factory/v16_progress.json` every batch. ~11 min wall.
- Dry-run `--limit 8` green before; smoke 8 real lemmas eye-checked before full run.

## Outputs (worktree `factory/fixtures/` + W: byte-verified)

- `topic_labels-v16.json` (1676 cards, same shape as v14c, `topic_source: llm-v16`).
- `topic_vectors-v16.json` (500 lemmas / 1676 senses, same shape as v15).
- `topic_migration_13_to_16.json` (old label → new label(s) + rule; 3 splits, 10 identities).
- `fixtures-v16.zip` (188,217 B).

## Validation (all pass)

- Sense ids exact (1676 == 1676, set-equal). topic_id 1..16, label matches id.
- Weight sums 1.0±0.01: 0 violations. primary == vector top entry: 0 mismatches.
- Multi-topic: **116/1676 = 6.9%** (v15: 101 = 6.0%).

## Distribution over 16 labels (n=1676)

| id | label | n | % |
|----|---|---|---|
| 1 | Daily Life & Home | 68 | 4.1 |
| 2 | Food & Drink | 44 | 2.6 |
| 3 | Health & Body | 81 | 4.8 |
| 4 | Work & Careers | 49 | 2.9 |
| 5 | Education & Exams | 37 | 2.2 |
| 6 | Travel & Transportation | 59 | 3.5 |
| 7 | Society | 108 | 6.4 |
| 8 | Arts & Culture | 86 | 5.1 |
| 9 | Animals & Living Beings | 35 | 2.1 |
| 10 | Nature & Environment | 77 | 4.6 |
| 11 | Science & Technology | 138 | 8.2 |
| 12 | Business & Economy | 47 | 2.8 |
| 13 | Law & Politics | 80 | 4.8 |
| 14 | Sports & Leisure | 70 | 4.2 |
| 15 | Emotions & Relationships | 145 | 8.7 |
| 16 | Other / Abstract | 552 | 32.9 |

Old split heads (v14c): Nature & Environment 104 → Animals 35 + Nature 77 (plus
inflow from other heads); Work & Education 131 → Work 49 + Education 37 (rest
re-decided out, e.g. time#28 → Daily); Society & Culture 187 → Society 108 + Arts 86.
Other rose 27.0% → 32.9% (fresh re-decisions, no anchoring to old labels by design).

## Probe eye-checks (old → new)

- fish#0 live animal Food → **Animals**; fish#22 cod → Animals (tie-break: living being);
  fish#26 fishing-time → Sports; fish#25 anchor-purchase-noise → Travel (WN-noise gloss, defensible).
- rock#1 music Society & Culture → **Arts**; rock#23/#4 motion → Other; rock#39 crystal → SciTech.
- light#62 lamp Other → SciTech; light#42 physics → SciTech; light#7/#21 → Other.
- pass#25 ticket Travel → Arts (borderline: theatre-ticket reading; flagged, single case).
- pass#8 "cause to pass" Travel → Other (generic, fine).
- flat#14 apartment → Daily (stable); flat#13 Health → Other (posture, fine).
- supporter#10 Society & Culture → **Society** (correct split branch).
- time#28 Work & Education → Daily; con#15 study → **Education**; con#2 → Education.
- Multi-vector samples: autumn#1 Nature 0.7 + Travel 0.3; bus#10 Education 0.6 + Travel 0.4;
  dining room#0 Daily 0.6 + Food 0.4; meal#10 Food 0.6 + Work 0.4;
  ice cream#0 (meth slang) Health 0.7 + Law 0.3 — verified correct against gloss.

## Flags (out of scope, no action taken)

- pass#25 Travel→Arts: single borderline drift, left as judged.
- `.env` never staged/printed. Primary repo untouched (read-only); all work in
  `.worktrees/research-lexicon-v14`, uncommitted per order.
