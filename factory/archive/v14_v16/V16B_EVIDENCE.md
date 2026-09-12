# v16b EVIDENCE — Other top-up (2026-09-03, worktree research-lexicon-v14)

Locked scope: owner order 2026-09-03 (Job 1). Script: `factory/run_v16b_topup.py`
(v16 transport/batch/resume/validation reused verbatim; only the prompt is stronger:
Other = last resort, multi-label up to 3 explicitly encouraged, no force-fit).
No pack changes. No commit, no PR.

## Input

- `ranked_senses-v14c.json` (gloss source; 500 entries / 497 distinct lemmas —
  most/outside/cast duplicated, pre-existing v14c quirk, see v15 evidence).
- `topic_labels-v16.json`: 552 Other/Abstract senses → relabel candidates.
- `topic_vectors-v16.json`: kept vectors for the 1124 non-Other senses (byte-kept).

## Run numbers

- Todo: 299 ranked entries touching Other (296 distinct lemmas), batch 8 → 38 batches.
- Calls: **39, ALL `muse-spark-1.3-contributor-free`** (1 probe smoke rock,flat + 38 full;
  smoke lemmas fall in different batches so full run still calls all 38).
  Fallback chain never needed. Sleep 2.5s, live tqdm, resume `factory/v16b_progress.json`
  every batch. ~5.5 min wall.
- Failed lemmas: **0** (no keep-Other fallback used; all relabeled rows `llm-v16b`).
- Dry-run `--dry-run --limit 8` green before; smoke `--lemmas rock,flat` eye-checked
  (rock#23 Daily+Emotions, flat#13 Health+Daily, flat#20/#40 honestly kept Other).

## Outputs (worktree `factory/fixtures/` + W `fixtures/`, md5-verified)

- `topic_labels-v16b.json` (1676 rows: 1124 kept byte-identical + 552 relabeled).
- `topic_vectors-v16b.json` (1676 senses, 500 entries, same layout incl. dup-lemma entries).
- `fixtures-v16b.zip` (189,707 B: the two JSONs).
- Resume: `factory/v16b_progress.json` (+ W copy).

## Validation (all pass, from files)

- Sense ids multiset-equal to v16 and to ranked input (1676 == 1676). topic_id 1..16,
  label matches id. Weight sums 1.0±0.01: 0 violations. primary == vector top: 0 mismatches.
- New Other: **296/1676 = 17.7%** (was 552 = 32.9%). Target ≤20% HIT; stretch ≤15% missed by 29 rows.
- Rescue rate: 256/552 Others moved to real heads (46.4%); 296 stayed (genuinely abstract).
- Multi-topic: **314/1676 = 18.7%** (312×2-topic, 2×3-topic; was 116 = 6.9%).
  202 of the 314 multi are ex-Other senses.
- Lemmas touching Other: 296 → 179.

## Distribution v16 → v16b (n=1676)

| head | v16 | v16b | Δ (Other→head) |
|---|---|---|---|
| Society | 108 | 150 | +42 |
| Emotions & Relationships | 145 | 179 | +34 |
| Daily Life & Home | 68 | 93 | +25 |
| Work & Careers | 49 | 74 | +25 |
| Education & Exams | 37 | 62 | +25 |
| Science & Technology | 138 | 159 | +21 |
| Business & Economy | 47 | 62 | +15 |
| Arts & Culture | 86 | 100 | +14 |
| Health & Body | 81 | 94 | +13 |
| Travel & Transportation | 59 | 72 | +13 |
| Nature & Environment | 77 | 89 | +12 |
| Law & Politics | 80 | 88 | +8 |
| Sports & Leisure | 70 | 76 | +6 |
| Food & Drink | 44 | 46 | +2 |
| Animals & Living Beings | 35 | 36 | +1 |
| Other / Abstract | 552 | 296 | −256 |

Food +2 / Animals +1: those heads were already correctly labeled in v16; remaining
Others have no food/animal anchor (or the model stayed conservative).

## Probes (v16b primary + vector)

- rock: #1 music Arts 1.0 (stable); #23 sway Other→**Daily 0.6+Emotions 0.4**;
  #4 tilt Other→**Travel 0.6+Nature 0.4**; #39 crystal SciTech (stable).
- light: #62 lamp SciTech (stable); #7 "not burdensome" Other→**Work 0.5+Daily 0.5**;
  #21 "less than legal amount" Other→**Business 0.6+Law 0.4**; #42 physics SciTech.
- pass: #8 "cause to pass" Other→Travel 1.0 (generic, movement reading — borderline,
  flagged); #25 ticket Arts (stable); #55 "An attempt" + #48 "difficult juncture" stay Other.
- flat: #14 apartment Daily (stable); #5 "forthrightly" Other→**Society 0.6+Emotions 0.4**;
  #13 posture Other→**Health 0.6+Daily 0.4**; #20/#40 (flat surface) stay Other.
- supporter: #10 person→Society (stable); #1 "something that supports" stays Other (generic, fine).
- time: #15 continuum Other→Daily; #28 resource→Daily; #31 instant→Daily (all Daily now).
- fish: no Other senses in v16 (unchanged): #0/#22 Animals, #26 Sports, #25 Travel (WN-noise, kept).
- communicate: #4 "transfer to another" Other→Society; #3 "join or connect" stays Other;
  #2 SciTech + #0 Society (stable).

## Flags (out of scope, no action)

- pass#8 Travel 1.0 is the clearest force-fit of the run (generic gloss, movement reading).
- flat#20/#40 staying Other is conservative; a Nature/Daily reading is arguable either way.
- Dup-lemma entries (most/outside/cast) merge sense-keyed, so both copies carry the same
  new label/vector; multiset check passes.
- `.env` never staged/printed. Primary repo untouched (read-only); all work in
  `.worktrees/research-lexicon-v14`, uncommitted per order.
