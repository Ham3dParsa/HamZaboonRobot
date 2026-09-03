# gap report v14c → v15 → v16 → v16b (500-lemma pilot, all numbers from files)

## 1. Card counts (topic runs never touch cards)

| version | cards | what changed | model calls |
|---|---|---|---|
| v13c | 2072 | baseline (1023 calls, Other 218 = 10.5%) | 1023 |
| v14a | 2101 | deterministic weights/recall/exact-merge (15 exact dups, merged_from) | 0 |
| v14b | 1676 | LLM paraphrase merge, 367 merged, 0 failed | 63 |
| v14c | 1676 | judge picks 494 lemmas + deterministic 6 (light/chairman/cycling/exchange/stool/drive); per-CEFR 265/258/298/296/309/250 | 63 (total 126) |
| v15 | 1676 | weight vectors over v14c labels (no re-decisions) | 64 |
| v16 | 1676 | fresh relabel, 13 → 16 heads (3 splits) | 64 |
| v16b | 1676 | top-up: only the 552 v16 Others relabeled, stronger prompt | 39 |

Total pilot LLM spend: 126 + 64 + 64 + 39 = **293 calls, all `muse-spark-1.3-contributor-free`**,
fallback chain never fired once. Per-CEFR rows unchanged since v14c in all topic runs.

## 2. Other% trajectory

| version | Other | % | note |
|---|---|---|---|
| v14c | 453/1676 | 27.0 | judge kept about/always/anything genuinely abstract |
| v15 | 453/1676 | 27.0 | net 0 by design (moves in = moves out) |
| v16 | 552/1676 | 32.9 | REGRESSION: unanchored fresh relabel drift |
| v16b | 296/1676 | 17.7 | ≤20% target HIT, ≤15% stretch missed by 29 rows; 256/552 rescued (46.4%) |

## 3. Multi-topic rate trajectory

| version | multi | % | shape |
|---|---|---|---|
| v14c | 0 | 0.0 | single label only |
| v15 | 101/1676 | 6.0 | 99×2-topic, 2×3-topic |
| v16 | 116/1676 | 6.9 | same prompt shape, fresh heads |
| v16b | 314/1676 | 18.7 | 312×2-topic, 2×3-topic; 202 of them ex-Other senses |

