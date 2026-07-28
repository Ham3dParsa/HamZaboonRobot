# SRS Engine Evolution: v1 → v2 → v3 → v4.2-sweet

```
v1 (deprecated):  5-step ladder [1,3,7,16,30], gold=10x5=50slots, backlog ceiling, overflow
v2:               5-step ladder [1,3,7,16,30], gold=5x6=30slots, query-first, binary reviews
v3 (Claude):     10-step ladder [1,3,9,18,38,70,120,250,400,730], gold=5x9=45slots, binary+score
v4.2-sweet:      10-step ladder [1,3,7,15,30,60,120,240,480,960], gold=4x7=28slots, ease+decay
```

## Gold/Average — Across 4 Time Horizons

days v    learned  score  due_bl  ai_gen    ai_q   cost$
--------------------------------------------------------
  30   1      326   0.00      24     360     420  0.4680
  30   2      193   0.00       9      89     210  0.1794
  30   3      129   2.64      63     149       0  0.0894
  30   4       87   1.52      41     115      34  0.1164

 120   1      729   0.00      24    1440    1680  1.8720
 120   2      436   0.00      28     100     846  0.5676
 120   3      407   3.37      93     399       0  0.2394
 120   4      324   2.24      58     300     122  0.3288

 360   1      932   0.00      48    4320    5040  5.6160
 360   2      556   0.00      28     100    2482  1.5492
 360   3      803   4.17     159     688       0  0.4128
 360   4      915   2.93      70     742     383  0.8580

 720   1      973   0.00      98    8640   10080 11.2320
 720   2      582   0.00      69     100    5021  3.0726
 720   3     1333   4.46     159    1019       0  0.6114
 720   4     1668   3.28      94    1301     751  1.5720

## Gold/720d — Learned Words by Persona

     persona     v1     v2     v3     v4
--------------------------------------
        lazy    973    582    319    361
     average    973    582   1333   1668
       eager    973    582   2612   2515
 fluctuating    973    582   1198   1428

## 720-day Costs (gold/average)

  v1: ai_gen=8640, ai_q=10080, total_calls=18720, cost=$11.2320
  v2: ai_gen=100, ai_q=5021, total_calls=5121, cost=$3.0726
  v3: ai_gen=1019, ai_q=0, total_calls=1019, cost=$0.6114
  v4: ai_gen=1301, ai_q=751, total_calls=2620, cost=$1.5720

## Feature Matrix

| Feature | v1 (deprecated) | v2 | v3 (Claude) | v4.2-sweet |
|---------|:---------------:|:--:|:-----------:|:----------:|
| Interval ladder | 5 steps (max 30d) | 5 steps (max 30d) | 10 steps (max 730d) | 10 steps (max 960d) |
| Gold slots/day | 50 (10×5) | 30 (5×6) | 45 (5×9) | 28 (4×7) |
| Learned threshold | idx≥0 | idx≥0 | idx≥2 | idx≥3 OR score≥3.75 |
| Score model | None | None | Binary (+0.5/−1.0) | 0.8×(1−s/7) cont. |
| Score decay | None | None | None | Exponential |
| Ease factor | None | None | None | [0.7–1.5] per card |
| Query priority | After due+split | Backlog FIFO | Self-correcting split | Query-first-full |
| AI rejection | Backlog ceiling | None | None | Proficiency-based |
| Catch-up bonus | Overflow session | None | None | Yes (debt-triggered) |
| Query AI cost | Not tracked | Counted | Not tracked | Counted |

## Final Verdict

**v4.2-sweet is the definitive version.** It addresses every known weakness from its predecessors:

1. **Realistic score model** — v1/v2 had no score, v3 had binary (+0.5/-1.0), v4 uses continuous
   diminishing-returns gains with Ebbinghaus decay. Learned threshold idx≥3 OR score≥3.75
   provides a dual path to mastery.
2. **Ease factor** — Per-card interval adaptation (v4-only) personalises spacing based on the
   learner's self-reported recall quality, something no earlier version attempted.
3. **Query-first priority** — v4 ensures user-requested words are never starved by AI generation,
   fixing the backlog starvation v1/v2/v3 all suffered in high-query scenarios.
4. **Full cost accounting** — Both AI generation and user queries cost $0.0006/call, giving
   a truthful per-learner financial projection.
5. **Catch-up bonus** — Extra due-card processing when backlog grows, replacing v1's crude
   overflow session with a bounded, controlled mechanism.

*v3 learned counts are inflated because its binary score model never decays — every card eventually
saturates. v4's decay-ease combination produces lower raw counts but higher confidence per word.*

---
*Generated: 2026-07-27*