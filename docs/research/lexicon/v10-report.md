# HamZaban v10 Factory — Cell1 PILOT_500 97/127/93/95/50/38 + Cell4 thr0.82 12-cap any>12 WN smoothed + Cell5 0.50/0.15/0.25/0.05/0.05 + Cell6 topic thr0.50 + expanded EVP ~2000 (no hard-coded boosts)

Formula: p(s|lemma)=normalized(0.50*Zipf.minmax +0.15*log(WN cnt+0.5).minmax +0.25*per-sense CEFR(expanded EVP/CEFR-J).minmax +0.05*centroid length-norm.minmax +0.05*topic_prior.minmax)
Tiers: beginner C0.85 Tau0.10 K3 (was K2) | intermediate C0.90 Tau0.05 K4 | advanced C0.95 Tau0.03 K6 — K3 compensates for keeping 83x6 pilot vs PILOT_500 quotas 97/127/93/95/50/38 (4000 scaled 250/330/240/247/130/98)
Cell4: thr 0.78->0.82, 12-cap ANY raw>12 (was verb>20 only) ranked by WN smoothed log(cnt+0.5)+length-norm centroid, full reclustering from raw Kaikki+WN, removed +0.4/+0.5 rock/light/pass hacks
Cell5: expanded EVP/CEFR-J vendored 2000 entries (was 14) + cefrj_pos 504 fallbacks, per-sense CEFR via guideword substring + Zipf proxy (never B1 default), verified April A1, tactic C2
Cell6: deterministic topic thr 0.50 (was hash fallback), EVP domain/CoreInventory + keyword ordered, per-goal diversity matrix unchanged
Model: all-MiniLM-L6-v2-cpu + wordfreq Zipf + NLTK WordNet + tqdm visible

## Counts

- uniq_senses-v10: 3862 senses across 500 lemmas avg 7.72 (v9 2993 avg 5.99, v7 2992 avg 5.98) — thr0.82 any>12 cap12_used 205 (v7 30 verbs>20, v9  patched any>12)
- ranked_senses-v10: 1846 cards avg 3.692 (v9 1688 avg 3.376, v7/v8 1676 avg 3.352) — +158 cards vs v9 due to beginner K2->K3
- topic_labels-v10: 1846 cards with per-sense CEFR + topic diversity + goal_weights

lens dist v10: {1:15, 2:40, 3:42, 4:31, 5:27, 6:34, 7:109, 9:2, 10:1, 11:1, 12:198}
lens dist v9:  12-cap any>12 patched, v7: {1:17,2:43,3:38,4:32,5:29,6:35,7:276,12:30}

## Per-CEFR cards (efficiency)

| CEFR | Tier | Lemmas | v7 cards | v9 cards | v10 cards | v10 avg | delta v10-v9 | PILOT_500 quota | 4000 quota |
|------|------|--------|----------|----------|-----------|---------|--------------|-----------------|------------|
| A1 | beginner | 83 | 165 | 165 | 243 | 2.93 | +78 | 97 | 250 |
| A2 | beginner | 83 | 162 | 162 | 239 | 2.88 | +77 | 127 | 330 |
| B1 | intermediate | 83 | 311 | 311 | 313 | 3.77 | +2 | 93 | 240 |
| B2 | intermediate | 83 | 317 | 319 | 319 | 3.84 | 0 | 95 | 247 |
| C1 | advanced | 83 | 374 | 383 | 381 | 4.59 | -2 | 50 | 130 |
| C2 | advanced | 85 | 347 | 348 | 351 | 4.13 | +3 | 38 | 98 |
| **Total** | | **500** | **1676** | **1688** | **1846** | **3.692** | **+158** | **500** | **4000** |

Per-tier rollup v10: beginner 482 (2.90 avg, K3), intermediate 632 (3.81 avg, K4), advanced 732 (4.35 avg, K6)
k dist v10: {1:15(3.0%), 2:43(8.6%), 3:191(38.2%), 4:161(32.2%), 5:12(2.4%), 6:78(15.6%)}
k dist v9: {1:?, 2:?, 3:?, 4:?, 5:?, 6:?} — v9 had ~200 at k=2; v10 shifts 148 lemmas from k=2 -> k=3 due to Kmax 3
PILOT_500 rebalance note: current pilot keeps 83x6 uniform for reproducibility; K3 raises beginner avg 1.97->2.90 to approach 97/127 target mass without resampling lemmas. For 4000 pool, resample to 250/330/240/247/130/98.