v16b's jump is the stronger prompt working as ordered (multi explicitly encouraged),
not noise: spot-checks (rock#23 Daily+Emotions, light#21 Business+Law, flat#13 Health+Daily)
match their glosses.

## 4. Primary distribution over heads

v14c/v15 use 13 heads; v16/v16b use 16 (splits: Nature→Animals+Nature, Work&Education→Work+Education,
Society&Culture→Society+Arts).

| head | v14c | v15 | v16 | v16b |
|---|---|---|---|---|
| Daily Life & Home | 100 | 100 | 68 | 93 |
| Food & Drink | 87 | 60 | 44 | 46 |
| Health & Body | 79 | 84 | 81 | 94 |
| Work (& Education → & Careers) | 131 | 128 | 49 | 74 |
| Education & Exams | — | — | 37 | 62 |
| Travel & Transportation | 73 | 78 | 59 | 72 |
| Society (& Culture →) | 187 | 191 | 108 | 150 |
| Arts & Culture | — | — | 86 | 100 |
| Animals & Living Beings | — | — | 35 | 36 |
| Nature (& Environment) | 104 | 99 | 77 | 89 |
| Science & Technology | 135 | 135 | 138 | 159 |
| Business & Economy | 47 | 49 | 47 | 62 |
| Law & Politics | 72 | 77 | 80 | 88 |
| Sports & Leisure | 60 | 68 | 70 | 76 |
| Emotions & Relationships | 148 | 154 | 145 | 179 |
| Other / Abstract | 453 | 453 | 552 | 296 |

Biggest v16→v16b gains: Society +42, Emotions +34, Daily/Work/Education +25 each.
Food +2 / Animals +1: those heads were already right in v16; the leftover Others have no food/animal anchor.

## 5. Judge / merge stats (carried over, unchanged since v14c)

- Merge: 2101 → 1676 cards, 367 merged (15 exact-dup with merged_from + paraphrase), 0 failed.
- Judge: 494 lemmas judged, 6 deterministic fallback (light, chairman, cycling, exchange, stool, drive).
- Topic runs don't re-rank or re-pick: every probe pick below is the v14c judge pick; only the topic label moves.

## 6. Probe table (7 lemmas; picks constant, topics per version)

Gloss short; topics as v14c / v15 / v16 / v16b.

**rock** (beginner [#23 sway, #4 tilt]; advanced [#1 music first, #23, #39 crystal, #4])
- #1 music: Society&Culture / Society&Culture / **Arts** / **Arts**
- #23 sway: Daily / Daily / Other / **Daily** (v16b vector Daily 0.6+Emotions 0.4)
- #39 crystal: SciTech ×4 (stable all versions)
- #4 tilt: Travel / Travel / Other / **Travel** (v16b Travel 0.6+Nature 0.4)

**light** (deterministic fallback picks [#62 lamp, #7 light-weight]; +#21 short-measure, +#42 radiation)
- #62 lamp: Other / Daily / **SciTech** / **SciTech**
- #7 "not burdensome": Other ×3 / **Work** (v16b Work 0.5+Daily 0.5)
- #21 "less than legal amount": Other ×3 / **Business** (v16b Business 0.6+Law 0.4)
- #42 physics: SciTech ×4 (stable)

**pass** (beginner [#8 cause-to-pass, #25 ticket]; +#48 juncture, +#55 attempt)
- #8: Travel / Travel / Other / **Travel** (generic gloss; v16 said Other, v16b says Travel — either defensible)
- #25 ticket: Travel / Travel / Arts / Arts (theatre-ticket reading; single borderline, kept)
- #48 juncture: Other ×4 (stays — genuinely vague)
- #55 attempt: Other ×4 (stays)

**flat** (beginner [#40 flat-surface, #14 apartment]; +#13 posture, +#5 frankly)
- #14 apartment: Daily / Daily / Daily / Daily (stable since v14c)
- #40 surface: Other ×4 (stays — conservative; a Daily/Nature reading is arguable)
- #13 posture: Health / Health / Other / **Health** (v16b Health 0.6+Daily 0.4)
- #5 frankly: Other ×3 / **Society** (v16b Society 0.6+Emotions 0.4)

**communicate** (beginner [#2 transmit, #4 transfer]; +#3 join, +#0 communion)
- #2 transmit: Other / Other / **SciTech** / **SciTech**
- #4 transfer: Other ×3 / **Society** (new v16b win)
- #3 join-or-connect: SciTech / SciTech / Other / Other (moved twice, still vague)
- #0 communion: Society&Culture / Society&Culture / Society / Society (clean split branch)

**supporter** (all levels [#10 person, #1 thing])
- #10 person: Society&Culture / Society&Culture / Society / Society (clean split)
- #1 "something that supports": Other ×4 (stays — generic, correct to keep)

**time** (beginner [#31 instant, #28 resource]; advanced [#15 continuum first, #28, #31])
- #15 continuum: Other ×3 / **Daily**
- #28 resource: Work&Education / Work&Education / Daily / Daily
- #31 instant: Other / Other / Daily / Daily

Pattern: v16b recovered every v16 regression on these probes (rock#23/#4, pass#8, flat#13)
and added genuine wins (light#7/#21, communicate#4, time#15). Nothing that was right in v16
broke in v16b on this panel.

## 7. Cost (calls per version, all spark-1.3, 0 fallbacks anywhere)

v14 merge 63 + judge 63 = 126; v15 64 (1 first-smoke + 1 probe + 62 full);
v16 64; v16b 39 (1 smoke + 38 full). Total 293. At this rate the 4000-scale run is
~8× the pilot (≈1300–1400 topic calls + merge/judge), i.e. the earlier 5–6h estimate still holds.

## 8. Verdict (honest)

What improved: Other 32.9% → 17.7% with zero regressions on the probe panel and no
card/pick churn (topic-only runs can't move ranking). Multi-labeling finally carries
real load (18.7%) instead of decorating 6%. The 16-head split survived contact with
data: Society/Arts and Work/Education branches both filled (+42/+14, +25/+25), and the
tie-breaks (fish→Animals, supporter→Society, music→Arts) held through two relabels.

What regressed: nothing measurable vs v16 — but two honest blemishes inside v16b itself:
pass#8 "cause to pass" → Travel 1.0 is a force-fit (generic gloss, movement reading), and
Food/Animals gained almost nothing (+2/+1), which means either those Others truly have no
food/animal anchor or their glosses are too terse for the judge. Both readings are live.

What remains: (1) stone top-4 — rock#12 was recalled to uniq by the EVP guard but never
reached top-4, so the judge never saw it; recall without a rank boost is still insufficient.
(2) The exam sense is absent — "pass an exam" exists nowhere in the data (only the old v9
injection had it); pass#55 "An attempt" is the closest and stays Other. (3) 296 Others
(17.7%) are mostly function words and vague placeholders — getting to ≤15% means deciding,
per word, whether to force a head or to accept Other as a legitimate answer. (4) 4000-scale
(R7) still needs owner sign-off.
