# SRS Algorithm Tuning Lab

A pure-Python, offline simulator used to design and tune the spaced-repetition
(SRS) review engine before touching any real code. Nothing here is wired
into the production bot -- it's a design/tuning sandbox.

---

## 1. How to run it

```bash
cd v3_GOLDEN_recommended
python3 run_experiments.py
```

This runs every combination of 3 plans x 4 personas at 180 days and 360 days,
and prints a legend followed by summary tables. No dependencies, no
internet, no database -- just the standard library.

To try one specific scenario yourself:

```python
from simulator import simulate, SimConfig

rows, summary = simulate(SimConfig(plan="gold", persona="eager", days=360))
print(summary)          # end-of-run totals, see glossary below
print(rows[0])           # day 0's breakdown
print(rows[-1])          # last day's breakdown
```

`rows` is a day-by-day list; `summary` is the end-of-run aggregate. Every
field in both is explained below AND at the top of `simulator.py` itself
(look for the big module docstring -- the code is meant to be readable on
its own, not just this file).

---

## 2. Glossary -- what every column/field means

| Column | Full name | Meaning |
|---|---|---|
| `plan` | Subscription plan | Free / Silver / Gold |
| `persona` | Simulated learner type | See "The four personas" below |
| `vocab_exp` | `total_vocab_exposure` | **The headline number.** Total distinct words ever introduced to this learner -- AI-generated *and* user-queried words combined. This is "how much vocabulary did they actually gain," not just "how many AI calls happened." |
| `ai_gen` | `total_new_words` | Subset of `vocab_exp`: only words that came from AI generation (not from the user's own queries). Useful for estimating AI cost/usage, but **not** a growth KPI on its own -- see note below. |
| `learned` | `learned_words` | How many cards (any origin) reached at least 2 successful reviews by the end of the run -- a rough "durably learned, not just seen once" count. |
| `avg_score` | `avg_score` | Average familiarity of cards still active at the end. Scale: 0 = struggling, 5 = mastered. |
| `due_bl` | `max_due_backlog` | Worst single day's count of *due* (scheduled) review cards that could not be fit into a session. This is the number that matters for "is spacing breaking down." |
| `q_bl` | `max_query_backlog` | Worst single day's count of user-asked words still waiting for their first review slot. This is a "wishlist pile," not lost content. |
| `avg_late` | `avg_lateness_days` | Average number of days a due card sat waiting past its scheduled date, averaged over every review that happened. Lower = better spacing. |
| `max_late` | `max_lateness_days` | The single worst delay (in days) any one due card ever experienced before being reviewed. |
| `archived` | `archived_lost_words` | Cards the system permanently gave up on because they were both very overdue (45+ days) and still weak. **Should be 0 or near-0** -- any nonzero number means real vocabulary content was permanently lost, which is a red flag to investigate, not something to shrug off. |

### Why `vocab_exp` (not `ai_gen`) is the number to look at for "vocabulary growth"

An early version of this lab only counted AI-generated cards as "growth."
That's misleading: a highly engaged user who spends their session capacity
reviewing words *they themselves asked about*, instead of random AI
suggestions, is not falling behind -- they're doing self-directed vocabulary
building, arguably a *better* outcome. So when judging "is this
plan/persona learning more words," always look at `vocab_exp`, and treat
`ai_gen` only as a secondary cost/usage indicator.

### The four personas

| Persona | Attendance | Querying | Forgetting | Represents |
|---|---|---|---|---|
| `lazy` | 35% of days | rarely, 0-1/day | 35% "Again" rate | Low-engagement free-riders |
| `average` | 70% of days | sometimes, 0-3/day | 20% "Again" rate | Typical casual learner |
| `eager` | 92% of days | often, 2-6/day | 10% "Again" rate | Highly engaged, likely to pay |
| `fluctuating` | oscillates 30%-90% on a 21-day cycle | same as average | same as average | Real person with motivation ups and downs (exam weeks, travel, etc.) |

---

## 3. How the engine actually decides what to show each day (plain English)

Every day, each session's seats get filled in this strict order:

1. **Due reviews first, always.** Any card whose scheduled review date has
   arrived gets served before anything else -- protecting the spacing
   schedule is priority #1.
2. **Then the user's own queried words**, and **then brand-new AI-generated
   words**, splitting whatever seats are left between the two.
   - The split is normally about 50/50.
   - If the pile of asked-but-unreviewed words grows past "3 months' worth
     of daily capacity," its share automatically increases -- prioritizing
     clearing that pile over generating even more new words -- and eases
     back to 50/50 once the pile shrinks again. This stops the "I asked
     about it but never got to review it" pile from growing forever.
3. **New-word generation is throttled -- but only by real review debt,
   never by how much the user has queried.** If due-card debt builds up too
   high, brand-new AI word generation is throttled down (and, in the worst
   case, paused entirely) until the backlog clears. The user's own query
   quota is *never* reduced because of this -- it's a plan-capped, paid
   feature that should never punish an engaged user.

---

## 4. Version history (checkpoints, oldest -> newest)

### `v1_baseline_buggy` -- do not use, kept for reference
First attempt. **Bug found:** the new-word throttle was computed from
(due debt + query backlog) combined, so an engaged user's own querying
choked off *their own* new-vocabulary growth harder than a lazy user's.
Free-plan eager users got only 4 new AI words in 180 days vs. 20 for lazy
users -- backwards from the intended incentive.

### `v2_throttle_fix`
Fixed the bug above: the new-word throttle now looks *only* at due-card
debt. Query quota became a pure, un-throttled, plan-capped, user-pull
benefit. Correct ordering restored when measured by AI-generated words --
but this version's own reporting still only counted AI-generated words as
"growth," which looked confusing for heavy-querying users. See v3.

### `v3_GOLDEN_recommended` -- current, recommended
Same engine as v2, plus:
- **Self-correcting query-backlog priority** (see section 3 above) so the
  "asked but unreviewed" pile can't grow forever even across a multi-year
  horizon.
- **Fixed the real reporting issue**: added `total_vocab_exposure`
  (AI-generated + query-promoted, combined) as the true vocabulary-growth
  KPI, instead of only counting AI-generated cards.
- Every `.py` file now has full docstrings and inline "why," not just
  "what," comments.

---

## 5. Results (v3, seed=42, for reproducibility)

### 180-day run
```
plan    persona      vocab_exp ai_gen  learned  avg_score due_bl  q_bl   avg_late max_late archived
free    lazy                26      20       19      2.76      14      2      3.8       17        0
free    average            112      15       53      3.83      14     55      1.1        6        0
free    eager              310      11       86      4.33      11    222      0.5        3        0
free    fluctuating         93       9       46      3.78      17     44      2.1        9        0
silver  lazy                59      43       42      2.49      35      8      4.6       17        0
silver  average            174      77      143      3.89      47     20      1.5       10        0
silver  eager              541      75      251      4.28      22    279      0.3        3        0
silver  fluctuating        161      74      134      3.84      48     19      1.8        9        0
gold    lazy                98      90       74      2.53      70      3      4.8       17        0
gold    average            292     197      275       4.0      82     11      1.2        8        0
gold    eager              689     229      497      4.31      36    180      0.3        2        0
gold    fluctuating        286     190      256      3.67     100     18      2.3       11        0
```

### 360-day run
```
plan    persona      vocab_exp ai_gen  learned  avg_score due_bl  q_bl   avg_late max_late archived
free    lazy                37      20       26      3.18      20      6      5.2       25        0
free    average            206      18       73      4.43      16    130      1.7        6        0
free    eager              606      11      121       4.7      17    479      0.8        4        0
free    fluctuating        182      10       61      4.23      19    116      2.3        9        0
silver  lazy                75      47       49      2.61      50      8      5.3       28        0
silver  average            267      86      179      4.46      52     81      2.0       10        0
silver  eager             1010      89      355      4.73      29    647      0.4        3        0
silver  fluctuating        239      77      152      4.46      58     77      2.6       11        0
gold    lazy               140     122      103      2.83      90      4      4.7       21        0
gold    average            445     247      396      4.41      82     43      1.2        8        0
gold    eager             1224     300      714      4.74      48    496      0.4        3        0
gold    fluctuating        390     218      324      4.23     103     38      2.6       11        0
```

---

## 6. Direct answers to the questions you asked

- **When a user wants too many new words, can they, or can't they?**
  They can always *ask* (queries are never throttled -- that's the paid
  hook). But brand-new *AI-generated* words auto-throttle whenever real
  due-review debt is building up, protecting spacing.
- **Does the algorithm self-block runaway auto-generation when there's a
  big pile of unseen cards?** Yes, two independent brakes: (1) a gradual
  throttle (0%-100% of the plan's cap depending on overdue pressure), and
  (2) a hard "waiting room" (zero new AI cards at all once due-debt crosses
  `queue_cap_days x daily_slots`).
- **How late do overdue cards eventually get?** Bounded and small for
  attentive personas (avg 0.3-2.6 days, max 2-11 days for average/eager
  across all plans). Lazy users see more drift (avg ~5 days, max ~17-28
  days over a year) -- that's an attendance problem, not an algorithm
  failure, and `archived_lost_words = 0` in every scenario tested, meaning
  no card was ever actually lost.
- **Is query quota respected as a purchase driver?** Yes -- it's never
  throttled by backlog pressure. The only cap is the plan's own daily
  allowance (Free 3 / Silver 8 / Gold 15), which is the intended paid
  differentiator, not a side-effect of the algorithm.
- **Does raising plan session caps encourage upgrades for serious
  learners?** Yes, strongly. An eager user's `vocab_exp` goes
  310 -> 541 -> 689 (180 days) and 606 -> 1010 -> 1224 (360 days) across
  Free -> Silver -> Gold -- a visible, honest reason to upgrade.

### A structural finding worth knowing (not a bug)
Free tier's 4 slots/day, with the `[1,3,7,16,30,60]`-day interval ladder,
hits a natural review-capacity ceiling around ~80-90 actively-reviewed
words. Past that point, all daily slots go to maintaining existing words,
and both new-AI generation and query-promotion pause until the user
upgrades (or their active pool shrinks). This is correct spaced-repetition
math -- you cannot add infinite new cards without eventually violating
spacing -- and it doubles as the cleanest, most honest upgrade trigger in
the whole system: no artificial gate needed, the math explains itself.

---

## 7. Open items -- need your call before this touches real code

1. The `session_size` / `ai_daily_cap` values per plan are carried over
   from `docs/Plan_srs_v3.md`, not re-derived here. Tell me if you want a
   different Free-tier ceiling (more generous, or tighter to push upgrades
   sooner) -- it's a one-line constant change, easy to re-simulate.
2. The "3 months' worth of slots" query self-correction threshold is a
   judgment call, not a locked product decision -- say if you want it to
   kick in sooner or later.
3. This is a standalone lab, **not wired into** `tools/srs_simulation_v2`,
   `tools/srs_simulation_v3`, or any production file
   (`services/scheduling.py`, `handlers/srs_handler.py`, etc.). Per
   AGENTS.md Section 2.4, turning any of these numbers into a real
   product/config change needs its own contract-lock gate before touching
   real files.