## Per-sense CEFR fix verification (Ticket 17)

| Lemma | Expected | v9 (14-entry) | v10 (2000-entry, no boost) | Fix status |
|-------|----------|---------------|----------------------------|------------|
| April (A1 lemma) | A1 | B1 (default) | A1 A1 A1 — `April#0` 0.3446 A1 Nature, `April#3` 0.3082 A1, `April#2` 0.2638 A1 | **FIXED** via cefrj_pos fallback A1 |
| tactic (C2 lemma) | C2 | C2 (but via WN-rank hack) | C2 C2 C2 — `tactic#5` 0.2327 C2 Daily Life, `tactic#4` 0.219 C2 Nature, `tactic#0` 0.2019 C2 | **KEPT C2** via expanded WN+Zipf->C2 |
| rock stone | A1 Nature | A1 Nature 0.1303 (boost +0.4) | A2 Nature 0.0979 `rock#4` formation, stone `rock#19` present in uniq but rank 5+ score 0.09 (no boost) | **REGRESSION** — guideword "stone" not in gloss "a lump or mass..." so CEFR A2 not A1, boost removed reveals natural ranking |
| light not-heavy | A1 Daily Life | A1 0.2371 (boost +0.4) | A1 0.1179 `light#1` A1 Daily Life rank3 (no boost, radiation top) | **PARTIAL** — CEFR correct A1 via weight guideword, but Zipf/centroid favors radiation (common) |

EVP expanded 2000 entries, cefrj fallbacks 504, no B1 default: Zipf proxy assigns A1>=5.2 A2>=4.6 B1>=4.0 B2>=3.5 C1>=3.0 else C2.

## Per-lemma detailed ranked lists — rock / pass / light / flat (with topic_id, goal tags, real examples)

### light — v7 (A1/beginner) k=2 vs v9 k=2 vs v10 k=3 (K3 adds third)

| rank | version | sense_id | cefr | topic | tid | score | gloss | goal_weight exam | example snippet |
|------|---------|----------|------|-------|-----|-------|-------|------------------|-----------------|
| 1 | v7 | light#97 | A1 | Food & Drink | - | 0.2336 | Electromagnetic radiation of any wavelength. | - | - |
| 2 | v7 | light#1 | A2 | Law & Politics | - | 0.1817 | A source of illumination. | - | - |
| 1 | v9 | light#0 | A1 | Daily Life & Home |1|0.2371|Having little weight as compared with bulk; of little densit|+0.9|—|
| 2 | v9 | light#101|A2|Daily Life & Home|1|0.1974|any device serving as a source of illumination|+0.9|—|
| 1 | v10| light#97| A1|Daily Life & Home|1|0.1271|Electromagnetic radiation of any wavelength.|0.9|—|
| 2 | v10| light#101| A1|Daily Life & Home|1|0.1235|any device serving as a source of illumination|0.9|—|
| 3 | v10| light#1| A1|Daily Life & Home|1|0.1179|A source of illumination.|0.9|—|

v10: all 3 senses now A1 Daily Life (expanded EVP weight guideword + Zipf), topic thr0.50 fixes Food&Drink mislabel. Avg Zipf radiation high, device mid, source mid; CEFR uniform A1 so Zipf decides order. Hard-coded +0.4 NOT HEAVY removed, so radiation (frequent) outranks not-heavy (also frequent but slightly less). Per-goal: exam 0.9, travel 1.3 etc.

### pass — v7 k=2 vs v9 k=2 (exam injected) vs v10 k=3 (any>12, K3)

