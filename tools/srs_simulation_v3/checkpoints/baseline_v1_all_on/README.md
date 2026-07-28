# SRS v3 Hybrid Session Simulator

A simple offline tool that simulates how the **HamZaban** language-learning review engine behaves over months of use.  
No AI, no database, no network — just pure math so you can see long-term patterns in seconds.

---

## What does it actually do?

Imagine a learner who:
- Studies with **review sessions** each day (e.g., 4 sessions × 7 cards = 28 slots/day).
- Sometimes **asks a word** via "Ask a Word" (each query costs 1 AI call).
- Sometimes **saves** that word to their review list.
- The system also **generates new AI cards** to fill any empty session slots.

This simulator runs that whole process for **30–360 days** and prints a daily table + a final summary.  
You can compare plans (Free / Silver / Gold), tweak probabilities, and see how big the backlog grows, how much AI budget is actually used, etc.

---

## Quick Start

### 1. Interactive (easiest)
```powershell
python -m tools.srs_simulation_v3
```
Just press **Enter** to accept the suggested defaults.

### 2. One-liner (for scripting / CSV export)
```powershell
python -m tools.srs_simulation_v3 --plan gold --days 360 --seed 42 --csv gold_run.csv
```

---

## Key Parameters (plain English)

| Flag | Meaning | Typical Range |
|------|---------|---------------|
| `--plan` | Which subscription tier (controls default caps) | `free`, `silver`, `gold` |
| `--days` | How many days to simulate | `30` (1 month) … `360` (1 year) |
| `--sessions` | Review sessions per day | `1` … `6` |
| `--session-size` | Cards per session | `4` … `10` |
| `--ai-daily-cap` | Max AI-generated cards per day | `3` … `20` |
| `--query-daily-cap` | Max "Ask a Word" queries per day | `3` … `10` |
| `--save-gate-rate` | Chance a query becomes a review card (0.0–1.0) | `0.3` … `0.8` |
| `--forget-rate` | How often the learner clicks "Again" (0.0–1.0) | `0.1` … `0.3` |
| `--seed` | Random seed (same seed = identical results) | any integer, e.g. `42` |
| `--report-every` | Print table every N days (0 = final only) | `5` |
| `--csv` | Save daily rows to a CSV file | `run1.csv` |

### New Feature Toggles
| Flag | Effect |
|------|--------|
| `--no-three-buttons` | Use classic 2-button review (Remembered / Again) |
| `--no-score` | Disable familiarity score (no interval adjustment) |
| `--no-random-intervals` | All cards use fixed intervals `[1,3,7,16,30]` |

---

## Reading the Output

### Daily Table
```
 Day  RevDone  Backlog  Slots  Empty  AIGen  AICalls  AICap  Total
------------------------------------------------------------------
   0        0       0     28     15     13       23     20     13
   5       20       1     28      0      8       18     20     85
```
- **Day** — simulation day (0 = first day)
- **RevDone** — how many due cards were actually reviewed that day
- **Backlog** — due cards that *didn't fit* in today's sessions (carries over)
- **Slots** — total session capacity today (`sessions × session-size`)
- **Empty** — slots left unused (session ran smaller than budgeted)
- **AIGen** — brand-new AI cards served today
- **AICalls** — total AI calls today = `queries_made + AIGen`
- **AICap** — daily AI budget ceiling
- **Total** — all cards currently in the SRS system

### Final Summary
```
Final Summary:
  Avg AI cards served per day:   6.2 / 20 cap -> 31.0% utilization (69.0% AI cost savings)
  Avg Total AI Calls per day:    12.4
  Max Backlog (any day):         42
  Avg Backlog (last 7 days):     8.1
  Days with empty slots (%):     12.3%
  Final Active Cards in SRS:     317
  Avg Final Score (0-5):         3.42
```
- **AI utilization** — how much of the daily AI budget was actually consumed
- **Max Backlog** — the worst traffic jam of due cards
- **Avg Final Score** — average familiarity (0 = struggling, 5 = mastered)

---

## Typical Experiments

### Compare plans (same seed = fair)
```powershell
python -m tools.srs_simulation_v3 --plan free --days 180 --seed 42 --csv free.csv
python -m tools.srs_simulation_v3 --plan silver --days 180 --seed 42 --csv silver.csv
python -m tools.srs_simulation_v3 --plan gold --days 180 --seed 42 --csv gold.csv
```
Open the three CSVs in Excel / Google Sheets and plot `backlog_count` or `ai_calls`.

### Toggle features to isolate effects
```powershell
# Baseline (all new features ON)
python -m tools.srs_simulation_v3 --plan gold --days 360 --seed 42 --csv all_on.csv

# All new features OFF (classic v3 behavior)
python -m tools.srs_simulation_v3 --plan gold --days 360 --seed 42 --no-three-buttons --no-score --no-random-intervals --csv all_off.csv

# Only randomized intervals
python -m tools.srs_simulation_v3 --plan gold --days 360 --seed 42 --no-three-buttons --no-score --csv intervals_only.csv
```

---

## Tips

- **Seed = reproducibility**. Always set `--seed 42` (or any number) when comparing runs.
- **Longer runs = clearer trends**. 30 days is noisy; 180–360 shows real steady-state.
- **High `save-gate-rate` + low `forget-rate`** = backlog grows fast, AI usage drops.
- **Low `save-gate-rate` + high `forget-rate`** = AI budget burns fast, cards reset often.
- **Random intervals** spread due dates naturally — backlog spikes disappear.
- **3-button mode** lets confident learners push cards further (LATER) or honest learners pull them closer (SOONER).

---

## Files

| File | Purpose |
|------|---------|
| `simulator_v3.py` | Pure simulation logic (no I/O, no CLI) |
| `__init__.py` | CLI entry point, argument parsing, interactive prompts |
| `__main__.py` | Tiny wrapper: `python -m tools.srs_simulation_v3` |
| `README.md` | This file |

---

## Need Help?

Run `python -m tools.srs_simulation_v3 --help` to see all flags with descriptions.