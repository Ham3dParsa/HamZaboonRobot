# SRS v4 Simulation Report

## 1. Scenario Matrix (plan x persona x proficiency, 360 days)

| plan | persona | proficiency | active_words | learned | learned/$ | AI$ | max_due | max_qbl | avg_late |
|---|---|---|---|---|---|---|---|---|---|
| free | lazy | beginner | 37 | 32 | 579.7 | 0.0552 | 9 | 2 | 2.0 |
| free | lazy | intermediate | 34 | 31 | 580.5 | 0.0534 | 13 | 5 | 2.3 |
| free | lazy | advanced | 34 | 31 | 580.5 | 0.0534 | 13 | 5 | 2.3 |
| free | average | beginner | 171 | 162 | 796.5 | 0.2034 | 13 | 7 | 0.6 |
| free | average | intermediate | 161 | 151 | 744.6 | 0.2028 | 15 | 6 | 0.6 |
| free | average | advanced | 161 | 151 | 744.6 | 0.2028 | 15 | 6 | 0.6 |
| free | eager | beginner | 236 | 225 | 1053.4 | 0.2136 | 11 | 8 | 0.2 |
| free | eager | intermediate | 236 | 225 | 1053.4 | 0.2136 | 11 | 8 | 0.2 |
| free | eager | advanced | 236 | 225 | 1053.4 | 0.2136 | 11 | 8 | 0.2 |
| free | fluctuating | beginner | 130 | 127 | 766.9 | 0.1656 | 21 | 6 | 1.3 |
| free | fluctuating | intermediate | 131 | 125 | 801.3 | 0.156 | 18 | 6 | 1.3 |
| free | fluctuating | advanced | 129 | 125 | 820.2 | 0.1524 | 18 | 7 | 1.2 |
| silver | lazy | beginner | 102 | 93 | 1019.7 | 0.0912 | 40 | 3 | 2.9 |
| silver | lazy | intermediate | 111 | 104 | 821.5 | 0.1266 | 34 | 2 | 2.7 |
| silver | lazy | advanced | 118 | 104 | 787.9 | 0.132 | 45 | 2 | 2.7 |
| silver | average | beginner | 483 | 461 | 1070.1 | 0.4308 | 38 | 10 | 0.7 |
| silver | average | intermediate | 471 | 458 | 962.6 | 0.4758 | 44 | 8 | 0.8 |
| silver | average | advanced | 472 | 462 | 933.3 | 0.495 | 35 | 10 | 0.7 |
| silver | eager | beginner | 782 | 758 | 1097.6 | 0.6906 | 31 | 30 | 0.3 |
| silver | eager | intermediate | 792 | 749 | 1066.0 | 0.7026 | 32 | 29 | 0.3 |
| silver | eager | advanced | 777 | 741 | 1089.1 | 0.6804 | 43 | 31 | 0.3 |
| silver | fluctuating | beginner | 436 | 426 | 1053.4 | 0.4044 | 60 | 8 | 1.8 |
| silver | fluctuating | intermediate | 433 | 423 | 928.9 | 0.4554 | 58 | 8 | 1.2 |
| silver | fluctuating | advanced | 412 | 401 | 977.1 | 0.4104 | 75 | 8 | 1.6 |
| gold | lazy | beginner | 230 | 193 | 986.7 | 0.1956 | 64 | 4 | 2.3 |
| gold | lazy | intermediate | 196 | 171 | 861.0 | 0.1986 | 73 | 2 | 2.7 |
| gold | lazy | advanced | 205 | 173 | 796.5 | 0.2172 | 76 | 2 | 2.9 |
| gold | average | beginner | 864 | 841 | 1184.8 | 0.7098 | 80 | 8 | 0.8 |
| gold | average | intermediate | 913 | 873 | 1021.1 | 0.855 | 88 | 8 | 0.8 |
| gold | average | advanced | 940 | 915 | 1066.4 | 0.858 | 70 | 11 | 0.7 |
| gold | eager | beginner | 1483 | 1424 | 1182.5 | 1.2042 | 44 | 19 | 0.2 |
| gold | eager | intermediate | 1441 | 1380 | 1104.2 | 1.2498 | 54 | 27 | 0.3 |
| gold | eager | advanced | 1450 | 1395 | 1108.2 | 1.2588 | 78 | 17 | 0.2 |
| gold | fluctuating | beginner | 782 | 765 | 1199.4 | 0.6378 | 119 | 8 | 2.0 |
| gold | fluctuating | intermediate | 808 | 783 | 1048.2 | 0.747 | 136 | 6 | 1.7 |
| gold | fluctuating | advanced | 803 | 774 | 1018.2 | 0.7602 | 118 | 10 | 1.7 |

