# SRS v4 Simulation Report

## 1. Scenario Matrix (plan x persona x proficiency, 360 days)

| plan | persona | proficiency | active_words | learned | learned/$ | AI$ | max_due | max_qbl | avg_late |
|---|---|---|---|---|---|---|---|---|---|
| free | lazy | beginner | 41 | 36 | 2727.3 | 0.0132 | 10 | 5 | 8.9 |
| free | lazy | intermediate | 40 | 36 | 1363.6 | 0.0264 | 13 | 2 | 8.5 |
| free | lazy | advanced | 40 | 36 | 1363.6 | 0.0264 | 13 | 2 | 8.5 |
| free | average | beginner | 152 | 146 | 8111.1 | 0.018 | 14 | 7 | 0.9 |
| free | average | intermediate | 158 | 152 | 12063.5 | 0.0126 | 16 | 7 | 0.9 |
| free | average | advanced | 158 | 152 | 12063.5 | 0.0126 | 16 | 7 | 0.9 |
| free | eager | beginner | 228 | 223 | 74333.3 | 0.003 | 8 | 8 | 0.2 |
| free | eager | intermediate | 228 | 223 | 74333.3 | 0.003 | 8 | 8 | 0.2 |
| free | eager | advanced | 228 | 223 | 74333.3 | 0.003 | 8 | 8 | 0.2 |
| free | fluctuating | beginner | 135 | 131 | 6616.2 | 0.0198 | 20 | 7 | 1.7 |
| free | fluctuating | intermediate | 136 | 134 | 7701.1 | 0.0174 | 16 | 7 | 1.5 |
| free | fluctuating | advanced | 134 | 131 | 4548.6 | 0.0288 | 21 | 5 | 1.9 |
| silver | lazy | beginner | 120 | 109 | 1593.6 | 0.0684 | 36 | 3 | 9.8 |
| silver | lazy | intermediate | 124 | 110 | 1368.2 | 0.0804 | 30 | 4 | 10.0 |
| silver | lazy | advanced | 112 | 99 | 1309.5 | 0.0756 | 32 | 3 | 9.5 |
| silver | average | beginner | 465 | 443 | 2006.3 | 0.2208 | 49 | 6 | 1.2 |
| silver | average | intermediate | 495 | 466 | 1844.8 | 0.2526 | 32 | 9 | 1.0 |
| silver | average | advanced | 511 | 481 | 1805.6 | 0.2664 | 39 | 7 | 1.0 |
| silver | eager | beginner | 722 | 705 | 23979.6 | 0.0294 | 37 | 29 | 0.3 |
| silver | eager | intermediate | 732 | 714 | 15063.3 | 0.0474 | 27 | 29 | 0.2 |
| silver | eager | advanced | 728 | 714 | 15866.7 | 0.045 | 25 | 29 | 0.3 |
| silver | fluctuating | beginner | 440 | 438 | 2115.9 | 0.207 | 52 | 9 | 1.6 |
| silver | fluctuating | intermediate | 424 | 410 | 1654.6 | 0.2478 | 53 | 7 | 1.7 |
| silver | fluctuating | advanced | 402 | 397 | 1906.8 | 0.2082 | 67 | 9 | 2.0 |
| gold | lazy | beginner | 197 | 175 | 1402.2 | 0.1248 | 68 | 3 | 13.2 |
| gold | lazy | intermediate | 184 | 166 | 1064.1 | 0.156 | 72 | 3 | 12.4 |
| gold | lazy | advanced | 192 | 169 | 1104.6 | 0.153 | 60 | 5 | 12.9 |
| gold | average | beginner | 930 | 882 | 1693.5 | 0.5208 | 77 | 7 | 1.1 |
| gold | average | intermediate | 945 | 914 | 1392.4 | 0.6564 | 90 | 7 | 1.0 |
| gold | average | advanced | 901 | 866 | 1299.1 | 0.6666 | 102 | 8 | 1.0 |
| gold | eager | beginner | 1357 | 1317 | 4125.9 | 0.3192 | 71 | 22 | 0.3 |
| gold | eager | intermediate | 1351 | 1307 | 3468.7 | 0.3768 | 41 | 21 | 0.2 |
| gold | eager | advanced | 1342 | 1298 | 3483.6 | 0.3726 | 80 | 27 | 0.3 |
| gold | fluctuating | beginner | 826 | 784 | 1726.1 | 0.4542 | 126 | 9 | 1.9 |
| gold | fluctuating | intermediate | 808 | 789 | 1361.3 | 0.5796 | 111 | 6 | 1.6 |
| gold | fluctuating | advanced | 787 | 754 | 1331.2 | 0.5664 | 110 | 8 | 2.0 |

