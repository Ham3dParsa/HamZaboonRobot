# v15 EVIDENCE — weighted topic vectors (2026-09-03, worktree research-lexicon-v14)

Locked scope per plan-v14.md v15 + CONTEXT-v14. No re-decisions. No commit/PR (owner merges).

## Artifacts (worktree factory/)
- `factory/run_v15_topics.py` (+ `--lemmas` subset filter for probe smoke; behavior otherwise per locked spec)
- `factory/v15_progress.json` (resume: done_lemmas, failed_lemmas, model_calls)
- `factory/fixtures/topic_vectors-v15.json` — 500 lemmas, 1676 vectors
- W synced: `W:\hamzaban_data_factory\fixtures\topic_vectors-v15.json` + `fixtures-v15.zip`

## Run log
- Dry-run `--dry-run --limit 8`: green (validation asserts pass).
- Smoke `--limit 8` (first 8 alphabetical): 1 call spark-1.3, 0 failed, all single-topic (correct for function/abstract words).
- Probe smoke `--lemmas rock,light,pass,flat,supporter`: 1 call, 0 failed, multi=2.
- Full run: 63 batches, 0 failed lemmas, 0 fallbacks.
- Calls per model: **muse-spark-1.3-contributor-free: 64** (1 first-smoke + 1 probe + 62 full; 1 full batch already done by probe smoke). Fallback chain never needed.

## Verification (from files)
- Multi-topic rate: **101/1676 = 6.03%** (99×2-topic, 2×3-topic, 1575×1-topic).
- Weight-sum audit: **all 1676 sums = 1.0** (0 outside ±0.01).
- ID audit: all 1676 vectors match input sense ids per lemma exactly once. Note: 12 sense-id strings repeat WITHIN a lemma in v14c input (most#9/#6/#2, outside#13/#2/#21/#5, cast#1/#10/#13/#18/#4 — pre-existing v14c quirk, out of v15 scope); per-lemma coverage exact.
- Sources: 1676 judge / 0 deterministic. Failed lemmas: none.

## Primary-topic distribution v14c → v15
| Label | v14c | v15 primary | Δ |
|---|---|---|---|
| Other / Abstract | 453 | 453 | 0 |
| Society & Culture | 187 | 191 | +4 |
| Emotions & Relationships | 148 | 154 | +6 |
| Science & Technology | 135 | 135 | 0 |
| Work & Education | 131 | 128 | −3 |
| Daily Life & Home | 100 | 100 | 0 |
| Nature & Environment | 104 | 99 | −5 |
| Health & Body | 79 | 84 | +5 |
| Travel & Transportation | 73 | 78 | +5 |
| Law & Politics | 72 | 77 | +5 |
| Sports & Leisure | 60 | 68 | +8 |
| Food & Drink | 87 | 60 | −27 |
| Business & Economy | 47 | 49 | +2 |

72/1676 primaries reordered (4.3%). Food & Drink −27 is the hotspot — inspected samples are
v14a keyword-mislabel CORRECTIONS, not noise: fish#0 (animal) Food→Nature, fish#26 (fishing
trip) Food→Sports, recycling#3/#6/#4 Food→Nature, salmon#8 (kiln bricks) Food→Work&Education,
bracelet#1 (watch band) Food→Daily Life. Other count net 0 (moves in = moves out).

## Probe vectors
- rock#1 (rock music) Society&Culture 1.0 — single (culture-only reading; no Emotions split).
  rock#23 Daily Life 1.0, rock#39 SciTech 1.0, rock#4 Travel 1.0.
- light#62 (lamp) Daily Life 0.7 + SciTech 0.3 (primary reordered Other→Daily Life, justified).
  light#42 (physics) SciTech 1.0; light#7/#21 Other 1.0.
- pass#25 (ticket) Travel 0.6 + Society 0.4. pass#8 Travel 1.0; pass#55/#48 Other 1.0.
- flat#14 (apartment) Daily Life 1.0; flat#13 (lying out) Health 1.0; flat#5/#20/#40 Other 1.0.
- supporter#10 Society 1.0; supporter#1 Other 1.0.
- 3-topic cases (2): bus#11 (MIRV part) Travel 0.4 + Law&Politics 0.35 + SciTech 0.25;
  stray#5 (wander) Travel 0.5 + Daily Life 0.3 + Work&Education 0.2.

## Deliberately not changed / uncertain
- Script adds only `--lemmas` run-subset filter (same validation/transport); no prompt/spec change.
- Within-lemma duplicate sense ids left as-is (v14c data quirk, needs owner decision if ever cleaned).
- plan-v14.md NOT touched (lives in primary, read-only) — owner merges this evidence in.