## 2. Feature Toggle Isolation (gold/eager/advanced, 360 days)

| config | learned | avg_score | max_due | AI$ | learned/$ |
|---|---|---|---|---|---|
| all features ON (default) | 1395 | 3.08 | 78 | 1.2588 | 1108.2 |
| rejection OFF | 1413 | 3.08 | 60 | 1.1412 | 1238.2 |
| catchup OFF | 1428 | 3.04 | 41 | 1.2936 | 1103.9 |
| continuous_mastery OFF (legacy binary) | 988 | 4.78 | 52 | 0.9126 | 1082.6 |
| session_rate_limit OFF | 1395 | 3.08 | 78 | 1.2588 | 1108.2 |
| all OFF (pure v3 legacy mode) | 1012 | 4.8 | 58 | 0.8712 | 1161.6 |

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

- Phase A (4x7): learned=489, max_due=74, AI$=0.489
- Phase B (clamped to 5x9): learned=663, max_due=103, AI$=0.6738
- Result: override band clamps the request to +30% (5x9 is exactly the +30% edge for 4x7 -> stays within [3,5] sessions and [5,9] size), system remains stable, no crash or runaway backlog.

## 4. Long-Run Stress Test (720 days)

| plan | persona | learned | learned/$ | max_due | max_qbl | avg_late | max_late | AI$ total |
|---|---|---|---|---|---|---|---|---|
| free | lazy | 59 | 668.9 | 14 | 3 | 2.4 | 13 | 0.0882 |
| free | eager | 417 | 1172.0 | 9 | 8 | 0.2 | 3 | 0.3558 |
| gold | lazy | 351 | 918.4 | 84 | 2 | 2.8 | 16 | 0.3822 |
| gold | eager | 2536 | 1137.4 | 64 | 31 | 0.2 | 3 | 2.2296 |
| gold | fluctuating | 1389 | 1007.0 | 135 | 11 | 1.8 | 11 | 1.3794 |

**Check**: no combination should show max_due_backlog growing unboundedly relative to queue_cap_days x daily_slots, and max_query_backlog should stay finite (queries eventually get drained by the self-correcting split even under lazy attendance), confirming bug 2/1 fixes hold at scale.

## 5. Learning Curve Over Time (gold/average/intermediate)

| day checkpoint | active_words | learned | avg_score | AI$ cumulative |
|---|---|---|---|---|
| 30 | 131 | 68 | 1.63 | 0.1212 |
| 90 | 280 | 259 | 2.31 | 0.258 |
| 180 | 496 | 474 | 2.63 | 0.4722 |
| 360 | 913 | 873 | 2.89 | 0.855 |
| 720 | 1589 | 1555 | 3.24 | 1.5168 |

## 6. v3-legacy-equivalent vs v4-full (360 days, matrix of personas)

| persona | mode | learned | avg_score | max_due | AI calls | AI$ |
|---|---|---|---|---|---|---|
| lazy | v3-legacy | 129 | 3.22 | 76 | 222 | 0.1332 |
| lazy | v4-full   | 173 | 1.88 | 76 | 362 | 0.2172 |
| average | v3-legacy | 478 | 4.5 | 80 | 701 | 0.4206 |
| average | v4-full   | 915 | 2.93 | 70 | 1430 | 0.858 |
| eager | v3-legacy | 1012 | 4.8 | 58 | 1452 | 0.8712 |
| eager | v4-full   | 1395 | 3.08 | 78 | 2098 | 1.2588 |
| fluctuating | v3-legacy | 425 | 4.45 | 93 | 630 | 0.378 |
| fluctuating | v4-full   | 774 | 2.65 | 118 | 1267 | 0.7602 |