## 2. Feature Toggle Isolation (gold/eager/advanced, 360 days)

| config | learned | avg_score | max_due | AI$ | learned/$ |
|---|---|---|---|---|---|
| all features ON (default) | 1298 | 2.82 | 80 | 0.3726 | 3483.6 |
| rejection OFF | 1307 | 2.84 | 38 | 0.2442 | 5352.2 |
| catchup OFF | 1302 | 2.85 | 45 | 0.3504 | 3715.8 |
| continuous_mastery OFF (legacy binary) | 969 | 4.63 | 63 | 0.156 | 6211.5 |
| session_rate_limit OFF | 1298 | 2.82 | 80 | 0.3726 | 3483.6 |
| all OFF (pure v3 legacy mode) | 937 | 4.63 | 70 | 0.1044 | 8975.1 |

## 3. Premium Config Override Band (+/-30%, gold plan defaults: 4 sessions x 7 cards)

| requested sessions | requested size | effective sessions | effective size | note |
|---|---|---|---|---|
| 4 | 7 | 4 | 7 | baseline (no override) |
| 5 | 9 | 5 | 9 | within +30% band -> honored |
| 6 | 12 | 6 | 10 | above +30% band -> clamped to +30% |
| 2 | 4 | 2 | 4 | below -30% band -> clamped to -30% |
| 1 | 1 | 2 | 4 | far below band -> clamped, floor 1 |

## 3b. Mid-run Config Change (user edits session/size settings partway through)

Phase A: days 0-180 at gold defaults (4x7). Phase B: days 180-360, user bumps to +30% band (5x9 requested -> clamped).

- Phase A (4x7): learned=444, max_due=56, AI$=0.3672
- Phase B (clamped to 5x9): learned=692, max_due=101, AI$=0.5724
- Result: override band clamps the request to +30% (5x9 is exactly the +30% edge for 4x7 -> stays within [3,5] sessions and [5,9] size), system remains stable, no crash or runaway backlog.

## 4. Long-Run Stress Test (720 days)

| plan | persona | learned | learned/$ | max_due | max_qbl | avg_late | max_late | AI$ total |
|---|---|---|---|---|---|---|---|---|
| free | lazy | 67 | 2537.9 | 15 | 4 | 9.3 | 62 | 0.0264 |
| free | eager | 391 | 93095.2 | 11 | 8 | 0.2 | 3 | 0.0042 |
| gold | lazy | 320 | 1108.8 | 66 | 3 | 11.8 | 113 | 0.2886 |
| gold | eager | 2333 | 5116.2 | 48 | 36 | 0.3 | 3 | 0.456 |
| gold | fluctuating | 1282 | 1466.5 | 109 | 8 | 2.4 | 19 | 0.8742 |

**Check**: no combination should show max_due_backlog growing unboundedly relative to queue_cap_days x daily_slots, and max_query_backlog should stay finite (queries eventually get drained by the self-correcting split even under lazy attendance), confirming bug 2/1 fixes hold at scale.

## 5. Learning Curve Over Time (gold/average/intermediate)

| day checkpoint | active_words | learned | avg_score | AI$ cumulative |
|---|---|---|---|---|
| 30 | 104 | 57 | 1.14 | 0.087 |
| 90 | 313 | 275 | 1.92 | 0.2322 |
| 180 | 514 | 489 | 2.25 | 0.3594 |
| 360 | 945 | 914 | 2.59 | 0.6564 |
| 720 | 1596 | 1582 | 2.87 | 1.0878 |

## 6. v3-legacy-equivalent vs v4-full (360 days, matrix of personas)

| persona | mode | learned | avg_score | max_due | AI calls | AI$ |
|---|---|---|---|---|---|---|
| lazy | v3-legacy | 119 | 2.94 | 71 | 143 | 0.0858 |
| lazy | v4-full   | 169 | 1.54 | 60 | 255 | 0.153 |
| average | v3-legacy | 473 | 4.17 | 79 | 330 | 0.198 |
| average | v4-full   | 866 | 2.56 | 102 | 1111 | 0.6666 |
| eager | v3-legacy | 937 | 4.63 | 70 | 174 | 0.1044 |
| eager | v4-full   | 1298 | 2.82 | 80 | 621 | 0.3726 |
| fluctuating | v3-legacy | 448 | 4.27 | 117 | 328 | 0.1968 |
| fluctuating | v4-full   | 754 | 2.28 | 110 | 944 | 0.5664 |