| rank | version | sense_id | cefr | topic | tid | score | gloss |
|------|---------|----------|------|-------|-----|-------|-------|
| 1 | v7 | pass#5 | A2 | Sports & Leisure | - |0.2152|pass from physical life and lose all bodily attributes and f|
| 2 | v7 | pass#68| B1 | Health & Body | - |0.1707|move past|
| 1 | v9 | pass#exam_injected | B1 | Work & Education |4|0.285|Success in an examination or similar test.|
| 2 | v9 | pass#68| A2|Travel & Transportation|5|0.19|move past|
| 1 | v10| pass#5| A2| Health & Body|3|0.1344|pass from physical life and lose all bodily attributes...|
| 2 | v10| pass#20| A2| Health & Body|3|0.115|come to pass|
| 3 | v10| pass#28| B1| Work & Education|4|0.1023|travel past|

v10: exam sense `go successfully through a test (pass.v.14 cnt2)` present in uniq as pass#? but ranked low (WN count 2 vs 32 for travel, 13 for legislate) and dedup 12-cap by WN smoothed dropped it below top12? After dedup, exam gloss not in top12 uniq (WN low), so missing in ranked. This is Ticket 20 trade-off: removing hard-coded injection reveals WN-hostile exam sense requires CEFR-aware dedup, not pure WN. v9 injection guaranteed exam top via +0.5 boost; v10 natural ranking shows gap.

### rock — v7 k=4 vs v9 k=4 (stone A1 boost) vs v10 k=4

| rank | version | sense_id | cefr | topic | tid | score | gloss |
|------|---------|----------|------|-------|-----|-------|-------|
| 1 | v7 | rock#34| B2|Law & Politics|-|0.1257|A lump or cube of ice.|
| 2 | v7 | rock#4| C1|Daily Life & Home|-|0.1049|A formation of minerals, specifically:|
| 3 | v7 | rock#39| B2|Daily Life & Home|-|0.1035|A crystallized lump of crack cocaine.|
| 4 | v7 | rock#8| C2|Science & Technology|-|0.1001|the Rock|
| 1 | v9 | rock#19| A1|Nature & Environment|7|0.1303|a lump or mass of hard consolidated mineral matter|+1.0 STONE boost|
| 2 | v9 | rock#8| A2|Nature & Environment|7|0.1172|the Rock|
| 3 | v9 | rock#18| A2|Nature & Environment|7|0.0896|move back and forth or sideways|
| 4 | v9 | rock#23| A2|Nature & Environment|7|0.088|To make love to or have sex (with).|
| 1 | v10| rock#8| A2|Nature & Environment|7|0.107|the Rock|
| 2 | v10| rock#18| A2|Nature & Environment|7|0.0984|move back and forth or sideways|
| 3 | v10| rock#4| A2|Nature & Environment|7|0.0979|A formation of minerals, specifically:|
| 4 | v10| rock#11| A2|Nature & Environment|7|0.0942|material consisting of the aggregate of minerals...|

v10: stone `rock#19` still in uniq (198 at 12) but rank 5 score ~0.09 just outside top4; without +0.4 boost, WN 14 count vs "the Rock" Zipf high + CEFR tie (both A2 after fix) lets Zipf decide. Topic all Nature correct via expanded EVP.

### flat — v7 k=4 vs v9 k=4 vs v10 k=4 (stable)

| rank | version | sense_id | cefr | topic | tid | score | gloss |
|------|---------|----------|------|-------|-----|-------|-------|
| 1 | v7 | flat#73| B1|Emotions & Relationships|-|0.2385|A complete domicile occupying only part of a building...|
| 2 | v7 | flat#30| B1|Daily Life & Home|-|0.2018|a suite of rooms...|
| 3 | v7 | flat#4| B2|Business & Economy|-|0.1851|Having no variations in height.|
| 4 | v7 | flat#15| B2|Health & Body|-|0.1474|having a surface without slope...|
| 1 | v9 | flat#73| B1|Society & Culture|6|0.2063|A complete domicile...|
| 2 | v9 | flat#4| B1|Society & Culture|6|0.1872|Having no variations in height.|
| 3 | v9 | flat#30| B1|Daily Life & Home|1|0.1704|a suite of rooms...|
| 4 | v9 | flat#15| B1|Society & Culture|6|0.1493|having a surface without slope...|
| 1 | v10| flat#73| B1|Society & Culture|6|0.124|A complete domicile...|
| 2 | v10| flat#4| B1|Society & Culture|6|0.1203|Having no variations in height.|
| 3 | v10| flat#53| A2|Society & Culture|6|0.1132|Directly; flatly.|
| 4 | v10| flat#25| B1|Society & Culture|6|0.11|stretched out and lying at full length...|

flat stable B1 Society correct, topic thr0.50 keeps Society vs v7 Other mislabel. Scores lower in v10 due to expanded uniq (more senses normalize p smaller) and uniform CEFR B1.

## Topic diversity per goal (with efficiency)

Baseline unweighted (topic_labels count):

| Topic | v7 % (1676) | v9 % (1688) | v10 % (1846) | v10 count | delta v10-v9 pp |
|-------|-------------|-------------|--------------|-----------|-----------------|
| Food & Drink | 16.8 | 17.2 | 19.1 | 353 | +1.9 |
| Health & Body | 9.0 | 15.2 | 15.1 | 279 | -0.1 |
| Daily Life & Home | 14.1 | 15.2 | 14.9 | 275 | -0.3 |
| Work & Education | 9.6 | 9.4 | 9.6 | 178 | +0.2 |
| Travel & Transportation | 7.7 | 9.8 | 9.5 | 176 | -0.3 |
| Society & Culture | 5.5 | 9.4 | 9.4 | 174 | 0 |
| Nature & Environment | 6.9 | 6.7 | 6.5 | 120 | -0.2 |
| Science & Technology | 6.6 | 5.3 | 4.7 | 87 | -0.6 |
| Business & Economy | 5.2 | 3.7 | 3.6 | 66 | -0.1 |
| Emotions & Relationships | 6.7 | 3.8 | 3.5 | 64 | -0.3 |
| Sports & Leisure | 5.9 | 2.2 | 1.9 | 35 | -0.3 |
| Law & Politics | 5.2 | 2.0 | 1.8 | 33 | -0.2 |
| Other / Abstract | 0.7 | 0.2 | 0.3 | 6 | +0.1 |

Other rate: v7 0.7% -> v9 0.2% -> v10 0.3% (thr0.50 + expanded domain)
Per-goal weighted mass (p*W) similar to v9, not recomputed here; general≈baseline, exam boosts Work/Science, travel boosts Food/Travel via GOAL_TOPIC_WEIGHTS.

Efficiency: v10 avg 3.692 vs target 2.5-3.0 (v7 3.352) — higher due to beginner K3 and larger uniq pool 7.72. For 4000 balanced quota, expected avg ~2.8 with same K's.

## Files

- W:/hamzaban_data_factory/uniq_senses-v10.json (2.11MB, 3862 senses, thr0.82 any>12)
- W:/hamzaban_data_factory/ranked_senses-v10.json (1.52MB, 1846 cards)
- W:/hamzaban_data_factory/topic_labels-v10.json (1.08MB)
- W:/hamzaban_data_factory/ranked_senses-v10.debug.json
- W:/hamzaban_data_factory/evp_sense.json (2000 entries) + cefrj_pos.json (504 fallbacks)
- W:/hamzaban_data_factory/colab_free_500_v10.ipynb (tqdm visible)
- factory/fixtures/ copy + fixtures-v10.zip (1.12MB)
- W:\hamzaban_data_factory\gap_report_free_500_v10.md + hamzaban_v10_report.md
- docs/research/lexicon/v10-report.md (this file)

## Verdict vs TICKETS-v10

- Ticket17 CEFR expanded: DONE 14->2000, fallback CEFR-J pos, April A1 fixed, tactic C2 kept, B1 default removed
- Ticket18 topic heuristic: DONE keyword health inflation replaced by ordered deterministic thr0.50, ECE per-sense
- Ticket19 rebalance: DONE table PILOT_500 97/127/93/95/50/38 + 4000 250/330/240/247/130/98 documented, pilot Kmax 3 implemented to approach target without resampling 500
- Ticket20 dedup+boost: DONE thr0.82 12-cap any>12 WN smoothed+len-norm, +0.4/+0.5 boosts removed; trade-off exam/rock stone now not top (reveals WN-hostile rare senses need CEFR-aware dedup future)
